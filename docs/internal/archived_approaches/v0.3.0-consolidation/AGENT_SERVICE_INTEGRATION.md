# Agent Service Integration Guide

**Status:** Agent service running, not connected to chat UI  
**Date:** 2025-12-07  
**Agent Service:** http://localhost/api/agent (developer+ roles only)

---

## Current State

### ✅ What's Working

1. **Agent Service Running**
   - Container: `shml-agent-service` (healthy)
   - Health: `http://localhost/api/agent/health` (requires OAuth)
   - Direct: `docker exec shml-agent-service curl http://localhost:8000/health` ✓

2. **Authentication**
   - OAuth2-Proxy protecting `/api/agent`
   - Requires: developer, elevated-developer, or admin role
   - JWT Bearer tokens supported (`skip-jwt-bearer-tokens=true`)

3. **ACE Workflow**
   - Generator → Reflector → Curator pattern
   - LangGraph 1.0.4 with checkpointing
   - 4 Skills: GitHub, Sandbox, Ray, WebSearch
   - WebSocket streaming for real-time updates

4. **Infrastructure**
   - Database: PostgreSQL (playbooks, session diary)
   - Models: Qwen2.5-Coder-32B (primary), 7B (fallback)
   - Docker socket: Mounted for sandbox execution
   - Redis: Available for pub/sub if needed

### ❌ What's Missing

1. **Chat UI Not Connected**
   - Current UI (`/chat-ui`) connects to `/chat` (simple chat-api)
   - Agent service (`/api/agent`) is not exposed to UI
   - No WebSocket client implemented
   - No ACE workflow visualization

2. **User Experience**
   - Users see simple chat, not agent workflow
   - No G-R-C stage streaming
   - No tool approval UI
   - No skill execution visibility

---

## Agent Service API

### Endpoints

#### 1. Health Check
```bash
GET /api/agent/health
Response: {"status": "healthy", "service": "agent-service", "version": "0.1.0"}
```

#### 2. Synchronous Execution (Non-Streaming)
```bash
POST /api/agent/api/v1/agent/execute
Content-Type: application/json

{
  "user_id": "user@example.com",
  "session_id": "optional-session-id",
  "task": "Create a Python function that calculates fibonacci",
  "category": "coding",
  "max_iterations": 15
}

Response: {
  "task": "...",
  "success": true,
  "generator_output": "...",
  "reflector_output": "...",
  "curator_lessons": [...],
  "tool_results": [...],
  "final_answer": "...",
  "iterations": 3,
  "duration": 12.5
}
```

**Note:** This endpoint executes the full workflow and returns when complete. No streaming.

#### 3. WebSocket Streaming (Real-Time)
```javascript
// Connect to WebSocket
const ws = new WebSocket('ws://localhost/api/agent/ws/agent/{session_id}');

// Send initial request
ws.send(JSON.stringify({
  type: 'agent_request',
  user_id: 'user@example.com',
  task: 'Create a Python function',
  category: 'coding'
}));

// Receive streaming updates
ws.onmessage = (event) => {
  const message = JSON.parse(event.data);

  switch (message.type) {
    case 'stage_output':
      // G-R-C stage streaming
      console.log(`${message.stage}: ${message.content}`);
      break;

    case 'tool_execution':
      // Tool call results
      console.log(`Tool ${message.tool}: ${message.result}`);
      break;

    case 'approval_request':
      // Human-in-loop approval needed
      // Send approval response
      ws.send(JSON.stringify({
        type: 'approval_response',
        tool_call_id: message.action.id,
        approved: true
      }));
      break;

    case 'complete':
      console.log('Agent workflow complete');
      break;

    case 'error':
      console.error('Agent error:', message.error);
      break;
  }
};
```

**Note:** WebSocket provides real-time streaming of each ACE stage.

---

## Integration Options

### Option A: Update Existing Chat UI

**Pros:**
- Reuse existing UI components
- Single user interface
- Model selection can include "Agent (ACE)"

**Cons:**
- Need to add WebSocket support
- Complex UI changes for ACE workflow
- May confuse users (chat vs agent mode)

**Implementation:**
1. Add WebSocket client to `chat-ui/src/api.ts`
2. Create ACE stage visualization components
3. Add tool approval UI
4. Add "Use Agent" toggle in chat interface

**Estimated Time:** 6-8 hours

---

### Option B: Create Dedicated Agent UI

**Pros:**
- Clean separation of concerns
- Optimized for agent workflow
- Better visualization of G-R-C stages
- Easier tool approval UX

**Cons:**
- Need to build new UI from scratch
- Users have two interfaces to learn
- More maintenance burden

**Implementation:**
1. Create `/agent-ui` route (similar to chat-ui)
2. Build WebSocket streaming components
3. Visualize Generator → Reflector → Curator flow
4. Add tool execution timeline
5. Implement approval workflow UI

**Estimated Time:** 12-16 hours

---

### Option C: Agent as Chat Model Option

**Pros:**
- Seamless integration
- Users can choose "Agent" model
- Minimal UI changes

**Cons:**
- Loses ACE workflow visibility
- No tool approval UI
- Feels like slower chat

**Implementation:**
1. Add "Agent (ACE)" to model selector in chat-ui
2. When selected, route to `/api/agent/api/v1/agent/execute`
3. Handle non-streaming response
4. Display final result as assistant message

**Estimated Time:** 2-3 hours

---

## Recommended Approach

**Start with Option C (Quick Win), then build Option B (Full Experience)**

### Phase 1: Quick Integration (Option C)
- Add agent as model option in chat UI
- Use synchronous API endpoint
- Display final result as chat message
- **Time:** 2-3 hours
- **User Value:** Can use agent immediately

### Phase 2: Full Agent UI (Option B)
- Build dedicated `/agent-ui` route
- WebSocket streaming
- ACE stage visualization
- Tool approval workflow
- **Time:** 12-16 hours
- **User Value:** Full agent experience with transparency

---

## Testing the Agent Service

### Manual Test (Browser)

1. **Login as admin** at http://localhost/chat-ui
2. **Open browser console**, run:
```javascript
fetch('http://localhost/api/agent/api/v1/agent/execute', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  credentials: 'include',
  body: JSON.stringify({
    user_id: 'test-user',
    session_id: 'test-' + Date.now(),
    task: 'Create a Python function that adds two numbers',
    category: 'coding',
    max_iterations: 3
  })
}).then(r => r.json()).then(console.log);
```

3. **Check console** for full agent response with G-R-C outputs

### WebSocket Test (Browser)

```javascript
const sessionId = 'ws-test-' + Date.now();
const ws = new WebSocket(`ws://localhost/api/agent/ws/agent/${sessionId}`);

ws.onopen = () => {
  console.log('✓ WebSocket connected');
  ws.send(JSON.stringify({
    type: 'agent_request',
    user_id: 'test-user',
    task: 'Calculate 5 squared',
    category: 'coding'
  }));
};

ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  console.log(`[${msg.type}]`, msg);
};

ws.onerror = (e) => console.error('WebSocket error:', e);
```

### Curl Test (Terminal)

```bash
# Synchronous execution (requires login cookie)
curl -X POST 'http://localhost/api/agent/api/v1/agent/execute' \
  -H 'Content-Type: application/json' \
  -b cookies.txt \
  -d '{
    "user_id": "test-user",
    "session_id": "curl-test-1",
    "task": "Create a Python function that calculates fibonacci",
    "category": "coding",
    "max_iterations": 5
  }' | jq .
```

**Note:** You need to save OAuth cookies first:
```bash
# Login and save cookies
curl -c cookies.txt -L 'http://localhost/oauth2-proxy/sign_in'
# Then use -b cookies.txt in subsequent requests
```

---

## Skills Available

### 1. GitHubSkill
- Search repositories
- Get file contents
- List issues/PRs
- **Requires:** GitHub token in environment

### 2. SandboxSkill
- Execute code in isolated containers
- Supports: Python, Node.js, Bash
- **Requires:** elevated-developer or admin role
- **Security:** Docker socket mounted read-only

### 3. RaySkill
- Submit Ray jobs
- Get job status
- List cluster resources
- **Requires:** Ray cluster running

### 4. WebSearchSkill
- DuckDuckGo search
- Web page scraping
- Content summarization
- **Requires:** Internet access

---

## Sandbox Execution

### Security Model

1. **Role Check:** Agent checks user has elevated-developer or admin
2. **Approval Request:** Sends WebSocket message for human approval
3. **Container Creation:** If approved, creates temporary Docker container
4. **Code Execution:** Runs code in isolated environment
5. **Cleanup:** Destroys container after execution

### Configuration

```python
# In app/skills.py
class SandboxSkill:
    ALLOWED_ROLES = ["elevated-developer", "admin"]

    async def execute(self, code: str, language: str, user_roles: List[str]):
        # Check role
        if not any(role in self.ALLOWED_ROLES for role in user_roles):
            raise PermissionError("Sandbox requires elevated-developer or admin")

        # Request approval
        approved = await self.request_approval(...)
        if not approved:
            return "Sandbox execution denied by user"

        # Execute in container
        container = docker.run(...)
        result = container.logs()
        container.remove()
        return result
```

---

## WebSocket Message Types

### Client → Server

#### 1. Initial Request
```json
{
  "type": "agent_request",
  "user_id": "user@example.com",
  "task": "Your task description",
  "category": "coding|research|general"
}
```

#### 2. Approval Response
```json
{
  "type": "approval_response",
  "tool_call_id": "tool-123",
  "approved": true|false
}
```

### Server → Client

#### 1. Stage Output (G-R-C)
```json
{
  "type": "stage_output",
  "stage": "generator|reflector|curator",
  "content": "Stage output text...",
  "timestamp": "2025-12-07T23:00:00Z"
}
```

#### 2. Tool Execution
```json
{
  "type": "tool_execution",
  "tool": "sandbox|github|ray|websearch",
  "status": "executing|completed|failed",
  "result": "Tool output..."
}
```

#### 3. Approval Request
```json
{
  "type": "approval_request",
  "action": {
    "id": "tool-123",
    "tool": "sandbox",
    "code": "print('hello')",
    "language": "python"
  },
  "timestamp": "2025-12-07T23:00:00Z"
}
```

#### 4. Completion
```json
{
  "type": "complete",
  "final_answer": "Agent's final response...",
  "success": true,
  "iterations": 3,
  "duration": 12.5
}
```

#### 5. Error
```json
{
  "type": "error",
  "error": "Error description",
  "stage": "generator|reflector|curator|tool"
}
```

---

## Next Steps

### Immediate (Option C - Quick Win)

1. **Add agent model to chat-ui** (2h)
   - Update `chat-ui/src/api.ts` with agent endpoint
   - Add "Agent (ACE)" to model selector
   - Handle synchronous response format
   - Test with admin account

2. **Document usage** (30m)
   - Add agent instructions to UI
   - Explain ACE workflow benefits
   - Link to this doc for details

3. **Test end-to-end** (1h)
   - Test coding tasks
   - Test sandbox execution (elevated-developer)
   - Test skill availability
   - Verify role enforcement

### Short-Term (Option B - Full Experience)

1. **Create agent-ui** (8-12h)
   - WebSocket client implementation
   - ACE stage visualization
   - Tool execution timeline
   - Approval workflow UI

2. **Add to platform navigation** (1h)
   - Add "Agent" link to main navigation
   - Update Homer dashboard with agent tile
   - Document in README.md

3. **User testing** (2h)
   - Test with different roles
   - Gather feedback on UX
   - Iterate on workflow

---

## Troubleshooting

### Issue: 401 Unauthorized

**Cause:** Not logged in or wrong role  
**Solution:**
- Login at http://localhost/chat-ui
- Check you have developer, elevated-developer, or admin role
- Verify OAuth cookie is sent with request

### Issue: WebSocket Connection Failed

**Cause:** OAuth2-Proxy doesn't support WebSocket auth  
**Solution:**
- WebSocket connections through OAuth2-Proxy need special handling
- May need to bypass OAuth for WebSocket endpoints
- Or implement token-based WebSocket auth

### Issue: Sandbox Permission Denied

**Cause:** User doesn't have elevated-developer or admin role  
**Solution:**
- Assign elevated-developer role in FusionAuth
- Or use admin account for testing

### Issue: Coding Model 500 Error

**Cause:** Coding model unhealthy or overloaded  
**Solution:**
```bash
docker restart coding-model-primary
# Wait for healthy status
docker ps | grep coding-model-primary
```

---

## Future Optimizations

### Model Loading Performance

**Current State:**
- Z-Image: 300s load time (timeout)
- Coding models: 75s load time
- Qwen3-VL: 6s load time

**Optimization Strategies:**

1. **Model Quantization**
   - Use INT8 or INT4 quantization
   - Reduces memory footprint
   - Faster loading, slightly lower quality
   - Already using INT4 for Qwen3-VL

2. **Lazy Loading**
   - Load models on first request, not startup
   - Keep loaded models in memory
   - Unload unused models after timeout

3. **Model Caching**
   - Cache model weights on SSD
   - Use memory-mapped files
   - Share weights between processes

4. **Infrastructure**
   - Faster GPUs (RTX 4090 vs 3090/2070)
   - NVMe SSDs for model storage
   - More VRAM (24GB+ per model)

5. **Container Optimization**
   - Pre-load models in container image
   - Use persistent volumes for models
   - Avoid container recreation

**Priority:** Medium (UX improvement, not blocking)  
**Estimated Impact:** 50-75% reduction in load times  
**Estimated Effort:** 8-12 hours

---

**Last Updated:** 2025-12-07  
**Next Review:** After Option C implementation  
**Owner:** Platform Team
