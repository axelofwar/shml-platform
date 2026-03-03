import pytest

from ray_compute.benchmarking.mlflow_artifacts import MLflowArtifactManager


def test_enforces_runs_uri_for_artifact_uri():
    manager = MLflowArtifactManager()

    with pytest.raises(ValueError):
        manager.enforce_mlflow_artifact_only_source(artifact_uri="/tmp/local-path")


def test_accepts_valid_runs_uri_source():
    manager = MLflowArtifactManager()
    manager.enforce_mlflow_artifact_only_source(
        artifact_uri="runs:/abc123/datasets/sample/1.0.0"
    )


def test_accepts_run_id_and_artifact_path_source():
    manager = MLflowArtifactManager()
    manager.enforce_mlflow_artifact_only_source(
        source_run_id="abc123",
        source_artifact_path="datasets/raw/sample.parquet",
    )
