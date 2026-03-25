from __future__ import annotations

import os
import pickle
import signal
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_torch_stub() -> MagicMock:
    stub = MagicMock(name="torch")
    stub.optim = MagicMock()
    stub.nn = MagicMock()
    return stub


for _mod_name in ["torch", "torch.nn", "torch.optim"]:
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = _make_torch_stub()

_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

_training_root = os.path.join(_root, "libs", "training")
if _training_root not in sys.path:
    sys.path.insert(0, _training_root)

from shml_training.core.checkpointing import (  # noqa: E402
    CheckpointManager,
    CheckpointMetadata,
    PreemptionHandler,
)


def _pickle_save(obj, path) -> None:
    with open(path, "wb") as handle:
        pickle.dump(obj, handle)


def _pickle_load(path, map_location=None):
    with open(path, "rb") as handle:
        return pickle.load(handle)


def _model() -> MagicMock:
    model = MagicMock(name="model")
    model.state_dict.return_value = {"weights": [1, 2, 3]}
    return model


def _optimizer() -> MagicMock:
    optimizer = MagicMock(name="optimizer")
    optimizer.state_dict.return_value = {"lr": 1e-4}
    return optimizer


def _scheduler() -> MagicMock:
    scheduler = MagicMock(name="scheduler")
    scheduler.state_dict.return_value = {"step": 3}
    return scheduler


class TestCheckpointMetadata:
    def test_round_trip(self):
        metadata = CheckpointMetadata(
            epoch=3,
            global_step=100,
            timestamp="2026-03-24T12:00:00",
            metrics={"loss": 0.2},
            config={"epochs": 10},
            is_best=True,
            is_preemption=False,
        )

        restored = CheckpointMetadata.from_dict(metadata.to_dict())

        assert restored == metadata


class TestCheckpointManager:
    def test_load_history_discovers_existing_checkpoints(self, tmp_path: Path):
        (tmp_path / "checkpoint_epoch1_step1.pt").write_bytes(b"a")
        (tmp_path / "best_epoch1.pt").write_bytes(b"b")

        manager = CheckpointManager(tmp_path)

        assert manager.get_latest_path() == tmp_path / "checkpoint_epoch1_step1.pt"
        assert manager.get_best_path() == tmp_path / "best_epoch1.pt"

    @patch("shml_training.core.checkpointing.torch.save", side_effect=_pickle_save)
    def test_save_regular_checkpoint_with_metadata(self, _mock_save, tmp_path: Path):
        manager = CheckpointManager(tmp_path, keep_last=3, keep_best=1)

        checkpoint_path = manager.save(
            epoch=2,
            model=_model(),
            optimizer=_optimizer(),
            scheduler=_scheduler(),
            metrics={"loss": 0.4},
            config={"epochs": 5},
            global_step=20,
            extra_state={"seed": 123},
        )

        assert checkpoint_path.name == "checkpoint_epoch2_step20.pt"
        assert checkpoint_path.exists()
        metadata_path = checkpoint_path.with_suffix(".json")
        assert metadata_path.exists()
        assert manager.get_latest_path() == checkpoint_path
        assert manager.get_best_path() == tmp_path / "best_epoch2.pt"

    @patch("shml_training.core.checkpointing.torch.save", side_effect=_pickle_save)
    def test_save_preemption_checkpoint_does_not_rotate_regular_keep_last(self, _mock_save, tmp_path: Path):
        manager = CheckpointManager(tmp_path, keep_last=1)

        regular = manager.save(epoch=1, model=_model(), global_step=10, metrics={"loss": 0.5})
        preempt = manager.save(
            epoch=2,
            model=_model(),
            global_step=20,
            metrics={"loss": 0.6},
            is_preemption=True,
        )

        assert regular.exists()
        assert preempt.exists()
        assert preempt.name.startswith("preemption_")

    @patch("shml_training.core.checkpointing.torch.save", side_effect=_pickle_save)
    def test_cleanup_old_removes_regular_checkpoints_beyond_limit(self, _mock_save, tmp_path: Path):
        manager = CheckpointManager(tmp_path, keep_last=2)

        first = manager.save(epoch=1, model=_model(), global_step=10, metrics={"loss": 0.9})
        second = manager.save(epoch=2, model=_model(), global_step=20, metrics={"loss": 0.8})
        third = manager.save(epoch=3, model=_model(), global_step=30, metrics={"loss": 0.7})

        assert not first.exists()
        assert second.exists()
        assert third.exists()
        assert manager.get_latest_path() == third

    @patch("shml_training.core.checkpointing.torch.save", side_effect=_pickle_save)
    def test_cleanup_best_respects_keep_best(self, _mock_save, tmp_path: Path):
        manager = CheckpointManager(tmp_path, keep_best=1)

        first = manager.save(epoch=1, model=_model(), global_step=10, metrics={"loss": 0.9})
        second = manager.save(epoch=2, model=_model(), global_step=20, metrics={"loss": 0.8})

        assert (tmp_path / "best_epoch1.pt").exists() is False
        assert (tmp_path / "best_epoch2.pt").exists() is True
        assert first.exists()
        assert second.exists()

    def test_check_is_best_handles_min_and_max_modes(self, tmp_path: Path):
        min_manager = CheckpointManager(tmp_path / "min", best_mode="min")
        max_manager = CheckpointManager(tmp_path / "max", best_mode="max")

        assert min_manager._check_is_best({"loss": 0.5}) is True
        assert min_manager._check_is_best({"loss": 0.6}) is False
        assert min_manager._check_is_best({"loss": 0.4}) is True

        assert max_manager._check_is_best({"accuracy": 0.6}) is False
        max_manager.best_metric = "accuracy"
        assert max_manager._check_is_best({"accuracy": 0.6}) is True
        assert max_manager._check_is_best({"accuracy": 0.5}) is False
        assert max_manager._check_is_best({"accuracy": 0.7}) is True

    @patch("shml_training.core.checkpointing.torch.load", side_effect=_pickle_load)
    def test_load_restores_all_states(self, _mock_load, tmp_path: Path):
        path = tmp_path / "checkpoint.pt"
        payload = {
            "epoch": 4,
            "global_step": 50,
            "model_state_dict": {"weights": [4]},
            "optimizer_state_dict": {"lr": 2e-4},
            "scheduler_state_dict": {"step": 9},
            "extra_state": {"seed": 99},
            "metadata": {"is_best": True},
        }
        _pickle_save(payload, path)

        manager = CheckpointManager(tmp_path)
        model = _model()
        optimizer = _optimizer()
        scheduler = _scheduler()

        loaded = manager.load(path, model, optimizer, scheduler, strict=False)

        model.load_state_dict.assert_called_once_with({"weights": [4]}, strict=False)
        optimizer.load_state_dict.assert_called_once_with({"lr": 2e-4})
        scheduler.load_state_dict.assert_called_once_with({"step": 9})
        assert loaded["epoch"] == 4
        assert loaded["global_step"] == 50
        assert loaded["extra_state"] == {"seed": 99}

    def test_load_missing_checkpoint_raises(self, tmp_path: Path):
        manager = CheckpointManager(tmp_path)

        with pytest.raises(FileNotFoundError, match="Checkpoint not found"):
            manager.load(tmp_path / "missing.pt", _model())

    def test_load_latest_and_best_return_none_when_empty(self, tmp_path: Path):
        manager = CheckpointManager(tmp_path)

        assert manager.load_latest(_model()) is None
        assert manager.load_best(_model()) is None
        assert manager.get_latest_path() is None
        assert manager.get_best_path() is None

    @patch("shml_training.core.checkpointing.torch.save", side_effect=_pickle_save)
    @patch("shml_training.core.checkpointing.torch.load", side_effect=_pickle_load)
    def test_load_latest_and_best_use_saved_checkpoints(self, _mock_load, _mock_save, tmp_path: Path):
        manager = CheckpointManager(tmp_path)
        manager.save(epoch=1, model=_model(), global_step=10, metrics={"loss": 0.9})
        manager.save(epoch=2, model=_model(), global_step=20, metrics={"loss": 0.8})

        latest = manager.load_latest(_model())
        best = manager.load_best(_model())

        assert latest["epoch"] == 2
        assert best["epoch"] == 2

    def test_list_checkpoints_uses_metadata_or_fallback(self, tmp_path: Path):
        checkpoint = tmp_path / "checkpoint_epoch1_step1.pt"
        checkpoint.write_bytes(b"1234")
        checkpoint.with_suffix(".json").write_text('{"epoch": 1, "global_step": 1}')

        fallback = tmp_path / "checkpoint_epoch2_step2.pt"
        fallback.write_bytes(b"5678")

        manager = CheckpointManager(tmp_path)
        listing = manager.list_checkpoints()

        by_name = {Path(item["path"]).name: item for item in listing}
        assert by_name["checkpoint_epoch1_step1.pt"]["epoch"] == 1
        assert by_name["checkpoint_epoch2_step2.pt"]["path"].endswith("checkpoint_epoch2_step2.pt")
        assert by_name["checkpoint_epoch2_step2.pt"]["size_mb"] > 0


class TestPreemptionHandler:
    def test_register_is_idempotent_and_unregister_restores_handlers(self):
        callback = MagicMock()
        handler = PreemptionHandler(callback, signals=[signal.SIGTERM])

        with patch("shml_training.core.checkpointing.signal.signal", return_value="old-handler") as mock_signal, \
             patch("shml_training.core.checkpointing.atexit.register") as mock_atexit:
            handler.register()
            handler.register()
            handler.unregister()

        assert mock_atexit.call_count == 1
        assert handler._registered is False
        assert mock_signal.call_args_list[0].args[0] == signal.SIGTERM

    def test_handle_sigusr1_requests_checkpoint_without_exit(self):
        callback = MagicMock()
        handler = PreemptionHandler(callback, signals=[signal.SIGUSR1] if hasattr(signal, "SIGUSR1") else [])

        signum = signal.SIGUSR1 if hasattr(signal, "SIGUSR1") else signal.SIGTERM
        if signum == signal.SIGTERM:
            pytest.skip("SIGUSR1 unavailable on this platform")

        handler._handle_signal(signum, None)

        callback.assert_called_once()
        assert handler.should_checkpoint() is True
        assert handler._checkpoint_done.is_set() is True

    def test_handle_sigterm_exits_after_checkpoint(self):
        callback = MagicMock()
        handler = PreemptionHandler(callback, signals=[signal.SIGTERM])

        with pytest.raises(SystemExit, match="0"):
            handler._handle_signal(signal.SIGTERM, None)

        callback.assert_called_once()
        assert handler._checkpoint_done.is_set() is True

    def test_handle_signal_failure_does_not_mark_checkpoint_done(self):
        callback = MagicMock(side_effect=RuntimeError("disk full"))
        handler = PreemptionHandler(callback, signals=[signal.SIGUSR1] if hasattr(signal, "SIGUSR1") else [])

        signum = signal.SIGUSR1 if hasattr(signal, "SIGUSR1") else signal.SIGTERM
        if signum == signal.SIGTERM:
            with pytest.raises(SystemExit):
                handler._handle_signal(signum, None)
        else:
            handler._handle_signal(signum, None)

        assert handler.should_checkpoint() is True
        assert handler._checkpoint_done.is_set() is False

    def test_atexit_handler_only_runs_when_checkpoint_not_done(self):
        callback = MagicMock()
        handler = PreemptionHandler(callback)

        handler._atexit_handler()
        callback.assert_called_once()

        callback.reset_mock()
        handler._checkpoint_done.set()
        handler._atexit_handler()
        callback.assert_not_called()

    def test_request_and_acknowledge_checkpoint(self):
        handler = PreemptionHandler(MagicMock())

        assert handler.should_checkpoint() is False
        handler.request_checkpoint()
        assert handler.should_checkpoint() is True
        handler.acknowledge_checkpoint()
        assert handler.should_checkpoint() is False
        assert handler._checkpoint_done.is_set() is True
