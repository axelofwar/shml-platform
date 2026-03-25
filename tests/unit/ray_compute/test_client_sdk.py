from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_RC_ROOT = _ROOT / "ray_compute"
for _path in [str(_ROOT), str(_RC_ROOT)]:
    if _path not in sys.path:
        sys.path.insert(0, _path)

from ray_compute.api.client import (  # noqa: E402
    JobType,
    RayComputeClient,
    submit_dataset_curation_job,
    submit_inference_job,
    submit_training_job,
)


def _response(payload):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = payload
    return response


class TestRayComputeClient:
    def test_init(self):
        client = RayComputeClient(base_url="http://ray:8266")
        assert client.base_url == "http://ray:8266"
        assert client.session is not None

    def test_submit_job(self):
        client = RayComputeClient()
        client.session.post = MagicMock(return_value=_response({"job_id": "job-1"}))
        job_id = client.submit_job(
            name="train",
            code="print('hi')",
            job_type=JobType.TRAINING,
            cpu=8,
            memory_gb=16,
            gpu=1,
            timeout_minutes=30,
            mlflow_experiment="exp",
            mlflow_tags={"phase": "p1"},
            env_vars={"ENV": "1"},
            arguments={"epochs": 3},
        )
        assert job_id == "job-1"
        payload = client.session.post.call_args.kwargs["json"]
        assert payload["job_type"] == "training"
        assert payload["requirements"]["gpu"] == 1

    def test_get_job(self):
        client = RayComputeClient()
        client.session.get = MagicMock(return_value=_response({"job_id": "job-1", "status": "RUNNING"}))
        result = client.get_job("job-1")
        assert result["status"] == "RUNNING"

    def test_list_jobs_with_filters(self):
        client = RayComputeClient()
        client.session.get = MagicMock(return_value=_response([{"job_id": "job-1"}]))
        result = client.list_jobs(status="RUNNING", job_type=JobType.TRAINING, limit=10)
        assert result[0]["job_id"] == "job-1"
        params = client.session.get.call_args.kwargs["params"]
        assert params["status"] == "RUNNING"
        assert params["job_type"] == "training"

    def test_get_logs(self):
        client = RayComputeClient()
        client.session.get = MagicMock(return_value=_response({"logs": "line1"}))
        assert client.get_logs("job-1") == "line1"

    def test_cancel_job(self):
        client = RayComputeClient()
        client.session.post = MagicMock(return_value=_response({"status": "STOPPED"}))
        result = client.cancel_job("job-1")
        assert result["status"] == "STOPPED"

    def test_delete_job(self):
        client = RayComputeClient()
        client.session.delete = MagicMock(return_value=_response({"deleted": True}))
        result = client.delete_job("job-1")
        assert result["deleted"] is True

    def test_get_resources(self):
        client = RayComputeClient()
        client.session.get = MagicMock(return_value=_response({"gpu": 1, "cpu": 16}))
        result = client.get_resources()
        assert result["cpu"] == 16

    def test_wait_for_job_completes(self):
        client = RayComputeClient()
        with patch.object(client, "get_job", side_effect=[{"status": "RUNNING"}, {"status": "SUCCEEDED", "job_id": "job-1"}]), \
             patch("ray_compute.api.client.time.sleep") as mock_sleep:
            result = client.wait_for_job("job-1", timeout=10, poll_interval=1)
        assert result["status"] == "SUCCEEDED"
        mock_sleep.assert_called_once_with(1)

    def test_wait_for_job_timeout(self):
        client = RayComputeClient()
        with patch.object(client, "get_job", return_value={"status": "RUNNING"}), \
             patch("ray_compute.api.client.time.time", side_effect=[0, 20]), \
             patch("ray_compute.api.client.time.sleep"):
            with pytest.raises(TimeoutError, match="did not complete"):
                client.wait_for_job("job-1", timeout=5, poll_interval=1)


class TestConvenienceFunctions:
    @patch("ray_compute.api.client.RayComputeClient")
    def test_submit_training_job(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.submit_job.return_value = "job-train"
        mock_client_cls.return_value = mock_client
        result = submit_training_job("train", "print('hi')", gpu=True, mlflow_experiment="exp")
        assert result == "job-train"
        kwargs = mock_client.submit_job.call_args.kwargs
        assert kwargs["job_type"] == JobType.TRAINING
        assert kwargs["gpu"] == 1

    @patch("ray_compute.api.client.RayComputeClient")
    def test_submit_inference_job(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.submit_job.return_value = "job-inf"
        mock_client_cls.return_value = mock_client
        result = submit_inference_job("infer", "print('hi')", gpu=False)
        assert result == "job-inf"
        kwargs = mock_client.submit_job.call_args.kwargs
        assert kwargs["job_type"] == JobType.INFERENCE
        assert kwargs["gpu"] == 0

    @patch("ray_compute.api.client.RayComputeClient")
    def test_submit_dataset_curation_job(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.submit_job.return_value = "job-curate"
        mock_client_cls.return_value = mock_client
        result = submit_dataset_curation_job("curate", "print('hi')")
        assert result == "job-curate"
        kwargs = mock_client.submit_job.call_args.kwargs
        assert kwargs["job_type"] == JobType.DATASET_CURATION
        assert kwargs["gpu"] == 0
