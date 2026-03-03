"""
Dynamic Model Manager - Integrates MPS control, routing, and training coordination.

This is the main integration point that brings together:
- SimpleModelManager (base model loading/inference)
- MPSController (MPS daemon control)
- GPUAllocator (GPU resource tracking)
- RequestRouter (intelligent request routing)
- TrainingCoordinator (training job orchestration)

Cross-references:
- DYNAMIC_MPS_DESIGN.md [NAV:ARCH] → Architecture overview
- DYNAMIC_MPS_DESIGN.md [NAV:STATE] → State machine diagram
- SOTA_BEST_PRACTICES_SUMMARY.md [NAV:TOOLORCH] → Orchestration patterns
"""

import asyncio
import logging
import os
from typing import Optional, Dict, Any, List
from datetime import datetime
from dataclasses import dataclass

from .model_manager_simple import SimpleModelManager
from .mps_controller import MPSController, MPSManager
from .gpu_allocator import GPUAllocator, GPUAllocationMode
from .request_router import (
    RequestRouter,
    RoutingConfig,
    RoutingResult,
    RoutingDecision,
    UserRole,
)
from .training_coordinator import (
    TrainingCoordinator,
    TrainingState,
    TrainingJob,
    CoordinatorConfig,
    QueuedRequest,
)
from .training_detector import (
    MultiSourceTrainingDetector,
    TrainingSignal,
    TrainingSource,
)

logger = logging.getLogger(__name__)


@dataclass
class DynamicModelManagerConfig:
    """Configuration for dynamic model manager."""

    # Model config
    model_id: str = ""
    model_mode: str = "primary"  # "primary" or "fallback"
    max_model_len: int = 4096
    gpu_memory_util: float = 0.85

    # MPS config
    enable_mps_control: bool = True
    mps_gpu_id: int = 0

    # Training coordination
    enable_training_coordination: bool = True
    ray_address: str = "http://ray-head:8265"

    # Routing config
    enable_intelligent_routing: bool = True
    context_threshold: int = 4096
    max_tokens_threshold: int = 2048

    # Queue config
    queue_enabled: bool = True
    queue_timeout_seconds: float = 30.0
    checkpoint_trigger_threshold: int = 3

    # Idle timeout
    idle_timeout_minutes: int = 30

    @classmethod
    def from_env(cls) -> "DynamicModelManagerConfig":
        """Load configuration from environment variables."""
        return cls(
            model_id=os.getenv("MODEL_ID", "Qwen/Qwen2.5-Coder-32B-Instruct-AWQ"),
            model_mode=os.getenv("MODEL_MODE", "primary"),
            max_model_len=int(os.getenv("MAX_MODEL_LEN", "4096")),
            gpu_memory_util=float(os.getenv("GPU_MEMORY_UTILIZATION", "0.85")),
            enable_mps_control=os.getenv("ENABLE_MPS_CONTROL", "true").lower()
            == "true",
            mps_gpu_id=int(os.getenv("MPS_GPU_ID", "0")),
            enable_training_coordination=os.getenv(
                "ENABLE_TRAINING_COORDINATION", "true"
            ).lower()
            == "true",
            ray_address=os.getenv("RAY_ADDRESS", "http://ray-head:8265"),
            enable_intelligent_routing=os.getenv(
                "ENABLE_INTELLIGENT_ROUTING", "true"
            ).lower()
            == "true",
            context_threshold=int(os.getenv("ROUTING_CONTEXT_THRESHOLD", "4096")),
            max_tokens_threshold=int(os.getenv("ROUTING_MAX_TOKENS_THRESHOLD", "2048")),
            queue_enabled=os.getenv("QUEUE_ENABLED", "true").lower() == "true",
            queue_timeout_seconds=float(os.getenv("QUEUE_TIMEOUT_SECONDS", "30.0")),
            checkpoint_trigger_threshold=int(
                os.getenv("CHECKPOINT_TRIGGER_THRESHOLD", "3")
            ),
            idle_timeout_minutes=int(os.getenv("IDLE_TIMEOUT_MINUTES", "30")),
        )


class DynamicModelManager:
    """
    Dynamic Model Manager with integrated MPS control and training coordination.

    This manager integrates multiple components to provide:
    1. MPS daemon control for GPU sharing
    2. Intelligent request routing with complexity detection
    3. Training job coordination with checkpointing
    4. Queue management for primary model requests

    Design Philosophy (from [NAV:TOOLORCH]):
    - Training is the priority
    - Defer to fallback unless absolutely necessary
    - Auto-selection goes through rigorous filtering
    - Primary hidden during training (not selectable in UI)

    State Transitions (from [NAV:STATE]):
    - IDLE: Normal operation, primary available
    - TRAINING: Training active, fallback only
    - CHECKPOINTING: Saving checkpoint before pause
    - PAUSED: Training paused, serving queued requests
    """

    def __init__(self, config: Optional[DynamicModelManagerConfig] = None):
        self.config = config or DynamicModelManagerConfig.from_env()

        # Core components
        self._base_manager: Optional[SimpleModelManager] = None
        self._mps_controller: Optional[MPSController] = None
        self._gpu_allocator: Optional[GPUAllocator] = None
        self._router: Optional[RequestRouter] = None
        self._coordinator: Optional[TrainingCoordinator] = None
        self._training_detector: Optional[MultiSourceTrainingDetector] = None

        # State
        self._initialized = False
        self._lock = asyncio.Lock()

        # Request queue for primary model during training
        self._request_queue: List[QueuedRequest] = []
        self._queue_drain_task: Optional[asyncio.Task] = None

        # Callbacks for AG-UI events
        self._on_routing_decision: Optional[callable] = None
        self._on_queue_update: Optional[callable] = None
        self._on_training_state_change: Optional[callable] = None

    async def initialize(self) -> bool:
        """Initialize all components."""
        try:
            logger.info("Initializing DynamicModelManager...")

            # Initialize base model manager
            self._base_manager = SimpleModelManager()
            await self._base_manager.initialize()
            logger.info("Base model manager initialized")

            # Initialize MPS controller (if enabled and primary mode)
            if self.config.enable_mps_control and self.config.model_mode == "primary":
                self._mps_controller = MPSController(gpu_id=self.config.mps_gpu_id)
                mps_running = await self._mps_controller.is_running()
                logger.info(f"MPS status: {'running' if mps_running else 'stopped'}")

            # Initialize GPU allocator
            self._gpu_allocator = GPUAllocator()
            await self._gpu_allocator.initialize()
            logger.info("GPU allocator initialized")

            # Initialize request router (if enabled)
            if self.config.enable_intelligent_routing:
                routing_config = RoutingConfig(
                    context_threshold=self.config.context_threshold,
                    max_tokens_threshold=self.config.max_tokens_threshold,
                    queue_timeout_seconds=self.config.queue_timeout_seconds,
                )
                self._router = RequestRouter(config=routing_config)
                logger.info("Request router initialized")

            # Initialize training coordinator (if enabled and primary mode)
            if (
                self.config.enable_training_coordination
                and self.config.model_mode == "primary"
            ):
                coordinator_config = CoordinatorConfig(
                    training_gpu=self.config.mps_gpu_id,
                    queue_timeout_seconds=self.config.queue_timeout_seconds,
                    checkpoint_trigger_threshold=self.config.checkpoint_trigger_threshold,
                    ray_address=self.config.ray_address,
                )
                self._coordinator = TrainingCoordinator(config=coordinator_config)
                await self._coordinator.initialize()

                # Register callbacks
                self._coordinator._on_state_change = self._on_coordinator_state_change
                self._coordinator._on_checkpoint_needed = self._on_checkpoint_needed
                self._coordinator._on_training_pause = self._on_training_pause
                self._coordinator._on_training_resume = self._on_training_resume

                logger.info("Training coordinator initialized")

            self._initialized = True
            logger.info("DynamicModelManager initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize DynamicModelManager: {e}")
            return False

    async def shutdown(self):
        """Clean shutdown of all components."""
        logger.info("Shutting down DynamicModelManager...")

        if self._queue_drain_task:
            self._queue_drain_task.cancel()

        if self._coordinator:
            await self._coordinator.shutdown()

        if self._base_manager:
            await self._base_manager.shutdown()

        logger.info("DynamicModelManager shut down")

    # =========================================================================
    # Request Routing
    # =========================================================================

    async def route_request(
        self,
        messages: list,
        max_tokens: Optional[int] = None,
        model_selection: Optional[str] = None,
        user_role: str = "developer",
        conversation_id: Optional[str] = None,
        force_primary: bool = False,
    ) -> RoutingResult:
        """
        Route a request to the appropriate model.

        Implements the filtering logic from [NAV:ROUTER]:
        1. Check if RAG has relevant context (score > 0.75) → Fallback
        2. Check if history has relevant answer → Fallback
        3. Check if prompt can be compressed to fit → Fallback
        4. Check if simple request (complexity < 0.4, < 3 skills) → Fallback
        5. Context > 8K → Queue for Primary
        6. Multi-skill task (≥ 3 tools) → Queue for Primary
        7. High complexity (≥ 0.6) → Queue for Primary

        Args:
            messages: Chat messages
            max_tokens: Requested max tokens
            model_selection: "primary", "fallback", "auto", or None
            user_role: "viewer", "developer", "elevated", "admin"
            conversation_id: For history check
            force_primary: Admin force override

        Returns:
            RoutingResult with decision and UI display info
        """
        if not self._router:
            # No routing, use base manager
            return RoutingResult(
                decision=(
                    RoutingDecision.PRIMARY
                    if self.config.model_mode == "primary"
                    else RoutingDecision.FALLBACK
                ),
                reason="routing_disabled",
                target_model=self.config.model_mode,
            )

        # Convert user role string to enum
        try:
            role = UserRole(user_role)
        except ValueError:
            role = UserRole.DEVELOPER

        # Check if training is active
        training_active = self._coordinator and self._coordinator.is_training_active
        self._router.set_training_active(training_active)
        self._router.set_queue_length(len(self._request_queue))

        # Analyze and route
        result = self._router.analyze_request(
            messages=messages,
            max_tokens=max_tokens,
            model_selection=model_selection,
            user_role=role,
            conversation_id=conversation_id,
            force_primary=force_primary,
        )

        # Emit AG-UI event
        if self._on_routing_decision:
            await self._on_routing_decision(result.to_dict())

        return result

    async def enqueue_request(
        self,
        request_id: str,
        complexity_score: float,
        user_role: str = "developer",
        requires_confirmation: bool = False,
    ) -> int:
        """
        Add request to primary model queue.

        Returns queue position.
        """
        now = datetime.now()
        queued = QueuedRequest(
            request_id=request_id,
            queued_at=now,
            timeout_at=now + timedelta(seconds=self.config.queue_timeout_seconds),
            priority=1 if user_role == "admin" else 5,
            complexity_score=complexity_score,
            user_role=user_role,
            requires_confirmation=requires_confirmation,
        )

        self._request_queue.append(queued)
        position = len(self._request_queue)

        # Update router queue length
        if self._router:
            self._router.set_queue_length(position)

        # Check if we should trigger checkpoint
        if self._coordinator and await self._should_trigger_checkpoint():
            logger.info(
                f"Queue threshold reached ({position} requests), triggering checkpoint"
            )
            asyncio.create_task(
                self._coordinator.pause_training(reason="queue_threshold")
            )

        # Emit queue update event
        if self._on_queue_update:
            await self._on_queue_update(
                {
                    "queue_length": position,
                    "request_id": request_id,
                    "estimated_wait": self._estimate_wait_time(position),
                }
            )

        return position

    async def _should_trigger_checkpoint(self) -> bool:
        """Check if queue state warrants pausing training."""
        if not self._coordinator or not self._coordinator.is_training_active:
            return False

        # Trigger if queue >= threshold
        if len(self._request_queue) >= self.config.checkpoint_trigger_threshold:
            return True

        # Trigger if any request waiting > 30s
        for req in self._request_queue:
            if req.wait_time_seconds() > self.config.queue_timeout_seconds:
                return True

        return False

    def _estimate_wait_time(self, queue_position: int) -> float:
        """Estimate wait time based on queue position."""
        if self._router:
            return self._router.estimate_wait_time(queue_position)
        return queue_position * 15.0  # Default 15s per request

    # =========================================================================
    # Training Control
    # =========================================================================

    async def start_training(self, job: TrainingJob) -> bool:
        """
        Start a training job.

        This will:
        1. Signal primary model to yield GPU
        2. Stop MPS daemon
        3. Start training with exclusive GPU access
        4. Update routing to fallback-only
        """
        if not self._coordinator:
            logger.error("Training coordinator not initialized")
            return False

        async with self._lock:
            # Yield GPU from inference
            if self._base_manager and self._base_manager.is_loaded:
                logger.info("Yielding GPU from inference for training")
                await self._base_manager._unload_model()
                self._base_manager.is_yielded = True

            # Start training via coordinator
            return await self._coordinator.start_training(job)

    async def stop_training(self, save_checkpoint: bool = True) -> bool:
        """
        Stop training and restore inference.

        This will:
        1. Stop training (optionally save checkpoint)
        2. Start MPS daemon
        3. Reload primary model
        4. Resume normal routing
        """
        if not self._coordinator:
            return False

        async with self._lock:
            result = await self._coordinator.stop_training(save_checkpoint)

            if result:
                # Restore inference
                if self._base_manager:
                    self._base_manager.is_yielded = False
                    await self._base_manager._load_model()

            return result

    async def get_training_status(self) -> Dict[str, Any]:
        """Get current training status."""
        if not self._coordinator:
            return {"state": "not_initialized", "training_available": False}

        state = self._coordinator.state
        job = self._coordinator._current_job

        return {
            "state": state.value,
            "training_active": self._coordinator.is_training_active,
            "current_job": (
                {
                    "job_id": job.job_id if job else None,
                    "current_step": job.current_step if job else None,
                    "last_checkpoint_step": job.last_checkpoint_step if job else None,
                    "started_at": (
                        job.started_at.isoformat() if job and job.started_at else None
                    ),
                }
                if job
                else None
            ),
            "queue_length": len(self._request_queue),
            "queue_requests": [
                {
                    "request_id": r.request_id,
                    "wait_seconds": r.wait_time_seconds(),
                    "expired": r.is_expired(),
                }
                for r in self._request_queue
            ],
            "mps_running": (
                await self._mps_controller.is_running()
                if self._mps_controller
                else None
            ),
            "gpu_allocation": (
                await self._gpu_allocator.get_status() if self._gpu_allocator else None
            ),
        }

    # =========================================================================
    # Coordinator Callbacks
    # =========================================================================

    async def _on_coordinator_state_change(self, state: TrainingState):
        """Handle training state changes."""
        logger.info(f"Training state changed to: {state.value}")

        # Emit AG-UI event
        if self._on_training_state_change:
            await self._on_training_state_change(
                {"state": state.value, "timestamp": datetime.now().isoformat()}
            )

        # If entering PAUSED, start draining queue
        if state == TrainingState.PAUSED:
            self._queue_drain_task = asyncio.create_task(self._drain_queue())

    async def _on_checkpoint_needed(self, job: TrainingJob) -> str:
        """Handle checkpoint request from coordinator."""
        logger.info(
            f"Checkpoint requested for job {job.job_id} at step {job.current_step}"
        )
        # This would call the actual checkpoint save mechanism
        # For now, return a dummy path
        checkpoint_path = f"/checkpoints/{job.job_id}/step_{job.current_step}"
        return checkpoint_path

    async def _on_training_pause(self, job: TrainingJob):
        """Handle training pause."""
        logger.info(f"Training paused for job {job.job_id}")
        # Signal actual training process to pause
        # This would integrate with the SHML training library

    async def _on_training_resume(self, job: TrainingJob):
        """Handle training resume."""
        logger.info(f"Training resumed for job {job.job_id}")
        # Signal actual training process to resume

    async def _drain_queue(self):
        """Drain the request queue when training is paused."""
        logger.info("Starting queue drain")

        while self._request_queue and self._coordinator.state == TrainingState.PAUSED:
            # Get next request
            request = self._request_queue.pop(0)

            if request.is_expired():
                logger.warning(f"Request {request.request_id} expired, skipping")
                continue

            # Execute callback if available
            if request.callback:
                try:
                    await request.callback()
                except Exception as e:
                    logger.error(f"Error processing queued request: {e}")

            # Update queue length
            if self._router:
                self._router.set_queue_length(len(self._request_queue))

            # Emit queue update
            if self._on_queue_update:
                await self._on_queue_update(
                    {
                        "queue_length": len(self._request_queue),
                        "request_processed": request.request_id,
                    }
                )

        logger.info("Queue drain complete")

        # Check if we should resume training
        if not self._request_queue and self._coordinator:
            # Wait a bit for potential new requests
            await asyncio.sleep(30)

            if not self._request_queue:
                logger.info("Queue empty for 30s, resuming training")
                await self._coordinator.resume_training()

    # =========================================================================
    # Inference Delegation
    # =========================================================================

    async def generate(
        self,
        messages: list,
        temperature: float = 0.7,
        top_p: float = 0.8,
        max_tokens: int = 4096,
        tools: Optional[list] = None,
        model_selection: Optional[str] = None,
        user_role: str = "developer",
        conversation_id: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Generate completion with intelligent routing.

        This is the main entry point that:
        1. Routes request to appropriate model
        2. Handles queueing during training
        3. Returns with routing metadata
        """
        # Route the request
        routing = await self.route_request(
            messages=messages,
            max_tokens=max_tokens,
            model_selection=model_selection,
            user_role=user_role,
            conversation_id=conversation_id,
        )

        # Handle routing decision
        if routing.decision == RoutingDecision.REJECTED:
            raise RuntimeError(f"Request rejected: {routing.reason.value}")

        if routing.decision == RoutingDecision.QUEUED_FOR_PRIMARY:
            # This request needs primary but training is active
            # The caller should handle queueing
            raise RuntimeError(
                f"Request queued for primary model. "
                f"Queue position: {routing.queue_position}, "
                f"Estimated wait: {routing.estimated_wait_seconds}s"
            )

        # Delegate to base manager
        if not self._base_manager:
            raise RuntimeError("Model manager not initialized")

        result = await self._base_manager.generate(
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            tools=tools,
            **kwargs,
        )

        # Add routing metadata
        result["routing"] = routing.to_dict()

        return result

    # =========================================================================
    # Status and Health
    # =========================================================================

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive status."""
        base_status = self._base_manager.get_status() if self._base_manager else {}

        return {
            **base_status,
            "dynamic_mode": True,
            "mps_enabled": self._mps_controller is not None,
            "routing_enabled": self._router is not None,
            "training_coordination_enabled": self._coordinator is not None,
            "queue_length": len(self._request_queue),
            "training_state": (
                self._coordinator.state.value
                if self._coordinator
                else "not_initialized"
            ),
        }

    def get_health(self) -> Dict[str, Any]:
        """Get health status for Traefik."""
        if not self._base_manager:
            return {"status": "unhealthy", "reason": "not_initialized"}

        return self._base_manager.get_health()

    def get_routing_config(self) -> Dict[str, Any]:
        """Get current routing configuration."""
        if not self._router:
            return {"routing_enabled": False}

        return {
            "routing_enabled": True,
            "context_threshold": self.config.context_threshold,
            "max_tokens_threshold": self.config.max_tokens_threshold,
            "queue_enabled": self.config.queue_enabled,
            "queue_timeout_seconds": self.config.queue_timeout_seconds,
            "checkpoint_trigger_threshold": self.config.checkpoint_trigger_threshold,
            "training_active": (
                self._coordinator.is_training_active if self._coordinator else False
            ),
        }

    def get_model_availability(self) -> Dict[str, Any]:
        """
        Get model availability for UI display.

        During training:
        - primary: hidden (not selectable)
        - auto: available (filtered to fallback unless truly needed)
        - fallback: available (always)
        """
        training_active = self._coordinator and self._coordinator.is_training_active

        return {
            "primary": {
                "available": not training_active,
                "selectable": not training_active,
                "reason": "training_active" if training_active else None,
            },
            "auto": {
                "available": True,
                "selectable": True,
                "behavior": (
                    "fallback_preferred" if training_active else "smart_routing"
                ),
            },
            "fallback": {"available": True, "selectable": True, "reason": None},
            "training_active": training_active,
            "queue_length": len(self._request_queue) if training_active else 0,
        }


# Import timedelta for queue management
from datetime import timedelta
