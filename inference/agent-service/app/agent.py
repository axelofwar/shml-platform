"""
ACE-based Agent Workflow - Generator-Reflector-Curator Pattern.

Implements the Agentic Context Engineering pattern with:
- Generator: Propose actions using playbook context
- Reflector: Self-critique with Kimi K2-style rubrics
- Curator: Extract lessons learned for future tasks
- Session diary: Track all actions and outcomes
"""

from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from typing import TypedDict, Annotated, List, Dict, Any, Optional, Sequence
import operator
from datetime import datetime
import logging
import httpx
import json
import os

from .context import AgentPlaybook, ContextBullet
from .diary import create_session_diary, ReflectionEngine
from .skills import get_active_skills, format_skill_contexts, SKILLS, execute_skill
from .security import get_system_prompt_preamble, filter_output
from .config import settings
from .skill_evolution import get_evolution_engine
import re

logger = logging.getLogger(__name__)

# Shared httpx client - avoids per-call client creation (memory leak prevention)
# Lazy-initialized on first use, reused across all LLM calls
_shared_http_client: Optional[httpx.AsyncClient] = None


def _get_shared_client() -> httpx.AsyncClient:
    """Get or create a shared httpx.AsyncClient.

    Prevents memory leaks from creating a new client per LLM call.
    Each client holds connection pools, SSL contexts, etc.
    """
    global _shared_http_client
    if _shared_http_client is None or _shared_http_client.is_closed:
        _shared_http_client = httpx.AsyncClient(
            timeout=300.0,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30,
            ),
        )
    return _shared_http_client


def parse_tool_calls(text: str) -> List[Dict[str, Any]]:
    """Parse tool calls from generator output.

    Expected formats:
    1. Multi-line format:
       Tool: GitHubSkill
       Operation: create_issue
       Params: {"repo": "owner/repo", "title": "Bug"}

    2. Inline format:
       [TOOL:GitHubSkill|create_issue|{"repo":"owner/repo"}]

    3. Code block format:
       ```
       Tool: RayJobSkill
       Operation: get_gpu_status
       Params: {}
       ```

    Returns:
        List of parsed tool calls with tool, operation, params

    Note: ShellSkill is ALWAYS preferred for GPU/system queries (shell-first architecture).
    RayJobSkill GPU calls are auto-converted to ShellSkill.gpu_status.
    """
    tool_calls = []

    # Pattern 1: Multi-line format (with or without code blocks)
    # More flexible: handles ** wrapping, various whitespace
    pattern1 = (
        r"Tool:\s*([\w]+)\s*\n\s*Operation:\s*([\w_]+)\s*\n\s*Params:\s*(\{[^}]*\})"
    )
    for match in re.finditer(pattern1, text, re.MULTILINE | re.IGNORECASE):
        try:
            params_str = match.group(3).strip()
            # Handle empty params
            params = json.loads(params_str) if params_str and params_str != "{}" else {}
            tool_calls.append(
                {
                    "tool": match.group(1).strip(),
                    "operation": match.group(2).strip(),
                    "params": params,
                }
            )
            logger.info(
                f"Parsed tool call (pattern1): {match.group(1)}.{match.group(2)}"
            )
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse tool params: {e}, raw: {match.group(3)}")

    # Pattern 2: Inline format [TOOL:Skill|operation|params]
    pattern2 = r"\[TOOL:([\w]+)\|([\w_]+)\|(\{[^}]*\})\]"
    for match in re.finditer(pattern2, text):
        try:
            params_str = match.group(3).strip()
            params = json.loads(params_str) if params_str and params_str != "{}" else {}
            tool_calls.append(
                {
                    "tool": match.group(1).strip(),
                    "operation": match.group(2).strip(),
                    "params": params,
                }
            )
            logger.info(
                f"Parsed tool call (pattern2): {match.group(1)}.{match.group(2)}"
            )
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse inline tool params: {e}")

    # ===== SHELL-FIRST ARCHITECTURE: Override GPU/system queries =====
    # If we parsed RayJobSkill calls for GPU status, convert to ShellSkill
    # ShellSkill is more reliable (nvidia-smi directly, no Ray API auth needed)
    text_lower = text.lower()
    is_gpu_query = "gpu" in text_lower and any(
        w in text_lower
        for w in ["status", "check", "memory", "vram", "utilization", "monitor"]
    )

    if is_gpu_query and tool_calls:
        # Replace any RayJobSkill GPU-related calls with ShellSkill
        converted = []
        for tc in tool_calls:
            if tc["tool"] == "RayJobSkill" and tc["operation"] in [
                "get_status",
                "get_gpu_status",
            ]:
                logger.info(
                    f"SHELL-FIRST: Converting {tc['tool']}.{tc['operation']} → ShellSkill.gpu_status"
                )
                converted.append(
                    {
                        "tool": "ShellSkill",
                        "operation": "gpu_status",
                        "params": {"format": "full"},
                    }
                )
            else:
                converted.append(tc)
        tool_calls = converted

    # Pattern 3: More lenient - tool name followed by operation anywhere
    # ALSO: Smart routing - use ShellSkill for GPU status (nvidia-smi directly is more reliable)
    if not tool_calls:
        text_lower = text.lower()

        # GPU status -> ShellSkill (nvidia-smi directly, not Ray API)
        if "gpu" in text_lower and any(
            w in text_lower
            for w in ["status", "check", "memory", "vram", "utilization", "monitor"]
        ):
            tool_calls.append(
                {
                    "tool": "ShellSkill",
                    "operation": "gpu_status",
                    "params": {"format": "full"},
                }
            )
            logger.info("Inferred tool call: ShellSkill.gpu_status (nvidia-smi direct)")

        # System info -> ShellSkill
        elif any(
            w in text_lower
            for w in ["disk space", "memory usage", "cpu", "system info", "uptime"]
        ):
            component = "all"
            if "disk" in text_lower:
                component = "disk"
            elif "memory" in text_lower or "ram" in text_lower:
                component = "memory"
            elif "cpu" in text_lower:
                component = "cpu"

            tool_calls.append(
                {
                    "tool": "ShellSkill",
                    "operation": "system_info",
                    "params": {"component": component},
                }
            )
            logger.info(f"Inferred tool call: ShellSkill.system_info({component})")

        # Docker status -> ShellSkill
        elif "docker" in text_lower and any(
            w in text_lower for w in ["status", "container", "running", "ps"]
        ):
            tool_calls.append(
                {
                    "tool": "ShellSkill",
                    "operation": "docker_status",
                    "params": {"stats": "stats" in text_lower},
                }
            )
            logger.info("Inferred tool call: ShellSkill.docker_status")

        # Try to find skill mentions and guess operations
        skills_mentioned = []
        for skill in [
            "RayJobSkill",
            "WebSearchSkill",
            "GitHubSkill",
            "SandboxSkill",
            "ShellSkill",
        ]:
            if skill.lower() in text_lower:
                skills_mentioned.append(skill)

        for skill in skills_mentioned:
            if skill == "RayJobSkill":
                # Ray for job management, not GPU status
                if "job" in text_lower:
                    if "list" in text_lower:
                        tool_calls.append(
                            {
                                "tool": "RayJobSkill",
                                "operation": "list_jobs",
                                "params": {},
                            }
                        )
                        logger.info("Inferred tool call: RayJobSkill.list_jobs")
                    elif "submit" in text_lower or "train" in text_lower:
                        tool_calls.append(
                            {
                                "tool": "RayJobSkill",
                                "operation": "submit_job",
                                "params": {},
                            }
                        )
                        logger.info("Inferred tool call: RayJobSkill.submit_job")
            elif skill == "WebSearchSkill":
                # Extract search query from task
                tool_calls.append(
                    {
                        "tool": "WebSearchSkill",
                        "operation": "search",
                        "params": {"query": text[:200], "max_results": 5},
                    }
                )
                logger.info("Inferred tool call: WebSearchSkill.search")

    return tool_calls


class AgentState(TypedDict, total=False):
    """LangGraph state with ACE playbook and session diary."""

    # Messages history
    messages: Annotated[Sequence[Dict], operator.add]

    # Current task
    current_task: str
    task_category: str  # coding, debugging, analysis, etc.
    user_id: str
    session_id: str

    # Multi-modal attachments
    attachments: Optional[
        List[Dict[str, Any]]
    ]  # {id, filename, type, mime_type, size, data (base64)}
    vision_context: Optional[str]  # Extracted context from vision model

    # ACE components (playbook not checkpointed, passed separately)
    playbook: Any  # AgentPlaybook - not serialized by checkpointer
    playbook_bullets_count: int  # Track playbook size for monitoring
    generator_output: Optional[str]
    reflector_output: Optional[str]
    reflector_rubric_scores: Optional[Dict[str, float]]
    curator_lessons: List[str]

    # Tool execution
    tool_results: List[Dict[str, Any]]
    tool_calls_pending: List[Dict[str, Any]]

    # Session diary tracking
    session_diary: List[str]
    generator_actions: List[Dict]
    reflector_analyses: List[Dict]

    # Final synthesized answer
    final_answer: Optional[str]

    # Execution metadata
    start_time: datetime
    success: bool
    error_messages: List[str]

    # WebSocket streaming (optional)
    connection_manager: Optional[Any]
    ws_session_id: Optional[str]


async def call_coding_model(
    prompt: str, temperature: float = 0.0, max_tokens: int = 2048
) -> str:
    """Call Qwen3.5-35B-A3B (thinking enabled) with intelligent routing.

    Routing logic:
    1. Check primary model health first
    2. If primary is healthy -> use primary (Qwen3.5-35B, thinking enabled, 128K ctx)
    3. If primary is unhealthy (yielding to training, error, etc.) -> use fallback (3B)

    This ensures:
    - Training jobs get GPU priority without interruption
    - Chat/agent requests are still served by fallback model
    - Best quality when primary is available (93.8% eval score vs 79% for Nemotron)

    Args:
        prompt: The prompt to send
        temperature: Sampling temperature (Qwen3.5 recommended: 0.6 general / 0.0 code)
        max_tokens: Maximum tokens to generate (does not include thinking tokens)

    Returns:
        Model response text (thinking tokens stripped by llama.cpp, only content returned)
    """
    from .config import settings

    primary_url = settings.GATEWAY_URL
    fallback_url = settings.FALLBACK_MODEL_URL

    client = _get_shared_client()
    if True:  # Preserve indentation block without context manager
        # Step 1: Check primary model health
        use_fallback = False
        try:
            health_response = await client.get(f"{primary_url}/health", timeout=5.0)
            if health_response.status_code == 200:
                health_data = health_response.json()
                if health_data.get("status") != "healthy":
                    reason = health_data.get("reason", "unknown")
                    logger.info(
                        f"Primary model unavailable (reason: {reason}), routing to fallback"
                    )
                    use_fallback = True
            else:
                logger.info(
                    f"Primary model health check failed (status {health_response.status_code}), routing to fallback"
                )
                use_fallback = True
        except Exception as e:
            logger.info(f"Primary model health check error: {e}, routing to fallback")
            use_fallback = True

        # Pattern 37 — ultrathink keyword → max thinking budget
        import re as _re
        _ULTRATHINK_RE = _re.compile(r'\bultrathink\b', _re.IGNORECASE)
        if _ULTRATHINK_RE.search(prompt):
            max_tokens = settings.ULTRATHINK_BUDGET_TOKENS
            logger.info("ultrathink detected → budget_tokens=%d", max_tokens)
        elif max_tokens == 2048 and settings.THINKING_MODE == "auto":
            max_tokens = settings.MAX_THINKING_TOKENS

        # Step 2: Select endpoint based on health check
        if use_fallback:
            endpoint = f"{fallback_url}/v1/chat/completions"
            model_name = "qwen2.5-coder-3b"
        else:
            endpoint = f"{primary_url}/v1/chat/completions"
            model_name = os.getenv("CODING_MODEL_ALIAS", "qwopus-coding")

        # Step 3: Make the inference request
        try:
            logger.info(f"Using model: {model_name} at {endpoint}")
            response = await client.post(
                endpoint,
                json={
                    "model": model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            data = response.json()
            logger.info(f"Successfully generated response with {model_name}")
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            # If we were using primary and it failed, try fallback
            if not use_fallback:
                logger.warning(
                    f"Primary model failed ({e.response.status_code}), trying fallback"
                )
                try:
                    fallback_response = await client.post(
                        f"{fallback_url}/v1/chat/completions",
                        json={
                            "model": "qwen2.5-coder-3b",
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                        },
                    )
                    fallback_response.raise_for_status()
                    data = fallback_response.json()
                    logger.info(
                        "Successfully used fallback model after primary failure"
                    )
                    return data["choices"][0]["message"]["content"]
                except Exception as fallback_error:
                    logger.error(f"Fallback also failed: {fallback_error}")
                    raise
            else:
                logger.error(f"Fallback model failed: {e}")
                raise
        except Exception as e:
            logger.error(f"Failed to call coding model: {e}")
            raise
    raise last_error or Exception("All model endpoints unavailable")


async def call_vision_model(
    prompt: str, image_data: str, temperature: float = 0.7, max_tokens: int = 2048
) -> str:
    """Call Qwen3-VL for vision/multimodal tasks.

    Args:
        prompt: The text prompt
        image_data: Base64-encoded image data (without data URI prefix)
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate

    Returns:
        Model response text with vision analysis
    """
    from .config import settings

    try:
        # Build request payload matching Qwen3-VL schema exactly
        payload = {
            "model": "qwen3-vl-8b",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_data}"
                            },
                        },
                    ],
                }
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        logger.info(
            f"Calling vision model with prompt length: {len(prompt)}, image data length: {len(image_data)}"
        )

        # Qwen3-VL uses OpenAI-compatible format with image_url
        client = _get_shared_client()
        response = await client.post(
            "http://qwen3-vl-api:8000/v1/chat/completions", json=payload
        )

        # Log full error for debugging
        if response.status_code != 200:
            error_detail = response.text
            logger.error(
                f"Vision model returned {response.status_code}: {error_detail}"
            )
            raise Exception(f"Vision API error {response.status_code}: {error_detail}")

        data = response.json()
        result = data["choices"][0]["message"]["content"]
        logger.info(f"Vision model response length: {len(result)}")
        return result

    except httpx.HTTPStatusError as e:
        logger.error(
            f"Vision API HTTP error: {e.response.status_code} - {e.response.text}"
        )
        raise
    except Exception as e:
        logger.error(f"Failed to call vision model: {e}", exc_info=True)
        raise


def parse_rubric_scores(reflection_text: str) -> Dict[str, float]:
    """Parse rubric scores from reflection text.

    Expected format:
    - Clarity: 0.9
    - Accuracy: 0.85
    - Safety: 1.0
    - Actionability: 0.95
    """
    scores = {}
    lines = reflection_text.split("\n")

    for line in lines:
        line = line.strip()
        if ":" in line:
            parts = line.split(":")
            if len(parts) == 2:
                # Extract rubric name (remove leading -, *, numbers)
                rubric = parts[0].strip().lstrip("-*0123456789. ")
                # Extract score
                try:
                    score_text = parts[1].strip()
                    # Try to parse as float
                    score = float(score_text)
                    if 0 <= score <= 1:
                        scores[rubric.lower()] = score
                except ValueError:
                    continue

    return scores


async def generator_node(state: AgentState) -> AgentState:
    """Generate action using playbook context (ACE).

    Retrieves relevant context bullets and generates the next action.
    Supports multi-modal routing for vision tasks.
    """
    logger.info(f"Generator node: task={state['current_task'][:100]}")

    # Stream stage start (if WebSocket connected)
    if state.get("connection_manager") and state.get("ws_session_id"):
        await state["connection_manager"].stream_stage(
            state["ws_session_id"], "generator", "Generator starting..."
        )

    # ===== MULTI-MODAL ROUTING =====
    # Check if task has image attachments and route to vision model first
    attachments = state.get("attachments", [])
    has_images = any(
        att.get("type") == "image" or att.get("mime_type", "").startswith("image/")
        for att in attachments
    )

    if has_images and not state.get("vision_context"):
        # Route to vision model to extract context from images
        logger.info("🖼️ Vision task detected, routing to Qwen3-VL")

        if state.get("connection_manager") and state.get("ws_session_id"):
            await state["connection_manager"].stream_stage(
                state["ws_session_id"], "vision", "Analyzing image with Qwen3-VL..."
            )

        try:
            # Extract first image
            first_image = next(
                att
                for att in attachments
                if att.get("type") == "image"
                or att.get("mime_type", "").startswith("image/")
            )
            image_data = first_image.get("data")

            # Build vision prompt
            vision_prompt = f"""Analyze this image in detail.

User's question: {state['current_task']}

Please provide:
1. **Visual Description**: What do you see in the image?
2. **Key Elements**: Important objects, text, or features
3. **Context**: What is this image likely showing?
4. **Answer**: Direct answer to the user's question based on the image

Be thorough and specific."""

            # Call vision model
            vision_response = await call_vision_model(
                prompt=vision_prompt,
                image_data=image_data,
                temperature=0.7,
                max_tokens=2048,
            )

            # Store vision context in state
            state["vision_context"] = vision_response
            logger.info(f"✅ Vision analysis complete: {len(vision_response)} chars")

            if state.get("connection_manager") and state.get("ws_session_id"):
                await state["connection_manager"].stream_stage(
                    state["ws_session_id"],
                    "vision",
                    f"Vision analysis complete\n\n{vision_response}",
                )

        except Exception as e:
            logger.error(f"Vision model error: {e}")
            state["error_messages"].append(f"Vision analysis failed: {str(e)}")
            # Continue without vision context

    # Build 3-tier context: session memory -> semantic retrieval -> curator lessons
    tiered_context = state["playbook"].build_tiered_context(
        query=state["current_task"],
        session_id=state.get("session_id"),
        budget_chars=12000,
        recent_k=6,
        semantic_k=8,
        curator_k=4,
        min_utility=0.3,
    )
    context_str = tiered_context["context"]
    logger.info(
        "Tiered context built: "
        f"tier1={tiered_context['tiers']['tier1_session']}, "
        f"tier2={tiered_context['tiers']['tier2_semantic']}, "
        f"tier3={tiered_context['tiers']['tier3_curator']}, "
        f"chars={tiered_context['used_chars']}/{tiered_context['budget_chars']}"
    )

    # Get active skill contexts (filtered by user role)
    user_role = state.get("user_role", "viewer")
    skill_contexts = get_active_skills(state["current_task"], user_role=user_role)
    skills_str = (
        format_skill_contexts(skill_contexts)
        if skill_contexts
        else "No skills activated."
    )

    # Prepend role-specific security instructions to the system prompt
    security_preamble = get_system_prompt_preamble(user_role)

    # Detect if task requires direct delivery (code, solution) vs tool usage
    task_lower = state["current_task"].lower()
    needs_direct_delivery = any(
        word in task_lower
        for word in [
            "write",
            "create",
            "implement",
            "build",
            "develop",
            "code",
            "function",
            "class",
            "script",
            "program",
            "solution",
        ]
    )

    # If task explicitly asks for search/research, prioritize that over direct delivery
    needs_search = any(
        word in task_lower
        for word in [
            "search",
            "find",
            "research",
            "look up",
            "investigate",
            "check",
            "web",
        ]
    )

    # Check if we already tried searching and failed (or got empty results)
    search_failed = False
    if state.get("tool_results"):
        for result in state["tool_results"]:
            if result.get("tool") == "WebSearchSkill":
                # Check if result indicates failure or empty results
                res_data = result.get("result", {})
                if "error" in res_data or res_data.get("count", 0) == 0:
                    search_failed = True
                    break

    if needs_search and not search_failed:
        needs_direct_delivery = False
    elif search_failed:
        # If search failed, force direct delivery to avoid loops
        needs_direct_delivery = True
        logger.info("Search failed previously, forcing direct delivery")

    # Prepare vision context section (if available)
    vision_section = ""
    if state.get("vision_context"):
        vision_section = f"""
**Vision Analysis** (from image):
{state['vision_context']}

**Use this vision analysis** to inform your response.
"""

    # Build prompt with context
    if needs_direct_delivery:
        # For direct delivery tasks: Emphasize producing the deliverable
        prompt = f"""You are an AI coding agent. Your job is to WRITE CODE and DELIVER SOLUTIONS directly.

**Task**: {state['current_task']}

**Task Category**: {state['task_category']}
{vision_section}
**Relevant Context from Previous Sessions**:
{context_str}

**Tool Results** (if any):
{json.dumps(state['tool_results'], indent=2) if state['tool_results'] else 'No tools executed yet'}

**CRITICAL INSTRUCTIONS**:
❌ DO NOT output "Analysis", "Action", "Expected Outcome" - these are planning steps
❌ DO NOT describe what you WILL do - just DO IT
❌ DO NOT say "Research the..." or "The task requires..." - DELIVER THE SOLUTION
✅ WRITE THE ACTUAL CODE/IMPLEMENTATION immediately
✅ Include brief explanation AFTER the code
✅ Show working examples

**WRONG (planning-style) output**:
"1. Analysis: The task requires researching...
2. Action: Research the best practices...
3. Expected Outcome: After researching..."

**CORRECT (direct implementation) output**:
"Here's an async download function with exponential backoff:

```python
import asyncio
import aiohttp
from typing import Optional

async def fetch_with_backoff(url: str, max_retries: int = 5) -> Optional[bytes]:
    \"\"\"Download with exponential backoff retry logic.\"\"\"
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    return await response.read()
        except aiohttp.ClientError as e:
            if attempt == max_retries - 1:
                raise
            wait_time = 2 ** attempt
            await asyncio.sleep(wait_time)
    return None

# Usage
content = await fetch_with_backoff('https://example.com/file.zip')
```

**Key features:**
- Exponential backoff: wait time doubles each retry (1s, 2s, 4s, 8s, 16s)
- Handles connection errors gracefully
- Returns None if all retries fail
- Uses async/await for non-blocking I/O"

**Now write your implementation** (code first, explanation after):"""
    else:
        # For research/tool-based tasks: Research THEN synthesize findings
        # Check if task requests code output (code, example, framework, implementation)
        needs_code_output = any(
            word in task_lower
            for word in [
                "code",
                "example",
                "framework",
                "implementation",
                "function",
                "snippet",
            ]
        )

        # Check if we have tool results (search complete)
        has_tool_results = bool(state.get("tool_results"))

        if has_tool_results and needs_code_output:
            # Phase 2: Synthesize research findings into code
            prompt = f"""You are an AI coding agent. The research is DONE. Now WRITE THE CODE.

**Original Task**: {state['current_task']}

**Task Category**: {state['task_category']}
{vision_section}
**Research Results** (already completed):
{json.dumps(state['tool_results'], indent=2)}

**Relevant Context from Previous Sessions**:
{context_str}

**CRITICAL INSTRUCTIONS**:
❌ DO NOT summarize the research again - we already have it
❌ DO NOT describe what the code should do - WRITE THE ACTUAL CODE
❌ DO NOT output planning steps like "1. Analysis 2. Action 3. Expected"
✅ WRITE COMPLETE, RUNNABLE CODE immediately
✅ Use SOTA patterns from the research above
✅ Include docstrings and inline comments
✅ Show usage examples

**Format**:
Brief intro sentence → Code block → Usage example → Key features list

**Example**:
"Based on the research, here's a production-ready async downloader:

```python
import asyncio
import boto3
from botocore.config import Config
from typing import List, Optional

async def download_s3_batch(
    bucket: str,
    keys: List[str],
    max_concurrent: int = 10
) -> List[bytes]:
    \"\"\"Download multiple S3 objects concurrently with retry logic.\"\"\"
    config = Config(
        retries={'mode': 'adaptive', 'max_attempts': 5}
    )
    s3_client = boto3.client('s3', config=config)

    async def download_one(key: str) -> bytes:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: s3_client.get_object(Bucket=bucket, Key=key)
        )
        return response['Body'].read()

    # Limit concurrency with semaphore
    semaphore = asyncio.Semaphore(max_concurrent)

    async def bounded_download(key: str) -> bytes:
        async with semaphore:
            return await download_one(key)

    tasks = [bounded_download(key) for key in keys]
    return await asyncio.gather(*tasks)

# Usage
files = await download_s3_batch(
    bucket='my-bucket',
    keys=['data1.json', 'data2.json', 'data3.json'],
    max_concurrent=10
)
```

**Key features from research:**
- Adaptive retry mode with max 5 attempts (boto3 best practice)
- Semaphore limits concurrent connections to avoid throttling
- run_in_executor makes boto3 sync calls work with asyncio
- Returns all files in original order via gather()"

**Now write your implementation using the research:**"""
        else:
            # Phase 1: Standard tool usage for research
            prompt = f"""You are an AI agent with TOOL EXECUTION capabilities.

**Task**: {state['current_task']}

**Task Category**: {state['task_category']}
{vision_section}
**Available Skills (USE THEM!)**:
{skills_str}

**Relevant Context from Previous Sessions**:
{context_str}

**CRITICAL: You MUST execute tools for tasks like "check status", "search", "find", "get info"**

**TOOL CALL FORMAT (use this EXACT format)**:
```
Tool: ShellSkill
Operation: gpu_status
Params: {{"format": "full"}}
```

**Available Operations by Skill:**
- ShellSkill (PREFERRED for system info):
  - gpu_status: Get GPU info via nvidia-smi (format: "full"|"brief"|"json")
  - system_info: Get CPU/memory/disk info (component: "cpu"|"memory"|"disk"|"all")
  - docker_status: List running containers (stats: true|false)
  - run: Execute safe shell command (command: string)
- RayJobSkill (for distributed training):
  - submit_job, submit_face_detection, list_jobs, get_status, cancel_job
- WebSearchSkill: search (params: query, max_results)
- GitHubSkill: create_issue, search_code (params: query)
- SandboxSkill: run_python, run_bash

**ROUTING RULES:**
- GPU status/memory/utilization → ShellSkill.gpu_status (nvidia-smi directly)
- System info (CPU, RAM, disk) → ShellSkill.system_info
- Docker containers → ShellSkill.docker_status
- Training jobs → RayJobSkill
- Web research → WebSearchSkill

**EXAMPLES**:

For "Check GPU status":
```
Tool: ShellSkill
Operation: gpu_status
Params: {{"format": "full"}}
```

For "List Ray jobs":
```
Tool: RayJobSkill
Operation: list_jobs
Params: {{}}
```

For "Search for X":
```
Tool: WebSearchSkill
Operation: search
Params: {{"query": "X topic", "max_results": 5}}
```

**Your Response Must Include:**
1. Brief analysis (1-2 sentences)
2. Tool call in the exact format above
3. Expected outcome

**START YOUR RESPONSE:**
"""

    # Prepend role-specific security instructions to the prompt
    prompt = security_preamble + prompt

    # Call LLM
    response = await call_coding_model(prompt, temperature=0.0)

    # Apply output filtering to prevent secret leakage
    response, redacted_count = filter_output(response, user_role)
    if redacted_count > 0:
        logger.warning(
            f"SECURITY: Filtered {redacted_count} sensitive patterns from LLM response for role '{user_role}'"
        )

    logger.info(f"Generator response length: {len(response)}")
    logger.info(f"Generator response preview: {response[:100]}")

    # Stream generator output (if WebSocket connected)
    if state.get("connection_manager") and state.get("ws_session_id"):
        await state["connection_manager"].send_message(
            state["ws_session_id"],
            {
                "type": "stage_output",
                "stage": "generator",
                "content": response,
            },
        )

    # Parse tool calls from output
    tool_calls = parse_tool_calls(response)
    if tool_calls:
        state["tool_calls_pending"] = tool_calls
        logger.info(
            f"Parsed {len(tool_calls)} tool calls: {[t['tool'] for t in tool_calls]}"
        )

    # Add to playbook as generator bullet
    state["playbook"].add_bullet(
        content=f"Generated action for '{state['current_task'][:50]}': {response[:200]}...",
        category="generator",
        source="agent",
        session_id=state["session_id"],
    )

    # Update state
    state["generator_output"] = response
    state["session_diary"].append(f"[GENERATOR] {response}")
    state["generator_actions"].append(
        {
            "timestamp": datetime.now().isoformat(),
            "content": response,
            "context_bullets_used": len(relevant_bullets),
            "skills_activated": [
                skill.__name__
                for skill in SKILLS
                if skill.is_activated(state["current_task"])
            ],
            "tool_calls": tool_calls,
        }
    )

    logger.info(f"Generator produced action with {len(tool_calls)} tool calls")
    return state


async def reflector_node(state: AgentState) -> AgentState:
    """Analyze generator output with Kimi K2-style rubrics (ACE).

    Evaluates:
    - Clarity: Is the action clear and unambiguous?
    - Accuracy: Does it correctly address the task?
    - Safety: Are there any risks or violations?
    - Actionability: Can this be executed?
    """
    logger.info("Reflector node: analyzing generator output")

    # Stream stage start (if WebSocket connected)
    if state.get("connection_manager") and state.get("ws_session_id"):
        await state["connection_manager"].stream_stage(
            state["ws_session_id"],
            "reflector",
            "Evaluating action with rubric scores...",
        )

    # Build reflection prompt
    prompt = f"""Analyze the following agent action:

**Original Task**: {state['current_task']}

**Generator's Proposed Action**:
{state['generator_output']}

**Tool Results** (if any):
{json.dumps(state['tool_results'], indent=2) if state['tool_results'] else 'No tools executed yet'}

**Evaluate on these rubrics** (score 0-1):

1. **Clarity**: Is the action clear and unambiguous?
   - 1.0: Completely clear, no ambiguity
   - 0.5: Somewhat clear, some ambiguity
   - 0.0: Unclear or confusing

2. **Accuracy**: Does it correctly address the task?
   - 1.0: Fully addresses the task
   - 0.5: Partially addresses the task
   - 0.0: Does not address the task

3. **Safety**: Are there any risks or policy violations?
   - 1.0: Completely safe
   - 0.5: Minor risks
   - 0.0: Significant risks or violations

4. **Actionability**: Can this be executed immediately?
   - 1.0: Ready to execute
   - 0.5: Needs minor clarification
   - 0.0: Not actionable

**Format your response as**:
- Clarity: [score]
  - Justification: [brief explanation]
- Accuracy: [score]
  - Justification: [brief explanation]
- Safety: [score]
  - Justification: [brief explanation]
- Actionability: [score]
  - Justification: [brief explanation]

**Summary**: [overall assessment and recommendations]
"""

    # Call LLM
    reflection = await call_coding_model(prompt, temperature=0.0)

    # Parse rubric scores
    rubric_scores = parse_rubric_scores(reflection)

    # Stream reflector output (if WebSocket connected)
    if state.get("connection_manager") and state.get("ws_session_id"):
        await state["connection_manager"].send_message(
            state["ws_session_id"],
            {
                "type": "stage_output",
                "stage": "reflector",
                "content": reflection,
                "rubric_scores": rubric_scores,
            },
        )

    # Add to playbook as reflector bullet
    state["playbook"].add_bullet(
        content=f"Reflection on action: {reflection[:200]}...",
        category="reflector",
        source="agent",
        session_id=state["session_id"],
        rubric_scores=rubric_scores,
    )

    # Update state
    state["reflector_output"] = reflection
    state["reflector_rubric_scores"] = rubric_scores
    state["session_diary"].append(f"[REFLECTOR] {reflection}")
    state["reflector_analyses"].append(
        {
            "timestamp": datetime.now().isoformat(),
            "content": reflection,
            "rubric_scores": rubric_scores,
        }
    )

    logger.info(f"Reflector completed: rubric_scores={rubric_scores}")
    return state


async def curator_node(state: AgentState) -> AgentState:
    """Curate knowledge from completed task (ACE).

    Extracts lessons learned and patterns for future tasks.
    """
    logger.info("Curator node: extracting lessons learned")

    # Stream stage start (if WebSocket connected)
    if state.get("connection_manager") and state.get("ws_session_id"):
        await state["connection_manager"].stream_stage(
            state["ws_session_id"], "curator", "Extracting lessons learned..."
        )

    # Build curation prompt
    prompt = f"""Extract lessons learned from this agent session:

**Task**: {state['current_task']}

**Generator Actions**:
{state['generator_output']}

**Reflector Analysis**:
{state['reflector_output']}

**Tool Results**:
{json.dumps(state['tool_results'], indent=2) if state['tool_results'] else 'No tools executed'}

**Rubric Scores**:
{json.dumps(state['reflector_rubric_scores'], indent=2) if state['reflector_rubric_scores'] else 'No scores'}

**Success**: {state.get('success', False)}

**Errors** (if any):
{json.dumps(state['error_messages'], indent=2) if state.get('error_messages') else 'None'}

**Extract 1-3 key lessons** that should be retained for future similar tasks:

Format as:
1. [Lesson about what worked or didn't work]
2. [Pattern or strategy to apply/avoid]
3. [Important context or constraint]

Focus on:
- What worked well (if successful)
- What went wrong (if errors occurred)
- Key constraints or requirements
- Patterns for similar tasks
"""

    # Call LLM
    lessons_text = await call_coding_model(prompt, temperature=0.0)

    # Parse lessons (each numbered item)
    lessons = []
    for line in lessons_text.split("\n"):
        line = line.strip()
        if line and (line[0].isdigit() or line.startswith("-") or line.startswith("*")):
            lesson = line.lstrip("0123456789.-* ")
            if len(lesson) > 20:  # Meaningful lesson
                lessons.append(lesson)

    # Add to playbook as high-value curator bullets
    for lesson in lessons:
        state["playbook"].add_bullet(
            content=lesson,
            category="curator",
            source="agent",
            session_id=state["session_id"],
            rubric_scores={"importance": 0.95, "actionable": 1.0},
        )

    # Update state
    state["curator_lessons"] = lessons
    state["session_diary"].append(f"[CURATOR] Extracted {len(lessons)} lessons")

    # ── GEPA: trigger skill evolution / auto-creation ─────────────────────
    if lessons:
        try:
            evolution_engine = get_evolution_engine(
                base_url=settings.GATEWAY_URL
            )
            evolution_results = await evolution_engine.process_lessons(
                lessons, session_id=state.get("session_id", "unknown")
            )
            if evolution_results:
                summary = evolution_engine.summarize_evolution_results(evolution_results)
                state["session_diary"].append(summary)
                logger.info(f"GEPA completed: {len(evolution_results)} skill updates")
                # Log individual results to playbook so they are visible in UI
                for result in evolution_results:
                    if result.action in ("created", "evolved"):
                        state["playbook"].add_bullet(
                            content=result.message,
                            category="gepa-evolution",
                            source="agent",
                            session_id=state.get("session_id", "unknown"),
                            rubric_scores={"importance": 0.9, "actionable": 1.0},
                        )
        except Exception as gepa_err:
            # GEPA is non-blocking — never fail the main workflow
            logger.warning(f"GEPA evolution error (non-fatal): {gepa_err}")
    # ─────────────────────────────────────────────────────────────────────

    logger.info(f"Curator extracted {len(lessons)} lessons")
    return state


async def synthesizer_node(state: AgentState) -> AgentState:
    """Synthesize final answer from all workflow outputs (SOTA pattern).

    This node creates the actual user-facing response by combining:
    - Generator outputs (code/implementation if any)
    - Tool results (search findings, execution results)
    - Reflector validation
    - Curator lessons

    SMART FALLBACK: If tool results are incomplete/unavailable,
    uses ShellSkill to get direct system information.

    The final_answer is what gets displayed to the user.
    """
    logger.info("Synthesizer node: generating final answer")

    # Stream stage start (if WebSocket connected)
    if state.get("connection_manager") and state.get("ws_session_id"):
        await state["connection_manager"].stream_stage(
            state["ws_session_id"], "synthesizer", "Generating final response..."
        )

    # Collect all generator outputs (may have multiple iterations)
    all_generator_outputs = [
        action.get("content", "") for action in state.get("generator_actions", [])
    ]

    # Find code blocks in generator outputs
    code_blocks = []
    for output in all_generator_outputs:
        if "```" in output:
            # Extract code blocks
            import re

            blocks = re.findall(r"```[\w]*\n(.*?)```", output, re.DOTALL)
            code_blocks.extend(blocks)

    # Collect tool results
    tool_results = state.get("tool_results", [])
    successful_tools = [t for t in tool_results if t.get("success", False)]
    failed_tools = [t for t in tool_results if not t.get("success", False)]

    # Check if tool results are incomplete/unhelpful
    needs_shell_fallback = False
    task_lower = state.get("current_task", "").lower()

    # Keywords that suggest we need detailed system info
    gpu_keywords = ["gpu", "nvidia", "cuda", "vram", "memory", "utilization"]
    system_keywords = ["status", "check", "monitor", "metrics", "info"]

    is_gpu_task = any(kw in task_lower for kw in gpu_keywords)
    is_system_task = any(kw in task_lower for kw in system_keywords)

    # Check if tool results are incomplete or failed
    needs_shell_fallback = False
    if is_gpu_task:
        # Check if we got actual detailed GPU data
        has_detailed_gpu = False
        for tr in successful_tools:
            result = tr.get("result", {})
            # Check for detailed metrics
            if isinstance(result, dict):
                # Has actual VRAM numbers?
                result_str = json.dumps(result)
                if any(
                    metric in result_str
                    for metric in [
                        "memory.used",
                        "utilization",
                        "temperature",
                        "MiB",
                        "GPU",
                        "RTX",
                        "GeForce",
                    ]
                ):
                    has_detailed_gpu = True
                    break
            elif isinstance(result, str) and (
                "GPU" in result or "nvidia" in result.lower()
            ):
                has_detailed_gpu = True
                break

        # Fallback if:
        # 1. No successful tools at all
        # 2. Successful tools but no detailed GPU data
        # 3. Only failed tools
        if (
            not successful_tools
            or not has_detailed_gpu
            or (failed_tools and not successful_tools)
        ):
            needs_shell_fallback = True
            logger.info(
                f"GPU task needs ShellSkill fallback: successful={len(successful_tools)}, has_detailed={has_detailed_gpu}, failed={len(failed_tools)}"
            )

    # Smart fallback: Use ShellSkill to get detailed info
    shell_results = {}
    if needs_shell_fallback:
        try:
            # Get detailed GPU info via nvidia-smi or alternatives
            shell_result = await execute_skill(
                skill_name="ShellSkill",
                operation="gpu_status",
                params={"format": "full"},
            )
            if shell_result and not shell_result.get("error"):
                shell_results["gpu_status"] = shell_result
                # Add to tool results for synthesis
                state["tool_results"].append(
                    {
                        "tool": "ShellSkill",
                        "operation": "gpu_status",
                        "params": {"format": "full"},
                        "result": shell_result,
                        "timestamp": datetime.now().isoformat(),
                        "success": True,
                        "fallback": True,  # Mark as fallback
                    }
                )
                successful_tools.append(state["tool_results"][-1])
                logger.info("ShellSkill GPU fallback successful")
        except Exception as e:
            logger.warning(f"ShellSkill fallback failed: {e}")

    # Get lessons
    lessons = state.get("curator_lessons", [])

    # Get rubric scores
    rubric_scores = state.get("reflector_rubric_scores", {})
    avg_score = sum(rubric_scores.values()) / len(rubric_scores) if rubric_scores else 0

    # Determine response type based on task

    # Check if this was a simple greeting/question (no tools, no code needed)
    is_simple_task = (
        not tool_results
        and not code_blocks
        and any(
            word in task_lower
            for word in ["hello", "hi", "hey", "what can you", "who are you", "help"]
        )
    )

    if is_simple_task:
        # For simple tasks, generate a direct conversational response
        prompt = f"""You are a helpful AI coding assistant. Respond directly to this message:

**User's Message**: {state['current_task']}

**Guidelines**:
- Be friendly and helpful
- If asked what you can do, list your capabilities
- Be concise but complete
- No need for code unless specifically asked

Respond naturally:"""

        final_answer = await call_coding_model(prompt, temperature=0.7, max_tokens=1024)

    elif is_gpu_task or is_system_task:
        # System/GPU status task: format the data nicely
        prompt = f"""Format this system information into a clear, helpful response:

**User's Request**: {state['current_task']}

**Raw Data**:
{json.dumps([t.get('result', {}) for t in successful_tools], indent=2)}

**Instructions**:
1. Present the information clearly with proper formatting
2. Use tables or bullet points for metrics
3. Highlight any important values (high usage, temperature, etc.)
4. Provide brief interpretation or recommendations if relevant
5. Be concise but complete

Format the response with proper markdown:"""

        final_answer = await call_coding_model(prompt, temperature=0.2, max_tokens=1500)

        # If we still don't have a good response, fall back to raw data
        if len(final_answer.strip()) < 50:
            # Use raw shell output directly if available
            for tr in successful_tools:
                if tr.get("tool") == "ShellSkill":
                    stdout = tr.get("result", {}).get("stdout", "")
                    if stdout:
                        final_answer = f"**GPU Status:**\n```\n{stdout}\n```"
                        break

    elif code_blocks or any(
        word in task_lower for word in ["code", "implement", "create", "build", "write"]
    ):
        # Code-focused task: prioritize the implementation
        best_code = None
        best_output = ""

        # Find the most complete code output
        for output in reversed(all_generator_outputs):
            if "```" in output and len(output) > len(best_output):
                best_output = output

        if best_output:
            # Use the code output directly as the answer
            final_answer = best_output

            # Append tool context if relevant
            if successful_tools:
                tool_context = "\n\n---\n\n**📊 Research/Tool Results Used:**\n"
                for tool in successful_tools[:3]:  # Top 3 tools
                    tool_name = f"{tool.get('tool', '')}.{tool.get('operation', '')}"
                    result_preview = str(tool.get("result", ""))[:200]
                    tool_context += f"- `{tool_name}`: {result_preview}...\n"
                final_answer += tool_context
        else:
            # No code found, synthesize from tools and generator
            final_answer = (
                all_generator_outputs[-1]
                if all_generator_outputs
                else "I was unable to generate a response."
            )

    elif tool_results:
        # Tool-based task: synthesize findings into actionable response
        prompt = f"""Synthesize these results into a clear, helpful response:

**Original Task**: {state['current_task']}

**Tool Results**:
{json.dumps(successful_tools, indent=2)}

**Generator Analysis**:
{all_generator_outputs[-1] if all_generator_outputs else 'No analysis available'}

**Failed Tools** (for context):
{json.dumps(failed_tools, indent=2) if failed_tools else 'None'}

**Instructions**:
1. Summarize the key findings from tool results
2. Provide actionable insights or recommendations
3. Include relevant code examples if appropriate
4. Be direct and helpful

Synthesized Response:"""

        final_answer = await call_coding_model(prompt, temperature=0.3, max_tokens=2048)

    else:
        # Fallback: use the last generator output
        final_answer = (
            all_generator_outputs[-1]
            if all_generator_outputs
            else "I was unable to generate a response for this task."
        )

    # === DETECT MISSING DEPENDENCIES & SUGGEST NEXT ACTIONS ===
    # Check if any tools failed due to missing deps
    missing_deps = []
    suggested_actions = []

    for tr in failed_tools:
        result = tr.get("result", {})
        error = result.get("error", "") if isinstance(result, dict) else str(result)
        error_lower = error.lower()

        # nvidia-smi not found
        if "nvidia-smi" in error_lower and "not found" in error_lower:
            missing_deps.append("nvidia-smi")
            suggested_actions.append(
                {
                    "description": "Install NVIDIA drivers",
                    "command": "sudo apt install nvidia-driver-535",
                    "reason": "nvidia-smi not available",
                }
            )

        # Docker not accessible
        if "docker" in error_lower and (
            "permission" in error_lower or "not found" in error_lower
        ):
            missing_deps.append("docker")
            suggested_actions.append(
                {
                    "description": "Fix Docker permissions",
                    "command": "sudo usermod -aG docker $USER && newgrp docker",
                    "reason": "Docker daemon not accessible",
                }
            )

        # Ray API auth failure
        if "401" in error or "unauthorized" in error_lower:
            suggested_actions.append(
                {
                    "description": "Authenticate with Ray API",
                    "command": "shml auth login",
                    "reason": "Ray API requires authentication",
                }
            )

        # Service not running
        if "connect" in error_lower and (
            "refused" in error_lower or "failed" in error_lower
        ):
            service_name = tr.get("tool", "service")
            suggested_actions.append(
                {
                    "description": f"Start {service_name} service",
                    "command": f"./start_all_safe.sh restart inference",
                    "reason": f"{service_name} service not responding",
                }
            )

    # Add suggestions to final answer if there are any
    if suggested_actions:
        suggestions_section = "\n\n---\n\n**⚠️ Action Required:**\n"
        for action in suggested_actions[:3]:  # Top 3 suggestions
            suggestions_section += f"\n**{action['description']}**\n"
            suggestions_section += f"  - Reason: {action['reason']}\n"
            suggestions_section += f"  - Command: `{action['command']}`\n"

        suggestions_section += "\nWould you like me to help with any of these?\n"
        final_answer += suggestions_section

    # Add lessons learned section if valuable
    if lessons and avg_score >= 0.7:
        lessons_section = "\n\n---\n\n**💡 Key Insights:**\n" + "\n".join(
            f"- {l}" for l in lessons[:3]
        )
        final_answer += lessons_section

    # Update state
    state["final_answer"] = final_answer
    state["session_diary"].append(
        f"[SYNTHESIZER] Generated final answer ({len(final_answer)} chars)"
    )

    # Stream final answer (if WebSocket connected)
    if state.get("connection_manager") and state.get("ws_session_id"):
        await state["connection_manager"].send_message(
            state["ws_session_id"],
            {
                "type": "final_answer",
                "stage": "synthesizer",
                "content": final_answer,
                "success": state.get("success", True),
            },
        )

    logger.info(f"Synthesizer generated final answer ({len(final_answer)} chars)")
    return state


async def tool_execution_node(state: AgentState) -> AgentState:
    """Execute pending tool calls using composable skills.

    Executes tools from the generator's proposed actions.
    """
    logger.info(
        f"Tool execution node: {len(state.get('tool_calls_pending', []))} tools pending"
    )

    # Stream stage start (if WebSocket connected)
    if state.get("connection_manager") and state.get("ws_session_id"):
        await state["connection_manager"].stream_stage(
            state["ws_session_id"],
            "tools",
            f"Executing {len(state.get('tool_calls_pending', []))} tool(s)...",
        )

    if state.get("tool_calls_pending"):
        for tool_call in state["tool_calls_pending"]:
            tool_name = tool_call.get("tool")
            operation = tool_call.get("operation")
            params = tool_call.get("params", {})

            logger.info(f"Executing: {tool_name}.{operation}({params})")

            try:
                # Execute skill using the helper function
                result = await execute_skill(
                    skill_name=tool_name, operation=operation, params=params
                )

                # Add result to state
                state["tool_results"].append(
                    {
                        "tool": tool_name,
                        "operation": operation,
                        "params": params,
                        "result": result,
                        "timestamp": datetime.now().isoformat(),
                        "success": "error" not in result,
                    }
                )

                # Add result to playbook for future context
                state["playbook"].add_bullet(
                    content=f"Tool {tool_name}.{operation} result: {str(result)[:200]}",
                    category="tool_result",
                    source="agent",
                    session_id=state["session_id"],
                )

                # Stream tool result (if WebSocket connected)
                if state.get("connection_manager") and state.get("ws_session_id"):
                    await state["connection_manager"].send_message(
                        state["ws_session_id"],
                        {
                            "type": "tool_result",
                            "stage": "tools",
                            "content": f"{tool_name}.{operation} completed",
                            "tool": tool_name,
                            "operation": operation,
                            "result": result,
                            "success": True,
                        },
                    )

                logger.info(f"Tool {tool_name}.{operation} executed successfully")

            except Exception as e:
                logger.error(f"Tool execution failed: {tool_name}.{operation} - {e}")
                state["tool_results"].append(
                    {
                        "tool": tool_name,
                        "operation": operation,
                        "params": params,
                        "error": str(e),
                        "timestamp": datetime.now().isoformat(),
                        "success": False,
                    }
                )
                state["error_messages"].append(
                    f"Tool error: {tool_name}.{operation} - {str(e)}"
                )

        # Clear pending tool calls
        state["tool_calls_pending"] = []

    return state


def should_execute_tools(state: AgentState) -> str:
    """Router: Execute tools or go straight to reflection?

    Checks if generator output contains parsed tool calls.
    """
    # Check if we have pending tool calls
    tool_calls_pending = state.get("tool_calls_pending", [])

    if tool_calls_pending:
        logger.info(
            f"Routing to tool execution: {len(tool_calls_pending)} tools pending"
        )
        return "execute_tools"

    logger.info("No tools needed, routing to reflector")
    return "reflect"


def should_continue(state: AgentState) -> str:
    """Router: Continue iteration until quality threshold is met.

    QUALITY-DRIVEN ITERATION:
    The agent should iterate until the response meets a quality threshold.
    This follows the pattern of reasoning models that refine until confident.

    Decision logic:
    1. If rubric scores below QUALITY_THRESHOLD (0.75) → Continue (improve)
    2. If tool execution failed and fallback available → Continue (retry with ShellSkill)
    3. If task needs code output AND we have tool results BUT no code yet → Continue (Phase 2)
    4. If max iterations (5) reached → Finish (prevent infinite loops)
    5. Otherwise → Finish (quality threshold met)
    """
    QUALITY_THRESHOLD = 0.75  # Minimum score to accept response
    MAX_ITERATIONS = 5  # Safety limit

    rubric_scores = state.get("reflector_rubric_scores", {})
    iteration_count = len(state.get("generator_actions", []))
    tool_results = state.get("tool_results", [])

    # Safety: Max iterations
    if iteration_count >= MAX_ITERATIONS:
        logger.info(f"Max iterations reached ({MAX_ITERATIONS}), finishing")
        return "finish"

    # Check for failed tools that might benefit from retry with different approach
    failed_tools = [tr for tr in tool_results if not tr.get("success", False)]
    has_shell_fallback = not any(tr.get("tool") == "ShellSkill" for tr in tool_results)

    if failed_tools and has_shell_fallback and iteration_count < 3:
        logger.info(
            f"Tools failed ({len(failed_tools)}), ShellSkill fallback available → CONTINUE"
        )
        # Add hint for next iteration to use ShellSkill
        state["_use_shell_fallback"] = True
        return "continue"

    # No rubric scores yet - first iteration
    if not rubric_scores:
        logger.info("No rubric scores yet, finishing first iteration")
        return "finish"

    # Calculate average score
    avg_score = sum(rubric_scores.values()) / len(rubric_scores) if rubric_scores else 0
    min_score = min(rubric_scores.values()) if rubric_scores else 0

    # Check if task requires code/implementation output
    task_lower = state.get("current_task", "").lower()
    needs_code_output = any(
        word in task_lower
        for word in [
            "code",
            "example",
            "framework",
            "implementation",
            "function",
            "snippet",
            "provide",
            "build",
            "create",
            "write",
        ]
    )

    # Check if we have tool results (Phase 1 complete)
    has_tool_results = bool(tool_results)

    # Check if generator already produced code
    generator_output = state.get("generator_output", "")
    has_code_block = "```" in generator_output

    # SOTA Logic: Two-phase synthesis pattern
    if (
        needs_code_output
        and has_tool_results
        and not has_code_block
        and iteration_count < 3
    ):
        logger.info(
            "Phase 2: Tool results available, need to synthesize into code → CONTINUE"
        )
        return "continue"

    # QUALITY CHECK: All scores must meet threshold
    if avg_score >= QUALITY_THRESHOLD and min_score >= 0.6:
        logger.info(
            f"Quality threshold met (avg={avg_score:.2f}, min={min_score:.2f}), finishing"
        )
        return "finish"

    # Low quality - continue iterating
    if iteration_count < 3:  # Only retry 2 more times after initial
        logger.info(
            f"Quality below threshold (avg={avg_score:.2f}), continuing iteration {iteration_count}"
        )
        return "continue"

    # Exhausted retries
    logger.info("Quality threshold not met but max retries exhausted, finishing")
    return "finish"


def build_ace_agent():
    """Build LangGraph agent with ACE pattern.

    Workflow:
    1. Generator: Propose action with playbook context
    2. [Optional] Tools: Execute tools if needed
    3. Reflector: Self-critique with rubrics
    4. [Optional] Loop back to Generator if scores low
    5. Curator: Extract lessons learned
    6. Synthesizer: Generate final user-facing answer
    """
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("generator", generator_node)
    workflow.add_node("reflector", reflector_node)
    workflow.add_node("curator", curator_node)
    workflow.add_node("synthesizer", synthesizer_node)
    workflow.add_node("tools", tool_execution_node)

    # Set entry point
    workflow.set_entry_point("generator")

    # Add conditional edges
    workflow.add_conditional_edges(
        "generator",
        should_execute_tools,
        {
            "execute_tools": "tools",
            "reflect": "reflector",
        },
    )

    # Tools always go to reflector
    workflow.add_edge("tools", "reflector")

    # Reflector decides whether to continue or finish
    workflow.add_conditional_edges(
        "reflector",
        should_continue,
        {
            "continue": "generator",  # Loop back for improvement
            "finish": "curator",
        },
    )

    # Curator goes to synthesizer
    workflow.add_edge("curator", "synthesizer")

    # Synthesizer is the end
    workflow.add_edge("synthesizer", END)

    # Compile without checkpointer for now (playbook stored in PostgreSQL)
    # TODO: Implement custom serialization for AgentPlaybook to enable checkpointing
    return workflow.compile()


# Export compiled agent
ace_agent = build_ace_agent()
