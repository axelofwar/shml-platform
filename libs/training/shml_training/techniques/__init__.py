"""
SHML Training - Proprietary Techniques
License: Commercial (See LICENSE-COMMERCIAL)

State-of-the-art training techniques requiring a valid license key.

Pricing Tiers:
    Hobbyist       - $29/month  (1 project, personal use)
    Professional   - $99/month  (3 projects, commercial use)
    Business       - $499/month (unlimited projects, team use)
    Enterprise     - Custom     (on-premises, white-label, support)

Techniques:
    Curriculum Learning    - Adaptive training progression
    SAPO Optimization     - Self-Adaptive Pareto Optimization
    Advantage Filter      - Selective gradient backpropagation
    Multi-scale Training  - Progressive resolution scaling

Planned:
    Neural Architecture Search (NAS)
    Dynamic Pruning
    Knowledge Distillation
    Meta-learning Adapters

Usage:
    export SHML_LICENSE_KEY="your-license-key-here"

    from shml_training.techniques import CurriculumLearning, SAPO

    config = TrainingConfig(
        model="yolov8l",
        techniques=["curriculum", "sapo"]
    )

To obtain a license key:
    1. Visit https://shml-platform.com/pricing
    2. Choose your tier
    3. Receive license key via email
    4. Set SHML_LICENSE_KEY environment variable

License Validation:
    All proprietary techniques check for a valid license key at import time.
    Invalid or missing keys will raise LicenseError.
"""

import os
import sys


class LicenseError(Exception):
    """Raised when license key is invalid or missing."""

    pass


def _validate_license():
    """Validate license key or raise LicenseError."""
    license_key = os.environ.get("SHML_LICENSE_KEY")

    if not license_key:
        raise LicenseError(
            "SHML_LICENSE_KEY environment variable not set. "
            "Proprietary techniques require a valid license. "
            "Visit https://shml-platform.com/pricing to obtain a key."
        )

    # TODO: Implement key validation (Phase P3)
    # - Check key format
    # - Verify signature
    # - Check expiration date
    # - Validate tier permissions
    # - Rate limit API calls

    # For now, accept any non-empty key (development only)
    if len(license_key) < 10:
        raise LicenseError(
            f"Invalid SHML_LICENSE_KEY format. "
            f"Expected license key, got: {license_key[:10]}..."
        )

    return True


# Validate license at module import
try:
    _validate_license()
    _LICENSED = True
except LicenseError as e:
    print(f"WARNING: {e}", file=sys.stderr)
    print("Proprietary techniques will not be available.", file=sys.stderr)
    _LICENSED = False

# Only export techniques if licensed
__all__ = []

if _LICENSED:
    # Import proprietary techniques
    from .sapo import SAPO, SAPOConfig
    from .advantage_filter import AdvantageFilter, BatchAdvantage
    from .curriculum import (
        CurriculumLearning,
        CurriculumStage,
        CurriculumConfig,
        SkillDifficulty,
    )

    __all__ = [
        # SAPO
        "SAPO",
        "SAPOConfig",
        # Advantage Filtering
        "AdvantageFilter",
        "BatchAdvantage",
        # Curriculum Learning
        "CurriculumLearning",
        "CurriculumStage",
        "CurriculumConfig",
        "SkillDifficulty",
    ]

    print("✅ SHML Proprietary Techniques loaded")
    print(f"   License key: {os.environ.get('SHML_LICENSE_KEY', 'N/A')[:20]}...")
    print(f"   Available techniques: {len(__all__)} modules")
