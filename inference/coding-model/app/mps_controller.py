"""
MPS Controller - Controls NVIDIA Multi-Process Service daemon.

This module provides low-level control over the MPS daemon, allowing
dynamic start/stop for GPU resource allocation between training and inference.
"""

import os
import asyncio
import subprocess
import logging
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class MPSState(Enum):
    """MPS daemon states."""

    RUNNING = "running"
    STOPPED = "stopped"
    STARTING = "starting"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class MPSStatus:
    """Current MPS status information."""

    state: MPSState
    gpu_id: int
    pid: Optional[int] = None
    uptime_seconds: Optional[float] = None
    active_clients: int = 0
    default_thread_percentage: int = 100
    last_error: Optional[str] = None
    last_state_change: datetime = field(default_factory=datetime.now)


class MPSController:
    """
    Controls NVIDIA Multi-Process Service daemon for a specific GPU.

    MPS allows multiple CUDA processes to share a GPU with time-slicing.
    When MPS is stopped, a single process gets exclusive GPU access.

    Note on pipe directories:
    - System-wide MPS typically uses /tmp/nvidia-mps (no GPU suffix)
    - Per-GPU MPS uses /tmp/nvidia-mps-{gpu_id}
    - This controller supports both patterns

    Usage:
        controller = MPSController(gpu_id=0)
        await controller.start()   # Enable shared GPU access
        await controller.stop()    # Disable for exclusive access (training)
    """

    # Common MPS pipe directory locations
    SYSTEM_PIPE_DIR = "/tmp/nvidia-mps"
    SYSTEM_LOG_DIR = "/tmp/nvidia-log"

    def __init__(
        self,
        gpu_id: int = 0,
        pipe_directory: Optional[str] = None,
        log_directory: Optional[str] = None,
        use_system_mps: bool = True,  # Try system-wide MPS first
    ):
        self.gpu_id = gpu_id
        self.use_system_mps = use_system_mps

        # Determine pipe directory
        if pipe_directory:
            self.pipe_directory = pipe_directory
        elif use_system_mps:
            self.pipe_directory = self.SYSTEM_PIPE_DIR
        else:
            self.pipe_directory = f"/tmp/nvidia-mps-{gpu_id}"

        # Determine log directory
        if log_directory:
            self.log_directory = log_directory
        elif use_system_mps:
            self.log_directory = self.SYSTEM_LOG_DIR
        else:
            self.log_directory = f"/var/log/nvidia-mps-{gpu_id}"

        self._state = MPSState.STOPPED
        self._pid: Optional[int] = None
        self._started_at: Optional[datetime] = None
        self._last_error: Optional[str] = None

    @property
    def env(self) -> dict:
        """Environment variables for MPS operations."""
        return {
            "CUDA_VISIBLE_DEVICES": str(self.gpu_id),
            "CUDA_MPS_PIPE_DIRECTORY": self.pipe_directory,
            "CUDA_MPS_LOG_DIRECTORY": self.log_directory,
        }

    async def start(self, default_thread_percentage: int = 100) -> bool:
        """
        Start the MPS daemon for this GPU.

        Args:
            default_thread_percentage: Default GPU thread % for new clients (1-100)

        Returns:
            True if started successfully, False otherwise
        """
        if self._state == MPSState.RUNNING:
            logger.info(f"MPS already running on GPU {self.gpu_id}")
            return True

        self._state = MPSState.STARTING
        logger.info(f"Starting MPS daemon on GPU {self.gpu_id}...")

        try:
            # Create directories
            os.makedirs(self.pipe_directory, exist_ok=True)
            os.makedirs(self.log_directory, exist_ok=True)

            # Start MPS daemon
            env = {**os.environ, **self.env}
            proc = await asyncio.create_subprocess_exec(
                "nvidia-cuda-mps-control",
                "-d",
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()

            if proc.returncode != 0:
                stderr = await proc.stderr.read()
                self._last_error = stderr.decode() if stderr else "Unknown error"
                self._state = MPSState.ERROR
                logger.error(f"Failed to start MPS: {self._last_error}")
                return False

            # Set default thread percentage if not 100
            if default_thread_percentage != 100:
                await self.set_default_thread_percentage(default_thread_percentage)

            # Verify it's running
            await asyncio.sleep(0.5)
            if await self.is_running():
                self._state = MPSState.RUNNING
                self._started_at = datetime.now()
                self._pid = await self._get_pid()
                logger.info(
                    f"MPS daemon started on GPU {self.gpu_id} (PID: {self._pid})"
                )
                return True
            else:
                self._state = MPSState.ERROR
                self._last_error = "Daemon started but not responding"
                return False

        except Exception as e:
            self._last_error = str(e)
            self._state = MPSState.ERROR
            logger.error(f"Exception starting MPS: {e}")
            return False

    async def stop(self, timeout: float = 10.0) -> bool:
        """
        Stop the MPS daemon, releasing GPU for exclusive access.

        Args:
            timeout: Max seconds to wait for clean shutdown

        Returns:
            True if stopped successfully, False otherwise
        """
        if self._state == MPSState.STOPPED:
            logger.info(f"MPS already stopped on GPU {self.gpu_id}")
            return True

        self._state = MPSState.STOPPING
        logger.info(f"Stopping MPS daemon on GPU {self.gpu_id}...")

        try:
            # Send quit command
            env = {**os.environ, **self.env}
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                "echo quit | nvidia-cuda-mps-control",
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("MPS quit command timed out, force killing...")
                if self._pid:
                    await self._force_kill()

            # Verify it's stopped
            await asyncio.sleep(0.5)
            if not await self.is_running():
                self._state = MPSState.STOPPED
                self._pid = None
                self._started_at = None
                logger.info(f"MPS daemon stopped on GPU {self.gpu_id}")
                return True
            else:
                # Force kill as last resort
                await self._force_kill()
                if not await self.is_running():
                    self._state = MPSState.STOPPED
                    return True

                self._state = MPSState.ERROR
                self._last_error = "Failed to stop daemon"
                return False

        except Exception as e:
            self._last_error = str(e)
            self._state = MPSState.ERROR
            logger.error(f"Exception stopping MPS: {e}")
            return False

    async def is_running(self) -> bool:
        """Check if MPS daemon is active and responding."""
        try:
            # First check if MPS control file exists
            control_path = os.path.join(self.pipe_directory, "control")
            if not os.path.exists(control_path):
                return False

            # Try to communicate with MPS daemon
            env = {**os.environ, **self.env}
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                f"timeout 2 bash -c 'echo get_default_active_thread_percentage | nvidia-cuda-mps-control'",
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            # If we get a number back, MPS is running
            if proc.returncode == 0 and stdout:
                try:
                    float(stdout.decode().strip())
                    return True
                except ValueError:
                    pass
            return False

        except Exception as e:
            logger.debug(f"MPS check failed: {e}")
            return False

    async def is_system_mps_running(self) -> bool:
        """Check if system-wide MPS is running (at /tmp/nvidia-mps)."""
        try:
            control_path = os.path.join(self.SYSTEM_PIPE_DIR, "control")
            if not os.path.exists(control_path):
                return False

            # Check for MPS processes
            proc = await asyncio.create_subprocess_exec(
                "pgrep",
                "-f",
                "nvidia-cuda-mps-control",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            return proc.returncode == 0 and stdout.strip() != b""

        except Exception:
            return False

    async def set_default_thread_percentage(self, percentage: int) -> bool:
        """
        Set default active thread percentage for new MPS clients.

        Args:
            percentage: Thread percentage (1-100)

        Returns:
            True if set successfully
        """
        if not 1 <= percentage <= 100:
            raise ValueError("Thread percentage must be 1-100")

        try:
            env = {**os.environ, **self.env}
            cmd = f"echo set_default_active_thread_percentage {percentage} | nvidia-cuda-mps-control"
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()

            if proc.returncode == 0:
                logger.info(
                    f"Set MPS default thread % to {percentage} on GPU {self.gpu_id}"
                )
                return True
            return False

        except Exception as e:
            logger.error(f"Failed to set thread percentage: {e}")
            return False

    async def get_default_thread_percentage(self) -> Optional[int]:
        """Get current default thread percentage."""
        try:
            env = {**os.environ, **self.env}
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                "echo get_default_active_thread_percentage | nvidia-cuda-mps-control",
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if proc.returncode == 0 and stdout:
                return int(stdout.decode().strip())
            return None

        except Exception:
            return None

    async def get_status(self) -> MPSStatus:
        """Get comprehensive MPS status."""
        is_running = await self.is_running()

        if is_running and self._state != MPSState.RUNNING:
            self._state = MPSState.RUNNING
            if not self._started_at:
                self._started_at = datetime.now()
        elif not is_running and self._state == MPSState.RUNNING:
            self._state = MPSState.STOPPED

        uptime = None
        if self._started_at and self._state == MPSState.RUNNING:
            uptime = (datetime.now() - self._started_at).total_seconds()

        thread_pct = await self.get_default_thread_percentage() if is_running else 100

        return MPSStatus(
            state=self._state,
            gpu_id=self.gpu_id,
            pid=self._pid,
            uptime_seconds=uptime,
            active_clients=0,  # Would need to parse MPS logs for this
            default_thread_percentage=thread_pct or 100,
            last_error=self._last_error,
            last_state_change=self._started_at or datetime.now(),
        )

    async def _get_pid(self) -> Optional[int]:
        """Get PID of MPS control daemon."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "pgrep",
                "-f",
                f"nvidia-cuda-mps-control.*{self.pipe_directory}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if proc.returncode == 0 and stdout:
                return int(stdout.decode().strip().split()[0])
            return None

        except Exception:
            return None

    async def _force_kill(self) -> bool:
        """Force kill MPS daemon if graceful shutdown fails."""
        try:
            # Kill any nvidia-cuda-mps processes for this GPU
            proc = await asyncio.create_subprocess_exec(
                "pkill",
                "-9",
                "-f",
                f"nvidia-cuda-mps.*{self.pipe_directory}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()

            # Also try killing by pipe directory
            env = {**os.environ, **self.env}
            proc = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                "echo quit | nvidia-cuda-mps-control 2>/dev/null || true",
                env=env,
            )
            await proc.wait()

            return True

        except Exception as e:
            logger.error(f"Failed to force kill MPS: {e}")
            return False


class MPSManager:
    """
    Manages MPS controllers for multiple GPUs.

    Usage:
        manager = MPSManager()
        await manager.start_all()
        await manager.stop_gpu(0)  # Stop MPS on GPU 0 for training
        await manager.start_gpu(0)  # Re-enable MPS after training
    """

    def __init__(self, gpu_ids: Optional[list] = None):
        """
        Initialize MPS manager.

        Args:
            gpu_ids: List of GPU IDs to manage. If None, auto-detect.
        """
        self.gpu_ids = gpu_ids or self._detect_gpus()
        self.controllers: dict[int, MPSController] = {
            gpu_id: MPSController(gpu_id) for gpu_id in self.gpu_ids
        }

    def _detect_gpus(self) -> list:
        """Detect available NVIDIA GPUs."""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return [int(idx.strip()) for idx in result.stdout.strip().split("\n")]
        except Exception:
            pass
        return [0]  # Default to GPU 0

    async def start_all(self) -> dict[int, bool]:
        """Start MPS on all managed GPUs."""
        results = {}
        for gpu_id, controller in self.controllers.items():
            results[gpu_id] = await controller.start()
        return results

    async def stop_all(self) -> dict[int, bool]:
        """Stop MPS on all managed GPUs."""
        results = {}
        for gpu_id, controller in self.controllers.items():
            results[gpu_id] = await controller.stop()
        return results

    async def start_gpu(self, gpu_id: int) -> bool:
        """Start MPS on specific GPU."""
        if gpu_id not in self.controllers:
            logger.error(f"GPU {gpu_id} not managed by MPSManager")
            return False
        return await self.controllers[gpu_id].start()

    async def stop_gpu(self, gpu_id: int) -> bool:
        """Stop MPS on specific GPU for exclusive access."""
        if gpu_id not in self.controllers:
            logger.error(f"GPU {gpu_id} not managed by MPSManager")
            return False
        return await self.controllers[gpu_id].stop()

    async def get_status(self) -> dict[int, MPSStatus]:
        """Get status of all managed GPUs."""
        return {
            gpu_id: await controller.get_status()
            for gpu_id, controller in self.controllers.items()
        }
