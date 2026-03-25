from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock


_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

_training_root = os.path.join(_root, "libs", "training")
if _training_root not in sys.path:
    sys.path.insert(0, _training_root)

from shml_training.core.callbacks import CallbackList, TrainingCallback  # noqa: E402


class _RecordingCallback(TrainingCallback):
    def __init__(self, name: str):
        self.name = name
        self.events: list[tuple[str, tuple[object, ...]]] = []

    def _record(self, event: str, *args: object) -> None:
        self.events.append((event, args))

    def on_run_start(self, trainer: "Trainer", config):
        self._record("run_start", trainer, config)

    def on_run_end(self, trainer: "Trainer", metrics):
        self._record("run_end", trainer, metrics)

    def on_epoch_start(self, trainer: "Trainer", epoch: int):
        self._record("epoch_start", trainer, epoch)

    def on_epoch_end(self, trainer: "Trainer", epoch: int, metrics):
        self._record("epoch_end", trainer, epoch, metrics)

    def on_batch_start(self, trainer: "Trainer", batch_idx: int, batch):
        self._record("batch_start", trainer, batch_idx, batch)

    def on_batch_end(self, trainer: "Trainer", batch_idx: int, batch, outputs):
        self._record("batch_end", trainer, batch_idx, batch, outputs)

    def on_step(self, trainer: "Trainer", step: int, loss: float, metrics=None):
        self._record("step", trainer, step, loss, metrics)

    def on_validation_start(self, trainer: "Trainer", epoch: int):
        self._record("validation_start", trainer, epoch)

    def on_validation_end(self, trainer: "Trainer", epoch: int, metrics):
        self._record("validation_end", trainer, epoch, metrics)

    def on_checkpoint_saved(self, trainer: "Trainer", checkpoint_path: str, metrics):
        self._record("checkpoint_saved", trainer, checkpoint_path, metrics)

    def on_early_stop(self, trainer: "Trainer", epoch: int, reason: str):
        self._record("early_stop", trainer, epoch, reason)

    def on_error(self, trainer: "Trainer", error: Exception):
        self._record("error", trainer, error)


class TestCallbackList:
    def test_add_and_remove_callback(self):
        callback = _RecordingCallback("one")
        callbacks = CallbackList()

        callbacks.add_callback(callback)
        assert callbacks.callbacks == [callback]

        callbacks.remove_callback(callback)
        assert callbacks.callbacks == []

    def test_dispatches_all_events_in_order(self):
        first = _RecordingCallback("first")
        second = _RecordingCallback("second")
        callbacks = CallbackList([first, second])
        trainer = MagicMock(name="trainer")
        batch = {"x": 1}
        outputs = {"loss": 0.2}
        metrics = {"accuracy": 0.9}
        error = RuntimeError("boom")

        callbacks.on_run_start(trainer, {"epochs": 1})
        callbacks.on_epoch_start(trainer, 1)
        callbacks.on_batch_start(trainer, 3, batch)
        callbacks.on_batch_end(trainer, 3, batch, outputs)
        callbacks.on_step(trainer, 4, 0.2, metrics)
        callbacks.on_validation_start(trainer, 1)
        callbacks.on_validation_end(trainer, 1, metrics)
        callbacks.on_checkpoint_saved(trainer, "/tmp/model.pt", metrics)
        callbacks.on_early_stop(trainer, 1, "plateau")
        callbacks.on_error(trainer, error)
        callbacks.on_epoch_end(trainer, 1, metrics)
        callbacks.on_run_end(trainer, metrics)

        expected_order = [
            "run_start",
            "epoch_start",
            "batch_start",
            "batch_end",
            "step",
            "validation_start",
            "validation_end",
            "checkpoint_saved",
            "early_stop",
            "error",
            "epoch_end",
            "run_end",
        ]
        assert [event for event, _ in first.events] == expected_order
        assert [event for event, _ in second.events] == expected_order

    def test_on_step_allows_none_metrics(self):
        callback = _RecordingCallback("one")
        callbacks = CallbackList([callback])

        callbacks.on_step(MagicMock(name="trainer"), 10, 0.5)

        assert callback.events == [("step", (callbacks.callbacks[0].events[0][1][0], 10, 0.5, None))] or callback.events[0][0] == "step"
        assert callback.events[0][1][1:] == (10, 0.5, None)
