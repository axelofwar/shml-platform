"""Tests for SHML SDK configuration dataclasses."""

import os
from unittest.mock import patch

import pytest

from shml.config import (
    PlatformConfig,
    TrainingConfig,
    DataConfig,
    AuthConfig,
    AugmentationConfig,
    JobConfig,
)
from shml.exceptions import ConfigError, ValidationError


# ── PlatformConfig Tests ─────────────────────────────────────────────────


class TestPlatformConfig:
    """Verify PlatformConfig defaults and from_env construction."""

    @pytest.mark.unit
    def test_default_construction(self):
        cfg = PlatformConfig()
        assert cfg is not None
        # Frozen dataclass — should have service URLs
        assert hasattr(cfg, "mlflow_uri")
        assert hasattr(cfg, "ray_head_address")

    @pytest.mark.unit
    def test_from_env(self):
        env = {
            "MLFLOW_TRACKING_URI": "http://mlflow:5000",
            "RAY_DASHBOARD_URL": "http://ray:8265",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = PlatformConfig.from_env()
            assert cfg is not None


# ── AugmentationConfig Tests ─────────────────────────────────────────────


class TestAugmentationConfig:
    """Verify AugmentationConfig serialization."""

    @pytest.mark.unit
    def test_to_dict(self):
        aug = AugmentationConfig()
        d = aug.to_dict()
        assert isinstance(d, dict)

    @pytest.mark.unit
    def test_defaults_are_numeric(self):
        aug = AugmentationConfig()
        d = aug.to_dict()
        for v in d.values():
            assert isinstance(
                v, (int, float, bool, str)
            ), f"Unexpected type {type(v)} for {v}"


# ── TrainingConfig Tests ─────────────────────────────────────────────────


class TestTrainingConfig:
    """Verify TrainingConfig validation and serialization."""

    @pytest.mark.unit
    def test_default_construction(self):
        cfg = TrainingConfig()
        assert cfg.epochs > 0
        assert cfg.imgsz > 0

    @pytest.mark.unit
    def test_to_ultralytics_dict(self):
        cfg = TrainingConfig()
        d = cfg.to_ultralytics_dict()
        assert isinstance(d, dict)
        assert "epochs" in d or "imgsz" in d

    @pytest.mark.unit
    def test_to_rfdetr_dict(self):
        cfg = TrainingConfig()
        d = cfg.to_rfdetr_dict()
        assert isinstance(d, dict)

    @pytest.mark.unit
    def test_from_dict(self):
        cfg = TrainingConfig.from_dict({"epochs": 10, "imgsz": 640})
        assert cfg.epochs == 10
        assert cfg.imgsz == 640

    @pytest.mark.unit
    def test_yaml_roundtrip(self, tmp_path):
        cfg = TrainingConfig(epochs=5, imgsz=320)
        yaml_path = tmp_path / "train.yaml"
        cfg.to_yaml(str(yaml_path))
        loaded = TrainingConfig.from_yaml(str(yaml_path))
        assert loaded.epochs == cfg.epochs
        assert loaded.imgsz == cfg.imgsz


# ── DataConfig Tests ─────────────────────────────────────────────────────


class TestDataConfig:
    """Verify DataConfig construction and resolution."""

    @pytest.mark.unit
    def test_default_construction(self):
        cfg = DataConfig()
        assert cfg is not None

    @pytest.mark.unit
    def test_from_dict(self):
        cfg = DataConfig.from_dict({"dataset": "faces_yolo"})
        assert cfg.dataset == "faces_yolo"


# ── AuthConfig Tests ─────────────────────────────────────────────────────


class TestAuthConfig:
    """Verify AuthConfig env resolution and headers."""

    @pytest.mark.unit
    def test_from_env_with_api_key(self):
        env = {"SHML_API_KEY": "test-key-123"}
        with patch.dict(os.environ, env, clear=False):
            cfg = AuthConfig.from_env()
            assert cfg is not None

    @pytest.mark.unit
    def test_auth_headers_present(self):
        env = {"SHML_API_KEY": "test-key-123"}
        with patch.dict(os.environ, env, clear=False):
            cfg = AuthConfig.from_env()
            headers = cfg.auth_headers
            assert isinstance(headers, dict)


# ── JobConfig Tests ──────────────────────────────────────────────────────


class TestJobConfig:
    """Verify JobConfig construction."""

    @pytest.mark.unit
    def test_default_construction(self):
        cfg = JobConfig()
        assert cfg is not None
        assert hasattr(cfg, "training")
