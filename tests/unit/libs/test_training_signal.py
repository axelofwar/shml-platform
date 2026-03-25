from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


_ROOT = Path(__file__).resolve().parents[3]
_TRAINING_ROOT = _ROOT / "libs" / "training"

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if str(_TRAINING_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRAINING_ROOT))


class TestFileSignals:
    def test_create_file_signal_writes_expected_payload(self, tmp_path: Path):
        from shml_training.core.signal import _create_file_signal, signal_config

        original_dir = signal_config.signal_dir
        signal_config.signal_dir = str(tmp_path)
        try:
            signal_file = _create_file_signal("job-123", [0, 1], priority=7)
        finally:
            signal_config.signal_dir = original_dir

        assert signal_file == tmp_path / "job-123.signal"
        payload = json.loads(signal_file.read_text())
        assert payload["job_id"] == "job-123"
        assert payload["gpus"] == [0, 1]
        assert payload["priority"] == 7
        assert payload["pid"] == os.getpid()

    def test_create_file_signal_returns_none_on_failure(self, tmp_path: Path):
        from shml_training.core.signal import _create_file_signal, signal_config

        original_dir = signal_config.signal_dir
        signal_config.signal_dir = str(tmp_path)
        try:
            with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
                assert _create_file_signal("job-123") is None
        finally:
            signal_config.signal_dir = original_dir

    def test_remove_file_signal_deletes_existing_file(self, tmp_path: Path):
        from shml_training.core.signal import _remove_file_signal, signal_config

        signal_file = tmp_path / "job-123.signal"
        signal_file.write_text("{}")
        original_dir = signal_config.signal_dir
        signal_config.signal_dir = str(tmp_path)
        try:
            _remove_file_signal("job-123")
        finally:
            signal_config.signal_dir = original_dir

        assert not signal_file.exists()


class TestHttpAndWaitHelpers:
    def test_send_http_signal_start_uses_first_successful_service(self):
        from shml_training.core.signal import _send_http_signal

        responses = [
            MagicMock(status_code=200, json=MagicMock(return_value={"status": "ok"})),
            MagicMock(status_code=200, json=MagicMock(return_value={"status": "yielded"})),
        ]

        with patch("httpx.post", side_effect=responses) as mock_post:
            result = _send_http_signal(
                "start",
                "job-123",
                gpus=[0],
                priority=9,
                metadata={"source": "test"},
            )

        assert result is True
        first_call = mock_post.call_args_list[0]
        assert first_call.kwargs["json"]["job_id"] == "job-123"
        assert first_call.kwargs["json"]["gpus"] == [0]
        assert first_call.kwargs["json"]["priority"] == 9
        assert first_call.kwargs["json"]["metadata"] == {"source": "test"}

    def test_send_http_signal_returns_false_when_all_services_fail(self):
        from shml_training.core.signal import _send_http_signal

        failure = RuntimeError("offline")
        with patch("httpx.post", side_effect=failure):
            assert _send_http_signal("stop", "job-123") is False

    def test_wait_for_gpu_resources_returns_true_when_gpu_is_free(self):
        from shml_training.core.signal import _wait_for_gpu_resources

        completed = MagicMock(returncode=0, stdout="12000, 16000\n")
        with patch("subprocess.run", return_value=completed):
            assert _wait_for_gpu_resources(timeout=0.1) is True

    def test_wait_for_gpu_resources_times_out_when_gpu_remains_busy(self):
        from shml_training.core.signal import _wait_for_gpu_resources

        completed = MagicMock(returncode=0, stdout="1000, 16000\n")
        with patch("subprocess.run", return_value=completed), patch("time.sleep"):
            assert _wait_for_gpu_resources(timeout=0.01) is False


class TestPublicSignals:
    def test_signal_training_start_uses_file_signal_as_fallback(self):
        from shml_training.core.signal import signal_training_start

        with patch("shml_training.core.signal._send_http_signal", return_value=False), patch(
            "shml_training.core.signal._create_file_signal",
            return_value=Path("/tmp/fallback.signal"),
        ) as create_signal, patch(
            "shml_training.core.signal._wait_for_gpu_resources",
            return_value=True,
        ) as wait_for_gpu:
            result = signal_training_start("job-123", gpus=[0], wait_for_yield=True)

        assert result is True
        create_signal.assert_called_once_with("job-123", [0], 10)
        wait_for_gpu.assert_called_once()

    def test_signal_training_start_respects_fail_on_yield_timeout(self):
        from shml_training.core.signal import signal_config, signal_training_start

        original_fail = signal_config.fail_on_yield_timeout
        signal_config.fail_on_yield_timeout = True
        try:
            with patch("shml_training.core.signal._send_http_signal", return_value=True), patch(
                "shml_training.core.signal._create_file_signal",
                return_value=None,
            ), patch(
                "shml_training.core.signal._wait_for_gpu_resources",
                return_value=False,
            ):
                assert signal_training_start("job-123", wait_for_yield=True) is False
        finally:
            signal_config.fail_on_yield_timeout = original_fail

    def test_signal_training_stop_reports_success_from_file_cleanup(self):
        from shml_training.core.signal import signal_training_stop

        with patch("shml_training.core.signal._send_http_signal", return_value=False), patch(
            "shml_training.core.signal._remove_file_signal"
        ) as remove_signal:
            result = signal_training_stop("job-123")

        assert result is True
        remove_signal.assert_called_once_with("job-123")


class TestTrainingContextAndDecorator:
    def test_training_context_signals_and_restores_handlers(self):
        from shml_training.core.signal import training_context

        original_sigint = object()
        original_sigterm = object()
        current_handlers: dict[int, object] = {}

        def fake_signal(sig: int, handler=None):
            if handler is None:
                return current_handlers[sig]
            current_handlers[sig] = handler
            return handler

        current_handlers = {
            __import__("signal").SIGINT: original_sigint,
            __import__("signal").SIGTERM: original_sigterm,
        }

        with patch("shml_training.core.signal.signal_training_start", return_value=True) as start_signal, patch(
            "shml_training.core.signal.signal_training_stop"
        ) as stop_signal, patch("shml_training.core.signal.signal.getsignal", side_effect=lambda sig: current_handlers[sig]), patch(
            "shml_training.core.signal.signal.signal",
            side_effect=fake_signal,
        ) as set_signal, patch("shml_training.core.signal.atexit.register") as register_exit, patch(
            "shml_training.core.signal.atexit.unregister"
        ) as unregister_exit:
            with training_context(job_id="job-123", gpus=[0], metadata={"run": 1}) as ctx:
                assert ctx == {"job_id": "job-123", "gpus": [0]}

        start_signal.assert_called_once_with(
            job_id="job-123",
            gpus=[0],
            priority=10,
            wait_for_yield=True,
            metadata={"run": 1},
        )
        assert stop_signal.call_count == 1
        register_exit.assert_called_once()
        unregister_exit.assert_called_once()
        assert set_signal.call_args_list[-2].args[1] is original_sigint
        assert set_signal.call_args_list[-1].args[1] is original_sigterm

    def test_training_context_signal_handler_only_calls_callable_original(self):
        import signal as signal_module

        from shml_training.core.signal import training_context

        handlers: dict[int, object] = {
            signal_module.SIGINT: signal_module.SIG_IGN,
            signal_module.SIGTERM: signal_module.SIG_DFL,
        }

        def fake_signal(sig: int, handler=None):
            if handler is None:
                return handlers[sig]
            previous = handlers[sig]
            handlers[sig] = handler
            return previous

        with patch("shml_training.core.signal.signal_training_start", return_value=True), patch(
            "shml_training.core.signal.signal_training_stop"
        ) as stop_signal, patch("shml_training.core.signal.signal.getsignal", side_effect=lambda sig: handlers[sig]), patch(
            "shml_training.core.signal.signal.signal",
            side_effect=fake_signal,
        ), patch("shml_training.core.signal.atexit.register"), patch(
            "shml_training.core.signal.atexit.unregister"
        ):
            with training_context(job_id="job-123"):
                handlers[signal_module.SIGINT](signal_module.SIGINT, None)
                handlers[signal_module.SIGTERM](signal_module.SIGTERM, None)

        assert stop_signal.call_count == 3

    def test_training_context_stops_on_exception(self):
        from shml_training.core.signal import training_context

        with patch("shml_training.core.signal.signal_training_start", return_value=True), patch(
            "shml_training.core.signal.signal_training_stop"
        ) as stop_signal, patch("shml_training.core.signal.signal.getsignal", return_value=None), patch(
            "shml_training.core.signal.signal.signal"
        ), patch("shml_training.core.signal.atexit.register"), patch(
            "shml_training.core.signal.atexit.unregister"
        ):
            with pytest.raises(RuntimeError, match="boom"):
                with training_context(job_id="job-123"):
                    raise RuntimeError("boom")

        stop_signal.assert_called_once_with("job-123")

    def test_requires_gpu_wraps_function_in_training_context(self):
        from shml_training.core.signal import requires_gpu

        with patch("shml_training.core.signal.training_context") as training_ctx:
            training_ctx.return_value.__enter__.return_value = {"job_id": "job-123"}

            @requires_gpu(job_id="job-123", gpus=[0], priority=4, wait_for_yield=False)
            def compute(value: int) -> int:
                return value * 2

            result = compute(5)

        assert result == 10
        training_ctx.assert_called_once_with(
            job_id="job-123",
            gpus=[0],
            priority=4,
            wait_for_yield=False,
        )


class TestSignalCli:
    def test_main_start_and_stop_paths(self, capsys):
        from shml_training.core import signal as signal_module

        with patch.object(sys, "argv", ["signal.py", "start", "--job-id", "job-123", "--no-wait"]), patch(
            "shml_training.core.signal.signal_training_start",
            return_value=True,
        ) as start_signal:
            signal_module.main()

        start_output = capsys.readouterr().out
        assert "Job ID: job-123" in start_output
        assert "success" in start_output
        start_signal.assert_called_once_with(
            job_id="job-123",
            gpus=None,
            priority=10,
            wait_for_yield=False,
        )

        with patch.object(sys, "argv", ["signal.py", "stop", "--job-id", "job-123"]), patch(
            "shml_training.core.signal.signal_training_stop",
            return_value=True,
        ) as stop_signal:
            signal_module.main()

        stop_output = capsys.readouterr().out
        assert "success" in stop_output
        stop_signal.assert_called_once_with("job-123")

    def test_main_status_failure_exits_with_code_one(self, capsys):
        from shml_training.core import signal as signal_module

        with patch.object(sys, "argv", ["signal.py", "status"]), patch(
            "httpx.get",
            side_effect=RuntimeError("offline"),
        ), pytest.raises(SystemExit) as exc:
            signal_module.main()

        assert exc.value.code == 1
        assert "Failed to get status: offline" in capsys.readouterr().out
