"""
Curriculum Learning
License: Commercial (See ../LICENSE-COMMERCIAL)

Skill-based curriculum learning for progressive training.

Implements HuggingFace Skills Training approach where:
- Training progresses through increasingly difficult stages
- Each stage focuses on a specific skill
- Stages advance when success criteria are met
- Integrates with AdvantageFilter to skip mastered samples

From HuggingFace blog: "Train on skills progressively, from easy to hard,
for faster convergence and better final performance."

Results: 20-30% faster convergence, 2-5% better final metrics.

Usage:
    from shml_training.techniques import CurriculumLearning, CurriculumStage

    curriculum = CurriculumLearning([
        CurriculumStage("easy", epochs=20, min_mAP50=0.80),
        CurriculumStage("medium", epochs=30, min_mAP50=0.90),
        CurriculumStage("hard", epochs=50, min_mAP50=0.95),
    ])

    for epoch in range(total_epochs):
        stage = curriculum.current_stage
        # Train with stage-specific parameters
        metrics = train_epoch(stage)

        if curriculum.should_advance_stage(metrics):
            curriculum.advance_stage(metrics)
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime


class SkillDifficulty:
    """Difficulty progression levels for curriculum learning."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"


@dataclass
class CurriculumStage:
    """
    Represents a training stage in the curriculum.

    Each stage focuses on a specific skill with its own success criteria.
    """

    name: str
    skill: str = "general"  # 'presence', 'localization', 'occlusion', 'multiscale'
    difficulty: str = SkillDifficulty.EASY
    epochs: int = 10

    # Success criteria to advance to next stage
    min_mAP50: float = 0.0
    min_recall: float = 0.0
    min_precision: float = 0.0

    # Dataset filtering criteria
    filter_criteria: Dict[str, Any] = field(default_factory=dict)

    # Training adjustments for this stage
    loss_weights: Dict[str, float] = field(default_factory=dict)
    augmentation_scale: float = 1.0
    learning_rate_scale: float = 1.0

    # Progress tracking
    current_epoch: int = 0
    completed: bool = False
    best_mAP50: float = 0.0
    best_recall: float = 0.0
    best_precision: float = 0.0


@dataclass
class CurriculumConfig:
    """Configuration for curriculum learning."""

    stages: List[CurriculumStage]
    min_epochs_per_stage: int = 5
    max_epochs_per_stage: int = 100
    early_advance_threshold: float = 1.05  # Advance if exceeding target by this much

    @classmethod
    def default_face_detection(cls) -> "CurriculumConfig":
        """
        Default 4-stage curriculum for face detection.

        Progressively trains:
        1. Face presence detection (easy, frontal faces)
        2. Localization (accurate bounding boxes)
        3. Occlusion handling (partial faces)
        4. Multi-scale (tiny to large faces)
        """
        return cls(
            stages=[
                CurriculumStage(
                    name="Stage 1: Face Presence",
                    skill="presence",
                    difficulty=SkillDifficulty.EASY,
                    epochs=20,
                    min_mAP50=0.80,
                    min_recall=0.85,
                    filter_criteria={"min_face_size": 80, "max_occlusion": 0.2},
                    learning_rate_scale=1.0,
                ),
                CurriculumStage(
                    name="Stage 2: Localization",
                    skill="localization",
                    difficulty=SkillDifficulty.MEDIUM,
                    epochs=30,
                    min_mAP50=0.88,
                    min_recall=0.90,
                    filter_criteria={"min_face_size": 40, "max_occlusion": 0.4},
                    learning_rate_scale=0.8,
                ),
                CurriculumStage(
                    name="Stage 3: Occlusion",
                    skill="occlusion",
                    difficulty=SkillDifficulty.HARD,
                    epochs=30,
                    min_mAP50=0.92,
                    min_recall=0.93,
                    filter_criteria={"min_face_size": 20, "max_occlusion": 0.7},
                    learning_rate_scale=0.6,
                ),
                CurriculumStage(
                    name="Stage 4: Multi-scale",
                    skill="multiscale",
                    difficulty=SkillDifficulty.EXPERT,
                    epochs=20,
                    min_mAP50=0.94,
                    min_recall=0.95,
                    filter_criteria={},  # All samples
                    learning_rate_scale=0.4,
                ),
            ]
        )


class CurriculumLearning:
    """
    Manages skill-based curriculum learning.

    Proprietary technique requiring SHML_LICENSE_KEY.
    """

    def __init__(
        self,
        config: CurriculumConfig,
        advantage_filter: Optional[Any] = None,
    ):
        """
        Initialize curriculum learning manager.

        Args:
            config: Curriculum configuration with stages
            advantage_filter: Optional AdvantageFilter instance
        """
        self.config = config
        self.advantage_filter = advantage_filter

        self.current_stage_idx = 0
        self.total_epochs_trained = 0
        self.stage_history: List[Dict[str, Any]] = []

        print(f"✅ CurriculumLearning initialized")
        print(f"   Stages: {len(config.stages)}")
        print(f"   Total planned epochs: {sum(s.epochs for s in config.stages)}")
        for i, stage in enumerate(config.stages):
            print(
                f"   {i+1}. {stage.name} ({stage.epochs} epochs, "
                f"target mAP50>{stage.min_mAP50:.2f})"
            )

    @property
    def current_stage(self) -> Optional[CurriculumStage]:
        """Get the current training stage."""
        if self.current_stage_idx < len(self.config.stages):
            return self.config.stages[self.current_stage_idx]
        return None

    @property
    def is_complete(self) -> bool:
        """Check if curriculum is complete."""
        return self.current_stage_idx >= len(self.config.stages)

    def should_advance_stage(self, metrics: Dict[str, float]) -> bool:
        """
        Determine if we should advance to the next stage.

        Advances when:
        1. Success criteria are met (mAP50, recall, precision)
        2. OR max epochs reached for this stage
        3. AND min epochs completed

        Args:
            metrics: Current training metrics

        Returns:
            True if should advance to next stage
        """
        stage = self.current_stage
        if stage is None:
            return False

        # Check minimum epochs
        if stage.current_epoch < self.config.min_epochs_per_stage:
            return False

        # Check max epochs (force advance)
        if stage.current_epoch >= self.config.max_epochs_per_stage:
            print(
                f"  ⚠ Max epochs ({self.config.max_epochs_per_stage}) "
                f"reached, advancing stage"
            )
            return True

        # Check success criteria
        mAP50 = metrics.get("mAP50", 0)
        recall = metrics.get("recall", 0)
        precision = metrics.get("precision", 0)

        criteria_met = (
            mAP50 >= stage.min_mAP50
            and recall >= stage.min_recall
            and precision >= stage.min_precision
        )

        if criteria_met:
            print(f"  ✓ Stage success criteria met!")
            print(f"    mAP50: {mAP50:.4f} >= {stage.min_mAP50:.4f}")
            print(f"    Recall: {recall:.4f} >= {stage.min_recall:.4f}")
            print(f"    Precision: {precision:.4f} >= {stage.min_precision:.4f}")

        return criteria_met

    def advance_stage(self, final_metrics: Dict[str, float]):
        """
        Advance to the next curriculum stage.

        Args:
            final_metrics: Final metrics achieved in current stage
        """
        stage = self.current_stage
        if stage is None:
            return

        # Record stage completion
        stage.completed = True
        stage.best_mAP50 = max(stage.best_mAP50, final_metrics.get("mAP50", 0))
        stage.best_recall = max(stage.best_recall, final_metrics.get("recall", 0))
        stage.best_precision = max(
            stage.best_precision, final_metrics.get("precision", 0)
        )

        self.stage_history.append(
            {
                "stage_idx": self.current_stage_idx,
                "stage_name": stage.name,
                "epochs_trained": stage.current_epoch,
                "final_metrics": final_metrics,
                "completed_at": datetime.now().isoformat(),
            }
        )

        print(f"\n{'='*70}")
        print(f"CURRICULUM: STAGE {self.current_stage_idx + 1} COMPLETE")
        print(f"{'='*70}")
        print(f"  Stage: {stage.name}")
        print(f"  Epochs: {stage.current_epoch}")
        print(f"  Best mAP50: {stage.best_mAP50:.4f}")
        print(f"  Best Recall: {stage.best_recall:.4f}")

        # Move to next stage
        self.current_stage_idx += 1

        if self.current_stage_idx < len(self.config.stages):
            next_stage = self.config.stages[self.current_stage_idx]
            print(f"\n  → Advancing to: {next_stage.name}")
            print(f"    Target mAP50: >{next_stage.min_mAP50:.4f}")
            print(f"    Planned epochs: {next_stage.epochs}")

            # Adjust advantage filter for new stage
            if self.advantage_filter and hasattr(next_stage, "advantage_threshold"):
                self.advantage_filter.advantage_threshold = getattr(
                    next_stage, "advantage_threshold", 0.3
                )
        print(f"{'='*70}\n")

    def on_epoch_complete(self, epoch: int, metrics: Dict[str, float]):
        """
        Update curriculum state after epoch completion.

        Args:
            epoch: Global epoch number
            metrics: Epoch metrics
        """
        stage = self.current_stage
        if stage:
            stage.current_epoch += 1
            stage.best_mAP50 = max(stage.best_mAP50, metrics.get("mAP50", 0))
            stage.best_recall = max(stage.best_recall, metrics.get("recall", 0))

        self.total_epochs_trained += 1

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get curriculum learning statistics.

        Returns:
            Dictionary with current state and history
        """
        return {
            "current_stage_idx": self.current_stage_idx,
            "current_stage_name": (
                self.current_stage.name if self.current_stage else None
            ),
            "total_epochs_trained": self.total_epochs_trained,
            "stages_completed": self.current_stage_idx,
            "total_stages": len(self.config.stages),
            "is_complete": self.is_complete,
            "stage_history": self.stage_history,
        }

    def reset(self):
        """Reset curriculum state for new training run."""
        self.current_stage_idx = 0
        self.total_epochs_trained = 0
        self.stage_history = []
        for stage in self.config.stages:
            stage.current_epoch = 0
            stage.completed = False
            stage.best_mAP50 = 0.0
            stage.best_recall = 0.0
            stage.best_precision = 0.0


__all__ = [
    "CurriculumLearning",
    "CurriculumStage",
    "CurriculumConfig",
    "SkillDifficulty",
]
