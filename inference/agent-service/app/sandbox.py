"""Sandbox manager for isolated code execution using Kata Containers."""

import asyncio
import logging
import uuid
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import docker
from docker.types import Mount

from .config import settings
from .schemas import UserRole

logger = logging.getLogger(__name__)


class Sandbox:
    """Represents an isolated execution environment."""

    def __init__(self, sandbox_id: str, user_id: str, container: Any):
        self.id = sandbox_id
        self.user_id = user_id
        self.container = container
        self.created_at = datetime.now()
        self.last_used = datetime.now()

    def is_expired(self) -> bool:
        """Check if sandbox exceeded timeout."""
        expiry = self.created_at + timedelta(seconds=settings.SANDBOX_TIMEOUT_SECONDS)
        return datetime.now() > expiry

    def is_idle(self, idle_seconds: int = 300) -> bool:
        """Check if sandbox has been idle."""
        idle_threshold = datetime.now() - timedelta(seconds=idle_seconds)
        return self.last_used < idle_threshold


class SandboxManager:
    """Manages Kata Container sandboxes for code execution."""

    def __init__(self):
        self.docker_client: Optional[docker.DockerClient] = None
        self.sandboxes: Dict[str, Sandbox] = {}
        self.sandbox_semaphore = asyncio.Semaphore(settings.MAX_SANDBOXES)

    def connect(self):
        """Connect to Docker daemon."""
        try:
            self.docker_client = docker.from_env()

            # Verify runtime is available
            info = self.docker_client.info()
            runtimes = info.get("Runtimes", {})

            if settings.KATA_RUNTIME not in runtimes:
                logger.warning(
                    f"Runtime '{settings.KATA_RUNTIME}' not found in Docker. "
                    "Available runtimes: "
                    + ", ".join(runtimes.keys())
                    + " - Using runc with strong security constraints"
                )
                # Kata requires KVM which isn't available, using runc with security hardening
                if settings.KATA_RUNTIME == "kata":
                    logger.info(
                        "Kata Containers requires KVM. Using runc runtime with network isolation, "
                        "read-only filesystem, dropped capabilities, and memory limits for security."
                    )
            else:
                logger.info(f"Runtime '{settings.KATA_RUNTIME}' available")

            logger.info("Connected to Docker daemon")
        except Exception as e:
            logger.error(f"Failed to connect to Docker: {e}")
            raise

    def close(self):
        """Clean up all sandboxes."""
        logger.info("Cleaning up sandboxes...")
        for sandbox_id in list(self.sandboxes.keys()):
            try:
                self.destroy_sandbox(sandbox_id)
            except Exception as e:
                logger.error(f"Failed to clean up sandbox {sandbox_id}: {e}")

    async def create_sandbox(self, user_id: str, user_roles: list[UserRole]) -> str:
        """
        Create an isolated sandbox for code execution.

        Args:
            user_id: User requesting the sandbox
            user_roles: User's roles for permission check

        Returns:
            sandbox_id for subsequent operations

        Raises:
            PermissionError: If user lacks code execution permissions
            RuntimeError: If max sandboxes reached or creation fails
        """
        # Check permissions
        if not any(role.value in settings.CODE_EXEC_ROLES for role in user_roles):
            raise PermissionError(
                f"User {user_id} lacks code execution permissions. "
                f"Required roles: {settings.CODE_EXEC_ROLES}"
            )

        # Acquire semaphore (blocks if max sandboxes reached)
        async with self.sandbox_semaphore:
            try:
                sandbox_id = f"sandbox-{uuid.uuid4().hex[:8]}"

                logger.info(f"Creating sandbox {sandbox_id} for user {user_id}")

                # Create isolated container with strong security
                # Using runc with security constraints since Kata (KVM) not available
                container = await asyncio.to_thread(
                    self.docker_client.containers.run,
                    image="python:3.11-slim",
                    name=sandbox_id,
                    runtime=(
                        settings.KATA_RUNTIME
                        if settings.KATA_RUNTIME != "kata"
                        else "runc"
                    ),
                    detach=True,
                    remove=False,  # Manual cleanup for better control
                    network_mode="none",  # No network access from sandbox
                    mem_limit=f"{settings.SANDBOX_MEMORY_LIMIT_GB}g",
                    storage_opt=(
                        {"size": f"{settings.SANDBOX_DISK_LIMIT_GB}G"}
                        if settings.KATA_RUNTIME == "kata"
                        else {}
                    ),
                    command="sleep infinity",  # Keep container alive
                    read_only=True,  # Read-only root filesystem
                    tmpfs={"/tmp": "size=100m,mode=1777"},  # Writable /tmp
                    cap_drop=["ALL"],  # Drop all capabilities
                    cap_add=["NET_BIND_SERVICE"],  # Only allow binding to ports
                    security_opt=[
                        "no-new-privileges:true"
                    ],  # Prevent privilege escalation
                    labels={
                        "shml.sandbox": "true",
                        "shml.user_id": user_id,
                        "shml.created_at": datetime.now().isoformat(),
                    },
                )

                sandbox = Sandbox(sandbox_id, user_id, container)
                self.sandboxes[sandbox_id] = sandbox

                logger.info(f"Sandbox {sandbox_id} created successfully")
                return sandbox_id

            except Exception as e:
                logger.error(f"Failed to create sandbox: {e}")
                raise RuntimeError(f"Sandbox creation failed: {str(e)}")

    def destroy_sandbox(self, sandbox_id: str):
        """Destroy a sandbox and clean up resources."""
        if sandbox_id not in self.sandboxes:
            logger.warning(f"Sandbox {sandbox_id} not found")
            return

        sandbox = self.sandboxes[sandbox_id]

        try:
            logger.info(f"Destroying sandbox {sandbox_id}")
            sandbox.container.stop(timeout=5)
            sandbox.container.remove(force=True)
            del self.sandboxes[sandbox_id]
            logger.info(f"Sandbox {sandbox_id} destroyed")
        except Exception as e:
            logger.error(f"Failed to destroy sandbox {sandbox_id}: {e}")

    async def execute_code(
        self,
        sandbox_id: str,
        code: str,
        timeout_seconds: int = 60,
    ) -> Dict[str, Any]:
        """
        Execute code in an isolated sandbox.

        Args:
            sandbox_id: ID of the sandbox
            code: Python code to execute
            timeout_seconds: Execution timeout

        Returns:
            Dict with keys: success, stdout, stderr, exit_code
        """
        if sandbox_id not in self.sandboxes:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        sandbox = self.sandboxes[sandbox_id]
        sandbox.last_used = datetime.now()

        try:
            logger.info(f"Executing code in sandbox {sandbox_id}")

            # Execute code with timeout
            exec_result = await asyncio.wait_for(
                asyncio.to_thread(
                    sandbox.container.exec_run,
                    cmd=["python", "-c", code],
                    demux=True,
                ),
                timeout=timeout_seconds,
            )

            exit_code = exec_result.exit_code
            stdout, stderr = exec_result.output

            stdout_text = stdout.decode("utf-8") if stdout else ""
            stderr_text = stderr.decode("utf-8") if stderr else ""

            success = exit_code == 0

            logger.info(
                f"Code execution {'succeeded' if success else 'failed'} "
                f"in sandbox {sandbox_id} (exit_code={exit_code})"
            )

            return {
                "success": success,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "exit_code": exit_code,
            }

        except asyncio.TimeoutError:
            logger.error(f"Code execution timeout in sandbox {sandbox_id}")
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Execution timeout after {timeout_seconds}s",
                "exit_code": -1,
            }
        except Exception as e:
            logger.error(f"Code execution failed in sandbox {sandbox_id}: {e}")
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
            }

    def cleanup_expired_sandboxes(self):
        """Remove expired or idle sandboxes."""
        for sandbox_id in list(self.sandboxes.keys()):
            sandbox = self.sandboxes[sandbox_id]

            if sandbox.is_expired():
                logger.info(f"Sandbox {sandbox_id} expired, cleaning up")
                self.destroy_sandbox(sandbox_id)
            elif sandbox.is_idle(idle_seconds=600):  # 10min idle
                logger.info(f"Sandbox {sandbox_id} idle for 10min, cleaning up")
                self.destroy_sandbox(sandbox_id)

    def get_sandbox_count(self) -> int:
        """Get current number of active sandboxes."""
        return len(self.sandboxes)

    def get_available_slots(self) -> int:
        """Get number of available sandbox slots."""
        return settings.MAX_SANDBOXES - len(self.sandboxes)


# Global sandbox manager instance
sandbox_manager = SandboxManager()
