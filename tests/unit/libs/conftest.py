"""conftest.py for tests/unit/libs/.

Stubs torch and other heavy ML deps at the earliest possible point
(pytest's conftest.py import phase, before any test module is collected).

This prevents ModuleNotFoundError when running all unit tests together —
if a higher-level conftest or another test module has imported a different
version / cleared these stubs.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

_TORCH_CHILD_MODULES = [
    "torch", "torch.nn", "torch.optim", "torch.amp", "torch.cuda",
    "torch.utils", "torch.utils.data", "torch.distributed",
    "torch.nn.functional", "torch.nn.parallel",
    "torch.cuda.amp",
]

if "torch" not in sys.modules:
    _t = MagicMock(name="torch")
    _t.__version__ = "2.0.0"  # simple_eval.py prints torch.__version__
    _t.cuda.is_available = MagicMock(return_value=False)
    _t.cuda.device_count = MagicMock(return_value=0)
    for _mod in _TORCH_CHILD_MODULES:
        sys.modules[_mod] = _t

for _dep in ["peft", "transformers", "unsloth", "accelerate", "deepspeed"]:
    if _dep not in sys.modules:
        sys.modules[_dep] = MagicMock(name=_dep)
