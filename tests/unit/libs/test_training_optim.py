from __future__ import annotations

import importlib
import importlib.util
import math
import os
import sys
import types
from collections import defaultdict

import pytest


class FakeTensor:
    def __init__(self, shape=(), label=None, dtype="float32", device="cpu", children=None):
        self.shape = tuple(shape) if isinstance(shape, (list, tuple)) else (shape,)
        if self.shape == (None,):
            self.shape = ()
        self.label = label
        self.dtype = dtype
        self.device = device
        self.children = children
        self.grad = None
        self.copied_from = None
        self.zeroed = False
        self.fill_value = None

    @property
    def mT(self):
        if len(self.shape) < 2:
            return FakeTensor(self.shape, label=self.label, dtype=self.dtype, device=self.device)
        swapped = (*self.shape[:-2], self.shape[-1], self.shape[-2])
        return FakeTensor(swapped, label=self.label, dtype=self.dtype, device=self.device)

    def __len__(self):
        return self.shape[0] if self.shape else 0

    def size(self, dim=None):
        if dim is None:
            return self.shape
        if dim < 0:
            dim += len(self.shape)
        return self.shape[dim]

    def numel(self):
        if not self.shape:
            return 1
        return math.prod(self.shape)

    def copy_(self, other):
        self.copied_from = other
        return self

    def zero_(self):
        self.zeroed = True
        return self

    def fill_(self, value):
        self.fill_value = value
        return self

    def unbind(self, dim=0):
        if self.children is not None:
            return list(self.children)
        if dim != 0 or not self.shape:
            return []
        child_shape = self.shape[1:]
        return [FakeTensor(child_shape, dtype=self.dtype, device=self.device) for _ in range(self.shape[0])]

    def to(self, dtype=None):
        if dtype is not None:
            self.dtype = dtype
        return self

    def float(self):
        self.dtype = "float32"
        return self

    def bfloat16(self):
        self.dtype = "bfloat16"
        return self

    def square(self):
        return FakeTensor(self.shape, dtype=self.dtype, device=self.device)

    def sqrt(self):
        return FakeTensor(self.shape, dtype=self.dtype, device=self.device)

    def clamp_min(self, _value):
        return FakeTensor(self.shape, dtype=self.dtype, device=self.device)

    def rsqrt(self):
        return FakeTensor(self.shape, dtype=self.dtype, device=self.device)

    def norm(self, dim=None, keepdim=False):
        return FakeTensor(_reduced_shape(self.shape, dim, keepdim), dtype=self.dtype, device=self.device)

    def mean(self, dim=None, keepdim=False):
        return FakeTensor(_reduced_shape(self.shape, dim, keepdim), dtype=self.dtype, device=self.device)

    def sum(self, dim=None, keepdim=False):
        return FakeTensor(_reduced_shape(self.shape, dim, keepdim), dtype=self.dtype, device=self.device)

    def lerp_(self, _other, _weight):
        return self

    def mul_(self, _other):
        return self

    def add_(self, _other, alpha=None):
        return self

    def sub_(self, _other):
        return self

    def __getitem__(self, key):
        if isinstance(key, slice):
            start, stop, step = key.indices(self.shape[0])
            length = max(0, (stop - start + (step - 1)) // step)
            return FakeTensor((length, *self.shape[1:]), dtype=self.dtype, device=self.device)
        if isinstance(key, tuple):
            current = self
            for item in key:
                current = current[item]
            return current
        if isinstance(key, int):
            return FakeTensor(self.shape[1:], dtype=self.dtype, device=self.device)
        raise TypeError(f"Unsupported key: {key!r}")

    def __pow__(self, _other):
        return FakeTensor(self.shape, dtype=self.dtype, device=self.device)

    def __truediv__(self, _other):
        return FakeTensor(self.shape, dtype=self.dtype, device=self.device)

    def __rtruediv__(self, _other):
        return FakeTensor(self.shape, dtype=self.dtype, device=self.device)

    def __mul__(self, _other):
        return FakeTensor(self.shape, dtype=self.dtype, device=self.device)

    def __rmul__(self, _other):
        return FakeTensor(self.shape, dtype=self.dtype, device=self.device)

    def __add__(self, _other):
        return FakeTensor(self.shape, dtype=self.dtype, device=self.device)

    def __radd__(self, _other):
        return FakeTensor(self.shape, dtype=self.dtype, device=self.device)

    def __sub__(self, _other):
        return FakeTensor(self.shape, dtype=self.dtype, device=self.device)

    def __rsub__(self, _other):
        return FakeTensor(self.shape, dtype=self.dtype, device=self.device)

    def __matmul__(self, _other):
        return FakeTensor(self.shape, dtype=self.dtype, device=self.device)

    def __ge__(self, _other):
        return FakeTensor(self.shape, dtype=self.dtype, device=self.device)

    def __neg__(self):
        return FakeTensor(self.shape, dtype=self.dtype, device=self.device)


def _reduced_shape(shape, dim, keepdim):
    if dim is None:
        return tuple(1 for _ in shape) if keepdim else ()
    dims = dim if isinstance(dim, tuple) else (dim,)
    normalized = set()
    for item in dims:
        normalized.add(item if item >= 0 else len(shape) + item)
    if keepdim:
        return tuple(1 if index in normalized else size for index, size in enumerate(shape))
    return tuple(size for index, size in enumerate(shape) if index not in normalized)


class FakeFuture:
    def __init__(self):
        self.waited = False

    def wait(self):
        self.waited = True
        return self


class FakeWork:
    def __init__(self):
        self.future = FakeFuture()

    def get_future(self):
        return self.future


class FakeOptimizer:
    def __init__(self, param_groups, defaults):
        self.param_groups = param_groups
        self.defaults = defaults
        self.state = defaultdict(dict)


class FakeDistModule(types.SimpleNamespace):
    def __init__(self):
        super().__init__()
        self.ReduceOp = types.SimpleNamespace(AVG="avg")
        self._rank = 0
        self._world_size = 2
        self.all_reduce_calls = []
        self.reduce_scatter_calls = []
        self.all_gather_calls = []

    def all_reduce(self, tensor, op=None, async_op=False):
        self.all_reduce_calls.append((tensor, op, async_op))
        return FakeWork()

    def reduce_scatter_tensor(self, output, tensor, op=None, async_op=False):
        output.copied_from = tensor
        self.reduce_scatter_calls.append((output, tensor, op, async_op))
        return FakeWork()

    def all_gather_into_tensor(self, output, tensor, async_op=False):
        output.copied_from = tensor
        self.all_gather_calls.append((output, tensor, async_op))
        return FakeWork()

    def get_rank(self):
        return self._rank

    def get_world_size(self):
        return self._world_size


def _identity_decorator(*args, **kwargs):
    if args and callable(args[0]) and len(args) == 1 and not kwargs:
        return args[0]

    def decorator(func):
        return func

    return decorator


def _install_torch_stub():
    fake_dist = FakeDistModule()

    torch_module = types.ModuleType("torch")
    torch_module.Tensor = FakeTensor
    torch_module.float32 = "float32"
    torch_module.bfloat16 = "bfloat16"
    torch_module.compile = _identity_decorator
    torch_module.no_grad = _identity_decorator
    torch_module.tensor = lambda *args, **kwargs: FakeTensor((), dtype=kwargs.get("dtype", "float32"), device=kwargs.get("device", "cpu"))
    torch_module.zeros_like = lambda tensor: FakeTensor(tensor.shape, dtype=tensor.dtype, device=tensor.device)
    torch_module.empty_like = lambda tensor: FakeTensor(tensor.shape, dtype=tensor.dtype, device=tensor.device)
    torch_module.zeros = lambda *shape, **kwargs: FakeTensor(shape[0] if len(shape) == 1 and isinstance(shape[0], tuple) else shape, dtype=kwargs.get("dtype", "float32"), device=kwargs.get("device", "cpu"))
    torch_module.empty = lambda *shape, **kwargs: FakeTensor(shape[0] if len(shape) == 1 and isinstance(shape[0], tuple) else shape, dtype=kwargs.get("dtype", "float32"), device=kwargs.get("device", "cpu"))
    torch_module.stack = lambda tensors: FakeTensor((len(tensors), *tensors[0].shape), dtype=tensors[0].dtype, device=tensors[0].device, children=list(tensors))
    torch_module._foreach_copy_ = lambda params, srcs: [setattr(param, "copied_from", src) for param, src in zip(params, srcs)]
    torch_module.optim = types.SimpleNamespace(Optimizer=FakeOptimizer)
    torch_module.distributed = fake_dist

    sys.modules["torch"] = torch_module
    sys.modules["torch.optim"] = torch_module.optim
    sys.modules["torch.distributed"] = fake_dist

    return fake_dist


def _load_optim_module():
    repo_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
    module_path = os.path.join(repo_root, "libs", "training", "shml_training", "core", "optim.py")
    module_name = "test_shml_training_core_optim"

    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _restore_torch_modules():
    tracked = ["torch", "torch.optim", "torch.distributed", "test_shml_training_core_optim"]
    original = {name: sys.modules.get(name) for name in tracked}
    try:
        yield
    finally:
        for name, module in original.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _param(shape):
    tensor = FakeTensor(shape)
    tensor.grad = FakeTensor(shape)
    return tensor


def test_fused_adamw_step_executes_with_tensor_stub():
    _install_torch_stub()
    optim = _load_optim_module()

    optim.adamw_step_fused(
        FakeTensor((4, 4)),
        FakeTensor((4, 4)),
        FakeTensor((4, 4)),
        FakeTensor((4, 4)),
        FakeTensor(()),
        FakeTensor(()),
        FakeTensor(()),
        FakeTensor(()),
        FakeTensor(()),
        FakeTensor(()),
    )


def test_fused_muon_step_executes_for_tall_and_wide_shapes():
    _install_torch_stub()
    optim = _load_optim_module()

    optim.muon_step_fused(
        FakeTensor((2, 4, 2)),
        FakeTensor((2, 4, 2)),
        FakeTensor((2, 4, 2)),
        FakeTensor((2, 4, 1)),
        FakeTensor(()),
        FakeTensor(()),
        FakeTensor(()),
        FakeTensor(()),
        2,
        -1,
    )
    optim.muon_step_fused(
        FakeTensor((2, 2, 4)),
        FakeTensor((2, 2, 4)),
        FakeTensor((2, 2, 4)),
        FakeTensor((2, 1, 4)),
        FakeTensor(()),
        FakeTensor(()),
        FakeTensor(()),
        FakeTensor(()),
        2,
        -2,
    )


def test_muon_adamw_runs_adamw_and_muon_groups(monkeypatch):
    _install_torch_stub()
    optim = _load_optim_module()

    adamw_calls = []
    muon_calls = []
    monkeypatch.setattr(optim, "adamw_step_fused", lambda *args: adamw_calls.append(args))
    monkeypatch.setattr(optim, "muon_step_fused", lambda *args: muon_calls.append(args))

    adamw_param = _param((2, 2))
    muon_param_a = _param((3, 2))
    muon_param_b = _param((3, 2))
    optimizer = optim.MuonAdamW(
        [
            {
                "params": [adamw_param],
                "kind": "adamw",
                "lr": 0.001,
                "betas": (0.9, 0.95),
                "eps": 1e-8,
                "weight_decay": 0.1,
            },
            {
                "params": [muon_param_a, muon_param_b],
                "kind": "muon",
                "lr": 0.01,
                "momentum": 0.95,
                "beta2": 0.99,
                "weight_decay": 0.0,
                "ns_steps": 3,
            },
        ]
    )

    optimizer.step()

    assert len(adamw_calls) == 1
    assert len(muon_calls) == 1
    assert optimizer.state[adamw_param]["step"] == 1
    assert "momentum_buffer" in optimizer.state[muon_param_a]
    assert muon_param_a.copied_from is not None
    assert muon_param_b.copied_from is not None


def test_muon_adamw_rejects_unknown_group_kind():
    _install_torch_stub()
    optim = _load_optim_module()

    optimizer = optim.MuonAdamW([{"params": [], "kind": "mystery"}])

    try:
        optimizer.step()
    except ValueError as exc:
        assert "Unknown optimizer kind" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unknown optimizer kind")


def test_dist_muon_adamw_reduce_and_compute_paths(monkeypatch):
    fake_dist = _install_torch_stub()
    optim = _load_optim_module()

    adamw_small = _param((4, 4))
    adamw_large = _param((2048, 2))
    muon_a = _param((4, 2))
    muon_b = _param((4, 2))
    muon_c = _param((4, 2))

    optimizer = optim.DistMuonAdamW(
        [
            {
                "params": [adamw_small, adamw_large],
                "kind": "adamw",
                "lr": 0.001,
                "betas": (0.9, 0.95),
                "eps": 1e-8,
                "weight_decay": 0.1,
            },
            {
                "params": [muon_a, muon_b, muon_c],
                "kind": "muon",
                "lr": 0.01,
                "momentum": 0.95,
                "beta2": 0.99,
                "weight_decay": 0.0,
                "ns_steps": 2,
            },
        ]
    )

    adamw_calls = []
    muon_calls = []
    monkeypatch.setattr(optim, "adamw_step_fused", lambda *args: adamw_calls.append(args))
    monkeypatch.setattr(optim, "muon_step_fused", lambda *args: muon_calls.append(args))
    fake_dist._rank = 1
    fake_dist._world_size = 2

    adamw_info = optimizer._reduce_adamw(optimizer.param_groups[0], fake_dist.get_world_size())
    muon_info = optimizer._reduce_muon(optimizer.param_groups[1], fake_dist.get_world_size())
    gather_list = []
    optimizer._compute_adamw(
        optimizer.param_groups[0],
        adamw_info,
        gather_list,
        fake_dist.get_rank(),
        fake_dist.get_world_size(),
    )
    optimizer._compute_muon(
        optimizer.param_groups[1],
        muon_info,
        gather_list,
        fake_dist.get_rank(),
    )
    optimizer._finish_gathers(gather_list)

    assert len(fake_dist.all_reduce_calls) == 1
    assert len(fake_dist.reduce_scatter_calls) == 2
    assert len(fake_dist.all_gather_calls) == 2
    assert len(adamw_calls) == 2
    assert len(muon_calls) == 1
    assert optimizer.state[adamw_small]["step"] == 1
    assert optimizer.state[adamw_large]["step"] == 1
    assert "momentum_buffer" in optimizer.state[muon_a]
    assert muon_a.copied_from is not None
    assert muon_b.copied_from is not None
    assert muon_c.copied_from is not None


def test_dist_muon_adamw_step_dispatch_and_unknown_kind(monkeypatch):
    fake_dist = _install_torch_stub()
    optim = _load_optim_module()

    optimizer = optim.DistMuonAdamW(
        [
            {"params": [], "kind": "adamw"},
            {"params": [], "kind": "muon"},
        ]
    )
    calls = []
    fake_dist._rank = 0
    fake_dist._world_size = 2

    monkeypatch.setattr(optimizer, "_reduce_adamw", lambda group, world_size: calls.append(("reduce_adamw", world_size)) or {"param_infos": {}})
    monkeypatch.setattr(optimizer, "_reduce_muon", lambda group, world_size: calls.append(("reduce_muon", world_size)) or {"future": FakeFuture(), "chunk_size": 0, "grad_chunk": FakeTensor((0, 2, 2)), "stacked_grads": FakeTensor((0, 2, 2))})
    monkeypatch.setattr(optimizer, "_compute_adamw", lambda group, info, gather_list, rank, world_size: calls.append(("compute_adamw", rank, world_size)))
    monkeypatch.setattr(optimizer, "_compute_muon", lambda group, info, gather_list, rank: calls.append(("compute_muon", rank)))
    monkeypatch.setattr(optimizer, "_finish_gathers", lambda gather_list: calls.append(("finish", len(gather_list))))

    optimizer.step()

    assert calls == [
        ("reduce_adamw", 2),
        ("reduce_muon", 2),
        ("compute_adamw", 0, 2),
        ("compute_muon", 0),
        ("finish", 0),
    ]

    bad_optimizer = optim.DistMuonAdamW([{"params": [], "kind": "broken"}])
    try:
        bad_optimizer.step()
    except ValueError as exc:
        assert "Unknown optimizer kind" in str(exc)
    else:
        raise AssertionError("Expected ValueError for unknown optimizer kind")
