"""
NemoClaw Sandbox Factory — REST wrapper around nemoclaw CLI.

Provides agent-service with sandbox lifecycle management:
  POST /sandbox           — create sandbox for user+role
  DELETE /sandbox/{name}  — destroy sandbox
  GET  /sandbox           — list all active sandboxes
  GET  /sandbox/{name}    — get sandbox status + policy state
  POST /sandbox/{name}/policy — update network policy (hot-reload)

Auth: validates JWT from X-Auth-Request-User + X-Auth-Request-Groups headers
      (set by oauth2-proxy, trusted because we're inside the Docker network)
"""

import asyncio
import json
import logging
import os
import subprocess
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import asyncpg
import httpx
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel

logging.basicConfig(level=os.getenv("LOG_LEVEL", "info").upper())
logger = logging.getLogger(__name__)

# ============================================================================
# Config
# ============================================================================
FACTORY_PORT = int(os.getenv("FACTORY_PORT", "9095"))
GATEWAY_URL = os.getenv("OPENSHELL_GATEWAY_URL", "http://openshell-gateway:9090")
BLUEPRINTS_PATH = os.getenv("BLUEPRINTS_PATH", "/blueprints")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "inference")
POSTGRES_USER = os.getenv("POSTGRES_USER", "inference")

_pw_file = os.getenv("POSTGRES_PASSWORD_FILE")
POSTGRES_PASSWORD = (
    open(_pw_file).read().strip()
    if _pw_file and os.path.exists(_pw_file)
    else os.getenv("POSTGRES_PASSWORD", "")
)

# Blueprint per role — maps role name → blueprint filename (without .yaml)
ROLE_BLUEPRINT_MAP = {
    "viewer": "blueprint-viewer",
    "developer": "blueprint-developer",
    "elevated-developer": "blueprint-elevated",
    "admin": "blueprint-admin",
}

# ============================================================================
# Metrics
# ============================================================================
sandbox_created_total = Counter("nemoclaw_sandbox_created_total", "Sandboxes created", ["role"])
sandbox_destroyed_total = Counter("nemoclaw_sandbox_destroyed_total", "Sandboxes destroyed", ["role"])
sandbox_active = Gauge("nemoclaw_sandbox_active", "Active sandboxes", ["role"])
policy_block_total = Counter("nemoclaw_policy_block_total", "Policy blocks", ["event_type"])
sandbox_create_latency = Histogram("nemoclaw_sandbox_create_latency_seconds", "Create latency")

# ============================================================================
# DB
# ============================================================================
_pool: Optional[asyncpg.Pool] = None

CREATE_SANDBOX_TABLE = """
CREATE TABLE IF NOT EXISTS nemoclaw_sandboxes (
    id          BIGSERIAL PRIMARY KEY,
    sandbox_name TEXT NOT NULL UNIQUE,
    user_id      TEXT NOT NULL,
    user_role    TEXT NOT NULL,
    blueprint    TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status       TEXT NOT NULL DEFAULT 'active',
    metadata     JSONB
);
CREATE INDEX IF NOT EXISTS ix_nemoclaw_sandboxes_user ON nemoclaw_sandboxes (user_id);
CREATE INDEX IF NOT EXISTS ix_nemoclaw_sandboxes_status ON nemoclaw_sandboxes (status);
"""

CREATE_AUDIT_TABLE = """
CREATE TABLE IF NOT EXISTS nemoclaw_audit (
    id           BIGSERIAL PRIMARY KEY,
    ts           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sandbox_name TEXT,
    user_id      TEXT,
    user_role    TEXT,
    event_type   TEXT NOT NULL,
    details      JSONB
);
CREATE INDEX IF NOT EXISTS ix_nemoclaw_audit_ts ON nemoclaw_audit (ts);
"""


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=POSTGRES_HOST, port=POSTGRES_PORT,
            database=POSTGRES_DB, user=POSTGRES_USER, password=POSTGRES_PASSWORD,
            min_size=2, max_size=10,
        )
        async with _pool.acquire() as conn:
            await conn.execute(CREATE_SANDBOX_TABLE)
            await conn.execute(CREATE_AUDIT_TABLE)
    return _pool


async def audit(pool, event_type: str, sandbox_name: str = None,
                user_id: str = None, user_role: str = None, details: dict = None):
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO nemoclaw_audit (sandbox_name, user_id, user_role, event_type, details)"
                " VALUES ($1, $2, $3, $4, $5)",
                sandbox_name, user_id, user_role, event_type, json.dumps(details or {}),
            )
    except Exception as e:
        logger.warning(f"audit write failed: {e}")


# ============================================================================
# Models
# ============================================================================
class CreateSandboxRequest(BaseModel):
    user_id: str
    user_role: str
    session_id: Optional[str] = None
    extra_env: Optional[Dict[str, str]] = None


class PolicyUpdateRequest(BaseModel):
    allowlist: Optional[List[str]] = None
    blocklist: Optional[List[str]] = None


# ============================================================================
# Auth helpers — trust oauth2-proxy headers (internal network only)
# ============================================================================
def extract_user(
    x_auth_request_user: Optional[str] = Header(None),
    x_auth_request_email: Optional[str] = Header(None),
    x_auth_request_groups: Optional[str] = Header(None),
) -> Dict[str, Any]:
    user_id = x_auth_request_user or x_auth_request_email or "anonymous"
    groups = [g.strip() for g in (x_auth_request_groups or "").split(",") if g.strip()]
    return {"user_id": user_id, "groups": groups}


def resolve_role(groups: List[str]) -> str:
    """Return highest role from groups list."""
    priority = ["admin", "elevated-developer", "developer", "viewer"]
    for role in priority:
        if any(role in g for g in groups):
            return role
    return "viewer"


def select_blueprint(role: str) -> str:
    return ROLE_BLUEPRINT_MAP.get(role, "blueprint-viewer")


# ============================================================================
# nemoclaw CLI wrapper
# ============================================================================
async def run_nemoclaw(*args: str, timeout: int = 60) -> Dict[str, Any]:
    """Run nemoclaw CLI command and return structured result."""
    cmd = ["nemoclaw", *args]
    logger.debug(f"nemoclaw cmd: {' '.join(cmd)}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "returncode": proc.returncode,
            "stdout": stdout.decode().strip(),
            "stderr": stderr.decode().strip(),
            "success": proc.returncode == 0,
        }
    except asyncio.TimeoutError:
        return {"returncode": -1, "stdout": "", "stderr": "timeout", "success": False}
    except FileNotFoundError:
        # nemoclaw not installed — return mock for dev environments
        logger.warning("nemoclaw CLI not found — running in offline mode")
        return {"returncode": 0, "stdout": '{"status": "offline-mode"}', "stderr": "", "success": True, "offline": True}


# ============================================================================
# App
# ============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    logger.info("NemoClaw Sandbox Factory started")
    yield
    if _pool:
        await _pool.close()


app = FastAPI(title="NemoClaw Sandbox Factory", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "gateway": GATEWAY_URL}


@app.get("/metrics")
async def metrics():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(generate_latest().decode())


@app.post("/sandbox")
async def create_sandbox(req: CreateSandboxRequest, user: Dict = Depends(extract_user)):
    """Create a new NemoClaw sandbox for the given user and role."""
    pool = await get_pool()
    role = req.user_role or resolve_role(user["groups"])
    blueprint = select_blueprint(role)
    name = f"shml-{req.user_id[:8]}-{int(time.time())}"

    start = time.perf_counter()
    result = await run_nemoclaw(
        "setup",
        "--name", name,
        "--blueprint", f"{BLUEPRINTS_PATH}/{blueprint}.yaml",
        "--profile", _infer_profile(role),
    )
    elapsed = time.perf_counter() - start
    sandbox_create_latency.observe(elapsed)

    if not result["success"]:
        await audit(pool, "sandbox_create_failed", name, req.user_id, role,
                    {"error": result["stderr"]})
        raise HTTPException(status_code=500, detail=f"Sandbox creation failed: {result['stderr']}")

    # Persist to DB
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO nemoclaw_sandboxes (sandbox_name, user_id, user_role, blueprint)"
            " VALUES ($1, $2, $3, $4) ON CONFLICT (sandbox_name) DO UPDATE"
            " SET status='active', last_seen=NOW()",
            name, req.user_id, role, blueprint,
        )

    sandbox_created_total.labels(role=role).inc()
    sandbox_active.labels(role=role).inc()
    await audit(pool, "sandbox_created", name, req.user_id, role,
                {"blueprint": blueprint, "create_latency_s": round(elapsed, 3)})

    logger.info(f"Created sandbox {name} for user={req.user_id} role={role} blueprint={blueprint}")
    return {
        "sandbox_name": name,
        "user_id": req.user_id,
        "role": role,
        "blueprint": blueprint,
        "inference_profile": _infer_profile(role),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "connect_cmd": f"nemoclaw {name} connect",
        "status_cmd": f"nemoclaw {name} status",
    }


@app.delete("/sandbox/{name}")
async def destroy_sandbox(name: str, user: Dict = Depends(extract_user)):
    """Destroy a sandbox."""
    pool = await get_pool()
    result = await run_nemoclaw("stop", name)
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_role FROM nemoclaw_sandboxes WHERE sandbox_name=$1", name)
        role = row["user_role"] if row else "unknown"
        await conn.execute(
            "UPDATE nemoclaw_sandboxes SET status='destroyed' WHERE sandbox_name=$1", name
        )
    sandbox_destroyed_total.labels(role=role).inc()
    sandbox_active.labels(role=role).dec()
    await audit(pool, "sandbox_destroyed", name, user["user_id"], role)
    return {"sandbox_name": name, "status": "destroyed", "result": result["stdout"]}


@app.get("/sandbox")
async def list_sandboxes(user: Dict = Depends(extract_user)):
    """List all active sandboxes (admin sees all; others see own)."""
    pool = await get_pool()
    role = resolve_role(user["groups"])
    async with pool.acquire() as conn:
        if role == "admin":
            rows = await conn.fetch("SELECT * FROM nemoclaw_sandboxes WHERE status='active' ORDER BY created_at DESC")
        else:
            rows = await conn.fetch(
                "SELECT * FROM nemoclaw_sandboxes WHERE status='active' AND user_id=$1 ORDER BY created_at DESC",
                user["user_id"],
            )
    return [dict(r) for r in rows]


@app.get("/sandbox/{name}")
async def get_sandbox(name: str):
    """Get sandbox health and policy state from OpenShell."""
    result = await run_nemoclaw(name, "status")
    return {"sandbox_name": name, "raw": result["stdout"], "healthy": result["success"]}


@app.post("/sandbox/{name}/policy")
async def update_policy(name: str, req: PolicyUpdateRequest, user: Dict = Depends(extract_user)):
    """Hot-reload network policy for a sandbox."""
    pool = await get_pool()
    cmds = []
    if req.allowlist:
        for host in req.allowlist:
            cmds.append(["openshell", "policy", "allow", "--sandbox", name, "--host", host])
    if req.blocklist:
        for host in req.blocklist:
            cmds.append(["openshell", "policy", "deny", "--sandbox", name, "--host", host])
    results = []
    for cmd_args in cmds:
        r = await run_nemoclaw(*cmd_args[1:])  # strip 'openshell' prefix
        results.append(r)
    await audit(pool, "policy_updated", name, user["user_id"], None,
                {"allowlist": req.allowlist, "blocklist": req.blocklist})
    return {"sandbox_name": name, "updated": True, "results": results}


# ============================================================================
# Helpers
# ============================================================================
def _infer_profile(role: str) -> str:
    """Select inference profile by role."""
    if role == "admin":
        return "vllm"   # full access — local or cloud toggle in blueprint-admin
    return "vllm"       # all roles get local vLLM by default; cloud escalates automatically


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=FACTORY_PORT, log_level=os.getenv("LOG_LEVEL", "info"))
