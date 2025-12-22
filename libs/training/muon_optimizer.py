import torch
from torch.optim import Optimizer


class MuonOptimizer(Optimizer):
    """
    Muon Optimizer (Placeholder).

    Intended to be a drop-in replacement for AdamW with faster convergence.
    Currently wraps AdamW until the full implementation is ported from PufferLib.
    """

    def __init__(
        self, params, lr=1e-3, betas=(0.9, 0.999), eps=1e-8, weight_decay=0.01
    ):
        # Initialize the base class
        defaults = dict(lr=lr, betas=betas, eps=eps, weight_decay=weight_decay)
        super(MuonOptimizer, self).__init__(params, defaults)

        # Use AdamW internally for now
        self.internal_optimizer = torch.optim.AdamW(
            params, lr=lr, betas=betas, eps=eps, weight_decay=weight_decay
        )

    def step(self, closure=None):
        """
        Performs a single optimization step.
        """
        # TODO: Implement actual Muon logic here
        # Reference: PufferLib implementation
        return self.internal_optimizer.step(closure)

    def zero_grad(self, set_to_none: bool = False):
        self.internal_optimizer.zero_grad(set_to_none=set_to_none)
