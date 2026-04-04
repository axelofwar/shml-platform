import os

"""
Agent Service FastAPI Application.

Provides:
- ACE-based agentic workflows
- WebSocket streaming with approval workflow
- Session diary and reflection engine
- Multi-user playbook management
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)

UTC = timezone.utc
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from prometheus_client import make_asgi_app

from .agent import AgentState, build_ace_agent
from .analytics import (
    init_role_quotas,
    track_websocket_connection,
    track_websocket_message,
    track_workflow,
)
from .auth import AuthUser, UserRole, get_current_user, require_min_role
from .context import load_playbook_from_db, save_playbook_to_db, retrieve_ann_from_db
from .conversation_history import (
    load_history_for_context,
    save_turns_batch,
)
from .database import AsyncSessionLocal, engine, get_db
from .diary import ReflectionEngine, create_session_diary
from .hybrid_router import get_hybrid_router
from .openai_compat import OpenAIChatCompletionRequest, OpenAICompatibilityLayer
from .scheduler import scheduler
from .schemas import AgentRequest, AgentResponse, ReflectionRequest

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# WebSocket connections manager with TTL-based cleanup (memory leak prevention)
class ConnectionManager:
    # Maximum age (seconds) before a stale connection is reaped
    CONNECTION_TTL_SECONDS = 3600  # 1 hour

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self._connection_times: Dict[str, float] = {}  # session_id -> connect timestamp

    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[session_id] = websocket
        self._connection_times[session_id] = __import__("time").time()
        logger.info(
            f"WebSocket connected: {session_id} (active: {len(self.active_connections)})"
        )
        # Opportunistic cleanup of stale connections
        await self._cleanup_stale()

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]
            self._connection_times.pop(session_id, None)
            logger.info(
                f"WebSocket disconnected: {session_id} (active: {len(self.active_connections)})"
            )

    async def _cleanup_stale(self):
        """Remove connections that have exceeded TTL or are silently closed."""
        import time

        now = time.time()
        stale = []
        for sid, ws in list(self.active_connections.items()):
            connect_time = self._connection_times.get(sid, now)
            age = now - connect_time
            if age > self.CONNECTION_TTL_SECONDS:
                stale.append(sid)
                continue
            # Check if the WebSocket client_state indicates disconnection
            try:
                if (
                    hasattr(ws, "client_state")
                    and ws.client_state.name == "DISCONNECTED"
                ):
                    stale.append(sid)
            except Exception:
                pass
        for sid in stale:
            logger.warning(f"Cleaning up stale WebSocket: {sid}")
            self.active_connections.pop(sid, None)
            self._connection_times.pop(sid, None)
        if stale:
            logger.info(
                f"Cleaned {len(stale)} stale connections, {len(self.active_connections)} remain"
            )

    async def send_message(self, session_id: str, message: dict):
        if session_id in self.active_connections:
            try:
                await self.active_connections[session_id].send_json(message)
            except Exception as e:
                logger.error(f"Failed to send message: {e}")

    async def stream_stage(self, session_id: str, stage: str, content: str):
        """Stream a stage output (generator, reflector, curator)."""
        await self.send_message(
            session_id,
            {
                "type": "stage_output",
                "stage": stage,
                "content": content,
                "timestamp": datetime.now().isoformat(),
            },
        )

    async def request_approval(self, session_id: str, action: dict) -> bool:
        """Request human-in-loop approval for elevated actions."""
        await self.send_message(
            session_id,
            {
                "type": "approval_request",
                "action": action,
                "timestamp": datetime.now().isoformat(),
            },
        )

        # Wait for approval response (with timeout)
        try:
            websocket = self.active_connections.get(session_id)
            if not websocket:
                return False

            # Wait for approval message (5 min timeout)
            data = await asyncio.wait_for(websocket.receive_json(), timeout=300.0)

            if data.get("type") == "approval_response":
                return data.get("approved", False)

            return False
        except asyncio.TimeoutError:
            logger.warning(f"Approval timeout for session {session_id}")
            return False
        except Exception as e:
            logger.error(f"Approval request failed: {e}")
            return False


manager = ConnectionManager()


# Lifespan context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize services on startup."""
    logger.info("Starting Agent Service...")

    # Create database tables
    from .context import Base
    from .conversation_history import ConversationTurn
    from .diary import Base as DiaryBase

    async with engine.begin() as conn:
        # Ensure inference schema exists
        await conn.execute(
            __import__("sqlalchemy").text("CREATE SCHEMA IF NOT EXISTS inference")
        )
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(DiaryBase.metadata.create_all)
        await conn.run_sync(ConversationTurn.metadata.create_all)

    logger.info("Database tables created (including conversation_turns)")

    # Initialize role quotas for analytics
    init_role_quotas()
    logger.info("Role quotas initialized")

    # Start background scheduler (GEPA evolution, diary export, etc.)
    await scheduler.start()
    logger.info("Agent scheduler started")

    # Start autonomous agent loop (off by default; enable via AGENT_LOOP_ENABLED=true)
    from .agent_loop import get_agent_loop
    agent_loop = get_agent_loop()
    if agent_loop._config.enabled:
        await agent_loop.start()
        logger.info("Autonomous agent loop started (max_complexity=%.1f)", agent_loop._config.max_complexity)
    else:
        logger.info("Autonomous agent loop disabled (set AGENT_LOOP_ENABLED=true to enable)")

    yield

    logger.info("Shutting down Agent Service...")
    if agent_loop._config.enabled:
        await agent_loop.stop()
    await scheduler.stop()
    logger.info("Agent scheduler stopped")


# Create FastAPI app
app = FastAPI(
    title="Agent Service",
    description="ACE-based agentic workflows with session diary and reflection",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:8080",
    ).split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Prometheus metrics endpoint (uses default REGISTRY)
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "agent-service",
        "version": "0.1.0",
        "model": "Qwen3.5-35B-A3B (thinking enabled)",
        "scheduler": scheduler.status(),
    }


@app.get("/admin/scheduler")
async def scheduler_status(user: AuthUser = Depends(require_min_role(UserRole.ELEVATED_DEVELOPER))):
    """Return scheduler job status (elevated-developer / admin only)."""
    return scheduler.status()


@app.post("/admin/skills/evolve")
async def trigger_skill_evolution(
    background_tasks: BackgroundTasks,
    force: bool = False,
    user: AuthUser = Depends(require_min_role(UserRole.ELEVATED_DEVELOPER)),
):
    """Manually trigger a GEPA skill evolution cycle (elevated-developer / admin only).

    Args:
        force: If True, bypass the PATTERN_THRESHOLD minimum-lessons guard
               and run evolution regardless of accumulated lesson count.

    Returns a 202 Accepted immediately; evolution runs in the background.
    The scheduler's nightly job uses the same code path.
    """
    from .scheduler import _job_skill_evolution_nightly
    from .skill_evolution import get_evolution_engine

    async def _run_evolution() -> None:
        if force:
            # Skip threshold check — run regardless of lesson count
            engine = get_evolution_engine(
                base_url=os.environ.get("CODING_MODEL_URL", "http://qwopus-coding:8000")
            )
            session_id = f"manual_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
            results = await engine.process_lessons([], session_id=session_id)
            logger.info(
                f"[GEPA/manual] Forced evolution: {len(results)} skill update(s)"
            )
            if results:
                logger.info(engine.summarize_evolution_results(results))
        else:
            await _job_skill_evolution_nightly()

    background_tasks.add_task(_run_evolution)
    return {
        "status": "accepted",
        "message": "GEPA evolution cycle started in background",
        "force": force,
        "triggered_by": user.user_id,
    }


# ── Autonomous Agent Loop endpoints ──────────────────────────────────────────

@app.post("/admin/agent/loop/start")
async def start_agent_loop(
    max_complexity: float = None,
    user: AuthUser = Depends(require_min_role(UserRole.ELEVATED_DEVELOPER)),
):
    """Start the autonomous issue loop (elevated-developer / admin only)."""
    from .agent_loop import get_agent_loop
    loop = get_agent_loop()
    if max_complexity is not None:
        await loop.update_config(max_complexity=max_complexity)
    await loop.start()
    return {"status": "started", "loop": loop.status(), "started_by": user.user_id}


@app.post("/admin/agent/loop/pause")
async def pause_agent_loop(
    reason: str = "manual pause",
    user: AuthUser = Depends(require_min_role(UserRole.ELEVATED_DEVELOPER)),
):
    """Pause the autonomous issue loop between cycles."""
    from .agent_loop import get_agent_loop
    loop = get_agent_loop()
    await loop.pause(reason=reason)
    return {"status": "paused", "reason": reason, "paused_by": user.user_id}


@app.post("/admin/agent/loop/resume")
async def resume_agent_loop(
    user: AuthUser = Depends(require_min_role(UserRole.ELEVATED_DEVELOPER)),
):
    """Resume a paused autonomous issue loop."""
    from .agent_loop import get_agent_loop
    loop = get_agent_loop()
    await loop.resume()
    return {"status": "resumed", "loop": loop.status(), "resumed_by": user.user_id}


@app.post("/admin/agent/loop/stop")
async def stop_agent_loop(
    user: AuthUser = Depends(require_min_role(UserRole.ADMIN)),
):
    """Stop the autonomous issue loop (admin only)."""
    from .agent_loop import get_agent_loop
    loop = get_agent_loop()
    await loop.stop()
    return {"status": "stopped", "stopped_by": user.user_id}


@app.get("/admin/agent/loop/status")
async def agent_loop_status(
    user: AuthUser = Depends(require_min_role(UserRole.ELEVATED_DEVELOPER)),
):
    """Return current agent loop state and counters."""
    from .agent_loop import get_agent_loop
    loop = get_agent_loop()
    return loop.status()


@app.get("/user/me")
async def get_user_info(user: AuthUser = Depends(get_current_user)):
    """Get current user information and role-based configuration."""
    return {
        "user_id": user.user_id,
        "email": user.email,
        "preferred_username": user.preferred_username,
        "roles": user.roles,
        "primary_role": user.primary_role.value,
        "token_budget": {
            UserRole.VIEWER: 2048,
            UserRole.DEVELOPER: 4096,
            UserRole.ELEVATED_DEVELOPER: 8192,
            UserRole.ADMIN: 16384,
        }.get(user.primary_role, 4096),
    }


@app.get("/v1/models")
async def openai_list_models():
    """
    OpenAI-compatible model listing endpoint.
    Required by Obsidian Copilot, Cursor, Continue.dev and other IDE tools
    that enumerate available models before making completions requests.
    """
    import time
    models = [
        {
            "id": "shml-agent",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "shml-platform",
            "permission": [],
            "root": "shml-agent",
            "parent": None,
        },
        {
            "id": "qwen-coder",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "shml-platform",
            "permission": [],
            "root": "qwen-coder",
            "parent": None,
        },
    ]
    return {"object": "list", "data": models}


@app.post("/v1/chat/completions")
async def openai_chat_completions(request: dict):
    """
    OpenAI-compatible chat completions endpoint.

    Enables integration with Cursor, Continue.dev, and other IDE tools.

    Differences from ACE workflow:
    - Simple mode: No Generator/Reflector/Curator stages
    - No tool execution or approval workflow
    - Direct model inference only
    - Streaming via SSE (Server-Sent Events)

    Authentication:
    - Uses OAuth2-Proxy (credentials from cookies)
    - No API keys required

    Example (non-streaming):
        curl -X POST http://localhost/api/agent/v1/chat/completions \
          -H "Content-Type: application/json" \
          -d '{
            "model": "qwen-coder",
            "messages": [{"role": "user", "content": "Hello"}]
          }'

    Example (streaming):
        curl -X POST http://localhost/api/agent/v1/chat/completions \
          -H "Content-Type: application/json" \
          -d '{
            "model": "qwen-coder",
            "messages": [{"role": "user", "content": "Count to 5"}],
            "stream": true
          }'
    """
    try:
        # Parse request
        openai_request = OpenAIChatCompletionRequest(
            model=request.get("model", "qwen-coder"),
            messages=request.get("messages", []),
            temperature=request.get("temperature", 0.7),
            max_tokens=request.get("max_tokens"),
            stream=request.get("stream", False),
            top_p=request.get("top_p", 1.0),
            frequency_penalty=request.get("frequency_penalty", 0.0),
            presence_penalty=request.get("presence_penalty", 0.0),
            stop=request.get("stop"),
            n=request.get("n", 1),
            tools=request.get("tools"),
            tool_choice=request.get("tool_choice"),
        )

        # TODO: Extract user info from OAuth2-Proxy headers
        # For now, use placeholder
        user_id = "openai-user"
        user_roles = ["user"]

        # Initialize compatibility layer (model_client no longer needed;
        # routing handled internally via hybrid_router)
        compat_layer = OpenAICompatibilityLayer(model_client=None)

        # Handle streaming vs non-streaming
        if openai_request.stream:
            # Streaming response (SSE)
            async def stream_wrapper():
                async for chunk in compat_layer.generate_stream(
                    openai_request, user_id, user_roles
                ):
                    yield chunk

            return StreamingResponse(
                stream_wrapper(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )
        else:
            # Non-streaming response
            response = await compat_layer.generate_completion(
                openai_request, user_id, user_roles
            )
            return response.to_dict()

    except Exception as e:
        logger.error(f"OpenAI endpoint error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"OpenAI endpoint error: {str(e)}",
        )


@app.post("/api/v1/agent/execute", response_model=AgentResponse)
async def execute_agent(
    request: AgentRequest,
    db=Depends(get_db),
):
    """Execute agent workflow synchronously (non-streaming).

    Args:
        request: Agent request with task, user_id, category

    Returns:
        Complete agent response with all stages
    """
    start_time = datetime.now()

    try:
        # Load user's playbook
        playbook = await load_playbook_from_db(db, request.user_id)

        # Load conversation history for context
        history = await load_history_for_context(
            db, request.session_id, request.user_id
        )
        logger.info(
            f"Loaded {len(history)} history turns for session={request.session_id}"
        )

        # Route via hybrid router
        router = get_hybrid_router()
        routing = router.route(
            prompt=request.task,
            request_id=request.session_id,
        )
        logger.info(f"Routed to {routing.model_type.value}: {routing.reasoning}")

        # Persist the incoming user turn
        await save_turns_batch(
            db,
            request.session_id,
            request.user_id,
            [{"role": "user", "content": request.task}],
        )

        # ── Tier-0 nano fast-path (T8.4) ───────────────────────────────────
        # When shl-nano already generated a confident reply, return it directly
        # without spinning up the full ACE agent workflow.
        nano_reply = routing.parameters.get("_nano_reply")
        if nano_reply:
            logger.info(
                f"⚡ nano fast-path [{request.session_id}]: "
                f"skipping full agent workflow"
            )
            await save_turns_batch(
                db,
                request.session_id,
                request.user_id,
                [{"role": "assistant", "content": str(nano_reply)}],
            )
            await db.commit()
            execution_time_ms = int(
                (datetime.now() - start_time).total_seconds() * 1000
            )
            return AgentResponse(
                session_id=request.session_id,
                final_answer=str(nano_reply),
                generator_output=str(nano_reply),
                success=True,
                execution_time_ms=execution_time_ms,
                iterations=1,
                task_complete=True,
            )

        # Build agent workflow
        ace_agent = build_ace_agent()

        # Initialize state
        state: AgentState = {
            "messages": history,  # Inject conversation history
            "current_task": request.task,
            "task_category": request.category or "general",
            "user_id": request.user_id,
            "session_id": request.session_id,
            "playbook": playbook,
            "generator_output": None,
            "reflector_output": None,
            "reflector_rubric_scores": None,
            "curator_lessons": [],
            "tool_results": [],
            "tool_calls_pending": [],
            "session_diary": [],
            "generator_actions": [],
            "reflector_analyses": [],
            "start_time": start_time,
            "success": False,
            "error_messages": [],
            "final_answer": None,  # Synthesizer output
            "connection_manager": None,  # No WebSocket for sync execution
            "ws_session_id": None,
        }

        # Execute agent workflow
        logger.info(
            f"Executing agent for user={request.user_id}, task={request.task[:100]}"
        )
        final_state = await ace_agent.ainvoke(
            state, config={"configurable": {"thread_id": request.session_id}}
        )

        # Mark as successful if no errors
        final_state["success"] = len(final_state["error_messages"]) == 0

        # Calculate execution time
        execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        # Create session diary
        await create_session_diary(
            db_session=db,
            user_id=request.user_id,
            session_id=request.session_id,
            task_description=request.task,
            task_category=request.category or "general",
            generator_actions=final_state["generator_actions"],
            reflector_analyses=final_state["reflector_analyses"],
            curator_lessons=final_state["curator_lessons"],
            tool_results=final_state["tool_results"],
            success=final_state["success"],
            execution_time_ms=execution_time_ms,
            error_messages=(
                final_state["error_messages"] if final_state["error_messages"] else None
            ),
            context_bullets_used=len(playbook.bullets),
        )

        # Persist assistant response
        final_answer = (
            final_state.get("final_answer") or final_state.get("generator_output") or ""
        )
        if final_answer:
            await save_turns_batch(
                db,
                request.session_id,
                request.user_id,
                [{"role": "assistant", "content": str(final_answer)}],
            )
        await db.commit()

        # Save updated playbook
        await save_playbook_to_db(db, playbook)

        # Calculate quality metrics
        rubric_scores = final_state.get("reflector_rubric_scores", {})
        avg_quality = (
            sum(rubric_scores.values()) / len(rubric_scores) if rubric_scores else None
        )
        iteration_count = len(final_state.get("generator_actions", []))

        # Generate next actions from tool results
        next_actions = []
        from .skills import SKILLS, ShellSkill

        for tr in final_state.get("tool_results", []):
            skill_name = tr.get("tool", "")
            if skill_name == "ShellSkill":
                suggestion = ShellSkill.suggest_next_action(tr, request.task)
                if suggestion:
                    next_actions.append(suggestion)
            elif skill_name in SKILLS:
                skill_cls = SKILLS[skill_name]
                if hasattr(skill_cls, "suggest_next_action"):
                    suggestion = skill_cls.suggest_next_action(tr, request.task)
                    if suggestion:
                        next_actions.append(suggestion)

        # Determine if task is complete based on quality threshold
        QUALITY_THRESHOLD = 0.75
        task_complete = (
            final_state["success"]
            and (avg_quality is None or avg_quality >= QUALITY_THRESHOLD)
            and not any(
                na.get("type")
                in [
                    "install_dependency",
                    "permission_error",
                    "gpu_unavailable",
                    "docker_unavailable",
                ]
                for na in next_actions
            )
        )

        # Generate continue prompt if not complete
        continue_prompt = None
        if not task_complete and next_actions:
            # Use the first actionable suggestion
            for na in next_actions:
                if na.get("prompt"):
                    continue_prompt = na["prompt"]
                    break
        elif not task_complete:
            continue_prompt = "The response quality is below threshold. Would you like me to refine the answer?"

        # Return response
        return AgentResponse(
            session_id=request.session_id,
            final_answer=final_state.get(
                "final_answer"
            ),  # Primary user-facing response
            generator_output=final_state.get("generator_output"),
            reflector_output=final_state.get("reflector_output"),
            rubric_scores=final_state.get("reflector_rubric_scores"),
            curator_lessons=final_state.get("curator_lessons"),
            tool_results=final_state.get("tool_results"),
            success=final_state["success"],
            execution_time_ms=execution_time_ms,
            error_messages=(
                final_state["error_messages"] if final_state["error_messages"] else None
            ),
            # New interactive fields
            iterations=iteration_count,
            quality_score=avg_quality,
            next_actions=next_actions,
            task_complete=task_complete,
            continue_prompt=continue_prompt,
        )

    except Exception as e:
        logger.error(f"Agent execution failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent execution failed: {str(e)}",
        )


async def handle_agent_workflow(
    session_id: str,
    user_id: str,
    task: str,
    category: str,
    request_session_id: str,
    auth_user: Optional[AuthUser] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
):
    """Execute agent workflow and send results via WebSocket."""
    workflow_start = datetime.now()
    status = "success"

    try:
        # Load user's playbook
        async with AsyncSessionLocal() as db:
            playbook = await load_playbook_from_db(db, user_id)

            # Load conversation history for context
            history = await load_history_for_context(db, request_session_id, user_id)
            logger.info(
                f"Loaded {len(history)} history turns for session={request_session_id}"
            )

            # Route via hybrid router
            router = get_hybrid_router()
            routing = router.route(
                prompt=task,
                attachments=attachments,
                request_id=request_session_id,
            )
            logger.info(f"Routed to {routing.model_type.value}: {routing.reasoning}")

            # Persist incoming user turn
            await save_turns_batch(
                db,
                request_session_id,
                user_id,
                [{"role": "user", "content": task}],
            )

            # Build agent workflow
            ace_agent = build_ace_agent()

            # Initial state with WebSocket manager
            initial_state = {
                "messages": history,  # Inject conversation history
                "current_task": task,
                "task_category": category,
                "user_id": user_id,
                "session_id": request_session_id,
                "attachments": attachments or [],  # Multi-modal support
                "vision_context": None,
                "playbook": playbook,
                "playbook_bullets_count": len(playbook.bullets),
                "generator_output": None,
                "reflector_output": None,
                "reflector_rubric_scores": None,
                "curator_lessons": [],
                "tool_results": [],
                "tool_calls_pending": [],
                "session_diary": [],
                "generator_actions": [],
                "reflector_analyses": [],
                "start_time": datetime.now(),
                "success": True,
                "error_messages": [],
                "final_answer": None,  # Synthesizer output
                "connection_manager": manager,
                "ws_session_id": session_id,
            }

            # Execute agent workflow (streaming happens in nodes)
            final_state = await ace_agent.ainvoke(
                initial_state,
                config={"configurable": {"thread_id": request_session_id}},
            )

            # Calculate execution time
            execution_time_ms = int(
                (datetime.now() - final_state["start_time"]).total_seconds() * 1000
            )

            # Create session diary
            await create_session_diary(
                db_session=db,
                user_id=user_id,
                session_id=request_session_id,
                task_description=task,
                task_category=category,
                generator_actions=final_state["generator_actions"],
                reflector_analyses=final_state["reflector_analyses"],
                curator_lessons=final_state["curator_lessons"],
                tool_results=final_state["tool_results"],
                success=final_state["success"],
                execution_time_ms=execution_time_ms,
                error_messages=(
                    final_state["error_messages"]
                    if final_state["error_messages"]
                    else None
                ),
                context_bullets_used=len(playbook.bullets),
            )

            # Persist assistant response
            final_answer = (
                final_state.get("final_answer")
                or final_state.get("generator_output")
                or ""
            )
            if final_answer:
                await save_turns_batch(
                    db,
                    request_session_id,
                    user_id,
                    [{"role": "assistant", "content": str(final_answer)}],
                )

            await db.commit()

            # Save updated playbook
            await save_playbook_to_db(db, playbook)

            # Send completion message
            await manager.send_message(
                session_id,
                {
                    "type": "complete",
                    "stage": "complete",
                    "content": "Workflow completed successfully",
                    "session_id": session_id,
                    "success": final_state["success"],
                    "execution_time_ms": execution_time_ms,
                    "lessons_count": len(final_state["curator_lessons"]),
                },
            )

    except Exception as e:
        status = "error"
        logger.error(f"Workflow error: {e}", exc_info=True)
        await manager.send_message(session_id, {"type": "error", "error": str(e)})

    finally:
        # Track workflow execution
        if auth_user:
            duration = (datetime.now() - workflow_start).total_seconds()
            track_workflow(auth_user, duration, status)


@app.websocket("/ws/agent/{session_id}")
async def agent_websocket(
    websocket: WebSocket, session_id: str, user: AuthUser = Depends(get_current_user)
):
    """WebSocket endpoint for streaming agent execution with SOTA reliability patterns.

    RFC 6455 Compliant:
    - Automatic ping/pong keepalive (every 20s)
    - Connection health monitoring
    - Graceful degradation on errors

    Authentication:
    - Requires valid OAuth2-Proxy headers
    - Tracks connections by user role

    Handles:
    - Agent workflow execution (concurrent with message processing)
    - Heartbeat messages (responds with ACK)
    - Multiple requests per connection
    - Proxy-aware connection maintenance

    Streams:
    - Generator stage output
    - Reflector stage output
    - Curator stage output
    - Tool execution results
    - Approval requests (for elevated actions)
    """
    # Track WebSocket connection
    track_websocket_connection(user, connected=True)
    logger.info(
        f"WebSocket connected for user {user.email} (role: {user.primary_role.value})"
    )

    await manager.connect(session_id, websocket)
    workflow_task = None
    ping_task = None

    async def send_periodic_pings():
        """Background task: Send WebSocket pings every 20s per RFC 6455.

        This keeps the connection alive through proxies and load balancers.
        The client will automatically respond with pong.
        """
        try:
            while True:
                await asyncio.sleep(20)  # 20s interval (SOTA standard)
                try:
                    # Send ping frame (opcode 0x9)
                    await websocket.send_text(
                        json.dumps(
                            {"type": "ping", "timestamp": datetime.now().isoformat()}
                        )
                    )
                    logger.debug(f"Sent ping to {session_id}")
                except Exception as e:
                    logger.warning(f"Failed to send ping to {session_id}: {e}")
                    break
        except asyncio.CancelledError:
            logger.debug(f"Ping task cancelled for {session_id}")

    try:
        # Start background ping task (RFC 6455 keepalive)
        ping_task = asyncio.create_task(send_periodic_pings())

        # Message loop - handle agent requests and heartbeats
        while True:
            try:
                # Non-blocking receive with short timeout
                # This allows concurrent processing of workflow + heartbeats
                data = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=5.0,  # Short timeout for responsiveness
                )
            except asyncio.TimeoutError:
                # No message received - this is normal
                # Connection is kept alive by ping task
                continue

            msg_type = data.get("type")

            # Handle heartbeat (client-initiated)
            if msg_type == "heartbeat":
                logger.debug(f"Received heartbeat from {session_id}, sending ACK")
                await manager.send_message(
                    session_id,
                    {
                        "type": "ack",
                        "timestamp": datetime.now().isoformat(),
                    },
                )
                continue

            # Handle pong response (from client ping)
            if msg_type == "pong":
                logger.debug(f"Received pong from {session_id}")
                continue

            # Handle agent request
            if msg_type == "agent_request":
                # Track incoming message
                track_websocket_message(user, "received")

                user_id = data.get("user_id")
                task = data.get("task")
                category = data.get("category", "general")
                request_session_id = data.get("session_id", session_id)
                attachments = data.get("attachments", [])  # Multi-modal support

                # Log attachments if present
                if attachments:
                    logger.info(
                        f"📎 Received {len(attachments)} attachments: {[a.get('filename') for a in attachments]}"
                    )

                if not user_id or not task:
                    await manager.send_message(
                        session_id,
                        {"type": "error", "error": "Missing user_id or task"},
                    )
                    track_websocket_message(user, "sent")
                    continue

                # If a workflow is already running, reject the request
                if workflow_task and not workflow_task.done():
                    await manager.send_message(
                        session_id,
                        {"type": "error", "error": "Workflow already in progress"},
                    )
                    track_websocket_message(user, "sent")
                    continue

                # Start workflow in background (non-blocking)
                workflow_task = asyncio.create_task(
                    handle_agent_workflow(
                        session_id,
                        user_id,
                        task,
                        category,
                        request_session_id,
                        user,
                        attachments,
                    )
                )
                continue

            # Unknown message type
            logger.warning(f"Unknown message type: {msg_type}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id} (user: {user.email})")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        try:
            await manager.send_message(session_id, {"type": "error", "error": str(e)})
        except Exception:
            pass  # Connection already closed
    finally:
        # Track disconnection
        track_websocket_connection(user, connected=False)

        # Cancel background tasks
        if ping_task and not ping_task.done():
            ping_task.cancel()
        if workflow_task and not workflow_task.done():
            workflow_task.cancel()
        manager.disconnect(session_id)


@app.websocket("/ws/test/{session_id}")
async def test_websocket(websocket: WebSocket, session_id: str):
    """Simple WebSocket test endpoint for development.

    Echoes back any messages received and responds to heartbeats.
    No authentication, no agent execution - just for testing the connection.
    """
    await websocket.accept()
    logger.info(f"Test WebSocket connected: {session_id}")

    try:
        # Send welcome message
        await websocket.send_json(
            {
                "type": "welcome",
                "session_id": session_id,
                "message": "Test WebSocket connected successfully!",
                "timestamp": datetime.now().isoformat(),
            }
        )

        # Echo loop
        while True:
            data = await websocket.receive_json()
            logger.info(f"Test WebSocket received: {data}")

            # Echo back with ack
            await websocket.send_json(
                {
                    "type": "ack",
                    "received": data,
                    "timestamp": datetime.now().isoformat(),
                }
            )

    except WebSocketDisconnect:
        logger.info(f"Test WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.error(f"Test WebSocket error: {e}", exc_info=True)


@app.post("/api/v1/reflection/analyze")
async def analyze_reflection(
    request: ReflectionRequest,
    db=Depends(get_db),
):
    """Analyze session patterns and generate recommendations.

    Args:
        request: Reflection request with user_id and last_n sessions

    Returns:
        Analysis with patterns, recommendations, and statistics
    """
    try:
        engine_instance = ReflectionEngine(db)

        # Import call_coding_model for LLM analysis
        from .agent import call_coding_model

        analysis = await engine_instance.analyze_session_patterns(
            user_id=request.user_id,
            last_n=request.last_n or 10,
            model_callable=call_coding_model,
        )

        # Optionally update playbook with recommendations
        if request.update_playbook:
            playbook = await load_playbook_from_db(db, request.user_id)
            await engine_instance.update_playbook_from_reflection(analysis, playbook)
            await save_playbook_to_db(db, playbook)

        return analysis

    except Exception as e:
        logger.error(f"Reflection analysis failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reflection analysis failed: {str(e)}",
        )


@app.get("/api/v1/playbook/{user_id}/summary")
async def get_playbook_summary(
    user_id: str,
    db=Depends(get_db),
):
    """Get playbook summary for a user.

    Args:
        user_id: User identifier

    Returns:
        Playbook statistics and category breakdown
    """
    try:
        playbook = await load_playbook_from_db(db, user_id)
        return playbook.get_summary()

    except Exception as e:
        logger.error(f"Failed to get playbook summary: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get playbook summary: {str(e)}",
        )


@app.post("/api/v1/playbook/{user_id}/feedback")
async def update_bullet_feedback(
    user_id: str,
    bullet_id: str,
    helpful: bool,
    db=Depends(get_db),
):
    """Update helpful/harmful feedback for a context bullet.

    Args:
        user_id: User identifier
        bullet_id: Bullet identifier
        helpful: True if helpful, False if harmful

    Returns:
        Success message
    """
    try:
        playbook = await load_playbook_from_db(db, user_id)
        playbook.update_feedback(bullet_id, helpful)
        await save_playbook_to_db(db, playbook)

        return {
            "status": "success",
            "message": f"Feedback updated for bullet {bullet_id}",
        }

    except Exception as e:
        logger.error(f"Failed to update feedback: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update feedback: {str(e)}",
        )


# ============================================================================
# MCP (Model Context Protocol) Endpoints for OpenCode Integration
# ============================================================================
#
# These endpoints expose SHML platform capabilities as MCP tools:
# - training_status: Get Ray job status and metrics
# - gpu_status: Check GPU VRAM usage and processes
# - mlflow_query: Query MLflow experiments and runs
# - vision_analyze: Analyze images with Qwen3-VL (RTX 2070)
#
# ⚠️ TRAINING SAFETY: Code generation tools are DISABLED while RTX 3090 is busy
#
# Reference: https://opencode.ai/docs/mcp-servers
# ============================================================================

from .mcp import mcp_server


@app.post("/api/v1/routing/preview")
async def preview_routing(request: dict):
    """Preview routing decision without executing.

    Useful for debugging and testing routing logic.
    """
    router = get_hybrid_router()
    prompt = request.get("prompt", "")
    attachments = request.get("attachments")
    selection = router.route(prompt, attachments, request_id="preview")
    return {
        "model_type": selection.model_type.value,
        "model_name": selection.model_name,
        "reasoning": selection.reasoning,
        "gpu": selection.gpu,
        "confidence": selection.confidence,
    }


@app.get("/api/v1/sessions/{session_id}/history")
async def get_session_history(
    session_id: str,
    limit: int = 20,
    db=Depends(get_db),
):
    """Get conversation history for a session.

    Backward-compatible: returns standard message format.
    """
    from .conversation_history import load_history

    messages = await load_history(db, session_id, limit=limit)
    return {"session_id": session_id, "messages": messages, "count": len(messages)}


@app.get("/mcp/health")
async def mcp_health():
    """MCP server health check with training status."""
    info = await mcp_server.get_server_info()
    return {
        "status": "healthy",
        "server": info.name,
        "version": info.version,
        "tools_count": info.tools_count,
        "training_active": info.training_active,
        "gpu_status": info.gpu_status,
        "warning": (
            "RTX 3090 busy with training - code generation blocked"
            if info.training_active
            else None
        ),
    }


@app.get("/mcp/tools")
async def mcp_list_tools():
    """
    List available MCP tools.

    Returns tool definitions in MCP format for OpenCode integration.

    Example opencode.json config:
    ```json
    {
      "mcp": {
        "shml-platform": {
          "type": "remote",
          "url": "http://localhost:8000/mcp",
          "timeout": 120
        }
      }
    }
    ```
    """
    info = await mcp_server.get_server_info()
    return {
        "tools": mcp_server.get_tools(),
        "server": {
            "name": info.name,
            "version": info.version,
            "training_active": info.training_active,
        },
    }


@app.post("/mcp/tools/{tool_name}/call")
async def mcp_call_tool(tool_name: str, arguments: dict = None):
    """
    Execute an MCP tool.

    Args:
        tool_name: Name of the tool (e.g., "training_status", "gpu_status")
        arguments: Tool arguments as JSON body

    Returns:
        Tool execution result

    Example:
        curl -X POST http://localhost:8000/mcp/tools/training_status/call \
          -H "Content-Type: application/json" \
          -d '{"job_id": "latest"}'

    Available tools:
        - training_status: Get Ray job status (safe during training)
        - gpu_status: Get GPU VRAM usage (safe during training)
        - mlflow_query: Query MLflow experiments (safe during training)
        - vision_analyze: Analyze image with Qwen3-VL (safe, uses RTX 2070)
        - vision_then_code: Vision + code gen (BLOCKED during training - needs RTX 3090)
    """
    if arguments is None:
        arguments = {}

    result = await mcp_server.call_tool(tool_name, arguments)

    if not result.success:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
                if "Unknown tool" in str(result.error)
                else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=result.error,
        )

    return {
        "success": result.success,
        "result": result.result,
        "execution_time_ms": result.execution_time_ms,
    }


@app.get("/mcp/tools/{tool_name}")
async def mcp_get_tool_info(tool_name: str):
    """Get information about a specific MCP tool."""
    tools = mcp_server.get_tools()
    tool = next((t for t in tools if t["name"] == tool_name), None)

    if not tool:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tool '{tool_name}' not found. Available: {[t['name'] for t in tools]}",
        )

    return tool


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
