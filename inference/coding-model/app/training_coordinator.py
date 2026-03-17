"""
Training Coordinator - Orchestrates training jobs with inference workloads.

Manages the lifecycle of training jobs including:
- Starting training with proper GPU allocation
- Pausing training for urgent inference requests
- Checkpointing and resume
- Queue management for primary model requests
"""

import asyncio
import logging
import httpx
from typing import Optional, Dict, Any, Callable, Awaitable, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json

from .mps_controller import MPSController, MPSManager
from .gpu_allocator import GPUAllocator, GPUAllocationMode
from .request_router import RequestRouter, RoutingConfig

logger = logging.getLogger(__name__)


class TrainingState(Enum):
    """Training coordinator states."""

    IDLE = "idle"  # No training, full inference available
    STARTING = "starting"  # Preparing to start training
    TRAINING = "training"  # Training active, fallback-only inference
    CHECKPOINTING = "checkpointing"  # Saving checkpoint before pause
    PAUSED = "paused"  # Training paused, primary inference active
    RESUMING = "resuming"  # Resuming training from checkpoint
    STOPPING = "stopping"  # Training completing/stopping


@dataclass
class TrainingJob:
    """Information about a training job."""

    job_id: str
    script_path: str
    gpu_ids: List[int]
    priority: int = 5
    checkpoint_interval: int = 100  # steps
    current_step: int = 0
    last_checkpoint_step: int = 0
    last_checkpoint_path: Optional[str] = None
    checkpoint_paths: List[str] = field(
        default_factory=list
    )  # Keep track of all checkpoints
    started_at: Optional[datetime] = None
    paused_at: Optional[datetime] = None
    total_pause_duration: timedelta = field(default_factory=lambda: timedelta())
    waiting_for_confirmation: bool = False
    confirmation_requested_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def steps_since_checkpoint(self) -> int:
        """Get steps since last checkpoint."""
        return self.current_step - self.last_checkpoint_step

    def needs_checkpoint_before_interrupt(self, threshold: int = 100) -> bool:
        """Check if we need to checkpoint before interrupting."""
        return self.steps_since_checkpoint() > threshold


@dataclass
class QueuedRequest:
    """A request queued for primary model."""

    request_id: str
    queued_at: datetime
    timeout_at: datetime
    priority: int
    complexity_score: float
    user_role: str = "developer"
    requires_confirmation: bool = False  # For admin force during training
    confirmed: bool = False
    callback: Optional[Callable[[], Awaitable[None]]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """Check if request has timed out."""
        return datetime.now() > self.timeout_at

    def wait_time_seconds(self) -> float:
        """Get how long this request has been waiting."""
        return (datetime.now() - self.queued_at).total_seconds()


@dataclass
class CoordinatorConfig:
    """Configuration for training coordinator."""

    # Training checkpointing
    checkpoint_interval: int = 100  # Save every 100 steps
    checkpoint_on_pause: bool = True
    max_checkpoints_to_keep: int = (
        3  # Keep last 3 checkpoints (~1.5-3GB total for typical models)
    )
    force_checkpoint_threshold: int = 100  # Force checkpoint if >100 steps since last

    # Pause/resume timing
    max_pause_duration_seconds: float = 300.0  # 5 min max pause
    idle_timeout_before_resume_seconds: float = 900.0  # 15 min idle -> resume training
    user_confirmation_timeout_seconds: float = 300.0  # 5 min to confirm -> auto-resume

    # Queue management
    queue_max_size: int = 10
    queue_timeout_seconds: float = 30.0  # 30s timeout per requirements
    checkpoint_trigger_threshold: int = (
        3  # Queue size OR user waiting >30s -> checkpoint
    )

    # GPU allocation
    training_gpu: int = 0  # GPU for training
    fallback_gpu: int = 1  # GPU for fallback (always available)

    # GPU sharing analysis (answer to question 2)
    # 32B model at 4-bit = ~18GB, needs ~22GB with KV cache
    # Training LoRA/QLoRA needs ~6-12GB depending on batch size
    # Conclusion: Cannot run 32B + training simultaneously on 24GB
    # Must use pause-based approach
    allow_concurrent_training_inference: bool = False

    # Inference endpoints
    primary_inference_url: str = "http://localhost:8000"
    fallback_inference_url: str = "http://localhost:8001"
    ray_address: str = "http://ray-head:8265"


class TrainingCoordinator:
    """
    Coordinates training jobs with inference workloads.

    State machine:
        IDLE <---> STARTING ---> TRAINING <---> CHECKPOINTING ---> PAUSED
          ^                         |                                 |
          |                         v                                 |
          +---------------------- STOPPING <--------------------------+

    Usage:
        coordinator = TrainingCoordinator(config)
        await coordinator.initialize()

        # Start training
        await coordinator.start_training(TrainingJob(...))

        # Request arrives that needs primary
        if await coordinator.should_pause_for_request(request):
            await coordinator.pause_training()
            # ... serve request ...
            await coordinator.resume_training()
    """

    def __init__(self, config: Optional[CoordinatorConfig] = None):
        self.config = config or CoordinatorConfig()
        self._state = TrainingState.IDLE
        self._current_job: Optional[TrainingJob] = None
        self._request_queue: List[QueuedRequest] = []

        # Components
        self._mps_controller = MPSController(gpu_id=self.config.training_gpu)
        self._gpu_allocator = GPUAllocator()
        self._router = RequestRouter()

        # Callbacks
        self._on_state_change: Optional[Callable[[TrainingState], Awaitable[None]]] = (
            None
        )
        self._on_checkpoint_needed: Optional[
            Callable[[TrainingJob], Awaitable[str]]
        ] = None
        self._on_training_pause: Optional[Callable[[TrainingJob], Awaitable[None]]] = (
            None
        )
        self._on_training_resume: Optional[Callable[[TrainingJob], Awaitable[None]]] = (
            None
        )

        # State
        self._lock = asyncio.Lock()
        self._initialized = False

    @property
    def state(self) -> TrainingState:
        """Current coordinator state."""
        return self._state

    @property
    def is_training_active(self) -> bool:
        """Whether training is currently running."""
        return self._state in (TrainingState.TRAINING, TrainingState.CHECKPOINTING)

    @property
    def queue_length(self) -> int:
        """Number of requests in queue."""
        return len(self._request_queue)

    async def initialize(self) -> bool:
        """Initialize coordinator components."""
        try:
            # Initialize GPU allocator
            if not await self._gpu_allocator.initialize():
                logger.error("Failed to initialize GPU allocator")
                return False

            # Check MPS status
            mps_running = await self._mps_controller.is_running()
            logger.info(
                f"MPS status on GPU {self.config.training_gpu}: {'running' if mps_running else 'stopped'}"
            )

            # Update router with training state
            self._router.set_training_active(False)

            self._initialized = True
            logger.info("TrainingCoordinator initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize TrainingCoordinator: {e}")
            return False

    async def start_training(self, job: TrainingJob) -> bool:
        """
        Start a training job.

        This will:
        1. Signal inference to yield GPU
        2. Stop MPS daemon
        3. Allocate GPU to training
        4. Update router for fallback-only mode

        Args:
            job: Training job to start

        Returns:
            True if training started successfully
        """
        async with self._lock:
            if self._state != TrainingState.IDLE:
                logger.error(f"Cannot start training in state: {self._state}")
                return False

            self._state = TrainingState.STARTING
            self._current_job = job

            try:
                logger.info(f"Starting training job: {job.job_id}")

                # Step 1: Signal inference model to yield
                await self._signal_inference_yield()

                # Step 2: Wait for GPU to be released
                await self._wait_for_gpu_release()

                # Step 3: Stop MPS daemon
                if await self._mps_controller.is_running():
                    if not await self._mps_controller.stop():
                        raise Exception("Failed to stop MPS daemon")

                # Step 4: Allocate GPU to training
                if not await self._gpu_allocator.allocate_to_training(
                    gpu_id=self.config.training_gpu, job_id=job.job_id
                ):
                    raise Exception("Failed to allocate GPU to training")

                # Step 5: Update router
                self._router.set_training_active(True)

                # Step 6: Start the actual training job (via Ray or direct)
                # This would be handled by the caller or a callback

                job.started_at = datetime.now()
                self._state = TrainingState.TRAINING

                if self._on_state_change:
                    await self._on_state_change(self._state)

                logger.info(f"Training started: {job.job_id}")
                return True

            except Exception as e:
                logger.error(f"Failed to start training: {e}")
                self._state = TrainingState.IDLE
                self._current_job = None
                return False

    async def pause_training(self, reason: str = "primary_request") -> bool:
        """
        Pause training to serve primary inference requests.

        This will:
        1. Check if checkpoint needed (>100 steps since last)
        2. Force checkpoint if needed before interrupting
        3. Signal training to pause
        4. Release GPU from training
        5. Start MPS daemon
        6. Update router to allow primary

        Args:
            reason: Why training is being paused

        Returns:
            True if paused successfully
        """
        async with self._lock:
            if self._state != TrainingState.TRAINING:
                logger.error(f"Cannot pause training in state: {self._state}")
                return False

            job = self._current_job
            if not job:
                return False

            # CRITICAL: Validate checkpoint before interrupting
            if job.needs_checkpoint_before_interrupt(
                self.config.force_checkpoint_threshold
            ):
                logger.info(
                    f"Force checkpoint required: {job.steps_since_checkpoint()} steps since last"
                )
                self._state = TrainingState.CHECKPOINTING

                if self._on_checkpoint_needed:
                    checkpoint_path = await self._on_checkpoint_needed(job)
                    job.last_checkpoint_path = checkpoint_path
                    job.last_checkpoint_step = job.current_step
                    job.checkpoint_paths.append(checkpoint_path)

                    # Prune old checkpoints
                    await self._prune_old_checkpoints(job)

                    logger.info(
                        f"Checkpoint saved at step {job.current_step}: {checkpoint_path}"
                    )
            else:
                self._state = TrainingState.CHECKPOINTING
                logger.info(
                    f"Recent checkpoint exists ({job.steps_since_checkpoint()} steps ago), skipping"
                )

            logger.info(f"Pausing training job: {job.job_id} (reason: {reason})")

            try:
                # Signal training to pause
                if self._on_training_pause:
                    await self._on_training_pause(job)

                # Release GPU
                await self._gpu_allocator.release_from_training(
                    self.config.training_gpu
                )

                # Start MPS daemon
                if not await self._mps_controller.start():
                    logger.warning("Failed to start MPS, continuing without it")

                # Signal inference to reclaim GPU
                await self._signal_inference_reclaim()

                # Update router
                self._router.set_training_active(False)

                job.paused_at = datetime.now()
                self._state = TrainingState.PAUSED

                # Start idle monitor
                asyncio.create_task(self._monitor_idle_timeout())

                if self._on_state_change:
                    await self._on_state_change(self._state)

                logger.info(f"Training paused: {job.job_id}")
                return True

            except Exception as e:
                logger.error(f"Failed to pause training: {e}")
                return False

    async def _prune_old_checkpoints(self, job: TrainingJob):
        """Remove old checkpoints keeping only the most recent N."""
        if len(job.checkpoint_paths) <= self.config.max_checkpoints_to_keep:
            return

        to_remove = job.checkpoint_paths[: -self.config.max_checkpoints_to_keep]
        job.checkpoint_paths = job.checkpoint_paths[
            -self.config.max_checkpoints_to_keep :
        ]

        for path in to_remove:
            try:
                import shutil
                import os

                if os.path.isdir(path):
                    shutil.rmtree(path)
                elif os.path.isfile(path):
                    os.remove(path)
                logger.info(f"Pruned old checkpoint: {path}")
            except Exception as e:
                logger.warning(f"Failed to prune checkpoint {path}: {e}")

    async def _monitor_idle_timeout(self):
        """
        Monitor for idle timeout to auto-resume training.

        If inference is idle for 15 minutes, prompt user to confirm.
        If no confirmation in 5 minutes, auto-resume training.
        """
        idle_start = datetime.now()

        while self._state == TrainingState.PAUSED:
            await asyncio.sleep(30)  # Check every 30 seconds

            # Check if there are pending requests
            if self._request_queue:
                idle_start = datetime.now()
                continue

            idle_duration = (datetime.now() - idle_start).total_seconds()

            # After 15 minutes of idle, request confirmation
            if idle_duration >= self.config.idle_timeout_before_resume_seconds:
                if self._current_job and not self._current_job.waiting_for_confirmation:
                    logger.info(
                        "Idle timeout reached, requesting confirmation to resume training"
                    )
                    self._current_job.waiting_for_confirmation = True
                    self._current_job.confirmation_requested_at = datetime.now()

                    # Emit event for UI (AG-UI protocol)
                    if self._on_state_change:
                        await self._on_state_change(TrainingState.PAUSED)

            # After 5 more minutes without confirmation, auto-resume
            if self._current_job and self._current_job.waiting_for_confirmation:
                if self._current_job.confirmation_requested_at:
                    confirm_wait = (
                        datetime.now() - self._current_job.confirmation_requested_at
                    ).total_seconds()
                    if confirm_wait >= self.config.user_confirmation_timeout_seconds:
                        logger.info("No confirmation received, auto-resuming training")
                        await self.resume_training()
                        return

    async def confirm_keep_paused(self):
        """User confirms to keep training paused (reset idle timer)."""
        if self._current_job:
            self._current_job.waiting_for_confirmation = False
            self._current_job.confirmation_requested_at = None
            logger.info("User confirmed to keep training paused")

    async def resume_training(self) -> bool:
        """
        Resume training after serving primary requests.

        This will:
        1. Signal inference to yield
        2. Stop MPS daemon
        3. Allocate GPU to training
        4. Resume from checkpoint
        5. Update router for fallback-only

        Returns:
            True if resumed successfully
        """
        async with self._lock:
            if self._state != TrainingState.PAUSED:
                logger.error(f"Cannot resume training in state: {self._state}")
                return False

            job = self._current_job
            if not job:
                return False

            self._state = TrainingState.RESUMING
            logger.info(f"Resuming training job: {job.job_id}")

            try:
                # Step 1: Signal inference to yield
                await self._signal_inference_yield()

                # Step 2: Wait for GPU release
                await self._wait_for_gpu_release()

                # Step 3: Stop MPS
                if await self._mps_controller.is_running():
                    if not await self._mps_controller.stop():
                        logger.warning("Failed to stop MPS, continuing anyway")

                # Step 4: Allocate GPU to training
                await self._gpu_allocator.allocate_to_training(
                    gpu_id=self.config.training_gpu, job_id=job.job_id
                )

                # Step 5: Resume training
                if self._on_training_resume:
                    await self._on_training_resume(job)

                # Step 6: Update router
                self._router.set_training_active(True)

                # Update pause duration
                if job.paused_at:
                    pause_duration = datetime.now() - job.paused_at
                    job.total_pause_duration += pause_duration
                    job.paused_at = None

                self._state = TrainingState.TRAINING

                if self._on_state_change:
                    await self._on_state_change(self._state)

                logger.info(
                    f"Training resumed: {job.job_id} from step {job.last_checkpoint_step}"
                )
                return True

            except Exception as e:
                logger.error(f"Failed to resume training: {e}")
                return False

    async def stop_training(self, save_checkpoint: bool = True) -> Optional[str]:
        """
        Stop training completely.

        Args:
            save_checkpoint: Whether to save a final checkpoint

        Returns:
            Path to final checkpoint if saved
        """
        async with self._lock:
            if self._state not in (TrainingState.TRAINING, TrainingState.PAUSED):
                logger.error(f"Cannot stop training in state: {self._state}")
                return None

            job = self._current_job
            if not job:
                return None

            prev_state = self._state
            self._state = TrainingState.STOPPING
            logger.info(f"Stopping training job: {job.job_id}")

            checkpoint_path = None

            try:
                # Save checkpoint if requested and was training
                if save_checkpoint and prev_state == TrainingState.TRAINING:
                    if self._on_checkpoint_needed:
                        checkpoint_path = await self._on_checkpoint_needed(job)
                        job.last_checkpoint_path = checkpoint_path

                # Release GPU if still allocated
                if prev_state == TrainingState.TRAINING:
                    await self._gpu_allocator.release_from_training(
                        self.config.training_gpu
                    )

                # Start MPS if not running
                if not await self._mps_controller.is_running():
                    await self._mps_controller.start()

                # Signal inference to reclaim
                await self._signal_inference_reclaim()

                # Update router
                self._router.set_training_active(False)

                self._state = TrainingState.IDLE
                self._current_job = None

                # Clear queue
                self._request_queue.clear()

                if self._on_state_change:
                    await self._on_state_change(self._state)

                logger.info(f"Training stopped: {job.job_id}")
                return checkpoint_path

            except Exception as e:
                logger.error(f"Failed to stop training: {e}")
                self._state = TrainingState.IDLE
                return None

    async def enqueue_request(
        self,
        request_id: str,
        priority: int = 5,
        complexity_score: float = 0.5,
        user_role: str = "developer",
        requires_confirmation: bool = False,
        callback: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> Optional[int]:
        """
        Add a request to the queue for primary model.

        Args:
            request_id: Unique request ID
            priority: Request priority (1-10)
            complexity_score: Complexity score (0-1)
            user_role: User's role
            requires_confirmation: Whether request needs confirmation (admin force)
            callback: Optional callback when request is dequeued

        Returns:
            Queue position, or None if queue is full
        """
        if len(self._request_queue) >= self.config.queue_max_size:
            logger.warning(f"Queue full, rejecting request {request_id}")
            return None

        queued_request = QueuedRequest(
            request_id=request_id,
            queued_at=datetime.now(),
            timeout_at=datetime.now()
            + timedelta(seconds=self.config.queue_timeout_seconds),
            priority=priority,
            complexity_score=complexity_score,
            user_role=user_role,
            requires_confirmation=requires_confirmation,
            callback=callback,
        )

        # Insert in priority order
        inserted = False
        for i, req in enumerate(self._request_queue):
            if priority > req.priority:
                self._request_queue.insert(i, queued_request)
                inserted = True
                break
        if not inserted:
            self._request_queue.append(queued_request)

        position = self._request_queue.index(queued_request) + 1
        self._router.set_queue_length(len(self._request_queue))

        logger.info(f"Enqueued request {request_id} at position {position}")

        # Check if should trigger checkpoint/pause
        should_trigger = len(
            self._request_queue
        ) >= self.config.checkpoint_trigger_threshold or any(
            r.wait_time_seconds() > self.config.queue_timeout_seconds
            for r in self._request_queue
        )

        if should_trigger and self._state == TrainingState.TRAINING:
            asyncio.create_task(self._handle_queue_threshold())

        return position

    async def dequeue_request(self) -> Optional[QueuedRequest]:
        """
        Remove and return the next request from queue.

        Returns:
            Next queued request, or None if queue is empty
        """
        if not self._request_queue:
            return None

        # Remove expired requests
        now = datetime.now()
        self._request_queue = [r for r in self._request_queue if r.timeout_at > now]

        if not self._request_queue:
            return None

        request = self._request_queue.pop(0)
        self._router.set_queue_length(len(self._request_queue))

        logger.info(f"Dequeued request {request.request_id}")
        return request

    async def _handle_queue_threshold(self):
        """
        Handle queue reaching threshold - trigger pause with checkpoint validation.

        Triggers when:
        - Queue size >= checkpoint_trigger_threshold (default 3)
        - OR any request has been waiting > 30 seconds

        Before interrupting:
        - Validate checkpoint exists within last 100 steps
        - Force save checkpoint if needed
        """
        job = self._current_job
        if not job:
            return

        # Check if any request has been waiting too long
        long_wait_request = any(
            r.wait_time_seconds() > self.config.queue_timeout_seconds
            for r in self._request_queue
        )

        trigger_reason = (
            "queue_size"
            if len(self._request_queue) >= self.config.checkpoint_trigger_threshold
            else "long_wait"
        )
        logger.info(
            f"Queue threshold reached (reason: {trigger_reason}), preparing to pause training"
        )

        # Validate checkpoint before interrupting
        if job.needs_checkpoint_before_interrupt(
            self.config.force_checkpoint_threshold
        ):
            logger.info(
                f"Must checkpoint before interrupt: {job.steps_since_checkpoint()} steps since last"
            )

        await self.pause_training(reason=f"queue_{trigger_reason}")

        # Process queue
        while self._request_queue:
            request = await self.dequeue_request()
            if request and request.callback:
                try:
                    await request.callback()
                except Exception as e:
                    logger.error(f"Request callback failed: {e}")

        # Wait a bit for any more incoming requests
        await asyncio.sleep(5.0)

        # If queue still empty and max pause not exceeded, resume
        if not self._request_queue:
            if self._current_job and self._current_job.paused_at:
                pause_duration = (
                    datetime.now() - self._current_job.paused_at
                ).total_seconds()
                if pause_duration < self.config.max_pause_duration_seconds:
                    await self.resume_training()

    async def _signal_inference_yield(self):
        """Signal inference model to yield GPU."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.config.primary_inference_url}/training/start",
                    json={
                        "job_id": (
                            self._current_job.job_id
                            if self._current_job
                            else "coordinator"
                        ),
                        "gpus": [self.config.training_gpu],
                        "priority": 10,
                    },
                )
                if response.status_code == 200:
                    logger.info("Inference yield signal sent")
                else:
                    logger.warning(
                        f"Inference yield signal failed: {response.status_code}"
                    )
        except Exception as e:
            logger.error(f"Failed to signal inference yield: {e}")

    async def _signal_inference_reclaim(self):
        """Signal inference model to reclaim GPU."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                job_id = (
                    self._current_job.job_id if self._current_job else "coordinator"
                )
                response = await client.post(
                    f"{self.config.primary_inference_url}/training/stop",
                    params={"job_id": job_id},
                )
                if response.status_code == 200:
                    logger.info("Inference reclaim signal sent")
                else:
                    logger.warning(
                        f"Inference reclaim signal failed: {response.status_code}"
                    )
        except Exception as e:
            logger.error(f"Failed to signal inference reclaim: {e}")

    async def _wait_for_gpu_release(self, timeout: float = 60.0):
        """Wait for GPU to be released by inference."""
        start = datetime.now()
        while (datetime.now() - start).total_seconds() < timeout:
            await self._gpu_allocator.refresh_memory_usage()
            alloc = self._gpu_allocator.get_allocation(self.config.training_gpu)

            if alloc and alloc.memory_used_mb < 1000:  # Less than 1GB = released
                logger.info(f"GPU {self.config.training_gpu} released")
                return

            await asyncio.sleep(1.0)

        logger.warning("Timeout waiting for GPU release")

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive coordinator status."""
        job_info = None
        if self._current_job:
            job = self._current_job
            job_info = {
                "job_id": job.job_id,
                "script_path": job.script_path,
                "gpu_ids": job.gpu_ids,
                "current_step": job.current_step,
                "last_checkpoint_step": job.last_checkpoint_step,
                "steps_since_checkpoint": job.steps_since_checkpoint(),
                "needs_checkpoint": job.needs_checkpoint_before_interrupt(
                    self.config.force_checkpoint_threshold
                ),
                "checkpoint_count": len(job.checkpoint_paths),
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "paused_at": job.paused_at.isoformat() if job.paused_at else None,
                "total_pause_seconds": job.total_pause_duration.total_seconds(),
                "waiting_for_confirmation": job.waiting_for_confirmation,
                "confirmation_requested_at": (
                    job.confirmation_requested_at.isoformat()
                    if job.confirmation_requested_at
                    else None
                ),
            }

        # Calculate queue stats
        queue_stats = {
            "length": len(self._request_queue),
            "max_size": self.config.queue_max_size,
            "checkpoint_trigger": self.config.checkpoint_trigger_threshold,
            "timeout_seconds": self.config.queue_timeout_seconds,
            "oldest_wait_seconds": max(
                (r.wait_time_seconds() for r in self._request_queue), default=0
            ),
            "requests": [
                {
                    "request_id": r.request_id,
                    "queued_at": r.queued_at.isoformat(),
                    "timeout_at": r.timeout_at.isoformat(),
                    "wait_seconds": r.wait_time_seconds(),
                    "priority": r.priority,
                    "user_role": r.user_role,
                    "requires_confirmation": r.requires_confirmation,
                    "is_expired": r.is_expired(),
                }
                for r in self._request_queue
            ],
        }

        return {
            "state": self._state.value,
            "training_active": self.is_training_active,
            "current_job": job_info,
            "queue": queue_stats,
            "config": {
                "checkpoint_interval": self.config.checkpoint_interval,
                "max_checkpoints_to_keep": self.config.max_checkpoints_to_keep,
                "force_checkpoint_threshold": self.config.force_checkpoint_threshold,
                "max_pause_seconds": self.config.max_pause_duration_seconds,
                "idle_timeout_seconds": self.config.idle_timeout_before_resume_seconds,
                "confirmation_timeout_seconds": self.config.user_confirmation_timeout_seconds,
                "training_gpu": self.config.training_gpu,
                "fallback_gpu": self.config.fallback_gpu,
                "allow_concurrent": self.config.allow_concurrent_training_inference,
            },
            "routing": self._router.get_config(),
            "available_models": self._router.get_available_models(),
        }

    def register_callbacks(
        self,
        on_state_change: Optional[Callable[[TrainingState], Awaitable[None]]] = None,
        on_checkpoint_needed: Optional[Callable[[TrainingJob], Awaitable[str]]] = None,
        on_training_pause: Optional[Callable[[TrainingJob], Awaitable[None]]] = None,
        on_training_resume: Optional[Callable[[TrainingJob], Awaitable[None]]] = None,
    ):
        """Register callbacks for training events."""
        self._on_state_change = on_state_change
        self._on_checkpoint_needed = on_checkpoint_needed
        self._on_training_pause = on_training_pause
        self._on_training_resume = on_training_resume
