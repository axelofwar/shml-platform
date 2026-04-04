#!/usr/bin/env python3
"""
SHML Platform MCP Bridge (stdio transport)

Translates MCP JSON-RPC 2.0 (stdin/stdout) to SHML agent-service REST API calls.
No external dependencies — stdlib only.

Usage in ~/.continue/config.yaml:
  mcpServers:
    - name: SHML Platform
      command: python3
      args: ["/home/axelofwar/Projects/shml-platform/scripts/continue_mcp_bridge.py"]

Requirements:
  - agent-service must be running with the docker-compose.override.yml port binding:
    127.0.0.1:8099:8000
  - Apply override: docker compose --env-file .env \
      -f inference/agent-service/docker-compose.yml \
      -f inference/agent-service/docker-compose.override.yml \
      up -d agent-service
"""

from __future__ import annotations

import json
import logging
import sys
import urllib.error
import urllib.request
from typing import Any

# Agent-service direct port (bypasses Traefik + OAuth).
# Set via env var SHML_MCP_BASE_URL to override.
import os
BASE_URL = os.environ.get("SHML_MCP_BASE_URL", "http://127.0.0.1:8099")

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def _http_get(path: str) -> dict[str, Any]:
    req = urllib.request.Request(f"{BASE_URL}{path}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _http_post(path: str, body: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def _write(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _ok(msg_id: Any, result: Any) -> None:
    _write({"jsonrpc": "2.0", "id": msg_id, "result": result})


def _err(msg_id: Any, code: int, message: str) -> None:
    _write({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})


def _tool_to_mcp(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert agent-service tool format to MCP inputSchema format."""
    params = tool.get("parameters", {"type": "object", "properties": {}})
    return {
        "name": tool["name"],
        "description": tool.get("description", ""),
        "inputSchema": params,
    }


def handle_initialize(msg_id: Any, _params: dict) -> None:
    _ok(msg_id, {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "SHML Platform", "version": "1.0.0"},
    })


def handle_tools_list(msg_id: Any) -> None:
    try:
        data = _http_get("/mcp/tools")
        tools = [_tool_to_mcp(t) for t in data.get("tools", [])]
        _ok(msg_id, {"tools": tools})
    except urllib.error.URLError as exc:
        logger.error("Cannot reach agent-service at %s: %s", BASE_URL, exc)
        _err(msg_id, -32603, f"agent-service unreachable ({BASE_URL}). Is it running with the override port? {exc}")
    except Exception as exc:
        _err(msg_id, -32603, str(exc))


def handle_tools_call(msg_id: Any, params: dict) -> None:
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})
    try:
        data = _http_post(f"/mcp/tools/{tool_name}/call", arguments)
        result_text = json.dumps(data.get("result", data), indent=2)
        _ok(msg_id, {"content": [{"type": "text", "text": result_text}]})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        _err(msg_id, -32603, f"Tool '{tool_name}' failed ({exc.code}): {body}")
    except urllib.error.URLError as exc:
        _err(msg_id, -32603, f"agent-service unreachable: {exc}")
    except Exception as exc:
        _err(msg_id, -32603, str(exc))


def main() -> None:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {}) or {}

        if method == "initialize":
            handle_initialize(msg_id, params)
        elif method in ("notifications/initialized", "initialized"):
            pass  # no response for notifications
        elif method == "tools/list":
            handle_tools_list(msg_id)
        elif method == "tools/call":
            handle_tools_call(msg_id, params)
        elif method == "ping":
            _ok(msg_id, {})
        else:
            if msg_id is not None:
                _err(msg_id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    main()
