"""
Usage Analytics and Metrics

Tracks API usage per user/role for:
- Request counts
- Token usage
- Response times
- Error rates
- Resource usage

Exports to Prometheus for Grafana dashboards.
"""

from prometheus_client import Counter, Histogram, Gauge, Info
from typing import Optional
import time
import logging
from contextlib import contextmanager

from .auth import AuthUser, UserRole

logger = logging.getLogger(__name__)

# ============================================================================
# Prometheus Metrics
# ============================================================================

# Request metrics
request_count = Counter(
    "agent_requests_total",
    "Total agent API requests",
    ["endpoint", "method", "role", "status_code"],
)

request_duration = Histogram(
    "agent_request_duration_seconds",
    "Agent API request duration",
    ["endpoint", "method", "role"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
)

# Token usage metrics
tokens_used = Counter(
    "agent_tokens_total",
    "Total tokens consumed",
    ["user_id", "role", "model", "endpoint"],
)

token_budget_usage = Gauge(
    "agent_token_budget_usage",
    "Current token budget usage percentage",
    ["user_id", "role"],
)

# WebSocket metrics
websocket_connections = Gauge(
    "agent_websocket_connections", "Current WebSocket connections", ["role"]
)

websocket_messages = Counter(
    "agent_websocket_messages_total",
    "Total WebSocket messages",
    ["role", "message_type"],
)

# Workflow metrics
workflow_executions = Counter(
    "agent_workflow_executions_total",
    "Total workflow executions",
    ["user_id", "role", "status"],
)

workflow_duration = Histogram(
    "agent_workflow_duration_seconds",
    "Workflow execution duration",
    ["role", "status"],
    buckets=[1.0, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0, 300.0],
)

workflow_stage_duration = Histogram(
    "agent_workflow_stage_duration_seconds",
    "Duration per workflow stage",
    ["role", "stage"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0],
)

# Tool execution metrics
tool_executions = Counter(
    "agent_tool_executions_total",
    "Total tool executions",
    ["tool_name", "role", "status"],
)

tool_duration = Histogram(
    "agent_tool_duration_seconds",
    "Tool execution duration",
    ["tool_name", "role"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# Error metrics
errors_total = Counter(
    "agent_errors_total", "Total errors by type", ["error_type", "endpoint", "role"]
)

# User session metrics
active_sessions = Gauge(
    "agent_active_sessions", "Current active user sessions", ["role"]
)

session_duration = Histogram(
    "agent_session_duration_seconds",
    "User session duration",
    ["role"],
    buckets=[60.0, 300.0, 600.0, 1800.0, 3600.0, 7200.0],
)

# Role-based quota metrics
role_quota_limit = Gauge(
    "agent_role_quota_limit", "Token quota limit per role", ["role"]
)

role_quota_used = Gauge(
    "agent_role_quota_used", "Token quota used per role per day", ["role", "date"]
)


# ============================================================================
# Analytics Functions
# ============================================================================


class RequestAnalytics:
    """Track analytics for a single request."""

    def __init__(
        self,
        endpoint: str,
        method: str,
        user: Optional[AuthUser] = None,
    ):
        self.endpoint = endpoint
        self.method = method
        self.user = user
        self.role = user.primary_role.value if user else "anonymous"
        self.start_time = time.time()

    def record_response(self, status_code: int):
        """Record request completion."""
        duration = time.time() - self.start_time

        # Update metrics
        request_count.labels(
            endpoint=self.endpoint,
            method=self.method,
            role=self.role,
            status_code=status_code,
        ).inc()

        request_duration.labels(
            endpoint=self.endpoint, method=self.method, role=self.role
        ).observe(duration)

        logger.debug(
            f"Request analytics: {self.method} {self.endpoint} - {status_code} - {duration:.2f}s - role={self.role}"
        )

    def record_error(self, error_type: str):
        """Record error occurrence."""
        errors_total.labels(
            error_type=error_type, endpoint=self.endpoint, role=self.role
        ).inc()


@contextmanager
def track_request(endpoint: str, method: str, user: Optional[AuthUser] = None):
    """Context manager to track request analytics."""
    analytics = RequestAnalytics(endpoint, method, user)
    try:
        yield analytics
        analytics.record_response(200)
    except Exception as e:
        analytics.record_error(type(e).__name__)
        analytics.record_response(500)
        raise


def track_tokens(
    user: AuthUser,
    tokens: int,
    model: str,
    endpoint: str,
):
    """Track token usage for a user."""
    tokens_used.labels(
        user_id=user.user_id,
        role=user.primary_role.value,
        model=model,
        endpoint=endpoint,
    ).inc(tokens)

    logger.debug(f"Token usage: {user.email} used {tokens} tokens on {endpoint}")


def track_workflow(
    user: AuthUser,
    duration_seconds: float,
    status: str,  # "success", "error", "cancelled"
):
    """Track workflow execution."""
    role = user.primary_role.value

    workflow_executions.labels(user_id=user.user_id, role=role, status=status).inc()

    workflow_duration.labels(role=role, status=status).observe(duration_seconds)


def track_workflow_stage(
    user: AuthUser,
    stage: str,  # "generator", "reflector", "curator", "tools"
    duration_seconds: float,
):
    """Track individual workflow stage duration."""
    workflow_stage_duration.labels(role=user.primary_role.value, stage=stage).observe(
        duration_seconds
    )


def track_tool_execution(
    user: AuthUser,
    tool_name: str,
    duration_seconds: float,
    status: str,  # "success", "error"
):
    """Track tool execution."""
    role = user.primary_role.value

    tool_executions.labels(tool_name=tool_name, role=role, status=status).inc()

    tool_duration.labels(tool_name=tool_name, role=role).observe(duration_seconds)


def track_websocket_connection(user: AuthUser, connected: bool):
    """Track WebSocket connection state."""
    role = user.primary_role.value
    if connected:
        websocket_connections.labels(role=role).inc()
    else:
        websocket_connections.labels(role=role).dec()


def track_websocket_message(user: AuthUser, message_type: str):
    """Track WebSocket message."""
    websocket_messages.labels(
        role=user.primary_role.value, message_type=message_type
    ).inc()


def update_token_budget(user: AuthUser, used_percentage: float):
    """Update token budget gauge for monitoring."""
    token_budget_usage.labels(user_id=user.user_id, role=user.primary_role.value).set(
        used_percentage
    )


def init_role_quotas():
    """Initialize role quota limits (called at startup)."""
    from .config import settings

    # Token quotas per role per day (example values)
    quotas = {
        UserRole.VIEWER.value: 10_000,  # 10k tokens/day
        UserRole.DEVELOPER.value: 50_000,  # 50k tokens/day
        UserRole.ELEVATED_DEVELOPER.value: 200_000,  # 200k tokens/day
        UserRole.ADMIN.value: 1_000_000,  # 1M tokens/day
    }

    for role, limit in quotas.items():
        role_quota_limit.labels(role=role).set(limit)

    logger.info(f"Initialized role quotas: {quotas}")


# Export metrics endpoint data
def get_user_analytics(user: AuthUser) -> dict:
    """Get analytics summary for a user (for API response)."""
    return {
        "user_id": user.user_id,
        "email": user.email,
        "role": user.primary_role.value,
        "roles": user.roles,
        "token_quota": {
            "viewer": 10_000,
            "developer": 50_000,
            "elevated_developer": 200_000,
            "admin": 1_000_000,
        }.get(user.primary_role.value, 50_000),
    }
