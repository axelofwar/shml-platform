# Chat UI & Agent Improvements Research
## Comprehensive Analysis from Industry Best Practices

**Date:** December 7, 2025  
**Purpose:** Research-driven improvements for Chat UI v2, ACE workflow, and agent service  
**Sources:** 14 research papers, frameworks, and implementations

---

## Executive Summary

This document synthesizes research from cutting-edge AI agent implementations, LangGraph architectures, CUDA optimization, MCP integrations, and UI/UX patterns. Key findings focus on:

1. **Context Engineering** - Managing agent memory and preventing context collapse
2. **Hybrid Architectures** - Combining deterministic routing with agentic reasoning
3. **Conversation History** - Preserving multimodal context without bloating windows
4. **Workflow Visualization** - Showing decision-making, reasoning, and tool execution
5. **Performance Optimization** - GPU memory management and CUDA best practices

---

## 1. Context Engineering (from Manus Agent)

**Source:** [Context Engineering in Manus](http://rlancemartin.github.io/2025/10/15/manus/)

### Key Insights

**Problem:** Agents using 50+ tool calls accumulate results in context window → Performance degrades

**Solution:** Three-tier context engineering strategy:

#### 1.1 Context Reduction
- **Full vs Compact Representations**: Store full tool results externally (filesystem), use compact references (file paths) in context
- **Stale Result Compaction**: Replace older tool results with references, keep recent results in full
- **Schema-Based Summarization**: When compaction reaches limits, summarize trajectories using consistent schemas

**Application to SHML:**
```typescript
// Current: All tool results in message content
// Improved: Store in separate collection, reference in context

interface ToolResultStorage {
  id: string
  tool: string
  result: any
  timestamp: string
  isStale: boolean
}

interface CompactReference {
  toolResultId: string
  summary: string // 1-2 sentence summary
  filePath?: string
}
```

#### 1.2 Context Offloading
- **Tools to Sandbox**: Use small set of atomic tools (Bash, filesystem) instead of binding every utility
- **Progressive Disclosure**: Store tool documentation in filesystem, load on-demand (like Claude Skills)
- **Tool Results to Storage**: Save full results externally, search with `grep`/`glob` without indexing

**Application to SHML:**
- Currently: 4 skills (GitHub, Sandbox, Ray, WebSearch)
- Improve: Add filesystem-based skill documentation, load contexts only when triggered

#### 1.3 Context Isolation
- **Sub-agents for Tasks**: Assign discrete tasks to sub-agents with isolated context
- **Selective Context Sharing**: Pass instructions only for simple tasks, full context for complex tasks
- **Planner Architecture**: Central planner routes tasks, sub-agents execute with defined output schemas

**Application to SHML:**
- ACE pattern already has Generator → Reflector → Curator stages
- Add: Task-specific sub-agents for multi-step operations (e.g., "Deploy model" = experiment creation + Ray job + registration)

---

## 2. Hybrid Architecture (from Energy Buddy)

**Source:** [LangGraph Hybrid Architecture](https://medium.com/@juan8arias/give-an-engineer-a-problem-and-he-will-langgraph-the-solution-2f330775b841) | [GitHub](https://github.com/juanfe88/energy_buddy)

### Key Insights

**Problem:** Pure agentic systems hallucinate, get distracted, or fail on deterministic tasks

**Solution:** Hybrid graph with deterministic routing + agentic reasoning

#### 2.1 Deterministic Routing
```python
def should_classify_image(state: AgentState):
    """Python function, not LLM call"""
    if state.get("has_image"):
        return "classify_image"
    elif state.get("is_query"):
        return "query_agent"
    return "responder"
```

**Application to SHML:**
- Current: Agent decides next step using LLM
- Improve: Pre-route based on content type (image → vision model, code → coding model, query → reasoner)

#### 2.2 Memory with Checkpointer
```python
from langgraph.checkpoint.memory import InMemorySaver

checkpointer = InMemorySaver()
workflow.compile(checkpointer=checkpointer)

workflow.invoke(
    initial_state,
    config={"configurable": {"thread_id": user_phone}}
)
```

**Application to SHML:**
- Current: Session diary stores reflections
- Improve: Add LangGraph InMemorySaver for short-term conversation memory
- Long-term: Semantic memory (vectors) + episodic memory (graphs) per user

---

## 3. Agentic Architecture Patterns (17 Patterns)

**Source:** [All Agentic Architectures](https://github.com/FareedKhan-dev/all-agentic-architectures)

### Relevant Patterns for SHML

| Pattern | Description | Use Case | Priority |
|---------|-------------|----------|----------|
| **Reflection** | Self-critique and refine | Already in ACE (Reflector stage) | ✅ Implemented |
| **Tool Use** | External API/function calls | Already in Skills | ✅ Implemented |
| **ReAct** | Reason → Act → Observe loop | Current agent pattern | ✅ Implemented |
| **Planning** | Decompose task before execution | Complex multi-step workflows | 🟡 Future |
| **Multi-Agent** | Specialized agents collaborate | MLflow + Ray + GitHub orchestration | 🟡 Future |
| **PEV (Plan-Execute-Verify)** | Self-correcting loop | High-stakes operations (model deployment) | 🟡 Future |
| **Episodic + Semantic Memory** | Vector store + graph DB | User-specific long-term memory | 🟡 Future |
| **Tree of Thoughts** | Explore multiple reasoning paths | Complex problem solving | 🔵 Nice-to-have |
| **Mental Loop (Simulator)** | Test actions internally first | Risk assessment before execution | 🔵 Nice-to-have |
| **Meta-Controller** | Route tasks to specialist agents | Skill routing based on task type | 🟡 Future |
| **Ensemble** | Multiple agents analyze, aggregate | High-stakes decisions | 🔵 Nice-to-have |
| **Dry-Run Harness** | Simulate before live execution | Safety-critical operations | 🟡 Future |
| **RLHF (Self-Improvement)** | Learn from critiques | Playbook improvement (already partial) | ✅ Partial |

#### Immediate Action Items

1. **Add Planning Stage** (before Generator)
   - Decompose complex tasks into subtasks
   - Estimate resources (tokens, time, GPU memory)
   - Show plan to user with approve/modify option

2. **Implement Dry-Run for Elevated Actions**
   - SandboxSkill: Show code before execution
   - RaySkill: Show job config before submission
   - MLflowSkill (future): Show registration before commit

3. **Meta-Controller for Skill Routing**
   - Analyze user input → Detect task type
   - Activate relevant skills only (not all 4)
   - Reduces context, improves speed

---

## 4. CUDA Optimization (NVIDIA Programming Guide)

**Source:** [CUDA Programming Guide Part 4](https://docs.nvidia.com/cuda/cuda-programming-guide/part4.html)

### Relevant Optimizations for SHML

#### 4.1 Unified Memory
- **Current:** Manual memory management in Qwen/SDXL
- **Improvement:** Use `cudaMallocManaged()` for automatic CPU↔GPU migration
- **Benefit:** Simplifies code, avoids OOM errors

#### 4.2 CUDA Graphs
- **Current:** Sequential kernel launches (high overhead)
- **Improvement:** Capture inference pipeline as CUDA graph
- **Benefit:** 2-5x faster inference for repeated operations

#### 4.3 Stream-Ordered Memory Allocator
- **Current:** Global memory pool
- **Improvement:** Per-stream allocators for concurrent model execution
- **Benefit:** Better GPU utilization when running Qwen + Z-Image

#### 4.4 L2 Cache Control
- **Problem:** Cache thrashing when switching models
- **Solution:** Persist frequently accessed data (embeddings, position encodings) in L2
- **Benefit:** 10-20% speedup on model swaps

#### 4.5 Async Barriers & Pipelines
- **Current:** Synchronous data transfers
- **Improvement:** Pipeline model loading with inference
- **Benefit:** Hide latency when switching GPU 0 between training/inference

**Priority for SHML:**
- 🔴 High: CUDA Graphs (easy win, 2-5x speedup)
- 🟡 Medium: Unified Memory (simplifies code)
- 🔵 Low: L2 Cache Control (complex, requires profiling)

---

## 5. MCP Integration Best Practices (Reddit MCP Buddy)

**Source:** [Reddit MCP Buddy](https://github.com/karanb192/reddit-mcp-buddy)

### Key Learnings

#### 5.1 Three-Tier Authentication
- Anonymous (10 req/min) → App-only (60 req/min) → Authenticated (100 req/min)
- **Application:** Implement tiered rate limits for SHML skills
  - Viewer: 10 tool calls/min
  - Developer: 60 tool calls/min
  - Elevated: 100 tool calls/min

#### 5.2 Smart Caching
- Memory-safe: 50MB hard limit
- Adaptive TTLs: Hot data (5min), New data (2min), Historical (30min)
- LRU eviction when approaching limits

**Application to SHML:**
```typescript
class ToolResultCache {
  maxSize: 50 * 1024 * 1024 // 50MB
  ttl: {
    hot: 5 * 60 * 1000,
    new: 2 * 60 * 1000,
    historical: 30 * 60 * 1000
  }
  evictionStrategy: 'LRU'
}
```

#### 5.3 Privacy & Data Handling
- **No tracking/telemetry**: All processing local
- **Credential safety**: Environment variables, never disk (except encrypted)
- **Read-only operations**: Agent can query but not modify

**Application to SHML:**
- Already following: No external analytics
- Improve: Document data flows in UI (show what's sent where)
- Add: User-controlled data retention (auto-delete conversations after N days)

---

## 6. Conversation History Management

### Current State Analysis

**Pros:**
- ✅ Conversations persist to localStorage
- ✅ Zustand state management
- ✅ Message history includes timestamps

**Cons:**
- ❌ No conversation list UI (can't browse history)
- ❌ No clear history button
- ❌ No new chat button (always uses same conversation)
- ❌ No lazy loading (all messages loaded on start)
- ❌ No multimodal context tracking (images, files)

### Recommended Improvements

#### 6.1 Conversation Sidebar
```tsx
<div className="w-64 border-r border-border overflow-y-auto">
  <div className="p-4 border-b border-border">
    <button onClick={createNewConversation} className="w-full btn-primary">
      + New Chat
    </button>
  </div>

  <div className="divide-y divide-border">
    {conversations.map((conv) => (
      <button
        key={conv.id}
        onClick={() => setCurrentConversation(conv.id)}
        className="w-full p-3 text-left hover:bg-muted"
      >
        <div className="font-medium truncate">{conv.title}</div>
        <div className="text-xs text-muted-foreground">
          {conv.messages.length} messages · {formatDate(conv.updated_at)}
        </div>
      </button>
    ))}
  </div>
</div>
```

#### 6.2 Context Window Management
**Problem:** Loading 1000+ messages causes:
- Long page load time
- Memory bloat
- Context window overflow

**Solution:** Lazy loading + summarization

```typescript
interface ConversationSummary {
  id: string
  title: string
  summary: string // AI-generated summary of older messages
  recentMessages: Message[] // Last 20 messages
  totalMessages: number
  contextTokens: number
}

// Load strategy
async function loadConversation(id: string) {
  const summary = await getSummary(id)
  const recent = await getRecentMessages(id, 20)

  // Send to agent: summary + recent (not full history)
  return {
    context: summary.summary,
    messages: recent,
    canLoadMore: summary.totalMessages > 20
  }
}
```

#### 6.3 Multimodal Context Tracking
```typescript
interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: string
  attachments?: Array<{
    type: 'image' | 'pdf' | 'file' | 'link'
    url: string
    name: string
    size?: number
    mimeType?: string
    metadata?: any // OCR text, page count, etc.
  }>
}

// When sending to agent:
function buildContext(messages: Message[]) {
  return messages.map(m => ({
    role: m.role,
    content: m.content,
    // Include attachment metadata (not full file)
    attachments: m.attachments?.map(a => ({
      type: a.type,
      name: a.name,
      // For images: Include in vision model context
      // For PDFs: Include extracted text
      // For links: Include title + description
      summary: a.metadata?.summary
    }))
  }))
}
```

---

## 7. Workflow Visualization (Decision-Making Display)

### Current State
- ✅ Shows workflow stages (Generator, Reflector, Curator)
- ✅ Shows stage status (pending, running, complete)
- ❌ Doesn't show **why** agent made decisions
- ❌ Doesn't show rubric scores
- ❌ Doesn't show tool execution details

### Recommended Improvements

#### 7.1 Decision Context Panel
```tsx
<div className="bg-muted/50 rounded-lg p-4 mb-4">
  <div className="font-semibold mb-2">🧠 Agent Reasoning</div>

  {/* Generator Stage */}
  <div className="mb-3">
    <div className="text-sm font-medium">Generator Proposal</div>
    <div className="text-xs text-muted-foreground mt-1">
      {stage.reasoning}
    </div>
    <div className="flex gap-2 mt-2">
      {stage.toolCalls?.map(tool => (
        <span key={tool.id} className="px-2 py-1 bg-blue-500/10 text-blue-400 rounded text-xs">
          🔧 {tool.function.name}
        </span>
      ))}
    </div>
  </div>

  {/* Reflector Stage */}
  <div className="mb-3">
    <div className="text-sm font-medium">Reflector Analysis</div>
    <div className="grid grid-cols-4 gap-2 mt-2">
      <MetricBadge label="Clarity" score={rubrics.clarity} />
      <MetricBadge label="Completeness" score={rubrics.completeness} />
      <MetricBadge label="Correctness" score={rubrics.correctness} />
      <MetricBadge label="Actionability" score={rubrics.actionability} />
    </div>
    <div className="text-xs text-muted-foreground mt-1">
      {rubrics.overall >= 0.7 ? '✓ Approved for execution' : '⚠️ Needs refinement'}
    </div>
  </div>

  {/* Curator Stage */}
  <div>
    <div className="text-sm font-medium">Lessons Learned</div>
    <ul className="text-xs text-muted-foreground mt-1 space-y-1">
      {stage.lessonsLearned?.map((lesson, i) => (
        <li key={i}>• {lesson}</li>
      ))}
    </ul>
  </div>
</div>

function MetricBadge({ label, score }: { label: string; score: number }) {
  const color = score >= 0.8 ? 'green' : score >= 0.6 ? 'yellow' : 'red'
  return (
    <div className={`text-center p-2 rounded bg-${color}-500/10 border border-${color}-500/20`}>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`text-sm font-bold text-${color}-400`}>{(score * 100).toFixed(0)}%</div>
    </div>
  )
}
```

#### 7.2 Tool Execution Timeline
```tsx
<div className="space-y-2">
  {toolResults.map((result, i) => (
    <div key={i} className="border-l-2 border-blue-500 pl-3 py-2">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">{result.tool}</span>
        <span className={`text-xs px-2 py-0.5 rounded ${
          result.status === 'success' ? 'bg-green-500/10 text-green-400' :
          result.status === 'error' ? 'bg-red-500/10 text-red-400' :
          'bg-yellow-500/10 text-yellow-400'
        }`}>
          {result.status}
        </span>
        <span className="text-xs text-muted-foreground ml-auto">
          {result.duration}ms
        </span>
      </div>
      <div className="text-xs text-muted-foreground mt-1">
        {result.summary || result.output?.substring(0, 100)}
      </div>
    </div>
  ))}
</div>
```

#### 7.3 Usage Instructions (How to Use Output)
```tsx
<div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4 mt-4">
  <div className="font-semibold text-blue-400 mb-2">💡 How to Use This</div>
  <div className="text-sm text-muted-foreground space-y-1">
    {message.usageInstructions?.map((instruction, i) => (
      <div key={i}>• {instruction}</div>
    ))}
  </div>
</div>
```

---

## 8. Performance & Resource Optimization

### 8.1 Frontend Optimization

**Problem:** Chat UI with 100+ messages lags

**Solutions:**
1. **Virtual Scrolling** (react-window):
```tsx
import { FixedSizeList } from 'react-window'

<FixedSizeList
  height={600}
  itemCount={messages.length}
  itemSize={80}
  width="100%"
>
  {({ index, style }) => (
    <div style={style}>
      <MessageComponent message={messages[index]} />
    </div>
  )}
</FixedSizeList>
```

2. **Message Pagination**:
```typescript
const PAGE_SIZE = 50
const [page, setPage] = useState(0)
const visibleMessages = messages.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
```

3. **Debounced Input**:
```typescript
import { useDebouncedCallback } from 'use-debounce'

const debouncedSave = useDebouncedCallback(
  (text) => setInputText(text),
  300
)
```

### 8.2 Backend Optimization

**Problem:** Agent takes 30+ seconds per iteration

**Solutions:**
1. **Parallel Tool Execution**:
```python
# Current: Sequential
result1 = await execute_tool('GitHub', args1)
result2 = await execute_tool('Ray', args2)

# Improved: Parallel
results = await asyncio.gather(
    execute_tool('GitHub', args1),
    execute_tool('Ray', args2)
)
```

2. **Streaming Tokens** (not just final output):
```python
async def generator_node(state):
    async for token in llm.astream(prompt):
        await connection_manager.send_stage_output({
            "stage": "generator",
            "type": "token",
            "content": token
        })
```

3. **Caching Playbook Embeddings**:
```python
# Current: Re-compute embeddings every retrieval
# Improved: Cache with TTL
embedding_cache = TTLCache(maxsize=1000, ttl=3600)

def get_playbook_context(task):
    cache_key = hash(task)
    if cache_key in embedding_cache:
        return embedding_cache[cache_key]

    embedding = model.encode(task)
    embedding_cache[cache_key] = embedding
    return embedding
```

---

## 9. Immediate Action Plan (Priority Order)

### Phase 1: Conversation Management (2-3 hours)

**Files to modify:**
- `chat-ui-v2/src/components/chat/ChatInterface.tsx`
- `chat-ui-v2/src/stores/chatStore.ts`
- Create: `chat-ui-v2/src/components/sidebar/ConversationSidebar.tsx`

**Tasks:**
1. Add "New Chat" button in header
2. Add "Clear History" button (with confirm dialog)
3. Add conversation list sidebar (collapsible)
4. Add lazy loading (load last 50 messages initially)
5. Add multimodal attachment tracking to Message interface

### Phase 2: Decision Context Display (2-3 hours)

**Files to modify:**
- `chat-ui-v2/src/components/chat/MessageContent.tsx`
- `chat-ui-v2/src/components/workflow/WorkflowPanel.tsx`
- Create: `chat-ui-v2/src/components/workflow/DecisionContext.tsx`

**Tasks:**
1. Extract reasoning from Generator output
2. Display rubric scores from Reflector
3. Show tool execution timeline
4. Add usage instructions panel
5. Add "Why did the agent do this?" expandable section

### Phase 3: Context Window Optimization (1-2 hours)

**Backend files:**
- `inference/agent-service/app/context.py`
- `inference/agent-service/app/agent.py`

**Tasks:**
1. Implement conversation summarization (after 20 messages)
2. Add context token counter
3. Add "context full" warning in UI
4. Implement message compaction (full → compact reference)

### Phase 4: Performance Optimization (3-4 hours)

**Tasks:**
1. Add virtual scrolling for messages
2. Implement parallel tool execution in agent
3. Add token streaming (not just final output)
4. Cache playbook embeddings
5. Profile and optimize GPU memory usage

---

## 10. Research-Backed Recommendations Summary

### Do Implement (High ROI)

| Feature | Effort | Impact | Source |
|---------|--------|--------|--------|
| Conversation sidebar | 2h | High | Industry standard |
| Clear/New chat buttons | 0.5h | High | User expectation |
| Decision context panel | 2h | High | Manus, Energy Buddy |
| Rubric score display | 1h | High | ACE pattern |
| Lazy loading messages | 1h | Medium | Performance best practice |
| Context summarization | 2h | High | Manus (context reduction) |
| Tool execution timeline | 1.5h | High | Transparency |
| Usage instructions | 1h | Medium | UX improvement |
| Virtual scrolling | 1h | Medium | Performance |
| Parallel tool execution | 2h | High | Speed 2-3x improvement |

**Total estimated: 14 hours for core improvements**

### Don't Implement Yet (Low ROI or Premature)

| Feature | Why Not Now |
|---------|-------------|
| Multi-agent system | Already have ACE stages, complex, needs use case |
| Tree of Thoughts | Complex, marginal benefit for current tasks |
| CUDA graph optimization | Premature, need profiling first |
| L2 cache control | Too low-level, requires CUDA expertise |
| Full episodic memory | Over-engineering, localStorage sufficient for now |
| Ensemble agents | High overhead, current quality already good |

### Document in Research (Future Work)

| Feature | Notes |
|---------|-------|
| Planning stage | Add before Generator for complex tasks |
| Dry-run harness | Safety for elevated operations |
| Meta-controller routing | Skill selection optimization |
| Long-term memory (vector + graph) | Per-user context across sessions |
| CUDA Graphs | After profiling shows bottleneck |
| Model KV cache | If switching between models frequently |

---

## 11. Documentation Consolidation Recommendations

### Current State: 27 files in `docs/internal/`

**Redundant/Overlapping:**
1. `AGENT_SERVICE_INTEGRATION.md` + `AGENT_SERVICE_QUICK_REF.md` → Merge
2. `ACE_IMPLEMENTATION_SUMMARY.md` + `AGENT_STATUS_AND_NEXT_STEPS.md` → Merge
3. `GPU_MEMORY_ANALYSIS.md` + `MULTI_MODEL_ORCHESTRATION_PLAN.md` → Merge

**Outdated:**
4. `PHASE1_COMPLETE.md` → Archive (replaced by `AGENT_STATUS_AND_NEXT_STEPS.md`)
5. `AGENT_IMPLEMENTATION_VERIFICATION.md` → Archive (implementation done)

**Can Move to Research:**
6. `RECOMMENDED_AGENT_SKILLS.md` → `docs/research/` (planning doc)
7. `PHASE2_PRIORITY_ANALYSIS.md` → `docs/research/` (decision doc)
8. `NATIVE_EXECUTION_OPTIONS.md` → `docs/research/` (exploration)

**Target: <12 core docs in `docs/internal/`**

### Proposed Structure

**Keep (Core Documentation):**
1. `ARCHITECTURE.md` - System design
2. `API_REFERENCE.md` - All APIs
3. `INTEGRATION_GUIDE.md` - Service integration
4. `TROUBLESHOOTING.md` - Common issues
5. `CHAT_UI_V2_PROJECT_BOARD.md` - Active roadmap
6. `AGENTIC_PLATFORM_DESIGN.md` - Platform vision
7. `AUTH_FLOW_AND_USER_ACCESS.md` - Authentication
8. `JWT_BEARER_TOKEN_AUTH.md` - Token auth
9. `FUSIONAUTH_CONFIGURATION_GUIDE.md` - FusionAuth setup
10. `NEW_GPU_SETUP.md` - GPU configuration
11. **NEW:** `AGENT_COMPLETE_GUIDE.md` (merge AGENT_SERVICE_INTEGRATION + AGENT_SERVICE_QUICK_REF + ACE_IMPLEMENTATION_SUMMARY + AGENT_STATUS)
12. **NEW:** `GPU_AND_MODELS_GUIDE.md` (merge GPU_MEMORY_ANALYSIS + MULTI_MODEL_ORCHESTRATION_PLAN)

**Archive:**
- `archived_approaches/` - Keep existing
- `PHASE1_COMPLETE.md`, `AGENT_IMPLEMENTATION_VERIFICATION.md`

**Move to Research:**
- `RECOMMENDED_AGENT_SKILLS.md`
- `PHASE2_PRIORITY_ANALYSIS.md`
- `NATIVE_EXECUTION_OPTIONS.md`
- `RECALL_IMPROVEMENT_GUIDE.md`

**Result: 12 core docs (down from 27)**

---

## 12. Next Steps

### Immediate (This Session)
1. ✅ Create this research document
2. Implement conversation sidebar + clear/new chat buttons
3. Add decision context panel to message display
4. Update project board with research findings

### Short-term (Next Session)
1. Implement lazy loading for messages
2. Add context summarization backend
3. Implement tool execution timeline
4. Add usage instructions to responses

### Medium-term (Next Week)
1. Consolidate internal documentation (27 → 12 files)
2. Implement virtual scrolling
3. Add parallel tool execution
4. Profile and optimize GPU usage

### Long-term (Backlog)
1. Planning stage (before Generator)
2. Dry-run harness for safety
3. Long-term memory (vectors + graph)
4. CUDA optimization after profiling

---

**References:**
- [Manus Context Engineering](http://rlancemartin.github.io/2025/10/15/manus/)
- [Energy Buddy Hybrid Architecture](https://medium.com/@juan8arias/give-an-engineer-a-problem-and-he-will-langgraph-the-solution-2f330775b841)
- [All Agentic Architectures](https://github.com/FareedKhan-dev/all-agentic-architectures)
- [CUDA Programming Guide](https://docs.nvidia.com/cuda/cuda-programming-guide/part4.html)
- [Reddit MCP Buddy](https://github.com/karanb192/reddit-mcp-buddy)
- Twitter/X references (bookmarked for future deep-dive)

---

**Author:** SHML Platform Team  
**Last Updated:** December 7, 2025
