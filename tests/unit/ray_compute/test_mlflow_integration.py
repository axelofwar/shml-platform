from __future__ import annotations

import importlib
import sys
import types
from datetime import datetime
from unittest.mock import MagicMock

import httpx
import pytest


_mlflow_stub = types.ModuleType("mlflow")
_mlflow_stub.set_tracking_uri = MagicMock()
_mlflow_stub.get_experiment_by_name = MagicMock(return_value=None)
_mlflow_stub.create_experiment = MagicMock(return_value="exp-1")
_mlflow_stub.set_experiment = MagicMock()
_mlflow_stub.start_run = MagicMock()
_mlflow_stub.log_params = MagicMock()
_mlflow_stub.log_metrics = MagicMock()
_mlflow_stub.log_artifact = MagicMock()
_mlflow_stub.end_run = MagicMock()

sys.modules["mlflow"] = _mlflow_stub
import ray_compute.api.mlflow_integration as mlflow_integration

if sys.modules.get("mlflow") is _mlflow_stub:
    del sys.modules["mlflow"]


@pytest.fixture(autouse=True)
def reset_module_state(monkeypatch):
    monkeypatch.delenv("DISABLE_MLFLOW_LOGGING", raising=False)
    monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
    monkeypatch.delenv("MLFLOW_EXPERIMENT_NAME", raising=False)

    importlib.reload(mlflow_integration)
    mlflow_integration.mlflow = _mlflow_stub
    mlflow_integration._auto_logger = mlflow_integration.MLflowAutoLogger()
    mlflow_integration._rest_client = None

    for attr in (
        "set_tracking_uri",
        "get_experiment_by_name",
        "create_experiment",
        "set_experiment",
        "start_run",
        "log_params",
        "log_metrics",
        "log_artifact",
        "end_run",
    ):
        getattr(_mlflow_stub, attr).reset_mock()


class TestMLflowAutoLogger:
    def test_init_reads_environment_defaults(self):
        logger = mlflow_integration.MLflowAutoLogger()

        assert logger.enabled is True
        assert logger.tracking_uri == "http://mlflow-nginx:80"
        assert logger.experiment_name == "Ray-Jobs"
        assert logger._initialized is False

    def test_init_respects_disable_env(self, monkeypatch):
        monkeypatch.setenv("DISABLE_MLFLOW_LOGGING", "true")

        logger = mlflow_integration.MLflowAutoLogger()

        assert logger.enabled is False

    def test_initialize_noops_when_disabled(self):
        logger = mlflow_integration.MLflowAutoLogger()
        logger.enabled = False

        logger.initialize()

        _mlflow_stub.set_tracking_uri.assert_not_called()

    def test_initialize_creates_missing_experiment(self):
        logger = mlflow_integration.MLflowAutoLogger()

        logger.initialize("custom-exp")

        _mlflow_stub.set_tracking_uri.assert_called_once_with(
            "http://mlflow-nginx:80"
        )
        _mlflow_stub.get_experiment_by_name.assert_called_once_with("custom-exp")
        _mlflow_stub.create_experiment.assert_called_once_with(
            name="custom-exp",
            tags={"source": "ray-compute", "auto_created": "true"},
        )
        _mlflow_stub.set_experiment.assert_called_once_with("custom-exp")
        assert logger._initialized is True

    def test_initialize_uses_existing_experiment(self):
        logger = mlflow_integration.MLflowAutoLogger()
        _mlflow_stub.get_experiment_by_name.return_value = types.SimpleNamespace(
            experiment_id="exp-existing"
        )

        logger.initialize()

        _mlflow_stub.create_experiment.assert_not_called()
        _mlflow_stub.set_experiment.assert_called_once_with("Ray-Jobs")
        assert logger._initialized is True

    def test_initialize_failure_disables_logger(self):
        logger = mlflow_integration.MLflowAutoLogger()
        _mlflow_stub.set_tracking_uri.side_effect = RuntimeError("boom")

        logger.initialize()

        assert logger.enabled is False
        assert logger._initialized is False

    def test_start_run_initializes_and_merges_tags(self):
        logger = mlflow_integration.MLflowAutoLogger()
        run = types.SimpleNamespace(info=types.SimpleNamespace(run_id="run-1"))
        _mlflow_stub.start_run.return_value = run

        result = logger.start_run("demo-run", tags={"team": "ml"})

        assert result is run
        _mlflow_stub.start_run.assert_called_once_with(
            run_name="demo-run",
            tags={"source": "ray-compute", "auto_logged": "true", "team": "ml"},
        )

    def test_start_run_returns_none_on_failure(self):
        logger = mlflow_integration.MLflowAutoLogger()
        _mlflow_stub.start_run.side_effect = RuntimeError("bad start")

        result = logger.start_run("demo-run")

        assert result is None

    def test_log_params_requires_initialized_logger(self):
        logger = mlflow_integration.MLflowAutoLogger()

        logger.log_params({"a": 1})

        _mlflow_stub.log_params.assert_not_called()

    def test_log_metrics_calls_mlflow(self):
        logger = mlflow_integration.MLflowAutoLogger()
        logger._initialized = True

        logger.log_metrics({"loss": 0.2}, step=4)

        _mlflow_stub.log_metrics.assert_called_once_with({"loss": 0.2}, step=4)

    def test_log_artifact_calls_mlflow(self):
        logger = mlflow_integration.MLflowAutoLogger()
        logger._initialized = True

        logger.log_artifact("artifact.txt", "outputs")

        _mlflow_stub.log_artifact.assert_called_once_with("artifact.txt", "outputs")

    def test_end_run_calls_mlflow(self):
        logger = mlflow_integration.MLflowAutoLogger()
        logger._initialized = True

        logger.end_run("FAILED")

        _mlflow_stub.end_run.assert_called_once_with(status="FAILED")


class TestAutoLogDecorator:
    def test_disabled_logger_executes_function_without_mlflow(self):
        mlflow_integration._auto_logger.enabled = False
        called = MagicMock(return_value={"accuracy": 0.9})

        @mlflow_integration.auto_log_mlflow(run_name="demo")
        def job(config):
            return called(config)

        result = job({"epochs": 3})

        assert result == {"accuracy": 0.9}
        called.assert_called_once_with({"epochs": 3})

    def test_successful_execution_logs_params_metrics_and_end(self):
        logger = mlflow_integration._auto_logger
        logger.start_run = MagicMock(return_value=object())
        logger.log_params = MagicMock()
        logger.log_metrics = MagicMock()
        logger.end_run = MagicMock()

        @mlflow_integration.auto_log_mlflow(run_name="decorated")
        def job(config):
            return {"accuracy": 0.97, "label": "ok"}

        result = job({"epochs": 5, "lr": 0.01})

        assert result == {"accuracy": 0.97, "label": "ok"}
        logger.log_params.assert_called_once_with(
            {"function": "job", "module": __name__, "epochs": 5, "lr": 0.01}
        )
        logger.log_metrics.assert_called_once_with({"accuracy": 0.97})
        logger.end_run.assert_called_once_with(status="FINISHED")

    def test_failure_marks_run_failed(self):
        logger = mlflow_integration._auto_logger
        logger.start_run = MagicMock(return_value=object())
        logger.log_params = MagicMock()
        logger.end_run = MagicMock()

        @mlflow_integration.auto_log_mlflow(run_name="boom")
        def job(config):
            raise ValueError("bad job")

        with pytest.raises(ValueError, match="bad job"):
            job({"epochs": 2})

        logger.end_run.assert_called_once_with(status="FAILED")

    def test_decorator_uses_config_from_kwargs(self):
        logger = mlflow_integration._auto_logger
        logger.start_run = MagicMock(return_value=object())
        logger.log_params = MagicMock()
        logger.log_metrics = MagicMock()
        logger.end_run = MagicMock()

        @mlflow_integration.auto_log_mlflow()
        def job(*, config):
            return {"loss": 0.1}

        job(config={"steps": 10})

        logger.log_params.assert_called_once_with(
            {"function": "job", "module": __name__, "steps": 10}
        )


class TestConvenienceFunctions:
    def test_get_auto_logger_returns_global_instance(self):
        assert mlflow_integration.get_auto_logger() is mlflow_integration._auto_logger

    def test_is_mlflow_enabled_reflects_global_state(self):
        mlflow_integration._auto_logger.enabled = False

        assert mlflow_integration.is_mlflow_enabled() is False

    def test_log_job_helpers_delegate_to_global_logger(self):
        logger = mlflow_integration._auto_logger
        logger.initialize = MagicMock()
        logger.start_run = MagicMock()
        logger.log_params = MagicMock()
        logger.log_metrics = MagicMock()
        logger.log_artifact = MagicMock()
        logger.end_run = MagicMock()

        mlflow_integration.log_job_start("demo", {"epochs": 3})
        mlflow_integration.log_job_metrics({"loss": 0.2}, step=7)
        mlflow_integration.log_job_artifact("out.txt", "artifacts")
        mlflow_integration.log_job_end("FAILED")

        logger.initialize.assert_called_once_with()
        logger.start_run.assert_called_once_with(
            run_name="demo", tags={"job_name": "demo"}
        )
        logger.log_params.assert_called_once_with({"epochs": 3})
        logger.log_metrics.assert_called_once_with({"loss": 0.2}, step=7)
        logger.log_artifact.assert_called_once_with("out.txt", "artifacts")
        logger.end_run.assert_called_once_with(status="FAILED")


class TestMLflowRESTClient:
    def test_api_call_get_uses_query_params(self):
        client = mlflow_integration.MLflowRESTClient("http://mlflow")
        response = MagicMock()
        response.json.return_value = {"ok": True}
        response.raise_for_status.return_value = None
        client._client.get = MagicMock(return_value=response)

        result = client._api_call("GET", "/experiments/get", params={"name": "demo"})

        assert result == {"ok": True}
        client._client.get.assert_called_once_with(
            "http://mlflow/api/2.0/mlflow/experiments/get",
            params={"name": "demo"},
        )

    def test_api_call_post_uses_json_body(self):
        client = mlflow_integration.MLflowRESTClient("http://mlflow")
        response = MagicMock()
        response.json.return_value = {"run_id": "abc"}
        response.raise_for_status.return_value = None
        client._client.post = MagicMock(return_value=response)

        result = client._api_call("POST", "/runs/create", json={"name": "demo"})

        assert result == {"run_id": "abc"}
        client._client.post.assert_called_once_with(
            "http://mlflow/api/2.0/mlflow/runs/create",
            json={"name": "demo"},
        )

    def test_api_call_re_raises_http_status_error(self):
        client = mlflow_integration.MLflowRESTClient("http://mlflow")
        request = httpx.Request("GET", "http://mlflow/test")
        response = httpx.Response(500, request=request, text="boom")
        client._client.get = MagicMock(
            side_effect=httpx.HTTPStatusError("fail", request=request, response=response)
        )

        with pytest.raises(httpx.HTTPStatusError):
            client._api_call("GET", "/test")

    def test_api_call_rejects_unsupported_method(self):
        client = mlflow_integration.MLflowRESTClient("http://mlflow")

        with pytest.raises(ValueError, match="Unsupported method"):
            client._api_call("PUT", "/runs/create")

    def test_get_or_create_experiment_returns_existing_id(self):
        client = mlflow_integration.MLflowRESTClient("http://mlflow")
        client._api_call = MagicMock(
            return_value={"experiment": {"experiment_id": "exp-42"}}
        )

        result = client.get_or_create_experiment("demo")

        assert result == "exp-42"

    def test_get_or_create_experiment_creates_after_404(self):
        client = mlflow_integration.MLflowRESTClient("http://mlflow")
        request = httpx.Request("GET", "http://mlflow/test")
        not_found = httpx.HTTPStatusError(
            "missing",
            request=request,
            response=httpx.Response(404, request=request),
        )
        client._api_call = MagicMock(
            side_effect=[not_found, {"experiment_id": "exp-new"}]
        )

        result = client.get_or_create_experiment("demo")

        assert result == "exp-new"

    def test_create_run_adds_default_and_custom_tags(self):
        client = mlflow_integration.MLflowRESTClient("http://mlflow")
        client._api_call = MagicMock(
            return_value={"run": {"info": {"run_id": "run-9"}}}
        )

        result = client.create_run("exp-1", "job-name", {"team": "platform"})

        assert result == "run-9"
        payload = client._api_call.call_args.kwargs["json"]
        assert payload["experiment_id"] == "exp-1"
        assert {"key": "team", "value": "platform"} in payload["tags"]

    def test_log_params_skips_none_and_truncates_values(self):
        client = mlflow_integration.MLflowRESTClient("http://mlflow")
        client._api_call = MagicMock()

        client.log_params("run-1", {"a": 1, "b": None, "long": "x" * 700})

        payload = client._api_call.call_args.kwargs["json"]
        assert payload == {
            "run_id": "run-1",
            "params": [
                {"key": "a", "value": "1"},
                {"key": "long", "value": "x" * 500},
            ],
        }

    def test_log_metrics_batch_keeps_only_numeric_values(self):
        client = mlflow_integration.MLflowRESTClient("http://mlflow")
        client._api_call = MagicMock()

        client.log_metrics_batch("run-1", {"loss": 0.1, "name": "bad", "n": 3})

        payload = client._api_call.call_args.kwargs["json"]
        assert payload["run_id"] == "run-1"
        assert len(payload["metrics"]) == 2
        assert {metric["key"] for metric in payload["metrics"]} == {"loss", "n"}

    def test_set_tag_truncates_value(self):
        client = mlflow_integration.MLflowRESTClient("http://mlflow")
        client._api_call = MagicMock()

        client.set_tag("run-1", "message", "x" * 6000)

        payload = client._api_call.call_args.kwargs["json"]
        assert payload == {
            "run_id": "run-1",
            "key": "message",
            "value": "x" * 5000,
        }

    def test_update_run_status_maps_terminal_status_and_sets_end_time(self):
        client = mlflow_integration.MLflowRESTClient("http://mlflow")
        client._api_call = MagicMock()
        end_time = datetime(2024, 1, 2, 3, 4, 5)

        client.update_run_status("run-1", "FAILED", end_time)

        payload = client._api_call.call_args.kwargs["json"]
        assert payload["run_id"] == "run-1"
        assert payload["status"] == "FAILED"
        assert payload["end_time"] == int(end_time.timestamp() * 1000)

    def test_close_closes_http_client(self):
        client = mlflow_integration.MLflowRESTClient("http://mlflow")
        client._client.close = MagicMock()

        client.close()

        client._client.close.assert_called_once_with()


class TestRESTHelpers:
    def test_get_mlflow_rest_client_is_singleton(self):
        first = mlflow_integration.get_mlflow_rest_client()
        second = mlflow_integration.get_mlflow_rest_client()

        assert first is second

    @pytest.mark.asyncio
    async def test_create_mlflow_run_for_job_logs_params_and_returns_ids(self):
        client = MagicMock()
        client.get_or_create_experiment.return_value = "exp-1"
        client.create_run.return_value = "run-2"
        client.log_params = MagicMock()
        mlflow_integration._rest_client = client

        result = await mlflow_integration.create_mlflow_run_for_job(
            experiment_name="demo-exp",
            job_id="job-1",
            job_name="demo-job",
            user="axel",
            job_type="training",
            job_params={"cpu": 4, "description": None},
        )

        assert result == ("exp-1", "run-2")
        client.create_run.assert_called_once_with(
            experiment_id="exp-1",
            run_name="demo-job",
            tags={
                "ray.job_id": "job-1",
                "ray.job_type": "training",
                "ray.user": "axel",
                "mlflow.note.content": "Ray job: demo-job\nSubmitted by: axel",
            },
        )
        client.log_params.assert_called_once_with(
            "run-2",
            {
                "job_id": "job-1",
                "job_name": "demo-job",
                "job_type": "training",
                "user": "axel",
                "cpu": 4,
            },
        )

    @pytest.mark.asyncio
    async def test_update_mlflow_run_for_job_logs_metrics_tags_and_status(self):
        client = MagicMock()
        mlflow_integration._rest_client = client
        end_time = datetime(2024, 1, 3, 4, 5, 6)

        await mlflow_integration.update_mlflow_run_for_job(
            run_id="run-1",
            status="FAILED",
            metrics={"duration_seconds": 12.5},
            end_time=end_time,
            error_message="stacktrace",
        )

        client.log_metrics_batch.assert_called_once_with(
            "run-1", {"duration_seconds": 12.5}
        )
        client.set_tag.assert_called_once_with(
            "run-1", "ray.error_message", "stacktrace"
        )
        client.update_run_status.assert_called_once_with("run-1", "FAILED", end_time)

    @pytest.mark.asyncio
    async def test_update_mlflow_run_for_job_ignores_empty_run_id(self):
        client = MagicMock()
        mlflow_integration._rest_client = client

        await mlflow_integration.update_mlflow_run_for_job(
            run_id="",
            status="SUCCEEDED",
        )

        client.log_metrics_batch.assert_not_called()
        client.update_run_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_mlflow_run_for_job_swallows_client_errors(self):
        client = MagicMock()
        client.update_run_status.side_effect = RuntimeError("boom")
        mlflow_integration._rest_client = client

        await mlflow_integration.update_mlflow_run_for_job(
            run_id="run-1",
            status="SUCCEEDED",
        )

        client.update_run_status.assert_called_once_with("run-1", "SUCCEEDED", None)

    def test_is_mlflow_server_available_checks_health_endpoint(self):
        client = MagicMock()
        client.tracking_uri = "http://mlflow"
        client._client.get.return_value = types.SimpleNamespace(status_code=200)
        mlflow_integration._rest_client = client

        assert mlflow_integration.is_mlflow_server_available() is True

    def test_is_mlflow_server_available_returns_false_on_error(self):
        client = MagicMock()
        client.tracking_uri = "http://mlflow"
        client._client.get.side_effect = RuntimeError("down")
        mlflow_integration._rest_client = client

        assert mlflow_integration.is_mlflow_server_available() is False