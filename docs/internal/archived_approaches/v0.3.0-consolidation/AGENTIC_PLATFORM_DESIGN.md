# SHML Platform - Agentic Features Design Document

> **Version**: 1.0.0  
> **Created**: 2025-12-05  
> **Status**: Implementation Ready  
> **Branch**: `feature/agentic-platform-v1`

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [System Requirements](#system-requirements)
3. [Architecture Overview](#architecture-overview)
4. [Permission Model](#permission-model)
5. [Component Specifications](#component-specifications)
6. [Implementation Phases](#implementation-phases)
7. [Security Considerations](#security-considerations)
8. [Monitoring & Observability](#monitoring--observability)

---

## Executive Summary

This document outlines the design for transforming the SHML Platform's Chat API into a full-featured agentic system with:

- **Tiered permissions** with granular tool access per role
- **MCP-compatible tools** for web search, GitHub integration, code execution
- **Secure sandboxed execution** using Kata Containers (VM-level isolation)
- **Real-time streaming UI** showing agent actions step-by-step
- **Admin-controlled model management** with approval workflows
- **Comprehensive audit logging** with tamper-proof storage

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Secret Management | Infisical (self-hosted) | Simpler than Vault, ~200MB RAM |
| Sandbox Isolation | Kata Containers | VM-level security, RAM abundant (48GB available) |
| Audit Logs | Append-only + HMAC signed | Tamper-proof, automated |
| Real-time Streaming | WebSockets + Redis pub/sub | Bidirectional, scalable |
| Tool Framework | Composio | MCP-compatible, 150+ integrations |
| Agent Framework | LangGraph | Checkpointing, state machines |
| Queue Strategy | Separate per tier | Fair, predictable |

---

## System Requirements

### Current Resources (as of 2025-12-05)

| Resource | Total | Used | Available |
|----------|-------|------|-----------|
| CPU | 24 cores (Ryzen 9 3900X) | ~13% | ~87% |
| RAM | 64 GB | ~15 GB | **~48 GB** |
| GPU (3090 Ti) | 24 GB VRAM | 22.6 GB | 1.5 GB |
| GPU (2070) | 8 GB VRAM | 6.7 GB | 1 GB |
| Disk | 1.8 TB NVMe | 326 GB | **1.4 TB** |

### Projected Additional Resources (10 concurrent users)

| Component | Memory | CPU | Notes |
|-----------|--------|-----|-------|
| Kata sandbox pool (3 warm) | 450 MB | ~1% idle | VM overhead |
| Active sandboxes (10 max) | 1.5 GB | ~10% | During execution |
| Infisical | 300 MB | ~1% | Secrets manager |
| WebSocket connections | 50 MB | <1% | 10 connections |
| Agent overhead | 1 GB | ~5% | 5 concurrent agents |
| **Total New** | **~3.3 GB** | **~17%** | Well within limits |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SHML Platform                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐    ┌──────────────┐    ┌─────────────────┐                │
│  │   Homer     │───▶│  Traefik     │───▶│   OAuth2-Proxy  │                │
│  │  Dashboard  │    │  (Routing)   │    │  (FusionAuth)   │                │
│  └─────────────┘    └──────────────┘    └────────┬────────┘                │
│                                                   │                          │
│                            ┌──────────────────────┴───────────────┐         │
│                            ▼                                      ▼         │
│  ┌─────────────────────────────────────┐    ┌──────────────────────────┐   │
│  │           Chat UI (React)            │    │      Chat API (FastAPI)  │   │
│  │  ┌─────────────────────────────────┐ │    │  ┌────────────────────┐  │   │
│  │  │ • Model selector (auto/fast/    │ │    │  │ Rate Limiter       │  │   │
│  │  │   quality)                       │ │    │  │ (Redis + tier)     │  │   │
│  │  │ • Real-time execution panel     │ │◀══▶│  ├────────────────────┤  │   │
│  │  │ • Interrupt/Cancel buttons      │ │ WS │  │ Agent Executor     │  │   │
│  │  │ • Cost estimation display       │ │    │  │ (LangGraph)        │  │   │
│  │  │ • Audit log viewer (admin)      │ │    │  ├────────────────────┤  │   │
│  │  └─────────────────────────────────┘ │    │  │ Tool Router        │  │   │
│  └─────────────────────────────────────┘    │  │ (Composio + MCP)   │  │   │
│                                              │  └─────────┬──────────┘  │   │
│                                              └────────────┼─────────────┘   │
│                                                           │                  │
│         ┌─────────────────────────────────────────────────┼──────────┐      │
│         │                                                 │          │      │
│         ▼                                                 ▼          ▼      │
│  ┌─────────────┐  ┌─────────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │  Infisical  │  │  Sandbox Pool   │  │   GitHub    │  │   Ollama    │    │
│  │  (Secrets)  │  │  (Kata VMs)     │  │   API       │  │   Models    │    │
│  │             │  │  ┌───┐┌───┐┌───┐│  │             │  │             │    │
│  │ • GitHub    │  │  │VM1││VM2││VM3││  │ • Issues    │  │ • Qwen 32B  │    │
│  │   tokens    │  │  └───┘└───┘└───┘│  │ • PRs       │  │ • Qwen 3B   │    │
│  │ • API keys  │  │  Warm pool (3)  │  │ • Search    │  │ • Pending   │    │
│  └─────────────┘  └─────────────────┘  └─────────────┘  └─────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                         Data Layer                                       ││
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    ││
│  │  │  PostgreSQL │  │    Redis    │  │  Audit Log  │  │   Grafana   │    ││
│  │  │  • Users    │  │  • Queues   │  │  • Append   │  │  • Usage    │    ││
│  │  │  • Convos   │  │  • Pub/Sub  │  │    only     │  │  • Costs    │    ││
│  │  │  • History  │  │  • State    │  │  • HMAC     │  │  • Metrics  │    ││
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘    ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Permission Model

### Role Hierarchy

```
Admin (Tier 4)
   │
   ├── Elevated Developer (Tier 3)
   │      │
   │      ├── Developer (Tier 2)
   │      │      │
   │      │      └── Viewer (Tier 1)
   │      │
   │      └── [Can be elevated by Admin]
   │
   └── [Full system access with approval workflows]
```

### Permission Matrix

| Capability | Viewer | Developer | Elevated Dev | Admin |
|------------|--------|-----------|--------------|-------|
| **Chat/Ask** | ✅ | ✅ | ✅ | ✅ |
| **Web Search** | ✅ | ✅ | ✅ | ✅ |
| **Code Search** | ✅ | ✅ | ✅ | ✅ |
| **GitHub Read** | ✅ | ✅ | ✅ | ✅ |
| **GitHub Issues** | ❌ | ❌ | ✅ | ✅ |
| **GitHub PRs** | ❌ | ❌ | ✅ | ✅ |
| **Sandbox Code Exec** | ❌ | ❌ | ✅ | ✅ |
| **Pull Models** | ❌ | ❌ | ✅ (quota) | ✅ |
| **Delete Models** | ❌ | ❌ | ❌ | ✅ |
| **Host Info Read** | ❌ | ❌ | ❌ | ✅ |
| **Container Mgmt** | ❌ | ❌ | ❌ | ✅ (approval) |
| **Host Execution** | ❌ | ❌ | ❌ | ✅ (approval) |
| **View All Audits** | ❌ | ❌ | ❌ | ✅ |
| **Approve Models** | ❌ | ❌ | ❌ | ✅ |
| **Elevate Users** | ❌ | ❌ | ❌ | ✅ |

### Rate Limits

| Tier | Ask Requests/min | Tool Calls/min | GitHub Actions/day | Model Pull Quota |
|------|------------------|----------------|-------------------|------------------|
| Viewer | 25 | 15 | 0 | 0 |
| Developer | 50 | 30 | 0 | 0 |
| Elevated Dev | 100 | 50 | 20 | 50 GB pending |
| Admin | Unlimited | Unlimited | Unlimited | Unlimited |

---

## Component Specifications

### 1. Infisical (Secrets Manager)

**Purpose**: Secure storage for GitHub tokens, API keys, encrypted with zero-knowledge architecture.

```yaml
# docker-compose.infra.yml addition
infisical:
  image: infisical/infisical:latest
  container_name: shml-infisical
  restart: unless-stopped
  environment:
    - ENCRYPTION_KEY=${INFISICAL_ENCRYPTION_KEY}
    - AUTH_SECRET=${INFISICAL_AUTH_SECRET}
    - MONGO_URL=mongodb://infisical-mongo:27017/infisical
    - REDIS_URL=redis://shml-redis:6379
    - SITE_URL=https://shml-platform.tail38b60a.ts.net/secrets
  ports:
    - "8070:8080"
  networks:
    - shml-network
  mem_limit: 512M

infisical-mongo:
  image: mongo:6
  container_name: shml-infisical-mongo
  restart: unless-stopped
  volumes:
    - infisical-mongo-data:/data/db
  networks:
    - shml-network
  mem_limit: 512M
```

**Integration with Chat API**:
```python
# inference/chat_api/app/secrets.py
from infisical_client import InfisicalClient

class SecretsManager:
    def __init__(self):
        self.client = InfisicalClient(
            site_url=os.getenv("INFISICAL_URL"),
            token=os.getenv("INFISICAL_SERVICE_TOKEN")
        )

    async def get_github_token(self, user_id: str) -> Optional[str]:
        """Retrieve user's GitHub token."""
        return self.client.get_secret(
            secret_name=f"github_token_{user_id}",
            project_id=os.getenv("INFISICAL_PROJECT_ID"),
            environment="production"
        )

    async def store_github_token(self, user_id: str, token: str):
        """Store user's GitHub token (encrypted at rest)."""
        self.client.create_secret(
            secret_name=f"github_token_{user_id}",
            secret_value=token,
            project_id=os.getenv("INFISICAL_PROJECT_ID"),
            environment="production"
        )
```

### 2. Kata Containers (Sandbox Isolation)

**Purpose**: VM-level isolation for agent code execution.

**Installation**:
```bash
# Install Kata Containers runtime
sudo apt-get install -y kata-containers

# Configure containerd to use kata
cat >> /etc/containerd/config.toml << EOF
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.kata]
  runtime_type = "io.containerd.kata.v2"
  [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.kata.options]
    ConfigPath = "/opt/kata/share/defaults/kata-containers/configuration.toml"
EOF

sudo systemctl restart containerd
```

**Sandbox Pool Manager**:
```python
# inference/chat_api/app/sandbox/pool.py
from dataclasses import dataclass
from typing import Optional
import asyncio
import docker

@dataclass
class SandboxConfig:
    memory_limit: str = "512m"
    cpu_limit: float = 0.5
    timeout_seconds: int = 60
    runtime: str = "kata"  # Use Kata Containers

class SandboxPool:
    """Manages a pool of pre-warmed Kata container sandboxes."""

    def __init__(self, pool_size: int = 3):
        self.pool_size = pool_size
        self.available: asyncio.Queue = asyncio.Queue()
        self.active: dict[str, dict] = {}
        self.docker = docker.from_env()

    async def initialize(self):
        """Pre-warm the sandbox pool."""
        for i in range(self.pool_size):
            container = await self._create_sandbox()
            await self.available.put(container)

    async def _create_sandbox(self) -> str:
        """Create a new Kata-isolated sandbox container."""
        container = self.docker.containers.run(
            image="shml-platform/sandbox:latest",
            runtime="kata",
            detach=True,
            mem_limit="512m",
            cpu_quota=50000,  # 0.5 CPU
            network_mode="none",  # No network access
            security_opt=["no-new-privileges"],
            read_only=True,
            tmpfs={"/tmp": "size=100M,mode=1777"},
        )
        return container.id

    async def acquire(self, user_id: str, timeout: float = 5.0) -> Optional[str]:
        """Get a sandbox from the pool (or wait)."""
        try:
            container_id = await asyncio.wait_for(
                self.available.get(),
                timeout=timeout
            )
            self.active[container_id] = {"user_id": user_id, "started_at": time.time()}
            # Start replacement creation in background
            asyncio.create_task(self._replenish())
            return container_id
        except asyncio.TimeoutError:
            return None

    async def release(self, container_id: str):
        """Return a sandbox to the pool (or destroy if tainted)."""
        if container_id in self.active:
            del self.active[container_id]
        # Destroy used container (don't reuse for security)
        try:
            container = self.docker.containers.get(container_id)
            container.remove(force=True)
        except:
            pass

    async def _replenish(self):
        """Maintain pool size."""
        if self.available.qsize() < self.pool_size:
            container = await self._create_sandbox()
            await self.available.put(container)
```

### 3. Audit Log System

**Database Schema**:
```sql
-- migrations/004_audit_logs.sql
CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id VARCHAR(255) NOT NULL,
    user_role VARCHAR(50) NOT NULL,
    action_type VARCHAR(100) NOT NULL,  -- 'tool_call', 'github_action', 'model_pull', etc.
    action_name VARCHAR(255) NOT NULL,
    action_input JSONB,
    action_output JSONB,
    success BOOLEAN NOT NULL,
    error_message TEXT,
    execution_time_ms INTEGER,
    cost_tokens INTEGER DEFAULT 0,
    session_id UUID,
    conversation_id UUID,
    -- HMAC signature for tamper detection
    signature VARCHAR(128) NOT NULL,
    -- Previous entry hash for chain integrity
    prev_hash VARCHAR(64),

    -- Constraints to enforce append-only
    CONSTRAINT audit_logs_no_update CHECK (TRUE)
);

-- Index for efficient queries
CREATE INDEX idx_audit_logs_user_id ON audit_logs(user_id, timestamp DESC);
CREATE INDEX idx_audit_logs_action_type ON audit_logs(action_type, timestamp DESC);
CREATE INDEX idx_audit_logs_session ON audit_logs(session_id, timestamp);

-- Prevent updates and deletes (append-only)
CREATE OR REPLACE FUNCTION prevent_audit_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Audit logs are append-only. Modifications not allowed.';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_logs_no_update_trigger
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_modification();
```

**Audit Logger Implementation**:
```python
# inference/chat_api/app/audit.py
import hashlib
import hmac
import json
from datetime import datetime
from typing import Any, Optional
import os

class AuditLogger:
    """Tamper-proof audit logging with HMAC signatures."""

    def __init__(self, db, signing_key: str):
        self.db = db
        self.signing_key = signing_key.encode()
        self._prev_hash: Optional[str] = None

    def _compute_signature(self, data: dict) -> str:
        """Compute HMAC-SHA256 signature for audit entry."""
        canonical = json.dumps(data, sort_keys=True, default=str)
        return hmac.new(
            self.signing_key,
            canonical.encode(),
            hashlib.sha256
        ).hexdigest()

    def _compute_hash(self, data: dict, signature: str) -> str:
        """Compute hash for chain integrity."""
        content = json.dumps(data, sort_keys=True, default=str) + signature
        return hashlib.sha256(content.encode()).hexdigest()

    async def log(
        self,
        user_id: str,
        user_role: str,
        action_type: str,
        action_name: str,
        action_input: Any = None,
        action_output: Any = None,
        success: bool = True,
        error_message: str = None,
        execution_time_ms: int = None,
        cost_tokens: int = 0,
        session_id: str = None,
        conversation_id: str = None,
    ) -> str:
        """Log an auditable action with tamper-proof signature."""

        timestamp = datetime.utcnow()

        # Build the data to sign
        data = {
            "timestamp": timestamp.isoformat(),
            "user_id": user_id,
            "user_role": user_role,
            "action_type": action_type,
            "action_name": action_name,
            "action_input": action_input,
            "action_output": action_output,
            "success": success,
            "error_message": error_message,
            "prev_hash": self._prev_hash,
        }

        # Compute signature
        signature = self._compute_signature(data)
        entry_hash = self._compute_hash(data, signature)

        # Insert into database
        audit_id = await self.db.execute(
            """
            INSERT INTO audit_logs (
                timestamp, user_id, user_role, action_type, action_name,
                action_input, action_output, success, error_message,
                execution_time_ms, cost_tokens, session_id, conversation_id,
                signature, prev_hash
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            RETURNING id
            """,
            timestamp, user_id, user_role, action_type, action_name,
            json.dumps(action_input), json.dumps(action_output),
            success, error_message, execution_time_ms, cost_tokens,
            session_id, conversation_id, signature, self._prev_hash
        )

        # Update chain
        self._prev_hash = entry_hash

        return audit_id

    async def verify_integrity(self, start_id: str = None) -> bool:
        """Verify audit log chain integrity."""
        entries = await self.db.fetch_all(
            "SELECT * FROM audit_logs ORDER BY timestamp ASC"
        )

        prev_hash = None
        for entry in entries:
            # Verify signature
            data = {
                "timestamp": entry["timestamp"].isoformat(),
                "user_id": entry["user_id"],
                "user_role": entry["user_role"],
                "action_type": entry["action_type"],
                "action_name": entry["action_name"],
                "action_input": json.loads(entry["action_input"]) if entry["action_input"] else None,
                "action_output": json.loads(entry["action_output"]) if entry["action_output"] else None,
                "success": entry["success"],
                "error_message": entry["error_message"],
                "prev_hash": entry["prev_hash"],
            }

            expected_sig = self._compute_signature(data)
            if entry["signature"] != expected_sig:
                return False

            # Verify chain
            if entry["prev_hash"] != prev_hash:
                return False

            prev_hash = self._compute_hash(data, entry["signature"])

        return True
```

### 4. WebSocket Streaming

**WebSocket Manager**:
```python
# inference/chat_api/app/websocket.py
from fastapi import WebSocket
from typing import Dict, Set
import asyncio
import json
import redis.asyncio as redis

class ConnectionManager:
    """Manages WebSocket connections with Redis pub/sub for scaling."""

    def __init__(self, redis_url: str):
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.redis = redis.from_url(redis_url)
        self.pubsub = self.redis.pubsub()

    async def connect(self, websocket: WebSocket, session_id: str):
        """Accept WebSocket and subscribe to session channel."""
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = set()
        self.active_connections[session_id].add(websocket)

        # Subscribe to Redis channel for this session
        await self.pubsub.subscribe(f"agent:session:{session_id}")

    async def disconnect(self, websocket: WebSocket, session_id: str):
        """Remove WebSocket connection."""
        if session_id in self.active_connections:
            self.active_connections[session_id].discard(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]
                await self.pubsub.unsubscribe(f"agent:session:{session_id}")

    async def broadcast_to_session(self, session_id: str, message: dict):
        """Broadcast message to all connections in a session via Redis."""
        await self.redis.publish(
            f"agent:session:{session_id}",
            json.dumps(message)
        )

    async def send_agent_event(
        self,
        session_id: str,
        event_type: str,
        data: dict
    ):
        """Send an agent execution event to the client."""
        message = {
            "type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "data": data,
        }
        await self.broadcast_to_session(session_id, message)


# Event types for agent execution visibility
class AgentEventType:
    STARTED = "agent.started"
    THINKING = "agent.thinking"
    TOOL_CALLING = "agent.tool.calling"
    TOOL_RESULT = "agent.tool.result"
    FILE_SEARCHING = "agent.file.searching"
    FILE_FOUND = "agent.file.found"
    CODE_EXECUTING = "agent.code.executing"
    CODE_RESULT = "agent.code.result"
    GITHUB_ACTION = "agent.github.action"
    CHECKPOINT = "agent.checkpoint"
    INTERRUPTED = "agent.interrupted"
    COMPLETED = "agent.completed"
    ERROR = "agent.error"
    COST_UPDATE = "agent.cost.update"
```

### 5. Composio Tools Integration

**Tool Configuration**:
```python
# inference/chat_api/app/tools/config.py
from composio import ComposioToolSet, App, Action
from typing import List

class ToolPermissions:
    """Tool access by role tier."""

    VIEWER_TOOLS = [
        Action.WEBSEARCH,
        Action.GITHUB_SEARCH_CODE,
        Action.GITHUB_SEARCH_REPOS,
        Action.GITHUB_GET_REPO,
        Action.GITHUB_GET_FILE,
    ]

    DEVELOPER_TOOLS = VIEWER_TOOLS + [
        # Same as viewer for now
    ]

    ELEVATED_DEV_TOOLS = DEVELOPER_TOOLS + [
        Action.GITHUB_CREATE_ISSUE,
        Action.GITHUB_CREATE_PR,
        Action.GITHUB_CREATE_BRANCH,
        Action.GITHUB_COMMIT_FILE,
        Action.CODE_EXECUTOR,  # Sandboxed
    ]

    ADMIN_TOOLS = ELEVATED_DEV_TOOLS + [
        Action.SHELL_EXECUTE,  # With approval
        Action.DOCKER_CONTAINER_LIST,
        Action.DOCKER_CONTAINER_LOGS,
        Action.DOCKER_CONTAINER_RESTART,
        Action.SYSTEM_INFO,
    ]

class AgentToolSet:
    """MCP-compatible tool set with role-based access."""

    def __init__(self):
        self.composio = ComposioToolSet()

    def get_tools_for_role(self, role: str) -> List:
        """Get available tools based on user role."""
        if role == "admin":
            actions = ToolPermissions.ADMIN_TOOLS
        elif role == "elevated-developer":
            actions = ToolPermissions.ELEVATED_DEV_TOOLS
        elif role == "developer":
            actions = ToolPermissions.DEVELOPER_TOOLS
        else:
            actions = ToolPermissions.VIEWER_TOOLS

        return self.composio.get_tools(actions=actions)

    async def execute_tool(
        self,
        tool_name: str,
        params: dict,
        user_id: str,
        user_role: str,
        github_token: str = None,
    ) -> dict:
        """Execute a tool with role validation."""
        # Validate access
        allowed = self.get_tools_for_role(user_role)
        if tool_name not in [t.name for t in allowed]:
            raise PermissionError(f"Tool {tool_name} not allowed for role {user_role}")

        # Set GitHub token if provided
        if github_token and tool_name.startswith("GITHUB"):
            self.composio.set_entity_id(user_id)
            self.composio.set_connection(
                app=App.GITHUB,
                connection_config={"access_token": github_token}
            )

        # Execute
        result = await self.composio.execute_action(
            action=tool_name,
            params=params,
        )

        return result
```

### 6. LangGraph Agent with Checkpointing

```python
# inference/chat_api/app/agent/executor.py
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.redis import RedisSaver
from typing import TypedDict, Annotated, List
from operator import add
import asyncio

class AgentState(TypedDict):
    """Agent execution state."""
    messages: Annotated[List[dict], add]
    user_id: str
    user_role: str
    session_id: str
    tools_used: List[str]
    cost_tokens: int
    current_step: str
    interrupted: bool
    error: str | None

class AgentExecutor:
    """LangGraph-based agent with checkpointing and real-time streaming."""

    def __init__(
        self,
        tools: AgentToolSet,
        model_router: ModelRouter,
        ws_manager: ConnectionManager,
        audit_logger: AuditLogger,
        redis_url: str,
    ):
        self.tools = tools
        self.model_router = model_router
        self.ws_manager = ws_manager
        self.audit = audit_logger
        self.checkpointer = RedisSaver.from_conn_string(redis_url)

        # Build the graph
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the agent execution graph."""
        graph = StateGraph(AgentState)

        # Add nodes
        graph.add_node("think", self._think_node)
        graph.add_node("execute_tool", self._tool_node)
        graph.add_node("generate_response", self._response_node)

        # Add edges
        graph.set_entry_point("think")
        graph.add_conditional_edges(
            "think",
            self._should_use_tool,
            {
                "use_tool": "execute_tool",
                "respond": "generate_response",
                "interrupt": END,
            }
        )
        graph.add_edge("execute_tool", "think")
        graph.add_edge("generate_response", END)

        return graph.compile(checkpointer=self.checkpointer)

    async def _think_node(self, state: AgentState) -> AgentState:
        """Determine next action."""
        # Emit event
        await self.ws_manager.send_agent_event(
            state["session_id"],
            AgentEventType.THINKING,
            {"step": "Analyzing request..."}
        )

        # Check for interrupt
        if state.get("interrupted"):
            return state

        # Use model to decide
        response = await self.model_router.generate(
            messages=state["messages"],
            tools=self.tools.get_tools_for_role(state["user_role"]),
        )

        state["current_step"] = "think"
        state["cost_tokens"] += response.usage.total_tokens

        # Emit cost update
        await self.ws_manager.send_agent_event(
            state["session_id"],
            AgentEventType.COST_UPDATE,
            {"tokens": state["cost_tokens"]}
        )

        return state

    async def _tool_node(self, state: AgentState) -> AgentState:
        """Execute a tool."""
        tool_call = state["messages"][-1].get("tool_calls", [{}])[0]

        # Emit event
        await self.ws_manager.send_agent_event(
            state["session_id"],
            AgentEventType.TOOL_CALLING,
            {"tool": tool_call.get("name"), "params": tool_call.get("arguments")}
        )

        try:
            # Execute tool
            result = await self.tools.execute_tool(
                tool_name=tool_call["name"],
                params=tool_call["arguments"],
                user_id=state["user_id"],
                user_role=state["user_role"],
            )

            # Log to audit
            await self.audit.log(
                user_id=state["user_id"],
                user_role=state["user_role"],
                action_type="tool_call",
                action_name=tool_call["name"],
                action_input=tool_call["arguments"],
                action_output=result,
                success=True,
                session_id=state["session_id"],
            )

            # Emit result
            await self.ws_manager.send_agent_event(
                state["session_id"],
                AgentEventType.TOOL_RESULT,
                {"tool": tool_call["name"], "result": result}
            )

            state["tools_used"].append(tool_call["name"])
            state["messages"].append({
                "role": "tool",
                "content": str(result),
                "tool_call_id": tool_call.get("id"),
            })

        except Exception as e:
            state["error"] = str(e)
            await self.audit.log(
                user_id=state["user_id"],
                user_role=state["user_role"],
                action_type="tool_call",
                action_name=tool_call["name"],
                action_input=tool_call["arguments"],
                success=False,
                error_message=str(e),
                session_id=state["session_id"],
            )

        return state

    async def run(
        self,
        user_id: str,
        user_role: str,
        session_id: str,
        messages: List[dict],
        thread_id: str = None,
    ) -> AsyncGenerator[dict, None]:
        """Run the agent with streaming events."""

        # Initialize state
        initial_state = AgentState(
            messages=messages,
            user_id=user_id,
            user_role=user_role,
            session_id=session_id,
            tools_used=[],
            cost_tokens=0,
            current_step="start",
            interrupted=False,
            error=None,
        )

        # Run with checkpointing
        config = {"configurable": {"thread_id": thread_id or session_id}}

        async for event in self.graph.astream(initial_state, config=config):
            yield event

    async def interrupt(self, thread_id: str):
        """Interrupt an in-progress execution."""
        # Get current state
        state = self.checkpointer.get(thread_id)
        if state:
            state["interrupted"] = True
            self.checkpointer.put(thread_id, state)

    async def resume(self, thread_id: str):
        """Resume from last checkpoint."""
        config = {"configurable": {"thread_id": thread_id}}
        async for event in self.graph.astream(None, config=config):
            yield event
```

### 7. Model Management System

```python
# inference/chat_api/app/models/manager.py
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List
import asyncio

@dataclass
class PendingModel:
    name: str
    size_gb: float
    requested_by: str
    requested_at: datetime
    expires_at: datetime
    approved: bool = False
    approved_by: Optional[str] = None

class ModelManager:
    """Manage Ollama models with quota and approval workflows."""

    QUOTA_PER_ELEVATED_DEV = 50  # GB
    PENDING_EXPIRY_DAYS = 7

    def __init__(self, db, ollama_client, notification_service):
        self.db = db
        self.ollama = ollama_client
        self.notify = notification_service

    async def request_model_pull(
        self,
        model_name: str,
        user_id: str,
        user_role: str,
    ) -> dict:
        """Request to pull a model (elevated dev or admin)."""

        if user_role not in ("elevated-developer", "admin"):
            raise PermissionError("Only elevated developers and admins can pull models")

        # Get model info
        model_info = await self.ollama.show(model_name)
        model_size_gb = model_info.get("size", 0) / (1024**3)

        # Check quota for elevated devs
        if user_role == "elevated-developer":
            current_pending = await self._get_user_pending_size(user_id)
            if current_pending + model_size_gb > self.QUOTA_PER_ELEVATED_DEV:
                raise ValueError(
                    f"Quota exceeded. Current: {current_pending:.1f}GB, "
                    f"Requested: {model_size_gb:.1f}GB, "
                    f"Limit: {self.QUOTA_PER_ELEVATED_DEV}GB"
                )

        # Check system resources
        system_usage = await self._get_system_model_usage()
        if system_usage + model_size_gb > self._max_model_storage():
            raise ValueError("System model storage limit would be exceeded")

        # Create pending entry
        expires_at = datetime.utcnow() + timedelta(days=self.PENDING_EXPIRY_DAYS)

        await self.db.execute(
            """
            INSERT INTO pending_models (name, size_gb, requested_by, requested_at, expires_at)
            VALUES ($1, $2, $3, $4, $5)
            """,
            model_name, model_size_gb, user_id, datetime.utcnow(), expires_at
        )

        # Notify admins
        await self.notify.send_approval_request(
            title=f"Model Pull Request: {model_name}",
            body=f"User {user_id} requests to pull {model_name} ({model_size_gb:.1f}GB). Expires in {self.PENDING_EXPIRY_DAYS} days.",
            action_url=f"/admin/models/pending",
        )

        # Start pulling in background (will be available when approved)
        if user_role == "admin":
            # Admins auto-approve
            await self._pull_model(model_name, user_id)
            return {"status": "pulling", "approved": True}

        return {
            "status": "pending_approval",
            "expires_at": expires_at.isoformat(),
            "size_gb": model_size_gb,
        }

    async def approve_model(
        self,
        model_name: str,
        admin_id: str,
    ):
        """Admin approves a pending model pull."""
        await self.db.execute(
            """
            UPDATE pending_models
            SET approved = true, approved_by = $1, approved_at = $2
            WHERE name = $3 AND approved = false
            """,
            admin_id, datetime.utcnow(), model_name
        )

        # Notify requester
        pending = await self.db.fetchone(
            "SELECT requested_by FROM pending_models WHERE name = $1",
            model_name
        )
        await self.notify.send_user_notification(
            user_id=pending["requested_by"],
            title=f"Model Approved: {model_name}",
            body=f"Your request to pull {model_name} has been approved.",
        )

    async def cleanup_expired(self):
        """Remove expired unapproved models (called by scheduler)."""
        expired = await self.db.fetch_all(
            """
            SELECT name FROM pending_models
            WHERE approved = false AND expires_at < $1
            """,
            datetime.utcnow()
        )

        for model in expired:
            try:
                await self.ollama.delete(model["name"])
            except:
                pass  # May not have been pulled yet

            await self.db.execute(
                "DELETE FROM pending_models WHERE name = $1",
                model["name"]
            )
```

---

## Implementation Phases

### Phase 1: Foundation (Week 1)
1. ✅ FusionAuth role updates (add elevated-developer)
2. ✅ Rate limit tier updates
3. ✅ Infisical setup
4. ✅ Kata Containers installation
5. ✅ Sandbox pool service

### Phase 2: Core Agent (Week 2)
6. ✅ Audit log system
7. ✅ WebSocket streaming
8. ✅ LangGraph agent framework
9. ✅ Composio tool integration

### Phase 3: GitHub & Models (Week 3)
10. ✅ GitHub OAuth linking
11. ✅ GitHub tools (issues, PRs)
12. ✅ Model management system
13. ✅ Admin approval workflows

### Phase 4: Admin Features (Week 4)
14. ✅ Host access tools (admin only)
15. ✅ Container management
16. ✅ Discord/Telegram notifications

### Phase 5: UI & Polish (Week 5)
17. ✅ Chat UI updates (real-time panel)
18. ✅ Grafana dashboards
19. ✅ Documentation
20. ✅ Testing

---

## Security Considerations

### Threat Model

| Threat | Mitigation |
|--------|------------|
| Token theft | Infisical encryption at rest, short-lived tokens |
| Sandbox escape | Kata VM isolation, no network in sandbox |
| Privilege escalation | Role checked at every tool call |
| Audit tampering | Append-only + HMAC + chain integrity |
| DoS via agent | Rate limits, queue separation, timeouts |
| Malicious model pulls | Quota limits, admin approval, auto-expiry |

### Admin Action Approval Flow

```
Admin requests sensitive action
         │
         ▼
┌─────────────────────┐
│ Cost/risk estimate  │
│ shown in UI         │
└─────────┬───────────┘
         │
         ▼
┌─────────────────────┐
│ "Are you sure?"     │
│ confirmation        │
└─────────┬───────────┘
         │
         ▼
┌─────────────────────┐
│ Preview changes     │
│ (diff view)         │
└─────────┬───────────┘
         │
         ▼
┌─────────────────────┐
│ Execute in sandbox  │
│ first (if possible) │
└─────────┬───────────┘
         │
         ▼
┌─────────────────────┐
│ Show result, offer  │
│ rollback option     │
└─────────────────────┘
```

---

## Monitoring & Observability

### Grafana Dashboards

1. **User Usage Dashboard**
   - Requests per user per day
   - Token consumption per user
   - Tool usage by user
   - Cost estimation per user

2. **Agent Performance Dashboard**
   - Average execution time
   - Tool call success rate
   - Checkpoint/resume frequency
   - Error rates by tool

3. **System Health Dashboard**
   - Sandbox pool utilization
   - Queue depths by tier
   - Model memory usage
   - API latency percentiles

### OpenTelemetry Integration

```python
# inference/chat_api/app/telemetry.py
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

def setup_telemetry():
    """Configure OpenTelemetry for distributed tracing."""
    provider = TracerProvider()
    processor = BatchSpanProcessor(
        OTLPSpanExporter(endpoint="http://localhost:4317")
    )
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    return trace.get_tracer("shml-chat-api")
```

---

## SMTP Configuration (Placeholder)

For email notifications via FusionAuth, configure SMTP:

```yaml
# In docker-compose environment or .env
SMTP_HOST: smtp.example.com  # TODO: Configure actual SMTP
SMTP_PORT: 587
SMTP_USER: notifications@shml-platform.local
SMTP_PASSWORD: ${SMTP_PASSWORD}
SMTP_FROM: "SHML Platform <notifications@shml-platform.local>"
SMTP_TLS: true
```

### SMTP Provider Options to Consider

| Provider | Self-Hosted | Cost | Pros | Cons |
|----------|-------------|------|------|------|
| **Mailcow** | ✅ Yes | Free | Full control, privacy | Complex setup |
| **Postal** | ✅ Yes | Free | Simple, lightweight | Limited features |
| **SendGrid** | ❌ Cloud | Free tier 100/day | Easy, reliable | Data leaves system |
| **AWS SES** | ❌ Cloud | $0.10/1000 | Cheap, scalable | AWS dependency |
| **Resend** | ❌ Cloud | Free tier 3000/mo | Modern API | Newer service |

**Recommendation**: Start with **Postal** (self-hosted) or **SendGrid free tier** for simplicity.

---

## Next Steps

1. Create feature branch: `feature/agentic-platform-v1`
2. Begin Phase 1 implementation
3. Set up CI/CD for new services
4. Create integration tests

---

*Document maintained by SHML Platform team. Last updated: 2025-12-05*
