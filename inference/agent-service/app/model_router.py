"""
Model Router - SOTA Multi-Modal Task Routing

Intelligently routes tasks to appropriate models based on:
- Presence of image attachments → Qwen3-VL (RTX 2070, vision)
- Code-related keywords → Qwen3.5-35B-A3B (RTX 3090 Ti, code + reasoning)
- Image generation keywords → Z-Image (RTX 3090 Ti, image synthesis)
- Multi-modal tasks → Chain multiple models
- **Training status** → Route to RTX 2070 when training active on RTX 3090 Ti

GPU Allocation:
- RTX 2070 (cuda:1, 8GB): Qwen3-VL-8B (always loaded)
- RTX 3090 Ti (cuda:0, 24GB): Qwen3.5-35B-A3B Q4_K_M (primary, thinking enabled), Z-Image (on-demand)

Training-Aware Routing:
- When training is active on RTX 3090 Ti, code requests fallback to Qwen3-VL
- Qwen3-VL can handle code tasks (less specialized but always available)
- Z-Image requests are queued until training completes

Multi-Model Orchestration:
- Sequential: vision → extract context → code generation
- Parallel: Independent tasks (e.g., analyze image + generate separate code)
"""

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)


class TrainingStatus:
    """Check training status from coding-model-manager (GPU yield lifecycle)"""

    QWEN_MANAGER_URLS = [
        os.getenv("CODING_MANAGER_URL", "http://nemotron-manager:8000/status"),
        "http://localhost:8021/status",
    ]
    # Legacy alias kept for backwards compatibility
    NEMOTRON_URLS = QWEN_MANAGER_URLS

    @classmethod
    def is_training_active(cls) -> bool:
        """
        Check if training is currently active on RTX 3090.

        Returns:
            True if training is active, False otherwise
        """
        for url in cls.QWEN_MANAGER_URLS:
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=2) as response:
                    data = json.loads(response.read().decode("utf-8"))
                    return data.get("training_active", False)
            except Exception:
                continue

        # Default to False if we can't reach the service
        return False

    @classmethod
    def get_training_info(cls) -> Optional[Dict[str, Any]]:
        """
        Get detailed training status info.

        Returns:
            Training info dict or None if unavailable
        """
        for url in cls.QWEN_MANAGER_URLS:
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=2) as response:
                    return json.loads(response.read().decode("utf-8"))
            except Exception:
                continue
        return None


class ModelType(str, Enum):
    """Available model types"""

    QWEN_CODER = "qwen-coder"  # Code generation (RTX 3090)
    QWEN3_VL = "qwen3-vl"  # Vision/multimodal (RTX 2070)
    Z_IMAGE = "z-image"  # Image generation (RTX 3090)


@dataclass
class ModelSelection:
    """Model selection with reasoning"""

    model_type: ModelType
    model_name: str
    reasoning: str
    gpu: str
    parameters: Dict[str, Any]
    confidence: float  # 0.0-1.0


@dataclass
class MultiModelPlan:
    """Orchestration plan for multiple models"""

    models: List[ModelSelection]
    execution_strategy: Literal["sequential", "parallel"]
    reasoning: str


class ModelRouter:
    """Intelligent model routing with task detection"""

    # Keywords for different task types
    CODE_KEYWORDS = [
        r"\bcode\b",
        r"\bfunction\b",
        r"\bclass\b",
        r"\bmethod\b",
        r"\bimplement\b",
        r"\bwrite.*code\b",
        r"\bscript\b",
        r"\bprogram\b",
        r"\balgorithm\b",
        r"\bapi\b",
        r"\brefactor\b",
        r"\bdebug\b",
        r"\bfix.*bug\b",
        r"\.py\b",
        r"\.js\b",
        r"\.ts\b",
        r"\.java\b",
        r"\.cpp\b",
        r"\bpython\b",
        r"\bjavascript\b",
        r"\btypescript\b",
    ]

    IMAGE_GEN_KEYWORDS = [
        r"\bgenerate.*image\b",
        r"\bcreate.*image\b",
        r"\bmake.*image\b",
        r"\bdraw\b",
        r"\bvisualize\b",
        r"\brender\b",
        r"\bgenerate.*picture\b",
        r"\bcreate.*picture\b",
        r"\billustration\b",
        r"\bartwork\b",
        r"\bdesign\b",
    ]

    VISION_KEYWORDS = [
        r"\bwhat.*see\b",
        r"\bdescribe.*image\b",
        r"\banalyze.*image\b",
        r"\bwhat.*in.*image\b",
        r"\bwhat.*picture\b",
        r"\bread.*image\b",
        r"\bextract.*from.*image\b",
        r"\bocr\b",
        r"\btext.*in.*image\b",
    ]

    def __init__(self):
        """Initialize router with model configs"""
        self.models_config = {
            ModelType.QWEN_CODER: {
                "name": "Qwen3.5-35B-A3B-Q4_K_M",  # Qwen3.5 MoE, thinking enabled
                "url": "http://qwopus-coding:8000",
                "gpu": "cuda:0",  # RTX 3090 Ti (GPU 0)
                "capabilities": ["code", "general", "reasoning"],
            },
            ModelType.QWEN3_VL: {
                "name": "Qwen/Qwen3-VL-8B",
                "gpu": "cuda:0",  # RTX 2070
                "capabilities": ["vision", "multimodal", "ocr"],
            },
            ModelType.Z_IMAGE: {
                "name": "thibaud/z-image-turbo",
                "gpu": "cuda:1",  # RTX 3090 (on-demand)
                "capabilities": ["image_generation"],
            },
        }

    def detect_task_type(
        self,
        prompt: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Detect task type from prompt and attachments

        Returns:
            {
                "has_vision": bool,
                "has_code": bool,
                "has_image_gen": bool,
                "vision_score": float,
                "code_score": float,
                "image_gen_score": float,
            }
        """
        prompt_lower = prompt.lower()

        # Check for image attachments
        has_image_attachment = False
        if attachments:
            has_image_attachment = any(
                att.get("type") == "image"
                or att.get("mime_type", "").startswith("image/")
                for att in attachments
            )

        # Score each task type
        vision_score = 0.0
        code_score = 0.0
        image_gen_score = 0.0

        # Vision detection
        if has_image_attachment:
            vision_score += 0.7  # Strong signal
        for pattern in self.VISION_KEYWORDS:
            if re.search(pattern, prompt_lower):
                vision_score += 0.3

        # Code detection
        for pattern in self.CODE_KEYWORDS:
            if re.search(pattern, prompt_lower):
                code_score += 0.2

        # Image generation detection
        for pattern in self.IMAGE_GEN_KEYWORDS:
            if re.search(pattern, prompt_lower):
                image_gen_score += 0.4

        # Normalize scores
        vision_score = min(vision_score, 1.0)
        code_score = min(code_score, 1.0)
        image_gen_score = min(image_gen_score, 1.0)

        return {
            "has_vision": vision_score > 0.3,
            "has_code": code_score > 0.3,
            "has_image_gen": image_gen_score > 0.3,
            "vision_score": vision_score,
            "code_score": code_score,
            "image_gen_score": image_gen_score,
            "has_image_attachment": has_image_attachment,
        }

    def select_model(
        self,
        prompt: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
        check_training: bool = True,
    ) -> ModelSelection:
        """
        Select single best model for the task

        Priority:
        1. Vision task with image → Qwen3-VL
        2. Image generation request → Z-Image (or queue if training)
        3. Code-related request → Qwen-Coder (or fallback if training)
        4. Default → Qwen-Coder (most capable for general tasks)

        Training-Aware Routing:
        - If training is active on RTX 3090, code requests use Qwen3-VL
        - Image generation is queued until training completes
        """
        task_type = self.detect_task_type(prompt, attachments)

        # Check if training is active on RTX 3090
        training_active = False
        if check_training:
            training_active = TrainingStatus.is_training_active()
            if training_active:
                logger.info("Training active on RTX 3090 - routing to fallback models")

        # Priority 1: Vision tasks (always available on RTX 2070)
        if task_type["has_vision"]:
            config = self.models_config[ModelType.QWEN3_VL]
            return ModelSelection(
                model_type=ModelType.QWEN3_VL,
                model_name=config["name"],
                reasoning="Vision/multimodal task detected (image attachment present)",
                gpu=config["gpu"],
                parameters={
                    "temperature": 0.7,
                    "max_tokens": 2048,
                },
                confidence=task_type["vision_score"],
            )

        # Priority 2: Image generation
        if task_type["has_image_gen"]:
            if training_active:
                # Queue image generation or return with notice
                config = self.models_config[ModelType.QWEN3_VL]
                return ModelSelection(
                    model_type=ModelType.QWEN3_VL,
                    model_name=config["name"],
                    reasoning="Image generation requested but training is active on RTX 3090. Using vision model to describe what would be generated.",
                    gpu=config["gpu"],
                    parameters={
                        "temperature": 0.7,
                        "max_tokens": 1024,
                        "_training_blocked": True,
                        "_original_task": "image_generation",
                    },
                    confidence=0.3,
                )
            config = self.models_config[ModelType.Z_IMAGE]
            return ModelSelection(
                model_type=ModelType.Z_IMAGE,
                model_name=config["name"],
                reasoning="Image generation request detected",
                gpu=config["gpu"],
                parameters={
                    "num_inference_steps": 4,  # Turbo model
                    "guidance_scale": 0.0,  # CFG-distilled
                },
                confidence=task_type["image_gen_score"],
            )

        # Priority 3: Code generation
        if task_type["has_code"]:
            if training_active:
                # Fallback to Qwen3-VL for code during training
                config = self.models_config[ModelType.QWEN3_VL]
                return ModelSelection(
                    model_type=ModelType.QWEN3_VL,
                    model_name=config["name"],
                    reasoning="Code task detected but training is active on RTX 3090. Using Qwen3-VL as fallback (less specialized but always available).",
                    gpu=config["gpu"],
                    parameters={
                        "temperature": 0.3,  # Lower for code
                        "max_tokens": 4096,
                        "_training_fallback": True,
                        "_original_model": "qwen-coder",
                    },
                    confidence=task_type["code_score"]
                    * 0.7,  # Reduced confidence for fallback
                )
            config = self.models_config[ModelType.QWEN_CODER]
            return ModelSelection(
                model_type=ModelType.QWEN_CODER,
                model_name=config["name"],
                reasoning="Code-related task detected",
                gpu=config["gpu"],
                parameters={
                    "temperature": 0.2,  # Lower for code
                    "max_tokens": 4096,
                },
                confidence=task_type["code_score"],
            )

        # Default: Qwen-Coder or fallback during training
        if training_active:
            config = self.models_config[ModelType.QWEN3_VL]
            return ModelSelection(
                model_type=ModelType.QWEN3_VL,
                model_name=config["name"],
                reasoning="Training active on RTX 3090, using Qwen3-VL as fallback",
                gpu=config["gpu"],
                parameters={
                    "temperature": 0.7,
                    "max_tokens": 2048,
                    "_training_fallback": True,
                },
                confidence=0.4,
            )

        config = self.models_config[ModelType.QWEN_CODER]
        return ModelSelection(
            model_type=ModelType.QWEN_CODER,
            model_name=config["name"],
            reasoning="General task, using most capable model",
            gpu=config["gpu"],
            parameters={
                "temperature": 0.7,
                "max_tokens": 2048,
            },
            confidence=0.5,
        )

    def plan_multi_model(
        self,
        prompt: str,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[MultiModelPlan]:
        """
        Detect if task requires multiple models and create execution plan

        Multi-model scenarios:
        1. "Analyze this image and generate code" → Vision + Code (sequential)
        2. "Describe image and create illustration" → Vision + Image Gen (parallel)
        3. "OCR this screenshot and refactor code" → Vision + Code (sequential)

        Returns None if single model sufficient
        """
        task_type = self.detect_task_type(prompt, attachments)

        # Check for multi-modal indicators
        multi_model_patterns = [
            (r"\band\b", "sequential"),  # "analyze image and generate code"
            (r"\balso\b", "parallel"),  # "describe image also create..."
            (r"\bthen\b", "sequential"),  # "analyze then generate"
        ]

        strategy = "sequential"
        for pattern, strat in multi_model_patterns:
            if re.search(pattern, prompt.lower()):
                strategy = strat
                break

        # Count how many task types are present
        task_count = sum(
            [
                task_type["has_vision"],
                task_type["has_code"],
                task_type["has_image_gen"],
            ]
        )

        if task_count < 2:
            return None  # Single model sufficient

        # Build multi-model plan
        models = []

        # Vision first (if present) - provides context for other models
        if task_type["has_vision"]:
            config = self.models_config[ModelType.QWEN3_VL]
            models.append(
                ModelSelection(
                    model_type=ModelType.QWEN3_VL,
                    model_name=config["name"],
                    reasoning="Vision analysis for context extraction",
                    gpu=config["gpu"],
                    parameters={"temperature": 0.7, "max_tokens": 1024},
                    confidence=task_type["vision_score"],
                )
            )

        # Code generation (if needed)
        if task_type["has_code"]:
            config = self.models_config[ModelType.QWEN_CODER]
            models.append(
                ModelSelection(
                    model_type=ModelType.QWEN_CODER,
                    model_name=config["name"],
                    reasoning=(
                        "Code generation based on vision context"
                        if task_type["has_vision"]
                        else "Code generation"
                    ),
                    gpu=config["gpu"],
                    parameters={"temperature": 0.2, "max_tokens": 4096},
                    confidence=task_type["code_score"],
                )
            )

        # Image generation (if needed)
        if task_type["has_image_gen"]:
            config = self.models_config[ModelType.Z_IMAGE]
            models.append(
                ModelSelection(
                    model_type=ModelType.Z_IMAGE,
                    model_name=config["name"],
                    reasoning="Image generation",
                    gpu=config["gpu"],
                    parameters={"num_inference_steps": 4, "guidance_scale": 0.0},
                    confidence=task_type["image_gen_score"],
                )
            )

        if len(models) < 2:
            return None

        return MultiModelPlan(
            models=models,
            execution_strategy=strategy,
            reasoning=f"Multi-modal task requires {len(models)} models: "
            + ", ".join([m.model_type.value for m in models]),
        )


# Global router instance
_router = None


def get_model_router() -> ModelRouter:
    """Get or create global router instance"""
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
