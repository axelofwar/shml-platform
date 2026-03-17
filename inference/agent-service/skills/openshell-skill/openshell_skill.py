"""
OpenShell Skill — NemoClaw-backed hardened code execution.

Replaces SandboxSkill (Docker-based) with policy-governed OpenShell sandboxes:
  - Landlock filesystem isolation
  - seccomp syscall filtering
  - Network namespace egress control
  - Inference routing through OpenShell policy engine

Falls back to SandboxSkill if NemoClaw factory is unavailable (alpha software).

Role requirements: elevated-developer or admin
Factory endpoint:  http://nemoclaw-sandbox-factory:9095
"""

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# Factory sidecar endpoint (internal Docker network)
FACTORY_URL = os.getenv("NEMOCLAW_FACTORY_URL", "http://nemoclaw-sandbox-factory:9095")
FACTORY_TIMEOUT = int(os.getenv("NEMOCLAW_FACTORY_TIMEOUT", "60"))
# Execution timeout inside sandbox (seconds)
SANDBOX_EXEC_TIMEOUT = int(os.getenv("NEMOCLAW_EXEC_TIMEOUT", "300"))

# Roles that can create OpenShell sandboxes
OPENSHELL_ALLOWED_ROLES = {"elevated-developer", "admin"}


class OpenShellSkill:
    """
    NemoClaw OpenShell sandboxed execution.

    Wraps the sandbox factory REST API and exposes a skill interface
    compatible with the existing SandboxSkill for smooth transition.
    """

    ACTIVATION_TRIGGERS = [
        "sandbox",
        "execute",
        "run code",
        "isolated",
        "openshell",
        "hardened",
        "policy",
        "nemoclaw",
        "secure execution",
        "cuda tools",
        "nvidia-smi",
        "platform code",
    ]

    # -----------------------------------------------------------------------
    # Public interface (mirrors SandboxSkill)
    # -----------------------------------------------------------------------

    @classmethod
    def is_activated(cls, user_task: str) -> bool:
        task_lower = user_task.lower()
        return any(t in task_lower for t in cls.ACTIVATION_TRIGGERS)

    @classmethod
    def get_context(cls, user_task: str) -> str:
        if not cls.is_activated(user_task):
            return ""
        return _CONTEXT_TEMPLATE

    @classmethod
    async def execute(cls, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch operation to factory or sandbox."""
        handlers = {
            "create_sandbox": cls._create_sandbox,
            "execute": cls._execute_in_sandbox,
            "run_code": cls._run_code_compat,   # SandboxSkill compatibility alias
            "destroy_sandbox": cls._destroy_sandbox,
            "list_sandboxes": cls._list_sandboxes,
            "status": cls._sandbox_status,
        }
        handler = handlers.get(operation)
        if not handler:
            return {"error": f"Unknown operation: {operation}", "available": list(handlers)}
        try:
            return await handler(params)
        except Exception as e:
            logger.error(f"OpenShellSkill.{operation} failed: {e}")
            return {"error": str(e), "operation": operation}

    # -----------------------------------------------------------------------
    # Factory calls
    # -----------------------------------------------------------------------

    @classmethod
    async def _factory_request(
        cls,
        method: str,
        path: str,
        json: Optional[Dict] = None,
        timeout: int = FACTORY_TIMEOUT,
    ) -> Dict[str, Any]:
        """Make a request to the sandbox factory."""
        url = f"{FACTORY_URL}{path}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await getattr(client, method)(url, json=json)
                resp.raise_for_status()
                return resp.json()
            except httpx.ConnectError:
                # Factory unavailable — signal caller to fall back to SandboxSkill
                raise FactoryUnavailableError(f"NemoClaw factory unreachable at {FACTORY_URL}")
            except httpx.HTTPStatusError as e:
                raise RuntimeError(f"Factory returned {e.response.status_code}: {e.response.text}")

    @classmethod
    async def _create_sandbox(cls, params: Dict[str, Any]) -> Dict[str, Any]:
        user_id = params.get("user_id", "agent-system")
        user_role = params.get("user_role", "developer")
        if user_role not in OPENSHELL_ALLOWED_ROLES:
            # Viewer/developer roles — use basic blueprint but still route through factory
            logger.debug(f"Role {user_role} → using developer blueprint")
        session_id = params.get("session_id")
        return await cls._factory_request("post", "/sandbox", json={
            "user_id": user_id,
            "user_role": user_role,
            "session_id": session_id,
        })

    @classmethod
    async def _execute_in_sandbox(cls, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute code/command inside an existing sandbox via OpenShell exec."""
        sandbox_name = params.get("sandbox_name")
        if not sandbox_name:
            return {"error": "sandbox_name required"}

        code = params.get("code", "")
        language = params.get("language", "bash")
        timeout = params.get("timeout_seconds", SANDBOX_EXEC_TIMEOUT)

        # OpenShell exec endpoint (gateway proxies to sandbox)
        return await cls._factory_request(
            "post",
            f"/sandbox/{sandbox_name}/exec",
            json={"code": code, "language": language, "timeout": timeout},
            timeout=timeout + 10,
        )

    @classmethod
    async def _run_code_compat(cls, params: Dict[str, Any]) -> Dict[str, Any]:
        """SandboxSkill compatibility: create ephemeral sandbox, run, destroy."""
        user_id = params.get("user_id", "agent-system")
        user_role = params.get("user_role", "elevated-developer")
        code = params.get("code", "")
        language = params.get("language", "python")
        timeout = params.get("timeout_seconds", 300)

        try:
            # Create ephemeral sandbox
            sandbox = await cls._create_sandbox({
                "user_id": user_id,
                "user_role": user_role,
            })
            sandbox_name = sandbox["sandbox_name"]

            # Execute
            result = await cls._execute_in_sandbox({
                "sandbox_name": sandbox_name,
                "code": code,
                "language": language,
                "timeout_seconds": timeout,
            })

            # Destroy
            await cls._destroy_sandbox({"sandbox_name": sandbox_name})
            return result

        except FactoryUnavailableError:
            logger.warning("OpenShell factory unavailable — falling back to SandboxSkill")
            return await _fallback_to_sandbox_skill(params)

    @classmethod
    async def _destroy_sandbox(cls, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("sandbox_name")
        if not name:
            return {"error": "sandbox_name required"}
        return await cls._factory_request("delete", f"/sandbox/{name}")

    @classmethod
    async def _list_sandboxes(cls, params: Dict[str, Any]) -> Dict[str, Any]:
        return await cls._factory_request("get", "/sandbox")

    @classmethod
    async def _sandbox_status(cls, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("sandbox_name")
        if not name:
            return {"error": "sandbox_name required"}
        return await cls._factory_request("get", f"/sandbox/{name}")


# ============================================================================
# Exceptions
# ============================================================================

class FactoryUnavailableError(RuntimeError):
    """NemoClaw sandbox factory is unreachable — caller should fallback."""
    pass


# ============================================================================
# SandboxSkill fallback
# ============================================================================

async def _fallback_to_sandbox_skill(params: Dict[str, Any]) -> Dict[str, Any]:
    """Fallback to legacy Docker-based SandboxSkill when OpenShell unavailable."""
    try:
        import importlib
        # app.skills is already in sys.modules when this module is loaded by skills.py;
        # importlib.import_module avoids relative-import errors from spec_from_file_location.
        skills_mod = importlib.import_module("app.skills")
        SandboxSkill = skills_mod.SandboxSkill  # type: ignore[attr-defined]
        result = await SandboxSkill.execute("run_code", params)
        result["_fallback"] = "SandboxSkill (OpenShell factory unavailable)"
        return result
    except Exception as e:
        return {"error": f"Both OpenShellSkill and SandboxSkill failed: {e}"}


# ============================================================================
# Context template
# ============================================================================

_CONTEXT_TEMPLATE = """# OpenShell Skill (NemoClaw)

**Purpose:** Hardened code execution inside NemoClaw OpenShell sandboxes.
Landlock filesystem isolation + seccomp + netns — stronger than plain Docker.

**Operations:**
- `create_sandbox` — provision sandbox for user+role → returns `sandbox_name`
- `execute` — run code/command in sandbox → returns `{stdout, stderr, exit_code}`
- `run_code` — ephemeral create→execute→destroy (SandboxSkill-compatible)
- `destroy_sandbox` — clean up sandbox
- `list_sandboxes` — show active sandboxes for current user
- `status` — sandbox health + policy state

**Language support:** bash, python, node, go, rust

**Policy:** network egress and filesystem access governed by role blueprint.
Admission to `elevated-developer+` required for full sandbox access.

**Fallback:** If NemoClaw factory is unreachable, execution routes through
legacy SandboxSkill (Docker isolation). This preserves availability during
NemoClaw upgrades (alpha software).

**Example (run nvidia-smi in sandbox):**
```json
{
  "operation": "run_code",
  "params": {
    "user_role": "elevated-developer",
    "code": "nvidia-smi --query-gpu=name,memory.free --format=csv",
    "language": "bash"
  }
}
```
"""
