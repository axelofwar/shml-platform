"""Simple Model Manager - Single GPU per Container.

Each container runs ONE model on ONE GPU.
- Primary container: RTX 3090 Ti with 30B model
- Fallback container: RTX 2070 with 7B model

Traefik handles routing between them based on health status.
"""

import gc
import os
import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime

import torch
import httpx

logger = logging.getLogger(__name__)


class SimpleModelManager:
    """Manages a single model on a single GPU."""

    def __init__(self):
        # Read config from environment (set in docker-compose.yml)
        self.model_id = os.getenv("MODEL_ID", "Qwen/Qwen2.5-Coder-7B-Instruct-AWQ")
        self.model_mode = os.getenv("MODEL_MODE", "fallback")  # "primary" or "fallback"
        self.max_model_len = int(os.getenv("MAX_MODEL_LEN", "8192"))
        self.gpu_memory_util = float(os.getenv("GPU_MEMORY_UTILIZATION", "0.80"))
        self.quantization = os.getenv("QUANTIZATION", None)  # "awq" or None
        self.yield_on_training = (
            os.getenv("YIELD_ON_TRAINING", "false").lower() == "true"
        )
        self.ray_address = os.getenv("RAY_ADDRESS", "http://ray-head:8265")
        self.check_interval = int(os.getenv("RAY_CHECK_INTERVAL_SECONDS", "10"))
        self.hf_home = os.getenv("HF_HOME", "/models")

        # Model state
        self.engine = None
        self.tokenizer = None
        self.is_loaded = False
        self.is_yielded = False
        self.load_time: Optional[datetime] = None
        self.requests_served = 0
        self.last_used: Optional[datetime] = None

        # Async resources
        self._monitor_task: Optional[asyncio.Task] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    async def initialize(self):
        """Load the model and start monitoring (if primary)."""
        self._http_client = httpx.AsyncClient(timeout=5.0)

        # Check training status first
        if self.yield_on_training:
            training_active = await self._is_training_active()
            if training_active:
                logger.info(f"Training active - {self.model_mode} container will wait")
                self.is_yielded = True
                self._monitor_task = asyncio.create_task(self._monitor_training())
                return

        # Load the model
        await self._load_model()

        # Start monitoring for primary
        if self.yield_on_training:
            self._monitor_task = asyncio.create_task(self._monitor_training())

    async def shutdown(self):
        """Clean shutdown."""
        if self._monitor_task:
            self._monitor_task.cancel()

        await self._unload_model()

        if self._http_client:
            await self._http_client.aclose()

    async def _load_model(self):
        """Load the model using vLLM."""
        if self.is_loaded:
            return

        logger.info(f"Loading {self.model_id}...")
        logger.info(f"  Mode: {self.model_mode}")
        logger.info(f"  Max context: {self.max_model_len}")
        logger.info(f"  GPU memory: {self.gpu_memory_util * 100:.0f}%")

        try:
            from vllm import LLM
            from transformers import AutoTokenizer

            # Load tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_id,
                trust_remote_code=True,
                cache_dir=self.hf_home,
            )

            # Build engine args
            engine_args = {
                "model": self.model_id,
                "tensor_parallel_size": 1,
                "gpu_memory_utilization": self.gpu_memory_util,
                "max_model_len": self.max_model_len,
                "trust_remote_code": True,
                "download_dir": self.hf_home,
                "enforce_eager": True,
                "disable_log_stats": True,
            }

            if self.quantization:
                engine_args["quantization"] = self.quantization

            # Load model
            self.engine = LLM(**engine_args)

            self.is_loaded = True
            self.is_yielded = False
            self.load_time = datetime.now()

            vram = self._get_vram_usage()
            logger.info(f"Model loaded successfully. VRAM: {vram:.2f}GB")

        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            self.engine = None
            self.tokenizer = None
            self.is_loaded = False
            raise

    async def _unload_model(self):
        """Unload the model and free GPU memory."""
        if not self.is_loaded:
            return

        logger.info(f"Unloading model...")

        try:
            if self.engine is not None:
                del self.engine
                self.engine = None

            if self.tokenizer is not None:
                del self.tokenizer
                self.tokenizer = None

            gc.collect()

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()

            self.is_loaded = False
            logger.info("Model unloaded")

        except Exception as e:
            logger.error(f"Error unloading model: {e}")

    def _get_vram_usage(self) -> float:
        """Get current VRAM usage in GB."""
        if not torch.cuda.is_available():
            return 0.0
        try:
            allocated = torch.cuda.memory_allocated(0) / (1024**3)
            return round(allocated, 2)
        except Exception:
            return 0.0

    # =========================================================================
    # Training Detection (Primary only)
    # =========================================================================

    async def _is_training_active(self) -> bool:
        """Check if Ray has active training jobs."""
        try:
            # Check Ray jobs
            response = await self._http_client.get(f"{self.ray_address}/api/jobs/")
            if response.status_code == 200:
                jobs = response.json()
                for job in jobs:
                    if job.get("status") == "RUNNING":
                        entrypoint = job.get("entrypoint", "").lower()
                        if any(
                            kw in entrypoint for kw in ["train", "fit", "ray.train"]
                        ):
                            return True

            # Check GPU allocation
            response = await self._http_client.get(
                f"{self.ray_address}/api/cluster_status"
            )
            if response.status_code == 200:
                status = response.json()
                resources = status.get("autoscaler_report", {}).get("usage", {})
                gpu_used = resources.get("GPU", [0, 0])[0]
                if gpu_used > 0:
                    return True

            return False

        except Exception as e:
            logger.debug(f"Could not check Ray: {e}")
            return False

    async def _monitor_training(self):
        """Monitor Ray and yield/reclaim GPU as needed."""
        logger.info("Starting training monitor...")
        was_training = False

        while True:
            try:
                training_active = await self._is_training_active()

                # Training just started - yield GPU
                if training_active and not was_training:
                    logger.info("Training detected! Yielding GPU...")
                    async with self._lock:
                        await self._unload_model()
                        self.is_yielded = True

                # Training just stopped - reclaim GPU
                elif not training_active and was_training:
                    logger.info("Training completed! Reclaiming GPU...")
                    await asyncio.sleep(30)  # Wait for training cleanup
                    async with self._lock:
                        await self._load_model()
                        self.is_yielded = False

                was_training = training_active

            except Exception as e:
                logger.error(f"Monitor error: {e}")

            await asyncio.sleep(self.check_interval)

    # =========================================================================
    # Generation
    # =========================================================================

    async def generate(
        self,
        messages: list,
        temperature: float = 0.7,
        top_p: float = 0.8,
        max_tokens: int = 4096,
        tools: Optional[list] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Generate completion."""
        async with self._lock:
            if not self.is_loaded:
                if self.is_yielded:
                    raise RuntimeError(
                        "Model yielded to training - use fallback service"
                    )
                raise RuntimeError("Model not loaded")

            self.requests_served += 1
            self.last_used = datetime.now()

            # Format prompt
            prompt = self._format_messages(messages, tools)

            # Generate
            from vllm import SamplingParams

            sampling_params = SamplingParams(
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                stop=kwargs.get("stop"),
            )

            outputs = self.engine.generate([prompt], sampling_params)
            output = outputs[0]

            return {
                "model": self.model_id,
                "mode": self.model_mode,
                "content": output.outputs[0].text,
                "finish_reason": output.outputs[0].finish_reason,
                "prompt_tokens": len(output.prompt_token_ids),
                "completion_tokens": len(output.outputs[0].token_ids),
            }

    def _format_messages(self, messages: list, tools: Optional[list] = None) -> str:
        """Format messages using tokenizer chat template."""
        if self.tokenizer is not None and hasattr(
            self.tokenizer, "apply_chat_template"
        ):
            try:
                return self.tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                    tools=tools,
                )
            except Exception as e:
                logger.warning(f"Chat template failed: {e}")

        # Fallback formatting
        formatted = ""
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                formatted += f"<|system|>\n{content}\n"
            elif role == "user":
                formatted += f"<|user|>\n{content}\n"
            elif role == "assistant":
                formatted += f"<|assistant|>\n{content}\n"
        formatted += "<|assistant|>\n"
        return formatted

    # =========================================================================
    # Status
    # =========================================================================

    def get_status(self) -> Dict[str, Any]:
        """Get current status."""
        return {
            "mode": self.model_mode,
            "model_id": self.model_id,
            "is_loaded": self.is_loaded,
            "is_yielded": self.is_yielded,
            "vram_gb": self._get_vram_usage(),
            "max_context": self.max_model_len,
            "requests_served": self.requests_served,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "load_time": self.load_time.isoformat() if self.load_time else None,
            "yield_on_training": self.yield_on_training,
        }

    def get_health(self) -> Dict[str, Any]:
        """Health check for Traefik."""
        # Return unhealthy if yielded (so Traefik routes to fallback)
        if self.is_yielded:
            return {
                "status": "unhealthy",
                "reason": "yielded_to_training",
                "model_id": self.model_id,
            }

        if not self.is_loaded:
            return {
                "status": "unhealthy",
                "reason": "not_loaded",
                "model_id": self.model_id,
            }

        return {
            "status": "healthy",
            "model_loaded": True,
            "model_id": self.model_id,
            "mode": self.model_mode,
            "vram_gb": self._get_vram_usage(),
        }
