"""
Feature Store Integration Client
==================================

Wraps Spark-backed feature extraction, storage, and retrieval.
Delegates to the platform's shml_features / shml_spark libraries.
"""

from __future__ import annotations

import importlib
from typing import Any

from shml.config import PlatformConfig
from shml.exceptions import FeatureStoreError


class FeatureClient:
    """Feature store client for experiment feature logging."""

    def __init__(self, config: PlatformConfig | None = None):
        self._config = config or PlatformConfig.from_env()
        self._client = None
        self._available = False
        self._init()

    def _init(self) -> None:
        """Try to import the platform feature client."""
        try:
            mod = importlib.import_module("shml_features")
            self._client = mod.FeatureClient()
            self._available = True
        except ImportError:
            # Try relative workspace import
            try:
                import sys
                import os

                libs_dir = os.path.join(
                    os.path.dirname(__file__), "..", "..", "..", "libs"
                )
                if os.path.isdir(libs_dir):
                    sys.path.insert(0, os.path.abspath(libs_dir))
                    mod = importlib.import_module("shml_features")
                    self._client = mod.FeatureClient()
                    self._available = True
            except Exception:
                self._available = False
        except Exception:
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def healthy(self) -> bool:
        """Check if the feature store backend is reachable."""
        if not self._available or self._client is None:
            return False
        try:
            return self._client.healthy()
        except Exception:
            return False

    def log_features(
        self,
        experiment_name: str,
        features: dict[str, Any],
        epoch: int | None = None,
        step: int | None = None,
    ) -> None:
        """Log feature vectors or metadata for an experiment.

        Args:
            experiment_name: Experiment identifier.
            features: Dict of feature name → value.
            epoch: Optional epoch number.
            step: Optional step number.
        """
        if not self._available or self._client is None:
            raise FeatureStoreError("Feature store not available")
        try:
            self._client.log_features(
                experiment_name=experiment_name,
                features=features,
                epoch=epoch,
                step=step,
            )
        except FeatureStoreError:
            raise
        except Exception as e:
            raise FeatureStoreError(f"Failed to log features: {e}")

    def get_features(
        self,
        experiment_name: str,
        epoch: int | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve features for an experiment.

        Returns a list of feature records.
        """
        if not self._available or self._client is None:
            raise FeatureStoreError("Feature store not available")
        try:
            return self._client.get_features(
                experiment_name=experiment_name,
                epoch=epoch,
            )
        except FeatureStoreError:
            raise
        except Exception as e:
            raise FeatureStoreError(f"Failed to get features: {e}")

    def log_model_metrics(
        self,
        experiment_name: str,
        metrics: dict[str, float],
        epoch: int,
    ) -> None:
        """Convenience: log training metrics as features.

        This stores metrics like loss, mAP, precision, recall
        in the feature store for later analysis and comparison.
        """
        features = {f"metric_{k}": v for k, v in metrics.items()}
        features["epoch"] = epoch
        self.log_features(experiment_name, features, epoch=epoch)

    def log_dataset_stats(
        self,
        experiment_name: str,
        stats: dict[str, Any],
    ) -> None:
        """Log dataset statistics (class counts, image sizes, etc.)."""
        features = {f"dataset_{k}": v for k, v in stats.items()}
        self.log_features(experiment_name, features)
