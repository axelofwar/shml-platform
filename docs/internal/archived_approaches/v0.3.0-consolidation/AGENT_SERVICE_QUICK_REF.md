# Agent Service Quick Reference

**ACE-Based Agentic Platform - Developer Guide**

---

## 🚀 Quick Start

### Start Agent Service
```bash
cd inference/agent-service
python -m app.main
# Runs on http://localhost:8000
```

### API Endpoints
```bash
# Health check
curl http://localhost:8000/health

# Execute agent (synchronous)
curl -X POST http://localhost:8000/api/v1/agent/execute \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-123",
    "session_id": "session-abc",
    "task": "Create a GitHub issue for bug in authentication",
    "category": "coding"
  }'

# Analyze session patterns (reflection)
curl -X POST http://localhost:8000/api/v1/reflection/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-123",
    "last_n": 10,
    "update_playbook": true
  }'

# Get playbook summary
curl http://localhost:8000/api/v1/playbook/user-123/summary

# Update bullet feedback
curl -X POST http://localhost:8000/api/v1/playbook/user-123/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "bullet_id": "generator_user-123_42",
    "helpful": true
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
      // User must approve elevated action
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

**1. AgentPlaybook** (context.py)
- Stores 1000 context bullets (auto-deduplicated)
- Semantic retrieval via sentence-transformers
- Utility-weighted ranking (helpful/harmful feedback)

**2. Generator-Reflector-Curator** (agent.py)
- **Generator**: Proposes actions with playbook context
- **Reflector**: Scores on clarity, accuracy, safety, actionability
- **Curator**: Extracts 1-3 lessons for future tasks

**3. Session Diary** (diary.py)
- Captures all actions, reflections, tool results
- PostgreSQL persistence with JSONB
- HMAC integrity for tamper-proof logs

**4. Reflection Engine** (diary.py)
- Analyzes last N sessions for patterns
- Detects repeated errors, successful strategies
- Updates playbook with recommendations

**5. Composable Skills** (skills.py)
- GitHubSkill, SandboxSkill, RayJobSkill, WebSearchSkill
- Activation triggers (keywords)
- <500 lines each

---

## 🔧 Adding a New Skill

### Step 1: Create Skill Class
```python
# inference/agent-service/app/skills.py

class MyCustomSkill(Skill):
    """Description of what this skill does."""

    ACTIVATION_TRIGGERS = [
        "keyword1", "keyword2", "keyword3"
    ]

    @classmethod
    def get_context(cls, user_task: str) -> str:
        """Return skill documentation."""
        if not cls.is_activated(user_task):
            return ""

        return """# My Custom Skill

**Operations:**
- `operation1`: Description
  - Params: param1, param2
  - Returns: result description

**Example:**
```python
result = await MyCustomSkill.execute("operation1", {
    "param1": "value1",
    "param2": "value2"
})
```
"""

    @classmethod
    async def execute(cls, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute skill operation."""
        if operation != "operation1":
            return {"error": f"Unknown operation: {operation}"}

        try:
            # Implement operation logic
            result = do_something(params["param1"], params["param2"])
            return {"result": result}
        except Exception as e:
            return {"error": str(e)}
```

### Step 2: Register Skill
```python
# Add to SKILLS list in skills.py
SKILLS = [
    GitHubSkill,
    SandboxSkill,
    RayJobSkill,
    WebSearchSkill,
    MyCustomSkill,  # Add here
]
```

### Step 3: Test Skill
```python
# Test activation
task = "Please use keyword1 to do something"
assert MyCustomSkill.is_activated(task)

# Test execution
result = await MyCustomSkill.execute("operation1", {
    "param1": "test",
    "param2": 42
})
assert "result" in result
```

---

## 📊 Monitoring & Debugging

### Check Playbook State
```python
from app.context import load_playbook_from_db
from app.database import AsyncSessionLocal

async with AsyncSessionLocal() as db:
    playbook = await load_playbook_from_db(db, "user-123")
    print(playbook.get_summary())
    # Output:
    # {
    #   "user_id": "user-123",
    #   "total_bullets": 247,
    #   "max_bullets": 1000,
    #   "category_counts": {
    #     "generator": 82,
    #     "reflector": 82,
    #     "curator": 65,
    #     "tool_result": 18
    #   },
    #   "avg_utility_score": 0.73
    # }
```

### View Session Diaries
```sql
-- PostgreSQL query
SELECT
    session_id,
    task_category,
    success,
    execution_time_ms,
    reflector_rubric_scores,
    curator_lessons
FROM session_diaries
WHERE user_id = 'user-123'
ORDER BY timestamp DESC
LIMIT 10;
```

### Analyze Rubric Scores
```python
from app.diary import ReflectionEngine
from app.agent import call_coding_model

async with AsyncSessionLocal() as db:
    engine = ReflectionEngine(db)
    analysis = await engine.analyze_session_patterns(
        user_id="user-123",
        last_n=20,
        model_callable=call_coding_model
    )

    print(f"Success rate: {analysis['statistics']['success_rate']:.1%}")
    print(f"Patterns: {len(analysis['patterns'])}")
    for pattern in analysis['patterns']:
        print(f"  - {pattern['type']}: {pattern['description']}")
```

---

## 🎯 Common Patterns

### Pattern 1: Add Context to Playbook
```python
from app.context import AgentPlaybook

playbook = AgentPlaybook(user_id="user-123")
playbook.add_bullet(
    content="Always check authentication before accessing GitHub API",
    category="curator",
    source="user",
    rubric_scores={"importance": 0.95, "actionable": 1.0}
)
```

### Pattern 2: Retrieve Relevant Context
```python
# Get top 10 relevant bullets for a task
relevant = playbook.retrieve_relevant(
    query="How to create a GitHub issue?",
    top_k=10,
    category="curator",  # Optional: filter by category
    min_utility=0.5  # Optional: filter by utility score
)

context_str = playbook.to_context_string(relevant)
# Use in LLM prompt
```

### Pattern 3: Manual Reflection
```python
# Trigger reflection and update playbook
analysis = await engine.analyze_session_patterns(
    user_id="user-123",
    last_n=10,
    model_callable=call_coding_model
)

await engine.update_playbook_from_reflection(analysis, playbook)
await save_playbook_to_db(db, playbook)
```

### Pattern 4: Custom Tool Approval
```python
# In agent workflow
if action_requires_approval(action, user_roles):
    approved = await manager.request_approval(session_id, action)
    if not approved:
        return {"error": "Action rejected by user"}

# Execute action
result = await execute_tool(action)
```

---

## 🧪 Testing

### Unit Tests
```python
# Test playbook retrieval
def test_playbook_retrieval():
    playbook = AgentPlaybook(user_id="test-user")

    # Add test bullets
    playbook.add_bullet("Test knowledge 1", "generator", "test")
    playbook.add_bullet("Test knowledge 2", "curator", "test")

    # Retrieve
    results = playbook.retrieve_relevant("Test knowledge", top_k=2)
    assert len(results) == 2

# Test skill activation
def test_skill_activation():
    task = "Create a GitHub issue"
    assert GitHubSkill.is_activated(task)
    assert not RayJobSkill.is_activated(task)

# Test rubric parsing
def test_rubric_parsing():
    text = """
    - Clarity: 0.9
    - Accuracy: 0.85
    """
    scores = parse_rubric_scores(text)
    assert scores["clarity"] == 0.9
    assert scores["accuracy"] == 0.85
```

### Integration Tests
```bash
# Run with pytest
pytest inference/agent-service/tests/

# Test agent execution
pytest tests/test_agent.py::test_full_workflow

# Test reflection engine
pytest tests/test_diary.py::test_pattern_detection
```

---

## 📚 Configuration

### Environment Variables
```bash
# Database (PostgreSQL)
POSTGRES_HOST=inference-postgres
POSTGRES_PORT=5432
POSTGRES_DB=inference_gateway
POSTGRES_USER=inference
POSTGRES_PASSWORD=<secret>

# Gateway URLs
GATEWAY_URL=http://inference-gateway:8000

# Redis (for WebSocket pub/sub)
REDIS_HOST=inference-redis
REDIS_PORT=6379

# FusionAuth (for GitHub tokens)
FUSIONAUTH_URL=http://fusionauth:9011
FUSIONAUTH_API_KEY=<api-key>
```

### Settings (config.py)
```python
MAX_AGENT_ITERATIONS = 15  # Max generator-reflector loops
AGENT_THINKING_TIMEOUT = 300  # 5 minutes per step
MAX_SANDBOXES = 10  # Concurrent Kata Containers
SANDBOX_TIMEOUT_SECONDS = 600  # 10 minutes
CODE_EXEC_ROLES = ["elevated-developer", "admin"]
```

---

## 🐛 Troubleshooting

### Issue: Playbook growing too large
**Solution**: Adjust `max_bullets` or lower `dedup_threshold`
```python
playbook = AgentPlaybook(
    user_id="user-123",
    max_bullets=500,  # Reduce from 1000
    dedup_threshold=0.90  # More aggressive (was 0.95)
)
```

### Issue: Rubric scores always low
**Problem**: Reflector prompt needs tuning or LLM temperature too high
**Solution**:
```python
# Lower temperature for more consistent scores
response = await call_coding_model(prompt, temperature=0.0)

# Or adjust rubric thresholds
if all(score >= 0.6 for score in rubric_scores.values()):  # Was 0.7
    return "finish"
```

### Issue: WebSocket disconnects
**Problem**: Long-running agent execution exceeds timeout
**Solution**:
```javascript
// Increase WebSocket timeout
const ws = new WebSocket('ws://localhost:8000/ws/agent/session-abc');
ws.binaryType = 'arraybuffer';
ws.timeout = 600000;  // 10 minutes

// Or send keep-alive pings
setInterval(() => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type: 'ping'}));
  }
}, 30000);
```

### Issue: Skills not activating
**Problem**: Keywords not matching user task
**Solution**:
```python
# Add more triggers
ACTIVATION_TRIGGERS = [
    "github", "repository", "repo",
    "pr", "pull request", "merge request",  # Add more synonyms
    "issue", "bug report", "ticket"
]

# Or log activation checks
logger.info(f"Checking activation for task: {user_task}")
logger.info(f"Activated skills: {[s.__name__ for s in SKILLS if s.is_activated(user_task)]}")
```

---

## 📖 Further Reading

- **ACE Framework**: https://arxiv.org/html/2510.04618v1
- **Kimi K2 Paper**: https://arxiv.org/html/2507.20534v1
- **Claude Diary**: https://rlancemartin.github.io/2025/12/01/claude_diary/
- **n8n-skills**: https://github.com/czlonkowski/n8n-skills
- **LangGraph Docs**: https://langchain-ai.github.io/langgraph/
- **Implementation Summary**: `docs/internal/ACE_IMPLEMENTATION_SUMMARY.md`

---

**Last Updated**: December 7, 2025  
**Version**: 0.1.0 (Phase 1 Complete)  
**Status**: 7/12 tasks completed (5 fully implemented, 2 in-progress)
