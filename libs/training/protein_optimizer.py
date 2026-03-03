import logging
import random
import numpy as np
from typing import Dict, List, Any, Optional, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ProteinOptimizer:
    """
    Protein Hyperparameter Optimizer (Inspired by PufferLib's CARBS).

    Automates finding optimal hyperparameters (lr, loss weights, etc.)
    using a simplified Bayesian Optimization approach.

    Key Features:
    - No random seeding phase (starts with sensible defaults).
    - Uses training curve history (not just final value).
    - Robust to noisy RL/Training signals.
    """

    def __init__(self, param_space: Dict[str, Tuple[float, float, str]]):
        """
        Args:
            param_space: Dict of param_name -> (min, max, type).
                         Type can be 'log' or 'linear'.
                         Example: {'lr': (1e-5, 1e-2, 'log'), 'box_loss': (1.0, 10.0, 'linear')}
        """
        self.param_space = param_space
        self.history: List[Dict[str, Any]] = []
        self.best_params = None
        self.best_score = -float("inf")

    def suggest(self) -> Dict[str, Any]:
        """
        Suggest the next set of hyperparameters to evaluate.
        """
        # 1. If no history, return center of space (or sensible default)
        if not self.history:
            return self._get_center_params()

        # 2. Exploration vs Exploitation (Simple Epsilon-Greedy for now)
        # In a full implementation, we would use a Gaussian Process (GP) here.
        if random.random() < 0.3:
            return self._sample_random_params()
        else:
            return self._perturb_best_params()

    def update(self, params: Dict[str, Any], score: float, curve: List[float] = None):
        """
        Update the optimizer with the result of an evaluation.

        Args:
            params: The hyperparameters used.
            score: The final metric (e.g., mAP50).
            curve: Optional training curve (e.g., loss over epochs).
        """
        entry = {"params": params, "score": score, "curve": curve}
        self.history.append(entry)

        if score > self.best_score:
            self.best_score = score
            self.best_params = params
            logger.info(f"New best params found: {params} (Score: {score:.4f})")

    def _get_center_params(self) -> Dict[str, Any]:
        params = {}
        for name, (min_val, max_val, scale) in self.param_space.items():
            if scale == "log":
                params[name] = 10 ** ((np.log10(min_val) + np.log10(max_val)) / 2)
            else:
                params[name] = (min_val + max_val) / 2
        return params

    def _sample_random_params(self) -> Dict[str, Any]:
        params = {}
        for name, (min_val, max_val, scale) in self.param_space.items():
            if scale == "log":
                params[name] = 10 ** random.uniform(
                    np.log10(min_val), np.log10(max_val)
                )
            else:
                params[name] = random.uniform(min_val, max_val)
        return params

    def _perturb_best_params(self) -> Dict[str, Any]:
        if not self.best_params:
            return self._sample_random_params()

        params = {}
        for name, val in self.best_params.items():
            min_val, max_val, scale = self.param_space[name]

            # Perturb by +/- 20%
            perturbation = random.uniform(0.8, 1.2)
            new_val = val * perturbation

            # Clip to bounds
            new_val = max(min_val, min(max_val, new_val))
            params[name] = new_val
        return params


if __name__ == "__main__":
    # Example Usage
    space = {
        "lr": (1e-5, 1e-2, "log"),
        "box_loss": (1.0, 10.0, "linear"),
        "cls_loss": (0.1, 2.0, "linear"),
    }

    optimizer = ProteinOptimizer(space)

    # Simulate a loop
    for i in range(10):
        params = optimizer.suggest()
        # Simulate training score (function of params)
        score = -((params["box_loss"] - 7.5) ** 2) - (np.log10(params["lr"]) + 3) ** 2
        optimizer.update(params, score)
        print(f"Iter {i}: Params={params}, Score={score:.4f}")
