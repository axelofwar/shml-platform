"""Regression tests for the inference stack compose contract.

These tests validate the actual docker-compose configuration used by the
inference services rather than hardcoded example dictionaries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
INFERENCE_COMPOSE = REPO_ROOT / "inference" / "docker-compose.inference.yml"
REQUIRED_PRIORITY = "2147483647"


def _load_compose() -> dict[str, Any]:
    with open(INFERENCE_COMPOSE, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _env_dict(service: dict[str, Any]) -> dict[str, str]:
    env = service.get("environment", [])
    result: dict[str, str] = {}
    for item in env:
        key, value = item.split("=", 1)
        result[key] = value
    return result


def _label_dict(service: dict[str, Any]) -> dict[str, str]:
    labels = service.get("labels", [])
    result: dict[str, str] = {}
    for item in labels:
        key, value = item.split("=", 1)
        result[key] = value
    return result


def _device_ids(service: dict[str, Any]) -> list[str]:
    devices = (
        service.get("deploy", {})
        .get("resources", {})
        .get("reservations", {})
        .get("devices", [])
    )
    if not devices:
        return []
    return list(devices[0].get("device_ids", []))


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return _load_compose()


@pytest.fixture(scope="module")
def services(compose: dict[str, Any]) -> dict[str, Any]:
    return compose["services"]


class TestComposeStructure:
    def test_compose_file_exists(self):
        assert INFERENCE_COMPOSE.exists()

    def test_required_services_exist(self, services: dict[str, Any]):
        for service_name in [
            "qwen3-vl-api",
            "z-image-api",
            "inference-gateway",
            "pii-blur-api",
            "pii-ui",
        ]:
            assert service_name in services

    def test_shared_network_declared(self, compose: dict[str, Any]):
        networks = compose.get("networks", {})
        assert "shml-platform" in networks

    def test_model_cache_and_shared_secret_declared(self, compose: dict[str, Any]):
        volumes = compose.get("volumes", {})
        secrets = compose.get("secrets", {})

        assert "model-cache" in volumes
        assert "shared_db_password" in secrets


class TestQwen3VLService:
    def test_environment_matches_expected_contract(self, services: dict[str, Any]):
        env = _env_dict(services["qwen3-vl-api"])

        assert env["MODEL_ID"] == "Qwen/Qwen3-VL-8B-Instruct"
        assert env["QUANTIZATION"] == "int4"
        assert env["DEVICE"] == "cuda:0"
        assert env["TRANSFORMERS_OFFLINE"] == "1"
        assert env["HF_HUB_OFFLINE"] == "1"
        assert env["YIELD_TO_TRAINING"] == "true"
        assert env["UNLOAD_TIMEOUT_SECONDS"] == "300"

    def test_gpu_binding_targets_rtx_2070_slot(self, services: dict[str, Any]):
        assert _device_ids(services["qwen3-vl-api"]) == ["1"]

    def test_resources_and_port_exposure(self, services: dict[str, Any]):
        service = services["qwen3-vl-api"]
        resources = service["deploy"]["resources"]

        assert service["expose"] == ["8000"]
        assert resources["limits"]["memory"] == "12G"
        assert resources["reservations"]["memory"] == "6G"

    def test_traefik_labels_guard_llm_route(self, services: dict[str, Any]):
        labels = _label_dict(services["qwen3-vl-api"])

        assert labels["traefik.http.routers.qwen3-vl.rule"] == "PathPrefix(`/api/llm`)"
        assert labels["traefik.http.routers.qwen3-vl.priority"] == REQUIRED_PRIORITY
        assert labels["traefik.http.services.qwen3-vl.loadbalancer.server.port"] == "8000"
        assert labels["traefik.http.middlewares.qwen3-strip.stripprefix.prefixes"] == "/api/llm"
        assert labels["traefik.http.routers.qwen3-vl.middlewares"] == "oauth2-errors,oauth2-auth,qwen3-strip"


class TestZImageService:
    def test_environment_matches_expected_contract(self, services: dict[str, Any]):
        env = _env_dict(services["z-image-api"])

        assert env["MODEL_ID"] == "Tongyi-MAI/Z-Image-Turbo"
        assert env["DTYPE"] == "bfloat16"
        assert env["NUM_INFERENCE_STEPS"] == "8"
        assert env["TRANSFORMERS_OFFLINE"] == "1"
        assert env["HF_HUB_OFFLINE"] == "1"
        assert env["YIELD_TO_TRAINING"] == "true"

    def test_gpu_binding_targets_rtx_2070_slot(self, services: dict[str, Any]):
        assert _device_ids(services["z-image-api"]) == ["1"]

    def test_traefik_labels_guard_image_route(self, services: dict[str, Any]):
        labels = _label_dict(services["z-image-api"])

        assert labels["traefik.http.routers.z-image.rule"] == "PathPrefix(`/api/image`)"
        assert labels["traefik.http.routers.z-image.priority"] == REQUIRED_PRIORITY
        assert labels["traefik.http.services.z-image.loadbalancer.server.port"] == "8000"
        assert labels["traefik.http.middlewares.z-image-strip.stripprefix.prefixes"] == "/api/image"
        assert labels["traefik.http.routers.z-image.middlewares"] == "oauth2-errors,oauth2-auth,z-image-strip"


class TestInferenceGatewayService:
    def test_environment_targets_internal_backends_and_db_secret(self, services: dict[str, Any]):
        service = services["inference-gateway"]
        env = _env_dict(service)

        assert env["QWEN3_VL_URL"] == "http://qwen3-vl-api:8000"
        assert env["Z_IMAGE_URL"] == "http://z-image-api:8000"
        assert env["POSTGRES_PASSWORD_FILE"] == "/run/secrets/shared_db_password"
        assert env["BACKUP_COMPRESSION"] == "zstd"
        assert env["BACKUP_RETENTION_DAYS"] == "90"
        assert service["secrets"] == ["shared_db_password"]

    def test_depends_on_model_backends(self, services: dict[str, Any]):
        depends_on = services["inference-gateway"]["depends_on"]

        assert depends_on["qwen3-vl-api"]["condition"] == "service_started"
        assert depends_on["z-image-api"]["condition"] == "service_started"

    def test_gateway_has_no_gpu_reservation(self, services: dict[str, Any]):
        assert _device_ids(services["inference-gateway"]) == []

    def test_traefik_labels_guard_gateway_route(self, services: dict[str, Any]):
        labels = _label_dict(services["inference-gateway"])

        assert labels["traefik.http.routers.inference.rule"] == "PathPrefix(`/inference`)"
        assert labels["traefik.http.routers.inference.priority"] == REQUIRED_PRIORITY
        assert labels["traefik.http.services.inference.loadbalancer.server.port"] == "8000"
        assert labels["traefik.http.middlewares.inference-strip.stripprefix.prefixes"] == "/inference"
        assert labels["traefik.http.routers.inference.middlewares"] == "oauth2-errors,oauth2-auth,inference-strip"


class TestPIIBlurService:
    def test_service_uses_shared_db_secret_and_gpu(self, services: dict[str, Any]):
        service = services["pii-blur-api"]
        env = _env_dict(service)

        assert env["POSTGRES_PASSWORD_FILE"] == "/run/secrets/shared_db_password"
        assert env["ENABLE_LICENSE_PLATE_DETECTION"] == "true"
        assert service["secrets"] == ["shared_db_password"]
        assert _device_ids(service) == ["1"]

    def test_traefik_labels_guard_pii_route(self, services: dict[str, Any]):
        labels = _label_dict(services["pii-blur-api"])

        assert labels["traefik.http.routers.pii-blur.rule"] == "PathPrefix(`/api/pii`)"
        assert labels["traefik.http.routers.pii-blur.priority"] == REQUIRED_PRIORITY
        assert labels["traefik.http.services.pii-blur.loadbalancer.server.port"] == "8000"
        assert labels["traefik.http.middlewares.pii-blur-strip.stripprefix.prefixes"] == "/api/pii"
        assert labels["traefik.http.routers.pii-blur.middlewares"] == "oauth2-errors,oauth2-auth,pii-blur-strip"


class TestSharedInvariants:
    @pytest.mark.parametrize(
        "service_name",
        ["qwen3-vl-api", "z-image-api", "inference-gateway", "pii-blur-api"],
    )
    def test_backend_services_share_platform_network(
        self, services: dict[str, Any], service_name: str
    ):
        assert services[service_name]["networks"] == ["shml-platform"]

    @pytest.mark.parametrize(
        ("service_name", "path_prefix"),
        [
            ("qwen3-vl-api", "/api/llm"),
            ("z-image-api", "/api/image"),
            ("inference-gateway", "/inference"),
            ("pii-blur-api", "/api/pii"),
        ],
    )
    def test_public_api_routes_use_max_priority(
        self, services: dict[str, Any], service_name: str, path_prefix: str
    ):
        labels = _label_dict(services[service_name])
        router_name = next(
            key.rsplit(".", 2)[1]
            for key, value in labels.items()
            if key.endswith(".rule") and value == f"PathPrefix(`{path_prefix}`)"
        )

        assert labels[f"traefik.http.routers.{router_name}.priority"] == REQUIRED_PRIORITY


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
