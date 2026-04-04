---
name: coding-assistant
description: "Expert coding assistance using Qwopus (Qwen3.5-27B reasoning distill) with native thinking mode. Use when the user asks for code generation, debugging, code review, refactoring, algorithm design, test creation, or any software engineering task. Preferred for all coding requests that benefit from deep reasoning."
license: MIT
compatibility: Requires qwopus-coding service (Qwopus Q4_K_M) running at CODING_MODEL_URL with --reasoning-format auto
metadata:
  author: shml-platform
  version: "1.1"
  model: Qwopus-Qwen3.5-27B-Q4_K_M
  context_window: 65536
  thinking_enabled: true
  eval_score: "93.8% (vs 79.0% Nemotron baseline)"
allowed-tools: Bash(python3:*) Bash(node:*) Bash(git:*) Bash(pytest:*) Bash(cargo:*) Bash(go:*)
---

# Coding Assistant Skill (Qwopus Optimized)

## When to use this skill

Activate for any task involving:
- Writing new code (any language: Python, TypeScript, Go, Rust, Java, C++, etc.)
- Debugging and error analysis
- Code review and quality assessment
- Refactoring and optimization
- Algorithm and data structure design
- Unit/integration test generation
- API design and documentation
- Performance profiling and optimization
- Architecture guidance and implementation planning
- Explaining existing code

## How to apply this skill

### 1. Leverage Thinking Mode
Qwopus (Qwen3.5-27B reasoning distill) internally reasons before producing output. **Do not**
include "think step by step" instructions — they are redundant and consume context.
Let the model think; focus the prompt on *what* is needed.

```
Good: "Implement a LRU cache with O(1) get/put using Python."
Bad:  "Think step by step, carefully analyze... implement a LRU cache..."
```

### 2. Code Quality Defaults
Always produce code with:
- Type annotations (Python: full typing, TypeScript: strict types)
- Docstrings on all public functions/classes
- Error handling (no bare `except:` in Python, typed errors in TS/Go)
- Test stubs (at minimum: one happy-path test per exported function)

### 3. Iterative Refinement
The ACE Reflector will validate generated code. Structure output to support
easy self-review:
- Separate implementation from tests
- Add inline comments for non-obvious logic
- Include a brief "Assumptions:" block for ambiguous requirements

### 4. Context Window Usage
Qwen3.5 supports 128K tokens. For large codebases:
- Include the most relevant file sections (not entire files)
- Use git diff format for change-focused requests
- Reference file paths explicitly: "in `src/handlers/auth.py`, line 42..."

### 5. Temperature Guidance
The model is served with `--temp 0.6` as default. For coding tasks:
- Code generation: `temperature=0.0–0.2` (most deterministic)
- Creative solution brainstorming: `temperature=0.6–0.8`
- Unit test variety: `temperature=0.4–0.6`

Call routing automatically uses `temperature=0.0` for curator/reflector tasks.

## Patterns to avoid

- **Over-prompting**: Do not pad prompts with meta-instructions. Qwen3.5 is a
  post-trained reasoning model — trust it.
- **Context stuffing**: Do not dump entire files when only functions are needed.
  Token budget for reasoning scales with input length.
- **Skipping docstrings**: All generated code must be self-documenting. The
  reflector will penalize undocumented code with a low `code_quality` rubric score.
- **Ignoring existing patterns**: Always read surrounding code before generating.
  Match naming conventions, import styles, and error handling patterns.

## Evaluation benchmark reference

| Model                   | Tasks Passed | Score  | Thinking |
|-------------------------|:------------:|:------:|:--------:|
| Qwen3.5-35B-A3B Q4_K_M | 135 / 144    | 93.8 % | Enabled  |
| Nemotron-3-Nano-30B     | 113 / 143    | 79.0 % | N/A      |

Qwen3.5 wins every task category: coding (26/28 vs 22/28), tool-use (36/36 vs
26/36), QA (44/44 vs 42/44), reasoning (29/36 vs 23/35).

## Examples

### Generate a Python async endpoint

```python
# Prompt: "Add a POST /v1/completions endpoint to FastAPI that streams Qwen responses"
@app.post("/v1/completions")
async def completions(request: CompletionRequest) -> StreamingResponse:
    """OpenAI-compatible streaming completions."""
    async def generate():
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{settings.GATEWAY_URL}/v1/chat/completions",
                json={"model": "qwopus-coding", "messages": request.messages, "stream": True},
            ) as resp:
                async for chunk in resp.aiter_text():
                    yield chunk
    return StreamingResponse(generate(), media_type="text/event-stream")
```

### Run generated code for validation

```bash
# After generating, execute with ShellSkill to verify:
python3 -c "<generated code snippet>"
pytest tests/test_generated.py -v
```
