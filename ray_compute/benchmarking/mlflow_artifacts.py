from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Optional

import mlflow

from .models import GoldenDatasetRef


DEFAULT_GOLDEN_EXPERIMENT = "platform-golden-datasets"
DEFAULT_BACKUP_EXPERIMENT = "platform-golden-datasets-backups"


class MLflowArtifactManager:
    """
    MLflow-first artifact manager for golden datasets and benchmark artifacts.

    Design rule:
    - Artifacts are always sourced from MLflow artifact URIs or run/artifact paths.
    - Local files are only temporary materialization during copy/validation.
    """

    def __init__(
        self,
        tracking_uri: Optional[str] = None,
        golden_experiment: str = DEFAULT_GOLDEN_EXPERIMENT,
        backup_experiment: str = DEFAULT_BACKUP_EXPERIMENT,
    ) -> None:
        if tracking_uri:
            mlflow.set_tracking_uri(tracking_uri)
        self.golden_experiment = golden_experiment
        self.backup_experiment = backup_experiment

    def _get_or_create_experiment_id(self, name: str) -> str:
        exp = mlflow.get_experiment_by_name(name)
        if exp is not None:
            return exp.experiment_id
        return mlflow.create_experiment(name=name)

    def _sha256(self, file_path: Path) -> str:
        digest = hashlib.sha256()
        with file_path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def create_or_update_golden_dataset(
        self,
        dataset_name: str,
        dataset_version: str,
        source_run_id: str,
        source_artifact_path: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> GoldenDatasetRef:
        """
        Copies a dataset artifact from an existing MLflow run into the golden dataset experiment.

        NOTE: This intentionally does not ingest arbitrary local files.
        """
        golden_exp_id = self._get_or_create_experiment_id(self.golden_experiment)
        local_path = Path(
            mlflow.artifacts.download_artifacts(
                run_id=source_run_id,
                artifact_path=source_artifact_path,
            )
        )

        tags = {
            "dataset.name": dataset_name,
            "dataset.version": dataset_version,
            "dataset.source_run_id": source_run_id,
            "dataset.source_artifact_path": source_artifact_path,
            "dataset.golden": "true",
        }
        if metadata:
            tags.update({f"dataset.meta.{k}": str(v) for k, v in metadata.items()})

        with mlflow.start_run(
            experiment_id=golden_exp_id,
            run_name=f"golden::{dataset_name}::{dataset_version}",
            tags=tags,
        ) as run:
            target_artifact_path = f"datasets/{dataset_name}/{dataset_version}"
            if local_path.is_dir():
                mlflow.log_artifacts(
                    str(local_path), artifact_path=target_artifact_path
                )
                total_size = sum(
                    p.stat().st_size for p in local_path.rglob("*") if p.is_file()
                )
                checksum = self._sha256(
                    next(p for p in local_path.rglob("*") if p.is_file())
                )
            else:
                mlflow.log_artifact(str(local_path), artifact_path=target_artifact_path)
                total_size = local_path.stat().st_size
                checksum = self._sha256(local_path)

            mlflow.log_params(
                {
                    "dataset_name": dataset_name,
                    "dataset_version": dataset_version,
                    "source_run_id": source_run_id,
                    "source_artifact_path": source_artifact_path,
                }
            )
            mlflow.log_metrics({"dataset_size_bytes": float(total_size)})
            mlflow.set_tag("dataset.sha256", checksum)

            return GoldenDatasetRef(
                name=dataset_name,
                version=dataset_version,
                source_run_id=source_run_id,
                source_artifact_path=source_artifact_path,
                sha256=checksum,
                size_bytes=total_size,
            )

    def resolve_golden_dataset_artifact_uri(
        self,
        dataset_name: str,
        dataset_version: Optional[str] = None,
    ) -> str:
        """
        Returns MLflow artifact URI for requested golden dataset version.
        If version is omitted, latest by start_time is selected.
        """
        exp = mlflow.get_experiment_by_name(self.golden_experiment)
        if exp is None:
            raise ValueError(
                f"Golden dataset experiment not found: {self.golden_experiment}"
            )

        filter_parts = [
            f"tags.dataset.name = '{dataset_name}'",
            "tags.dataset.golden = 'true'",
        ]
        if dataset_version:
            filter_parts.append(f"tags.dataset.version = '{dataset_version}'")

        runs = mlflow.search_runs(
            experiment_ids=[exp.experiment_id],
            filter_string=" and ".join(filter_parts),
            order_by=["attributes.start_time DESC"],
            max_results=1,
        )
        if runs.empty:
            raise ValueError(
                f"No golden dataset found for name={dataset_name}, version={dataset_version or 'latest'}"
            )

        run_id = runs.iloc[0]["run_id"]
        version = dataset_version or runs.iloc[0]["tags.dataset.version"]
        return f"runs:/{run_id}/datasets/{dataset_name}/{version}"

    def backup_golden_dataset(self, dataset_name: str, dataset_version: str) -> str:
        """
        Creates a backup run by copying the golden dataset artifact into a backup experiment.
        Returns backup run_id.
        """
        backup_exp_id = self._get_or_create_experiment_id(self.backup_experiment)
        source_uri = self.resolve_golden_dataset_artifact_uri(
            dataset_name=dataset_name,
            dataset_version=dataset_version,
        )

        with tempfile.TemporaryDirectory(prefix="golden-backup-") as tmp_dir:
            local_copy = Path(
                mlflow.artifacts.download_artifacts(
                    artifact_uri=source_uri, dst_path=tmp_dir
                )
            )
            with mlflow.start_run(
                experiment_id=backup_exp_id,
                run_name=f"backup::{dataset_name}::{dataset_version}",
                tags={
                    "dataset.name": dataset_name,
                    "dataset.version": dataset_version,
                    "backup.source_uri": source_uri,
                    "backup.type": "golden-dataset",
                },
            ) as run:
                artifact_path = f"backups/datasets/{dataset_name}/{dataset_version}"
                if local_copy.is_dir():
                    mlflow.log_artifacts(str(local_copy), artifact_path=artifact_path)
                else:
                    mlflow.log_artifact(str(local_copy), artifact_path=artifact_path)
                return run.info.run_id

    def enforce_mlflow_artifact_only_source(
        self,
        artifact_uri: Optional[str] = None,
        source_run_id: Optional[str] = None,
        source_artifact_path: Optional[str] = None,
    ) -> None:
        if artifact_uri:
            if not artifact_uri.startswith("runs:/"):
                raise ValueError("artifact_uri must use MLflow runs:/ URI scheme")
            return

        if source_run_id and source_artifact_path:
            return

        raise ValueError(
            "Artifacts must come from MLflow: provide runs:/artifact_uri or source_run_id + source_artifact_path"
        )
