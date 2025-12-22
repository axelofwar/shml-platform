"""
Ray Compute Integration for SHML Training Library.

This module provides Ray-specific wrappers for distributed training
on the SHML platform's Ray cluster.

Usage:
    from shml_training.ray_wrapper import RayTrainer, submit_ray_job

    # Submit a training job to Ray cluster
    result = submit_ray_job(
        train_fn=my_train_function,
        config=training_config,
        num_gpus=1,
        ray_address="auto",
    )

    # Or use the trainer wrapper
    trainer = RayTrainer(config, ray_address="auto")
    result = trainer.train(train_fn, callbacks=[...])
"""

import os
import time
from typing import Optional, Dict, Any, List, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime

from ..core.config import TrainingConfig
from ..core.hardware import HardwareDetector, HardwareProfile
from ..core.memory import MemoryOptimizer
from ..core.checkpointing import CheckpointManager
from .progress import ProgressReporter, AGUIEventEmitter
from .orchestrator import JobSpec, JobResult, JobStatus, JobPriority


@dataclass
class RayJobConfig:
    """Configuration for Ray job submission."""

    # Resource allocation
    num_gpus: float = 1.0
    num_cpus: int = 4
    memory_gb: float = 0  # 0 = auto

    # Ray settings
    ray_address: str = "auto"
    namespace: Optional[str] = None
    runtime_env: Optional[Dict[str, Any]] = None

    # Job settings
    max_retries: int = 3
    timeout_seconds: int = 0  # 0 = no timeout

    # Placement
    node_affinity: Optional[str] = None  # Node IP or hostname
    accelerator_type: Optional[str] = None  # "RTX-3090", "A100", etc.

    # MLflow integration
    mlflow_tracking_uri: Optional[str] = None
    mlflow_experiment: Optional[str] = None


def submit_ray_job(
    train_fn: Callable[[TrainingConfig], Dict[str, float]],
    config: TrainingConfig,
    ray_config: Optional[RayJobConfig] = None,
    job_name: str = "shml-training",
    user_id: str = "anonymous",
    user_role: str = "developer",
    **train_kwargs,
) -> JobResult:
    """
    Submit a training job to Ray cluster.

    Args:
        train_fn: Training function taking config, returning metrics dict
        config: Training configuration
        ray_config: Ray job configuration
        job_name: Name for the job
        user_id: User ID for tracking
        user_role: User role (affects resource limits)
        **train_kwargs: Additional kwargs passed to train_fn

    Returns:
        JobResult with metrics and status
    """
    try:
        import ray
    except ImportError:
        raise ImportError("Ray not installed. Run: pip install 'ray[default]'")

    ray_config = ray_config or RayJobConfig()

    # Initialize Ray
    if not ray.is_initialized():
        ray.init(address=ray_config.ray_address)

    # Create remote function with resource requirements
    @ray.remote(
        num_gpus=ray_config.num_gpus,
        num_cpus=ray_config.num_cpus,
        max_retries=ray_config.max_retries,
    )
    def ray_train_wrapper(cfg: TrainingConfig, kwargs: Dict) -> Dict[str, Any]:
        """Ray remote training wrapper."""
        import os

        # Setup environment
        if ray_config.mlflow_tracking_uri:
            os.environ["MLFLOW_TRACKING_URI"] = ray_config.mlflow_tracking_uri

        # Initialize memory optimizer
        optimizer = MemoryOptimizer(cfg)
        optimizer.optimize_for_hardware()

        # Initialize progress reporter
        reporter = ProgressReporter(
            run_id=job_name,
            total_epochs=cfg.epochs,
            log_to_console=True,
        )

        # Add reporter to kwargs for train_fn to use
        kwargs["progress_reporter"] = reporter
        kwargs["memory_optimizer"] = optimizer

        try:
            reporter.start_run(config=cfg.to_dict() if hasattr(cfg, "to_dict") else {})

            result = train_fn(cfg, **kwargs)

            reporter.end_run(metrics=result, status="completed")
            return {"status": "completed", "metrics": result}

        except Exception as e:
            import traceback

            tb = traceback.format_exc()
            reporter.log_error(str(e), tb)
            return {"status": "failed", "error": str(e), "traceback": tb}

    # Submit job
    start_time = datetime.now()

    try:
        ref = ray_train_wrapper.remote(config, train_kwargs)

        # Wait for result
        if ray_config.timeout_seconds > 0:
            ready, _ = ray.wait([ref], timeout=ray_config.timeout_seconds)
            if not ready:
                ray.cancel(ref)
                return JobResult(
                    job_id=job_name,
                    status=JobStatus.FAILED,
                    start_time=start_time,
                    end_time=datetime.now(),
                    error_message="Job timed out",
                )

        result = ray.get(ref)
        end_time = datetime.now()

        if result.get("status") == "completed":
            return JobResult(
                job_id=job_name,
                status=JobStatus.COMPLETED,
                start_time=start_time,
                end_time=end_time,
                metrics=result.get("metrics", {}),
            )
        else:
            return JobResult(
                job_id=job_name,
                status=JobStatus.FAILED,
                start_time=start_time,
                end_time=end_time,
                error_message=result.get("error"),
                error_traceback=result.get("traceback"),
            )

    except Exception as e:
        return JobResult(
            job_id=job_name,
            status=JobStatus.FAILED,
            start_time=start_time,
            end_time=datetime.now(),
            error_message=str(e),
        )


class RayTrainer:
    """
    Ray-integrated trainer for SHML platform.

    Provides:
    - Automatic resource allocation based on user role
    - MLflow experiment tracking integration
    - Distributed training coordination
    - Preemption handling

    Usage:
        trainer = RayTrainer(
            config=training_config,
            ray_address="auto",
            user_role="admin",  # Full GPU access
        )

        result = trainer.train(
            train_fn=my_training_function,
            checkpoint_dir="./checkpoints",
        )
    """

    def __init__(
        self,
        config: TrainingConfig,
        ray_address: str = "auto",
        user_id: str = "anonymous",
        user_role: str = "developer",
        mlflow_tracking_uri: Optional[str] = None,
        mlflow_experiment: Optional[str] = None,
    ):
        """
        Args:
            config: Training configuration
            ray_address: Ray cluster address
            user_id: User identifier
            user_role: User role (developer, elevated, admin, super_admin)
            mlflow_tracking_uri: MLflow tracking URI
            mlflow_experiment: MLflow experiment name
        """
        self.config = config
        self.ray_address = ray_address
        self.user_id = user_id
        self.user_role = user_role
        self.mlflow_tracking_uri = mlflow_tracking_uri
        self.mlflow_experiment = mlflow_experiment

        # Determine resource allocation based on role
        self.ray_config = self._configure_resources()

    def _configure_resources(self) -> RayJobConfig:
        """Configure resources based on user role."""
        hardware = HardwareDetector.detect()

        # Role-based resource allocation
        if self.user_role in ("admin", "super_admin"):
            # Full access - no restrictions
            return RayJobConfig(
                num_gpus=len(hardware.gpu_info) if hardware.gpu_info else 0,
                num_cpus=hardware.cpu_count or 4,
                ray_address=self.ray_address,
                mlflow_tracking_uri=self.mlflow_tracking_uri,
            )

        elif self.user_role == "elevated":
            # Elevated access - up to 16GB GPU
            return RayJobConfig(
                num_gpus=(
                    min(1.0, 16.0 / hardware.total_vram_gb)
                    if hardware.total_vram_gb > 0
                    else 0
                ),
                num_cpus=min(8, hardware.cpu_count or 4),
                ray_address=self.ray_address,
                mlflow_tracking_uri=self.mlflow_tracking_uri,
            )

        else:
            # Developer - limited access (2GB 3090, 0.5GB 2070 via MPS)
            return RayJobConfig(
                num_gpus=0.1,  # Small GPU fraction
                num_cpus=min(4, hardware.cpu_count or 2),
                ray_address=self.ray_address,
                mlflow_tracking_uri=self.mlflow_tracking_uri,
            )

    def train(
        self,
        train_fn: Callable[[TrainingConfig], Dict[str, float]],
        checkpoint_dir: Optional[str] = None,
        callbacks: Optional[List[Callable]] = None,
        **kwargs,
    ) -> JobResult:
        """
        Execute training on Ray cluster.

        Args:
            train_fn: Training function
            checkpoint_dir: Directory for checkpoints
            callbacks: Optional callbacks for training events
            **kwargs: Additional args for train_fn

        Returns:
            JobResult with metrics and status
        """
        # Generate job name
        import uuid

        job_name = f"shml-{self.user_id}-{uuid.uuid4().hex[:8]}"

        # Add checkpoint dir to kwargs
        if checkpoint_dir:
            kwargs["checkpoint_dir"] = checkpoint_dir

        # Submit job
        result = submit_ray_job(
            train_fn=train_fn,
            config=self.config,
            ray_config=self.ray_config,
            job_name=job_name,
            user_id=self.user_id,
            user_role=self.user_role,
            **kwargs,
        )

        return result

    def train_distributed(
        self,
        train_fn: Callable[[TrainingConfig], Dict[str, float]],
        num_workers: int = 2,
        use_gpu: bool = True,
        **kwargs,
    ) -> JobResult:
        """
        Execute distributed training using Ray Train.

        Args:
            train_fn: Training function
            num_workers: Number of distributed workers
            use_gpu: Whether to use GPUs
            **kwargs: Additional args for train_fn

        Returns:
            JobResult with metrics and status
        """
        try:
            import ray
            from ray import train
            from ray.train.torch import TorchTrainer
            from ray.train import ScalingConfig, RunConfig, CheckpointConfig
        except ImportError:
            raise ImportError("Ray Train not installed. Run: pip install 'ray[train]'")

        # Initialize Ray
        if not ray.is_initialized():
            ray.init(address=self.ray_address)

        import uuid

        job_name = f"shml-distributed-{self.user_id}-{uuid.uuid4().hex[:8]}"

        # Create training function wrapper for Ray Train
        def ray_train_loop(ray_train_config: Dict[str, Any]):
            """Training loop for Ray Train."""
            config = ray_train_config["training_config"]

            # Initialize distributed training
            from ..core.distributed import (
                init_distributed,
                DistributedWrapper,
                DistributedConfig,
            )

            dist_info = init_distributed()

            # Run training
            result = train_fn(config, **kwargs)

            # Report metrics
            train.report(result)

            return result

        # Configure scaling
        scaling_config = ScalingConfig(
            num_workers=num_workers,
            use_gpu=use_gpu,
            resources_per_worker={
                "CPU": self.ray_config.num_cpus // num_workers,
                "GPU": self.ray_config.num_gpus / num_workers if use_gpu else 0,
            },
        )

        # Configure run
        run_config = RunConfig(
            name=job_name,
            storage_path=kwargs.get("checkpoint_dir", "./ray_results"),
        )

        # Create trainer
        trainer = TorchTrainer(
            train_loop_per_worker=ray_train_loop,
            train_loop_config={"training_config": self.config},
            scaling_config=scaling_config,
            run_config=run_config,
        )

        # Run training
        start_time = datetime.now()

        try:
            ray_result = trainer.fit()

            return JobResult(
                job_id=job_name,
                status=JobStatus.COMPLETED,
                start_time=start_time,
                end_time=datetime.now(),
                metrics=ray_result.metrics,
            )

        except Exception as e:
            import traceback

            return JobResult(
                job_id=job_name,
                status=JobStatus.FAILED,
                start_time=start_time,
                end_time=datetime.now(),
                error_message=str(e),
                error_traceback=traceback.format_exc(),
            )


def get_ray_cluster_info(ray_address: str = "auto") -> Dict[str, Any]:
    """
    Get information about the Ray cluster.

    Returns:
        Dict with cluster status, nodes, resources
    """
    try:
        import ray
    except ImportError:
        return {"error": "Ray not installed"}

    if not ray.is_initialized():
        try:
            ray.init(address=ray_address)
        except Exception as e:
            return {"error": f"Failed to connect to Ray: {e}"}

    try:
        nodes = ray.nodes()
        resources = ray.available_resources()

        return {
            "connected": True,
            "num_nodes": len(nodes),
            "nodes": [
                {
                    "node_id": n.get("NodeID", "")[:8],
                    "alive": n.get("Alive", False),
                    "resources": n.get("Resources", {}),
                }
                for n in nodes
            ],
            "available_resources": resources,
            "total_cpus": resources.get("CPU", 0),
            "total_gpus": resources.get("GPU", 0),
            "total_memory_gb": resources.get("memory", 0) / 1e9,
        }
    except Exception as e:
        return {"error": str(e)}


def list_ray_jobs(ray_address: str = "auto") -> List[Dict[str, Any]]:
    """
    List jobs running on Ray cluster.

    Returns:
        List of job information dicts
    """
    try:
        import ray
        from ray.job_submission import JobSubmissionClient
    except ImportError:
        return []

    try:
        client = JobSubmissionClient(
            ray_address if ray_address != "auto" else "http://127.0.0.1:8265"
        )
        jobs = client.list_jobs()

        return [
            {
                "job_id": job.job_id,
                "status": job.status.value,
                "start_time": job.start_time,
                "end_time": job.end_time,
                "runtime_env": job.runtime_env,
            }
            for job in jobs
        ]
    except Exception:
        return []
