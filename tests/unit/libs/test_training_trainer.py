from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest


def _identity_decorator(*args, **kwargs):
    if args and callable(args[0]) and len(args) == 1 and not kwargs:
        return args[0]

    def decorator(func):
        return func

    return decorator


def _make_torch_stub():
    torch_stub = types.SimpleNamespace()
    torch_stub.Tensor = object
    torch_stub.FloatTensor = object
    torch_stub.BoolTensor = object
    torch_stub.device = object
    torch_stub.float32 = "float32"
    torch_stub.float16 = "float16"
    torch_stub.bfloat16 = "bfloat16"
    torch_stub.compile = _identity_decorator
    torch_stub.no_grad = _identity_decorator
    torch_stub.tensor = lambda *args, **kwargs: None
    torch_stub.zeros = lambda *args, **kwargs: None
    torch_stub.ones = lambda *args, **kwargs: None
    torch_stub.sigmoid = lambda value: value
    torch_stub.load = lambda *args, **kwargs: None
    torch_stub.save = lambda *args, **kwargs: None
    torch_stub.cuda = types.SimpleNamespace(
        is_available=lambda: False,
        device_count=lambda: 0,
    )
    torch_stub.nn = types.SimpleNamespace(Module=object, Parameter=object)
    torch_stub.optim = types.SimpleNamespace(Optimizer=object, AdamW=lambda *args, **kwargs: None)
    torch_stub.amp = types.SimpleNamespace()
    return torch_stub


for _module_name, _module in {
    "torch": _make_torch_stub(),
    "torch.nn": types.SimpleNamespace(Module=object, Parameter=object),
    "torch.optim": types.SimpleNamespace(Optimizer=object, AdamW=lambda *args, **kwargs: None),
    "torch.amp": types.SimpleNamespace(),
    "torch.cuda": types.SimpleNamespace(is_available=lambda: False, device_count=lambda: 0),
    "torch.utils": types.SimpleNamespace(),
    "torch.utils.data": types.SimpleNamespace(),
    "torch.distributed": types.SimpleNamespace(),
    "torch.nn.functional": types.SimpleNamespace(),
    "torch.nn.parallel": types.SimpleNamespace(),
}.items():
    sys.modules.setdefault(_module_name, _module)

for _dep in ["peft", "transformers", "unsloth", "accelerate", "deepspeed"]:
    sys.modules.setdefault(_dep, types.SimpleNamespace())

_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

_training_root = os.path.join(_root, "libs", "training")
if _training_root not in sys.path:
    sys.path.insert(0, _training_root)

from shml_training.core.callbacks import TrainingCallback
from shml_training.core.config import CheckpointConfig, TrainingConfig
from shml_training.core.trainer import Trainer, UltralyticsTrainer


class FakeParam:
    def __init__(self, shape: tuple[int, ...], requires_grad: bool = True):
        self.shape = shape
        self.requires_grad = requires_grad

    def dim(self) -> int:
        return len(self.shape)


class FakeModel:
    def __init__(self, params):
        self._params = params

    def parameters(self):
        return list(self._params)


class RecordingCallback(TrainingCallback):
    def __init__(self):
        self.events = []

    def on_run_start(self, trainer, config):
        self.events.append(("run_start", config["epochs"]))

    def on_run_end(self, trainer, metrics):
        self.events.append(("run_end", metrics))

    def on_epoch_start(self, trainer, epoch):
        self.events.append(("epoch_start", epoch))

    def on_epoch_end(self, trainer, epoch, metrics):
        self.events.append(("epoch_end", epoch, metrics.copy()))

    def on_validation_start(self, trainer, epoch):
        self.events.append(("validation_start", epoch))

    def on_validation_end(self, trainer, epoch, metrics):
        self.events.append(("validation_end", epoch, metrics.copy()))

    def on_checkpoint_saved(self, trainer, checkpoint_path, metrics):
        self.events.append(("checkpoint", checkpoint_path, metrics.copy()))

    def on_early_stop(self, trainer, epoch, reason):
        self.events.append(("early_stop", epoch, reason))

    def on_error(self, trainer, error):
        self.events.append(("error", str(error)))


class DemoTrainer(Trainer):
    def __init__(self, config: TrainingConfig, callbacks=None):
        super().__init__(config, callbacks)
        self.saved = []

    def _setup(self):
        self.global_step = 5

    def _train_epoch(self, epoch: int):
        self.callbacks.on_epoch_start(self, epoch)
        self.global_step += 10
        return {"loss": float(epoch) + 0.5}

    def _validate_epoch(self, epoch: int):
        self.callbacks.on_validation_start(self, epoch)
        metrics = {"val_accuracy": 0.8 + epoch}
        self.callbacks.on_validation_end(self, epoch, metrics)
        return metrics

    def _save_checkpoint(self, epoch: int, metrics):
        path = super()._save_checkpoint(epoch, metrics)
        self.saved.append((epoch, metrics.copy(), path))
        return path

    def _finalize(self):
        return {"best_accuracy": 0.9}


class EarlyStopTrainer(DemoTrainer):
    def _should_early_stop(self, epoch: int, metrics):
        return epoch == 0


class FailingTrainer(Trainer):
    def _setup(self):
        raise RuntimeError("setup exploded")


class FakeMuonAdamW:
    def __init__(self, param_groups):
        self.param_groups = param_groups


class FakeYOLO:
    last_instance = None

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.train_kwargs = None
        FakeYOLO.last_instance = self

    def train(self, **kwargs):
        self.train_kwargs = kwargs
        return types.SimpleNamespace(results_dict={"mAP50": 0.77})


class TestTrainerCheckpointConfig:
    def test_checkpoint_helpers_use_nested_checkpoint_config(self, monkeypatch):
        calls = []

        class FakeCheckpointManager:
            def __init__(self, checkpoint_dir, max_checkpoints):
                calls.append((checkpoint_dir, max_checkpoints))

        monkeypatch.setattr("shml_training.core.trainer.CheckpointManager", FakeCheckpointManager)

        config = TrainingConfig(
            checkpoint=CheckpointConfig(
                checkpoint_dir="/tmp/checkpoints",
                keep_last_n=7,
                save_every_n_epochs=3,
            )
        )
        trainer = Trainer(config)

        assert trainer.checkpoint_manager is trainer.checkpoint_manager
        assert calls == [("/tmp/checkpoints", 7)]
        assert trainer._save_checkpoint(2, {}) == "/tmp/checkpoints/epoch_2.pt"
        assert trainer._should_checkpoint(1) is False
        assert trainer._should_checkpoint(2) is True


class TestTrainerOptimizerSetup:
    def test_setup_optimizer_uses_only_trainable_params_for_adamw(self, monkeypatch):
        captured = {}

        def fake_adamw(params, lr, weight_decay):
            captured["params"] = params
            captured["lr"] = lr
            captured["weight_decay"] = weight_decay
            return "adamw"

        monkeypatch.setattr("shml_training.core.trainer.torch.optim.AdamW", fake_adamw)

        model = FakeModel([
            FakeParam((2, 2), requires_grad=True),
            FakeParam((4,), requires_grad=False),
        ])
        trainer = Trainer(TrainingConfig())

        optimizer = trainer._setup_optimizer(model)

        assert optimizer == "adamw"
        assert captured["params"] == [model.parameters()[0]]
        assert captured["lr"] == trainer.config.learning_rate
        assert captured["weight_decay"] == 0.1

    def test_setup_optimizer_builds_shape_bucketed_muon_hybrid_groups(self, monkeypatch):
        fake_optim_module = types.SimpleNamespace(MuonAdamW=FakeMuonAdamW)
        monkeypatch.setitem(sys.modules, "shml_training.core.optim", fake_optim_module)

        config = TrainingConfig(optimizer_type="muon_adamw")
        trainer = Trainer(config)
        model = FakeModel([
            FakeParam((2, 2)),
            FakeParam((2, 2)),
            FakeParam((3, 3)),
            FakeParam((4,)),
        ])

        optimizer = trainer._setup_optimizer(model)
        groups = optimizer.param_groups

        assert [group["kind"] for group in groups] == ["adamw", "muon", "muon"]
        assert len(groups[0]["params"]) == 1
        assert len(groups[1]["params"]) == 2
        assert len(groups[2]["params"]) == 1
        assert groups[0]["betas"] == (0.9, 0.95)
        assert groups[1]["momentum"] == 0.95
        assert groups[1]["ns_steps"] == 5

    def test_setup_optimizer_rejects_non_matrix_params_for_muon(self, monkeypatch):
        fake_optim_module = types.SimpleNamespace(MuonAdamW=FakeMuonAdamW)
        monkeypatch.setitem(sys.modules, "shml_training.core.optim", fake_optim_module)

        trainer = Trainer(TrainingConfig(optimizer_type="muon"))
        model = FakeModel([FakeParam((8, 8)), FakeParam((8,))])

        with pytest.raises(ValueError, match="Muon optimizer requires 2D parameters"):
            trainer._setup_optimizer(model)


class TestTrainerRunFlow:
    def test_train_runs_validation_checkpoint_and_finalize(self):
        callback = RecordingCallback()
        trainer = DemoTrainer(
            TrainingConfig(
                epochs=2,
                checkpoint=CheckpointConfig(
                    checkpoint_dir="/tmp/demo-checkpoints",
                    save_every_n_epochs=1,
                ),
            ),
            callbacks=[callback],
        )

        result = trainer.train()

        assert result == {
            "run_id": trainer.run_id,
            "epochs_trained": 2,
            "global_steps": 25,
            "metrics": {"best_accuracy": 0.9},
        }
        assert len(trainer.saved) == 2
        assert callback.events[0] == ("run_start", 2)
        assert ("epoch_start", 0) in callback.events
        assert ("validation_start", 1) in callback.events
        assert callback.events[-1] == ("run_end", {"best_accuracy": 0.9})

    def test_train_honors_early_stop(self):
        callback = RecordingCallback()
        trainer = EarlyStopTrainer(
            TrainingConfig(
                epochs=3,
                checkpoint=CheckpointConfig(checkpoint_dir="/tmp/early-stop"),
            ),
            callbacks=[callback],
        )

        result = trainer.train()

        assert result["epochs_trained"] == 1
        assert any(event[0] == "early_stop" for event in callback.events)

    def test_train_notifies_error_and_reraises(self):
        callback = RecordingCallback()
        trainer = FailingTrainer(TrainingConfig(), callbacks=[callback])

        with pytest.raises(RuntimeError, match="setup exploded"):
            trainer.train()

        assert ("error", "setup exploded") in callback.events


class TestUltralyticsTrainer:
    def test_train_uses_nested_checkpoint_dir_and_extracts_metrics(self, monkeypatch):
        fake_ultralytics = types.SimpleNamespace(YOLO=FakeYOLO)
        monkeypatch.setitem(sys.modules, "ultralytics", fake_ultralytics)

        callback = RecordingCallback()
        trainer = UltralyticsTrainer(
            TrainingConfig(
                epochs=3,
                batch_size=4,
                device="cpu",
                checkpoint=CheckpointConfig(checkpoint_dir="/tmp/runs/exp1"),
            ),
            model_name="demo.pt",
            callbacks=[callback],
        )

        result = trainer.train()
        train_kwargs = FakeYOLO.last_instance.train_kwargs

        assert FakeYOLO.last_instance.model_name == "demo.pt"
        assert train_kwargs["project"] == Path("/tmp/runs")
        assert train_kwargs["name"] == "exp1"
        assert train_kwargs["epochs"] == 3
        assert result["metrics"] == {"mAP50": 0.77}
        assert callback.events[0] == ("run_start", 3)
        assert callback.events[-1] == ("run_end", {"mAP50": 0.77})

    def test_extract_ultralytics_metrics_handles_alternate_shapes(self):
        trainer = UltralyticsTrainer(TrainingConfig())

        assert trainer._extract_ultralytics_metrics(None) == {}
        assert trainer._extract_ultralytics_metrics(
            types.SimpleNamespace(metrics={"loss": 1.2})
        ) == {"loss": 1.2}
