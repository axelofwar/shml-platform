"""Simple Model Manager - Single GPU per Container.

Each container runs ONE model on ONE GPU.
- Primary container: RTX 3090 Ti with 32B model
- Fallback container: RTX 2070 with 3B model

Traefik handles routing between them based on health status.

Idle Management:
- Primary model goes idle after 60 minutes of inactivity to free GPU resources
- When idle, health check returns unhealthy so Traefik routes to fallback
- On next request, primary wakes up while fallback handles the current request
- Primary resumes handling requests once loaded (typically 2-3 minutes)

Warmup Feature:
- Sends periodic pings to keep model warm when training is not active
- Respects both Ray training jobs and native training (via file signals)
- Prevents unexpected wake-up delays during normal usage periods
"""

import gc
import os
import asyncio
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

import torch
import httpx

from .training_detector import (
    MultiSourceTrainingDetector,
    TrainingSignal,
    TrainingSource,
)

logger = logging.getLogger(__name__)

# Default idle timeout: 30 minutes
DEFAULT_IDLE_TIMEOUT_MINUTES = 30


class SimpleModelManager:
    """Manages a single model on a single GPU with idle timeout support."""

    def __init__(self):
        # Read config from environment (set in deploy/compose/docker-compose.yml)
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

        # Idle timeout configuration (primary only)
        # Set to 0 to disable idle timeout
        self.idle_timeout_minutes = int(
            os.getenv("IDLE_TIMEOUT_MINUTES", str(DEFAULT_IDLE_TIMEOUT_MINUTES))
        )
        self.idle_check_interval = int(os.getenv("IDLE_CHECK_INTERVAL_SECONDS", "60"))

        # Warmup configuration - keep model warm when training is not active
        self.warmup_enabled = os.getenv("WARMUP_ENABLED", "false").lower() == "true"
        self.warmup_interval_minutes = int(os.getenv("WARMUP_INTERVAL_MINUTES", "15"))

        # Multi-source training detection
        self.enable_file_signals = (
            os.getenv("ENABLE_FILE_SIGNALS", "true").lower() == "true"
        )
        self.enable_gpu_pressure = (
            os.getenv("ENABLE_GPU_PRESSURE", "false").lower() == "true"
        )

        # Model state
        self.engine = None
        self.tokenizer = None
        self.is_loaded = False
        self.is_yielded = False
        self.is_idle = False  # True when unloaded due to idle timeout
        self.load_time: Optional[datetime] = None
        self.requests_served = 0
        self.last_used: Optional[datetime] = None
        self._wake_up_in_progress = False

        # Async resources
        self._monitor_task: Optional[asyncio.Task] = None
        self._idle_monitor_task: Optional[asyncio.Task] = None
        self._warmup_task: Optional[asyncio.Task] = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()
        self._training_detector: Optional[MultiSourceTrainingDetector] = None
        self._current_training_signal: Optional[TrainingSignal] = None

    async def initialize(self):
        """Load the model and start monitoring (if primary)."""
        self._http_client = httpx.AsyncClient(timeout=5.0)

        # Initialize multi-source training detector
        if self.yield_on_training:
            self._training_detector = MultiSourceTrainingDetector(
                ray_address=self.ray_address if self.yield_on_training else None,
                enable_file_signals=self.enable_file_signals,
                enable_gpu_pressure=self.enable_gpu_pressure,
                http_client=self._http_client,
            )
            logger.info(
                f"Training detector initialized with sources: "
                f"{self._training_detector.get_status()['detectors']}"
            )

        # Check training status first
        if self.yield_on_training:
            training_signal = await self._training_detector.detect()
            if training_signal and training_signal.active:
                logger.info(
                    f"Training active ({training_signal.source.value}) - "
                    f"{self.model_mode} container will wait"
                )
                self.is_yielded = True
                self._current_training_signal = training_signal
                self._monitor_task = asyncio.create_task(self._monitor_training())
                return

        # Load the model
        await self._load_model()

        # Start monitoring for primary
        if self.yield_on_training:
            self._monitor_task = asyncio.create_task(self._monitor_training())

        # Start idle monitoring for primary (if timeout > 0)
        if self.model_mode == "primary" and self.idle_timeout_minutes > 0:
            logger.info(
                f"Idle timeout enabled: {self.idle_timeout_minutes} minutes, "
                f"check interval: {self.idle_check_interval}s"
            )
            self._idle_monitor_task = asyncio.create_task(self._monitor_idle())

        # Start warmup task for primary (keeps model warm when training is not active)
        if self.model_mode == "primary" and self.warmup_enabled:
            logger.info(
                f"Warmup enabled: will ping model every {self.warmup_interval_minutes} minutes "
                f"when training is not active"
            )
            self._warmup_task = asyncio.create_task(self._warmup_loop())

    async def shutdown(self):
        """Clean shutdown."""
        if self._monitor_task:
            self._monitor_task.cancel()

        if self._idle_monitor_task:
            self._idle_monitor_task.cancel()

        if self._warmup_task:
            self._warmup_task.cancel()

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
    # Training Detection (Multi-Source)
    # =========================================================================

    async def _is_training_active(self) -> bool:
        """Check if training is active from any source.

        Uses MultiSourceTrainingDetector to check:
        - Ray Jobs API
        - File-based signals
        - HTTP signals
        - GPU memory pressure (if enabled)
        """
        if self._training_detector is None:
            return False

        signal = await self._training_detector.detect()
        if signal and signal.active:
            self._current_training_signal = signal
            return True

        self._current_training_signal = None
        return False

    async def _monitor_training(self):
        """Monitor all training sources and yield/reclaim GPU as needed."""
        logger.info("Starting multi-source training monitor...")
        was_training = False

        while True:
            try:
                training_active = await self._is_training_active()

                # Training just started - yield GPU
                if training_active and not was_training:
                    source = (
                        self._current_training_signal.source.value
                        if self._current_training_signal
                        else "unknown"
                    )
                    job_id = (
                        self._current_training_signal.job_id
                        if self._current_training_signal
                        else None
                    )
                    logger.info(
                        f"Training detected from {source}! "
                        f"Job: {job_id or 'N/A'}. Yielding GPU..."
                    )
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
                        self._current_training_signal = None

                was_training = training_active

            except Exception as e:
                logger.error(f"Monitor error: {e}")

            await asyncio.sleep(self.check_interval)

    # =========================================================================
    # Idle Timeout (Primary only - free resources when not in use)
    # =========================================================================

    async def _monitor_idle(self):
        """Monitor for idle timeout and unload model to free resources.

        When the primary model has been idle for > idle_timeout_minutes:
        1. Unload the model to free GPU memory
        2. Mark as idle (health check returns unhealthy)
        3. Traefik will route requests to fallback
        4. On next request, wake_up() is called to reload
        """
        logger.info(
            f"Starting idle monitor (timeout: {self.idle_timeout_minutes}min)..."
        )

        while True:
            try:
                await asyncio.sleep(self.idle_check_interval)

                # Skip if already idle, yielded, or not loaded
                if self.is_idle or self.is_yielded or not self.is_loaded:
                    continue

                # Skip if no activity yet
                if self.last_used is None:
                    continue

                # Check idle time
                idle_duration = datetime.now() - self.last_used
                idle_minutes = idle_duration.total_seconds() / 60

                if idle_minutes >= self.idle_timeout_minutes:
                    logger.info(
                        f"Model idle for {idle_minutes:.1f} minutes "
                        f"(threshold: {self.idle_timeout_minutes}min). Going to sleep..."
                    )
                    async with self._lock:
                        await self._unload_model()
                        self.is_idle = True
                        logger.info(
                            "Primary model now idle. Fallback will handle requests. "
                            "Will wake up on next primary-level request."
                        )

            except asyncio.CancelledError:
                logger.info("Idle monitor cancelled")
                break
            except Exception as e:
                logger.error(f"Idle monitor error: {e}")

    async def _warmup_loop(self):
        """Periodically send warmup requests to keep model warm when training is not active.

        This prevents the model from going idle during periods of low usage,
        but respects training by checking if training is active before warming up.
        """
        warmup_interval_seconds = self.warmup_interval_minutes * 60
        logger.info(
            f"Starting warmup loop (interval: {self.warmup_interval_minutes}min)..."
        )

        while True:
            try:
                await asyncio.sleep(warmup_interval_seconds)

                # Skip warmup if:
                # 1. Model is yielded to training
                # 2. Model is already idle (let it sleep)
                # 3. Model is not loaded
                # 4. Training is currently active (check all sources)

                if self.is_yielded:
                    logger.debug("Warmup skipped: model yielded to training")
                    continue

                if self.is_idle:
                    logger.debug("Warmup skipped: model is idle")
                    continue

                if not self.is_loaded:
                    logger.debug("Warmup skipped: model not loaded")
                    continue

                # Check if training is active from any source
                if self._training_detector:
                    signal = await self._training_detector.detect()
                    if signal and signal.active:
                        logger.debug(
                            f"Warmup skipped: training active ({signal.source.value})"
                        )
                        continue

                # Also check for native training via file signals
                native_training_active = await self._check_native_training()
                if native_training_active:
                    logger.debug("Warmup skipped: native training active")
                    continue

                # Send warmup request - just update last_used timestamp
                # This resets the idle timer without actually generating anything
                logger.debug("Sending warmup ping to keep model warm")
                self.last_used = datetime.now()

            except asyncio.CancelledError:
                logger.info("Warmup loop cancelled")
                break
            except Exception as e:
                logger.error(f"Warmup loop error: {e}")

    async def _check_native_training(self) -> bool:
        """Check if native (non-Ray) training is active via file signals."""
        import os
        from pathlib import Path

        # Check common signal file locations
        signal_paths = [
            Path("/tmp/training_active"),
            Path("/app/data/training_active"),
            Path(os.getenv("TRAINING_SIGNAL_FILE", "/tmp/training_active")),
        ]

        for path in signal_paths:
            if path.exists():
                try:
                    # Check if file was modified in last 5 minutes (training still active)
                    mtime = path.stat().st_mtime
                    age_seconds = datetime.now().timestamp() - mtime
                    if age_seconds < 300:  # 5 minutes
                        return True
                except Exception:
                    pass

        return False

    async def wake_up(self) -> bool:
        """Wake up the model from idle state.

        Called when a request comes in that needs the primary model.
        The fallback handles the current request while primary loads.

        Returns True if wake-up initiated, False if already awake or in progress.
        """
        if self.is_loaded and not self.is_idle:
            return False  # Already awake

        if self._wake_up_in_progress:
            logger.debug("Wake-up already in progress")
            return False

        if self.is_yielded:
            logger.debug("Cannot wake up - yielded to training")
            return False

        logger.info("Waking up primary model from idle state...")
        self._wake_up_in_progress = True

        try:
            async with self._lock:
                await self._load_model()
                self.is_idle = False
                self.last_used = datetime.now()  # Reset idle timer

            logger.info("Primary model awake and ready")
            return True

        except Exception as e:
            logger.error(f"Failed to wake up model: {e}")
            return False
        finally:
            self._wake_up_in_progress = False

    def is_sleeping(self) -> bool:
        """Check if the model is in idle/sleep state."""
        return self.is_idle or (not self.is_loaded and not self.is_yielded)

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
        """Generate completion.

        If the model is idle, triggers wake-up in background and returns
        a response indicating the request should go to fallback.
        """
        # If model is idle, trigger wake-up and redirect to fallback
        if self.is_idle:
            # Start wake-up in background
            asyncio.create_task(self.wake_up())
            raise RuntimeError(
                "Model is idle - waking up. Use fallback service for this request."
            )

        async with self._lock:
            if not self.is_loaded:
                if self.is_yielded:
                    raise RuntimeError(
                        "Model yielded to training - use fallback service"
                    )
                raise RuntimeError("Model not loaded")

            self.requests_served += 1
            self.last_used = datetime.now()  # Update activity timestamp

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
        idle_for_minutes = None
        if self.last_used:
            idle_for_minutes = round(
                (datetime.now() - self.last_used).total_seconds() / 60, 1
            )

        return {
            "mode": self.model_mode,
            "model_id": self.model_id,
            "is_loaded": self.is_loaded,
            "is_yielded": self.is_yielded,
            "is_idle": self.is_idle,
            "idle_timeout_minutes": self.idle_timeout_minutes,
            "idle_for_minutes": idle_for_minutes,
            "wake_up_in_progress": self._wake_up_in_progress,
            "vram_gb": self._get_vram_usage(),
            "max_context": self.max_model_len,
            "requests_served": self.requests_served,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "load_time": self.load_time.isoformat() if self.load_time else None,
            "yield_on_training": self.yield_on_training,
        }

    def get_health(self) -> Dict[str, Any]:
        """Health check for Traefik.

        Returns unhealthy when:
        - Model is yielded to training
        - Model is idle (sleeping)
        - Model failed to load

        This allows Traefik to route traffic to the fallback model.
        """
        # Return unhealthy if yielded (so Traefik routes to fallback)
        if self.is_yielded:
            return {
                "status": "unhealthy",
                "reason": "yielded_to_training",
                "model_id": self.model_id,
            }

        # Return unhealthy if idle (so Traefik routes to fallback)
        if self.is_idle:
            return {
                "status": "unhealthy",
                "reason": "idle_sleeping",
                "model_id": self.model_id,
                "wake_up_in_progress": self._wake_up_in_progress,
                "message": "Model is sleeping to conserve resources. Waking up...",
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
