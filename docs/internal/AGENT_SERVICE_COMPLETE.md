# Agent Service - Complete Documentation

**ACE-Based Agentic Platform - Comprehensive Guide**

**Status:** ✅ Production Ready  
**Last Updated:** January 11, 2025  
**Version:** 1.0.0

---

## Table of Contents

1. [Quick Start](#-quick-start)
2. [Architecture Overview](#-architecture-overview)
3. [API Reference](#-api-reference)
4. [Skills System](#-skills-system)
5. [WebSocket Integration](#-websocket-integration)
6. [Implementation Details](#-implementation-details)
7. [Recommended Skills](#-recommended-skills)
8. [Development Notes](#-development-notes)

---

## 🚀 Quick Start

### Start Agent Service
```bash
cd inference/agent-service
python -m app.main
# Runs on http://localhost:8000
```

### Health Check
```bash
curl http://localhost:8000/health
```

### Execute Agent (REST)
```bash
curl -X POST http://localhost:8000/api/v1/agent/execute \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-123",
    "session_id": "session-abc",
    "task": "Create a GitHub issue for bug in authentication",
    "category": "coding"
  }'
```

### WebSocket Connection
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/agent/session-abc');

ws.onopen = () => {
  ws.send(JSON.stringify({
    type: 'agent_request',
    user_id: 'user-123',
    task: 'Analyze this code for bugs',
    category: 'debugging'
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  switch(data.type) {
    case 'stage_output':
      console.log(`[${data.stage}] ${data.content}`);
      break;
    case 'approval_request':
      ws.send(JSON.stringify({
        type: 'approval_response',
        approved: true
      }));
      break;
    case 'complete':
      console.log('Agent execution complete');
      break;
  }
};
```

---

## 🏗️ Architecture Overview

### ACE Pattern Workflow

```
User Task
    ↓
Generator (retrieve context + propose action)
    ↓
[Optional] Tools (execute GitHub/Sandbox/Ray)
    ↓
Reflector (self-critique with 4 rubrics)
    ↓
[Loop if scores <0.7, max 3 iterations]
    ↓
Curator (extract lessons learned)
    ↓
Session Diary + Playbook Update
```

### Key Components

| Component | File | Description |
|-----------|------|-------------|
| AgentPlaybook | `context.py` | 1000 context bullets, semantic retrieval |
| G-R-C Workflow | `agent.py` | LangGraph StateGraph implementation |
| Session Diary | `diary.py` | PostgreSQL persistence, JSONB columns |
| Reflection Engine | `diary.py` | Pattern analysis across sessions |
| Composable Skills | `skills.py` | GitHub, Sandbox, Ray, WebSearch |

### Database Integration

```python
# Async engine with connection pooling
engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True
)
```

### Implementation Statistics

- **Lines Written:** ~3,000 lines
- **Core Files:** 8 implementation files
- **Skills:** 4 composable skills (extensible)
- **Test Coverage:** Comprehensive test suite

---

## 📡 API Reference

### REST Endpoints

#### Execute Agent
```http
POST /api/v1/agent/execute
Content-Type: application/json

{
  "user_id": "string",
  "session_id": "string",
  "task": "string",
  "category": "coding" | "debugging" | "research" | "general"
}
```

#### Analyze Session Patterns
```http
POST /api/v1/reflection/analyze
Content-Type: application/json

{
  "user_id": "string",
  "last_n": 10,
  "update_playbook": true
}
```

#### Get Playbook Summary
```http
GET /api/v1/playbook/{user_id}/summary
```

#### Update Bullet Feedback
```http
POST /api/v1/playbook/{user_id}/feedback
Content-Type: application/json

{
  "bullet_id": "string",
  "helpful": true
}
```

### OpenAI-Compatible Endpoint

```http
POST /v1/chat/completions
Content-Type: application/json

{
  "model": "ace-agent",
  "messages": [
    {"role": "user", "content": "Your task here"}
  ],
  "stream": true
}
```

### WebSocket Protocol

**Endpoint:** `ws://localhost:8000/ws/agent/{session_id}`

**Client → Server Messages:**
```json
{
  "type": "agent_request",
  "user_id": "user-123",
  "task": "Your task",
  "category": "coding"
}
```

```json
{
  "type": "approval_response",
  "approved": true
}
```

**Server → Client Messages:**
```json
{
  "type": "stage_output",
  "stage": "generator" | "reflector" | "curator",
  "content": "Stage output text"
}
```

```json
{
  "type": "tool_execution",
  "tool": "github_search",
  "status": "running" | "success" | "error",
  "result": {...}
}
```

```json
{
  "type": "approval_request",
  "tool": "sandbox_execute",
  "code": "print('hello')",
  "timeout_seconds": 30
}
```

```json
{
  "type": "complete",
  "session_id": "string",
  "duration_ms": 1234
}
```

---

## 🔧 Skills System

### Current Skills

| Skill | Triggers | Description |
|-------|----------|-------------|
| GitHubSkill | github, repo, issue, pr | GitHub API operations |
| SandboxSkill | execute, run, code | Docker sandbox execution |
| RayJobSkill | ray, training, distributed | Ray cluster job submission |
| WebSearchSkill | search, find, lookup | DuckDuckGo web search |

### Adding a New Skill

```python
# inference/agent-service/app/skills.py

class MyCustomSkill(Skill):
    """Description of what this skill does."""

    ACTIVATION_TRIGGERS = [
        "keyword1", "keyword2", "keyword3"
    ]

    @classmethod
    def get_context(cls, user_task: str) -> str:
        if not cls.is_activated(user_task):
            return ""

        return """# MyCustom Skill

**Available Operations:**
- operation1: Description
- operation2: Description

**Usage:**
```python
await MyCustomSkill.execute("operation1", {...})
```
"""

    @classmethod
    async def execute(cls, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the skill operation."""
        try:
            if operation == "operation1":
                # Implementation
                return {"success": True, "result": ...}
            else:
                return {"error": f"Unknown operation: {operation}"}
        except Exception as e:
            return {"error": str(e)}
```

### Registration

```python
# Add to skills.py SKILL_REGISTRY
SKILL_REGISTRY = [
    GitHubSkill,
    SandboxSkill,
    RayJobSkill,
    WebSearchSkill,
    MyCustomSkill,  # Add new skill
]
```

---

## 🌐 WebSocket Integration

### React Hook Example

```typescript
// chat-ui-v2/src/hooks/useAgentWebSocket.ts
import useWebSocket from 'react-use-websocket';

export function useAgentWebSocket(sessionId: string) {
  const { sendJsonMessage, lastJsonMessage, readyState } = useWebSocket(
    `ws://localhost:8000/ws/agent/${sessionId}`,
    {
      shouldReconnect: () => true,
      reconnectAttempts: 10,
      reconnectInterval: 3000,
    }
  );

  const executeTask = (task: string, userId: string) => {
    sendJsonMessage({
      type: 'agent_request',
      user_id: userId,
      task,
      category: 'coding',
    });
  };

  const approveAction = (approved: boolean) => {
    sendJsonMessage({
      type: 'approval_response',
      approved,
    });
  };

  return {
    executeTask,
    approveAction,
    lastMessage: lastJsonMessage,
    isConnected: readyState === WebSocket.OPEN,
  };
}
```

### Message Handling

```typescript
// Handle incoming messages
useEffect(() => {
  if (!lastMessage) return;

  switch (lastMessage.type) {
    case 'stage_output':
      addStageOutput(lastMessage.stage, lastMessage.content);
      break;
    case 'tool_execution':
      updateToolStatus(lastMessage.tool, lastMessage.status);
      break;
    case 'approval_request':
      showApprovalDialog(lastMessage);
      break;
    case 'complete':
      finishExecution(lastMessage.duration_ms);
      break;
  }
}, [lastMessage]);
```

---

## 🔍 Implementation Details

### Context Bullet System

```python
@dataclass
class ContextBullet:
    id: str
    content: str
    category: str  # generator, reflector, curator, tool_result
    embedding: List[float]
    rubric_scores: Dict[str, float]
    helpful_count: int = 0
    harmful_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
```

### Rubric Evaluation (Kimi K2-style)

The Reflector evaluates Generator output on 4 dimensions:

1. **Clarity** (0.0-1.0): Is the response clear and well-structured?
2. **Accuracy** (0.0-1.0): Is the information correct?
3. **Safety** (0.0-1.0): Does it avoid harmful actions?
4. **Actionability** (0.0-1.0): Can the user act on this?

If average score < 0.7, the Generator loops (max 3 iterations).

### Session Diary Structure

```python
class SessionDiary(Base):
    __tablename__ = "session_diaries"

    id = Column(String, primary_key=True)
    user_id = Column(String, index=True)
    session_id = Column(String, index=True)
    task_description = Column(Text)
    task_category = Column(String)

    # JSONB columns for structured data
    generator_actions = Column(JSONB, default=[])
    reflector_analyses = Column(JSONB, default=[])
    curator_lessons = Column(JSONB, default=[])
    tool_results = Column(JSONB, default=[])
    user_feedback = Column(JSONB, default={})

    # Metadata
    execution_time_ms = Column(Integer)
    success = Column(Boolean)
    error_message = Column(Text)

    # Integrity
    hmac_signature = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
```

### Reflection Engine

```python
async def analyze_sessions(
    user_id: str,
    last_n: int = 10,
    update_playbook: bool = True
) -> Dict[str, Any]:
    """Analyze recent sessions for patterns."""

    sessions = await get_recent_sessions(user_id, last_n)

    patterns = {
        "repeated_errors": find_repeated_errors(sessions),
        "successful_strategies": find_success_patterns(sessions),
        "common_tools": count_tool_usage(sessions),
        "avg_iterations": calculate_avg_iterations(sessions),
    }

    if update_playbook:
        # Add recommendations to playbook
        await update_playbook_with_patterns(user_id, patterns)

    return patterns
```

---

## 📚 Recommended Skills (Future)

### Tier 1: Platform Core

| Skill | Priority | Complexity |
|-------|----------|------------|
| MLflowSkill | ⭐⭐⭐ | Medium |
| TraefikSkill | ⭐⭐⭐ | Low |
| DockerSkill | ⭐⭐⭐ | Medium |

### Tier 2: Developer Productivity

| Skill | Priority | Complexity |
|-------|----------|------------|
| PrometheusSkill | ⭐⭐ | Low |
| ImageProcessingSkill | ⭐⭐ | High |
| DocumentationSkill | ⭐⭐ | Medium |

### MLflowSkill Example

```python
class MLflowSkill(Skill):
    """MLflow experiment tracking and model registry."""

    ACTIVATION_TRIGGERS = [
        "mlflow", "experiment", "model", "artifact", "metric",
        "log", "track", "register", "deploy", "version"
    ]

    @classmethod
    async def execute(cls, operation: str, params: Dict) -> Dict:
        import mlflow
        client = MlflowClient()

        if operation == "create_experiment":
            exp_id = client.create_experiment(params["name"])
            return {"experiment_id": exp_id}

        elif operation == "log_metrics":
            client.log_metrics(params["run_id"], params["metrics"])
            return {"success": True}

        elif operation == "register_model":
            result = mlflow.register_model(
                f"runs:/{params['run_id']}/model",
                params["model_name"]
            )
            return {"name": result.name, "version": result.version}
```

---

## 📝 Development Notes

### Known Limitations

1. **Checkpointing Disabled:** AgentPlaybook serialization needs implementation for LangGraph checkpoints
2. **CORS Origins:** Currently `allow_origins=["*"]` - restrict in production

### Production Checklist

- [ ] Restrict CORS origins
- [ ] Enable checkpointing
- [ ] Configure rate limiting
- [ ] Set up monitoring alerts
- [ ] Review security headers

### Key Files

| File | Lines | Description |
|------|-------|-------------|
| `context.py` | ~450 | Context bullets, playbook |
| `diary.py` | ~350 | Session diary, reflection |
| `skills.py` | ~400 | Composable skills |
| `agent.py` | ~500 | G-R-C workflow |
| `main.py` | ~300 | FastAPI routes |
| `websocket.py` | ~250 | WebSocket handlers |
| `openai_compat.py` | ~200 | OpenAI-compatible API |

### Testing

```bash
# Run all tests
cd inference/agent-service
pytest tests/ -v

# Test specific component
pytest tests/test_skills.py -v

# Test with coverage
pytest tests/ --cov=app --cov-report=html
```

---

## 🔗 Related Documentation

- **Chat UI Integration:** `docs/internal/CHAT_UI_V2_PROJECT_BOARD.md`
- **Research:** `docs/research/CHAT_UI_IMPROVEMENTS_RESEARCH.md`
- **Architecture:** `docs/internal/ARCHITECTURE.md`
- **API Reference:** `docs/internal/API_REFERENCE.md`
- **Troubleshooting:** `docs/internal/TROUBLESHOOTING.md`

---

**Consolidated from:**
- ACE_IMPLEMENTATION_SUMMARY.md
- AGENT_IMPLEMENTATION_VERIFICATION.md
- AGENT_SERVICE_INTEGRATION.md
- AGENT_SERVICE_QUICK_REF.md
- AGENT_STATUS_AND_NEXT_STEPS.md
- PHASE1_COMPLETE.md
- PHASE2_PRIORITY_ANALYSIS.md
- RECOMMENDED_AGENT_SKILLS.md (partial)

**Migration Date:** January 11, 2025
