#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP


AGENT_SERVICE_ROOT = Path(__file__).resolve().parents[2] / "inference" / "agent-service"
sys.path.insert(0, str(AGENT_SERVICE_ROOT))

from app.mcp import mcp_server  # noqa: E402


server = FastMCP(
    name="shml-platform",
    instructions="SHML platform tools for training status, GPUs, MLflow, vision, and NemoClaw sandbox management.",
    log_level="ERROR",
)


async def _call_tool(tool_name: str, **arguments: Any) -> dict[str, Any]:
    filtered_arguments = {key: value for key, value in arguments.items() if value is not None}
    result = await mcp_server.call_tool(tool_name, filtered_arguments)
    if not result.success:
        raise RuntimeError(result.error or f"{tool_name} failed")
    if isinstance(result.result, dict):
        return result.result
    return {"result": result.result}


@server.tool(description="Get Ray training status, MLflow metrics, and GPU usage.")
async def training_status(job_id: str = "latest") -> dict[str, Any]:
    return await _call_tool("training_status", job_id=job_id)


@server.tool(description="Get GPU VRAM usage, processes, and temperature.")
async def gpu_status(gpu_id: int | None = None) -> dict[str, Any]:
    return await _call_tool("gpu_status", gpu_id=gpu_id)


@server.tool(description="Query MLflow experiments, runs, and metrics.")
async def mlflow_query(
    experiment_name: str | None = None,
    run_id: str | None = None,
    metric: str | None = None,
) -> dict[str, Any]:
    return await _call_tool(
        "mlflow_query",
        experiment_name=experiment_name,
        run_id=run_id,
        metric=metric,
    )


@server.tool(description="Analyze an image with Qwen3-VL on the RTX 2070.")
async def vision_analyze(
    image: str,
    prompt: str = "Describe this image in detail",
) -> dict[str, Any]:
    return await _call_tool("vision_analyze", image=image, prompt=prompt)


@server.tool(description="Analyze an image and then generate code from it.")
async def vision_then_code(image: str, task: str) -> dict[str, Any]:
    return await _call_tool("vision_then_code", image=image, task=task)


@server.tool(description="Provision a NemoClaw OpenShell sandbox for a user and role.")
async def create_sandbox(
    user_id: str,
    user_role: str = "developer",
    session_id: str | None = None,
) -> dict[str, Any]:
    return await _call_tool(
        "create_sandbox",
        user_id=user_id,
        user_role=user_role,
        session_id=session_id,
    )


@server.tool(description="List active NemoClaw sandboxes.")
async def list_sandboxes() -> dict[str, Any]:
    return await _call_tool("list_sandboxes")


@server.tool(description="Destroy a NemoClaw sandbox.")
async def destroy_sandbox(sandbox_name: str) -> dict[str, Any]:
    return await _call_tool("destroy_sandbox", sandbox_name=sandbox_name)


@server.tool(description="Get the health and policy state for a NemoClaw sandbox.")
async def get_sandbox_policy(sandbox_name: str) -> dict[str, Any]:
    return await _call_tool("get_sandbox_policy", sandbox_name=sandbox_name)


@server.tool(description="Hot-reload the network policy for a running NemoClaw sandbox.")
async def update_sandbox_policy(
    sandbox_name: str,
    allowlist: list[str] | None = None,
    blocklist: list[str] | None = None,
) -> dict[str, Any]:
    return await _call_tool(
        "update_sandbox_policy",
        sandbox_name=sandbox_name,
        allowlist=allowlist or [],
        blocklist=blocklist or [],
    )


if __name__ == "__main__":
    server.run("stdio")
