"""Smart Model Manager with Dynamic GPU Allocation.

Manages two models:
1. Primary (RTX 3090 Ti): Best quality, yields to training
2. Fallback (RTX 2070): Always available for agentic coding

Monitors Ray cluster and automatically switches between GPUs.
"""

import gc
import time
import asyncio
import threading
import logging
from typing import Optional, Dict, Any, Literal
from datetime import datetime
from enum import Enum

import torch
import httpx

from .config import (
    PRIMARY_GPU,
    FALLBACK_GPU,
    RAY_ADDRESS,
    RAY_CHECK_INTERVAL_SECONDS,
    YIELD_DELAY_SECONDS,
    RECLAIM_DELAY_SECONDS,
    IDLE_TIMEOUT_SECONDS,
    HF_HOME,
    GPUConfig,
)

logger = logging.getLogger(__name__)


class GPUState(Enum):
    """State of a GPU for inference."""

    AVAILABLE = "available"
    LOADING = "loading"
    READY = "ready"
    YIELDING = "yielding"
    TRAINING = "training"  # Occupied by Ray training


class ModelInstance:
    """Represents a loaded model instance on a specific GPU."""

    def __init__(self, gpu_config: GPUConfig):
        self.gpu_config = gpu_config
        self.engine = None  # vLLM LLM or AsyncLLMEngine
        self.tokenizer = None
        self.state = GPUState.AVAILABLE
        self.last_used: Optional[datetime] = None
        self.requests_served: int = 0
        self.load_time: Optional[datetime] = None
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self.engine is not None and self.state == GPUState.READY

    def get_vram_usage(self) -> float:
        """Get current VRAM usage in GB."""
        if not torch.cuda.is_available():
            return 0.0
        try:
            device_id = self.gpu_config.device_id
            allocated = torch.cuda.memory_allocated(device_id) / (1024**3)
            return round(allocated, 2)
        except Exception:
            return 0.0


class DualGPUModelManager:
    """Manages models across two GPUs with training-aware routing."""

    def __init__(self):
        self.primary = ModelInstance(PRIMARY_GPU)
        self.fallback = ModelInstance(FALLBACK_GPU)

        self._training_active = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._yield_task: Optional[asyncio.Task] = None
        self._idle_task: Optional[asyncio.Task] = None

        self._lock = asyncio.Lock()
        self._http_client: Optional[httpx.AsyncClient] = None

    async def initialize(self):
        """Start the manager and begin monitoring."""
        self._http_client = httpx.AsyncClient(timeout=5.0)

        # Start Ray monitoring
        self._monitor_task = asyncio.create_task(self._monitor_ray_cluster())

        # Check if training is active
        training_active = await self._is_training_active()

        if training_active:
            # Training running - load small fallback model
            # NOTE: This requires container restart with CUDA_VISIBLE_DEVICES=1
            # For now, we'll wait for training to complete
            logger.info(
                "Training active, waiting for completion before loading model..."
            )
            # Start with primary anyway, training detection will yield if needed
            logger.info("Loading primary model on RTX 3090 Ti...")
            await self._load_model(self.primary)
        else:
            # Training idle - load the big 30B model on 3090 Ti
            logger.info("Training idle, loading primary 30B model on RTX 3090 Ti...")
            await self._load_model(self.primary)

        logger.info("Service ready with Qwen3-Coder-30B-A3B model.")

    async def shutdown(self):
        """Clean shutdown of all models and tasks."""
        if self._monitor_task:
            self._monitor_task.cancel()
        if self._yield_task:
            self._yield_task.cancel()
        if self._idle_task:
            self._idle_task.cancel()

        await self._unload_model(self.primary)
        await self._unload_model(self.fallback)

        if self._http_client:
            await self._http_client.aclose()

    async def get_best_available_model(self) -> ModelInstance:
        """Get the best available model for inference.

        Returns primary (3090 Ti) if loaded, otherwise fallback (2070).
        """
        async with self._lock:
            if self.primary.is_loaded:
                self.primary.last_used = datetime.now()
                return self.primary

            if self.fallback.is_loaded:
                self.fallback.last_used = datetime.now()
                return self.fallback

            # Neither loaded - load fallback urgently
            logger.warning("No model loaded! Loading fallback model...")
            await self._load_model(self.fallback)
            self.fallback.last_used = datetime.now()
            return self.fallback

    async def generate(
        self,
        messages: list,
        temperature: float = 0.7,
        top_p: float = 0.8,
        max_tokens: int = 4096,
        tools: Optional[list] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Generate completion using the best available model."""
        model = await self.get_best_available_model()
        model.requests_served += 1

        # Format messages for the model
        prompt = self._format_messages(messages, model, tools)

        # Generate with vLLM
        from vllm import SamplingParams

        sampling_params = SamplingParams(
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stop=kwargs.get("stop"),
        )

        outputs = model.engine.generate([prompt], sampling_params)
        output = outputs[0]

        return {
            "model": model.gpu_config.model_id,
            "gpu": model.gpu_config.name,
            "content": output.outputs[0].text,
            "finish_reason": output.outputs[0].finish_reason,
            "prompt_tokens": len(output.prompt_token_ids),
            "completion_tokens": len(output.outputs[0].token_ids),
        }

    def _format_messages(
        self, messages: list, model: ModelInstance, tools: Optional[list] = None
    ) -> str:
        """Format chat messages for the model."""
        # Use the tokenizer's chat template
        if model.tokenizer is None:
            # Fallback to simple formatting
            formatted = ""
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                formatted += f"<|{role}|>\n{content}\n"
            formatted += "<|assistant|>\n"
            return formatted

        # Use proper chat template
        return model.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            tools=tools,
        )

    # =========================================================================
    # Ray Cluster Monitoring
    # =========================================================================

    async def _monitor_ray_cluster(self):
        """Continuously monitor Ray cluster for training jobs."""
        while True:
            try:
                was_training = self._training_active
                self._training_active = await self._is_training_active()

                # Training just started
                if self._training_active and not was_training:
                    logger.info("Training detected! Scheduling primary model yield...")
                    self._yield_task = asyncio.create_task(
                        self._delayed_yield_primary()
                    )

                # Training just stopped
                elif not self._training_active and was_training:
                    logger.info(
                        "Training completed! Scheduling primary model reclaim..."
                    )
                    if self._yield_task:
                        self._yield_task.cancel()
                    asyncio.create_task(self._delayed_reclaim_primary())

            except Exception as e:
                logger.error(f"Error monitoring Ray cluster: {e}")

            await asyncio.sleep(RAY_CHECK_INTERVAL_SECONDS)

    async def _is_training_active(self) -> bool:
        """Check if Ray cluster has active training jobs using GPU 1."""
        try:
            # Check Ray jobs API
            response = await self._http_client.get(f"{RAY_ADDRESS}/api/jobs/")
            if response.status_code == 200:
                jobs = response.json()
                # Check for running jobs
                for job in jobs:
                    if job.get("status") == "RUNNING":
                        # Check if job is using GPU resources
                        entrypoint = job.get("entrypoint", "")
                        # Heuristic: training jobs usually have these keywords
                        if any(
                            kw in entrypoint.lower()
                            for kw in ["train", "fit", "ray.train"]
                        ):
                            return True

            # Also check cluster resources
            response = await self._http_client.get(f"{RAY_ADDRESS}/api/cluster_status")
            if response.status_code == 200:
                status = response.json()
                # Check GPU utilization
                resources = status.get("autoscaler_report", {}).get("usage", {})
                gpu_used = resources.get("GPU", [0, 0])[0]  # [used, total]
                if gpu_used > 0:
                    return True

            return False

        except Exception as e:
            logger.warning(f"Could not check Ray status: {e}")
            # Assume training could be active if we can't check
            return False

    async def _delayed_yield_primary(self):
        """Yield primary GPU after a delay (allows short jobs to complete)."""
        await asyncio.sleep(YIELD_DELAY_SECONDS)

        async with self._lock:
            if self._training_active and self.primary.is_loaded:
                logger.info("Yielding RTX 3090 Ti to training...")
                await self._unload_model(self.primary)

    async def _delayed_reclaim_primary(self):
        """Reclaim primary GPU after training stops."""
        await asyncio.sleep(RECLAIM_DELAY_SECONDS)

        async with self._lock:
            if not self._training_active and not self.primary.is_loaded:
                logger.info("Reclaiming RTX 3090 Ti for inference...")
                await self._load_model(self.primary)

    # =========================================================================
    # Model Loading/Unloading
    # =========================================================================

    async def _load_model(self, instance: ModelInstance):
        """Load a model onto its designated GPU."""
        if instance.is_loaded:
            return

        instance.state = GPUState.LOADING
        gpu = instance.gpu_config

        try:
            logger.info(f"Loading {gpu.model_id} on {gpu.name} ({gpu.device})...")

            # Import vLLM
            from vllm import LLM
            from transformers import AutoTokenizer

            # Load tokenizer
            instance.tokenizer = AutoTokenizer.from_pretrained(
                gpu.model_id,
                trust_remote_code=True,
                cache_dir=str(HF_HOME),
            )

            # Build vLLM engine arguments
            engine_args = {
                "model": gpu.model_id,
                "tensor_parallel_size": 1,
                "gpu_memory_utilization": gpu.gpu_memory_utilization,
                "max_model_len": gpu.max_model_len,
                "trust_remote_code": True,
                "download_dir": str(HF_HOME),
                "enforce_eager": True,  # Disable CUDA graphs for stability
                "disable_log_stats": True,
            }

            # Add quantization if specified
            if gpu.quantization:
                engine_args["quantization"] = gpu.quantization

            # Set CUDA device
            import os

            os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu.device_id)

            # Load model
            instance.engine = LLM(**engine_args)

            instance.state = GPUState.READY
            instance.load_time = datetime.now()

            vram = instance.get_vram_usage()
            logger.info(f"Model loaded on {gpu.name}. VRAM: {vram:.2f}GB")

        except Exception as e:
            logger.error(f"Failed to load model on {gpu.name}: {e}")
            instance.state = GPUState.AVAILABLE
            instance.engine = None
            instance.tokenizer = None
            raise

    async def _unload_model(self, instance: ModelInstance):
        """Unload a model from its GPU."""
        if not instance.is_loaded:
            return

        instance.state = GPUState.YIELDING
        gpu = instance.gpu_config

        try:
            logger.info(f"Unloading model from {gpu.name}...")

            # Delete engine
            if instance.engine is not None:
                del instance.engine
                instance.engine = None

            if instance.tokenizer is not None:
                del instance.tokenizer
                instance.tokenizer = None

            # Force garbage collection
            gc.collect()

            # Clear CUDA cache
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()

            instance.state = GPUState.AVAILABLE
            logger.info(f"Model unloaded from {gpu.name}")

        except Exception as e:
            logger.error(f"Error unloading model from {gpu.name}: {e}")
            instance.state = GPUState.AVAILABLE

    # =========================================================================
    # Status
    # =========================================================================

    def get_status(self) -> Dict[str, Any]:
        """Get current status of both GPUs."""
        return {
            "training_active": self._training_active,
            "primary": {
                "gpu": self.primary.gpu_config.name,
                "model": self.primary.gpu_config.model_id,
                "state": self.primary.state.value,
                "loaded": self.primary.is_loaded,
                "vram_gb": self.primary.get_vram_usage(),
                "requests_served": self.primary.requests_served,
                "last_used": (
                    self.primary.last_used.isoformat()
                    if self.primary.last_used
                    else None
                ),
            },
            "fallback": {
                "gpu": self.fallback.gpu_config.name,
                "model": self.fallback.gpu_config.model_id,
                "state": self.fallback.state.value,
                "loaded": self.fallback.is_loaded,
                "vram_gb": self.fallback.get_vram_usage(),
                "requests_served": self.fallback.requests_served,
                "last_used": (
                    self.fallback.last_used.isoformat()
                    if self.fallback.last_used
                    else None
                ),
            },
            "active_gpu": (
                self.primary.gpu_config.name
                if self.primary.is_loaded
                else (
                    self.fallback.gpu_config.name if self.fallback.is_loaded else "none"
                )
            ),
        }


# Global singleton
model_manager = DualGPUModelManager()
