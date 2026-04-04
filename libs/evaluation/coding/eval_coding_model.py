#!/usr/bin/env python3
"""
Qwen3.5-35B-A3B vs Nemotron-3-Nano-30B-A3B — Full Ecosystem Evaluation
======================================================================

Comprehensive comparison of local coding models across the ENTIRE platform
ecosystem, not just isolated tasks. Tests how each model performs when driving
the full agent harness, skill evolution, memory management, and pipeline
orchestration workflows.

Dimensions tested:
  1. Coding accuracy (function generation, bug fixing, refactoring)
  2. Agentic tool use (structured JSON tool calls, multi-step plans)
  3. Long-context retrieval (needle-in-haystack at various depths)
  4. Throughput (tokens/sec, time-to-first-token)
  5. VRAM headroom (memory usage at steady state and peak)
  --- ECOSYSTEM ---
  6. Hermes/GEPA skill evolution (read skill → critique → propose improvement)
  7. Obsidian memory management (ingest → link → retrieve → update)
  8. ACE agent orchestration (Generator → Reflector → tool calls → synthesis)
  9. MCP tool routing (parse schemas, choose tools, handle failures)
  10. Pipeline orchestration (multi-step training → eval → analysis flows)

Usage:
  # Full ecosystem eval (managed A/B — starts each model sequentially on GPU 0):
  ./ray_compute/jobs/evaluation/run_model_ab_eval.sh

  # Manual: compare both models (both must be running):
  python eval_coding_model.py --nemotron-url http://localhost:8010/v1 \
                               --qwen-url http://localhost:8020/v1 \
                               --output results/coding_model_eval.json

  # Single model benchmark:
  python eval_coding_model.py --target qwen --qwen-url http://localhost:8020/v1

  # Specific category:
  python eval_coding_model.py --target qwen --category ecosystem

  # Dry run (print prompts, skip inference):
  python eval_coding_model.py --dry-run

References:
  - Nemotron config:  inference/qwopus/docker-compose.yml
  - Qwen config:      inference/qwen/docker-compose.yml
  - Agent service:    inference/agent-service/app/agent.py (ACE pattern)
  - Skills:           inference/agent-service/app/skills.py (ShellSkill, etc.)
  - MCP:              inference/agent-service/app/mcp.py (tool definitions)
  - Hardware:         RTX 3090 Ti (24GB) + RTX 2070 (8GB) + 64GB RAM
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

# ═══════════════════════════════════════════════════════════════════════════
# EVALUATION TASKS
# ═══════════════════════════════════════════════════════════════════════════

CODING_TASKS = [
    {
        "id": "code-01-function",
        "category": "coding",
        "name": "Generate YOLO callback",
        "prompt": (
            "Write a Python class `EarlyStopOnPlateau` that acts as an Ultralytics YOLO callback. "
            "It should:\n"
            "1. Track `metrics/recall(B)` each epoch\n"
            "2. If recall hasn't improved by at least `min_delta=0.005` for `patience=10` consecutive epochs, "
            "set a flag `trainer.stop = True`\n"
            "3. Log the best recall and the epoch it was achieved\n"
            "4. Include a `register(model)` method that hooks `on_train_epoch_end`\n\n"
            "Use type hints and docstrings."
        ),
        "check_contains": [
            "class EarlyStopOnPlateau",
            "on_train_epoch_end",
            "trainer.stop",
            "min_delta",
            "patience",
            "register",
        ],
        "max_tokens": 1024,
    },
    {
        "id": "code-02-bugfix",
        "category": "coding",
        "name": "Fix OOM retry logic",
        "prompt": (
            "This function has a bug. The `batch` variable is used in the retry but was already "
            "freed. Fix it:\n\n"
            "```python\n"
            "def train_with_retry(model, data, batch, imgsz):\n"
            "    try:\n"
            "        model.train(data=data, batch=batch, imgsz=imgsz)\n"
            "    except torch.cuda.OutOfMemoryError:\n"
            "        del model\n"
            "        gc.collect()\n"
            "        torch.cuda.empty_cache()\n"
            "        model = YOLO(weights)\n"
            "        model.train(data=data, batch=batch // 2, imgsz=imgsz)\n"
            "```\n\n"
            "Explain the bug and provide the corrected code."
        ),
        "check_contains": ["new_batch", "batch // 2", "weights"],
        "max_tokens": 768,
    },
    {
        "id": "code-03-refactor",
        "category": "coding",
        "name": "Extract config from hardcoded values",
        "prompt": (
            "Refactor this training configuration into a dataclass with validation:\n\n"
            "```python\n"
            "imgsz = 640\n"
            "batch = 2\n"
            "lr0 = 0.0005\n"
            "lrf = 0.05\n"
            "mosaic = 1.0\n"
            "mixup = 0.2\n"
            "max_det = 1500\n"
            "cache = False\n"
            "```\n\n"
            "Requirements:\n"
            "1. Use `@dataclass` with type hints\n"
            "2. Add `__post_init__` validation (imgsz must be divisible by 32, batch >= 1, etc.)\n"
            "3. Add a `to_dict()` method for serialization\n"
            "4. Add a `from_yaml(path)` classmethod"
        ),
        "check_contains": ["@dataclass", "__post_init__", "to_dict", "from_yaml"],
        "max_tokens": 1024,
    },
]

TOOL_USE_TASKS = [
    {
        "id": "tool-01-structured",
        "category": "tool_use",
        "name": "Generate tool call JSON",
        "system": (
            "You are a coding assistant with access to the following tools:\n"
            "- `run_training(config: dict) -> dict` — Starts a YOLO training run\n"
            "- `check_gpu_memory() -> dict` — Returns GPU memory stats\n"
            "- `evaluate_model(weights: str, dataset: str) -> dict` — Runs FiftyOne eval\n"
            "- `yield_gpu(gpu_id: int) -> bool` — Stops inference model to free GPU\n\n"
            "Respond with a JSON array of tool calls in order. Each call should be:\n"
            '`{"tool": "name", "args": {...}}`'
        ),
        "prompt": (
            "I want to run Phase 10 training at 960px. First check if there's enough GPU memory, "
            "then yield the inference model, then start training with batch=2 and 20 epochs, "
            "then evaluate the result on WIDER Face."
        ),
        "check_contains": ["check_gpu_memory", "yield_gpu", "run_training", "evaluate_model"],
        "max_tokens": 512,
    },
    {
        "id": "tool-02-multiplan",
        "category": "tool_use",
        "name": "Multi-step agent plan",
        "system": (
            "You are an ML engineering agent. Given a goal, produce a step-by-step execution plan "
            "with tool calls. Available tools:\n"
            "- `read_file(path)` — Read a file\n"
            "- `write_file(path, content)` — Write a file\n"
            "- `run_command(cmd)` — Execute shell command\n"
            "- `search_code(pattern)` — Grep workspace\n"
            "- `ask_human(question)` — Ask for clarification\n\n"
            "Output format: numbered steps, each with tool call and expected outcome."
        ),
        "prompt": (
            "The Phase 10 training crashed with an OOM error at 1280px batch=2. "
            "Investigate the telemetry log, determine if batch=1 would fit, "
            "update the training config, and restart."
        ),
        "check_contains": ["read_file", "run_command", "write_file"],
        "max_tokens": 768,
    },
]

LONG_CONTEXT_TASKS = [
    {
        "id": "ctx-01-needle-4k",
        "category": "long_context",
        "name": "Needle at 4K context",
        "context_size": 4096,
        "needle": "The secret recall threshold for Phase 10 validation is exactly 0.8237.",
        "needle_position": 0.5,  # middle
        "question": "What is the exact secret recall threshold for Phase 10 validation?",
        "expected": "0.8237",
        "max_tokens": 64,
    },
    {
        "id": "ctx-02-needle-32k",
        "category": "long_context",
        "name": "Needle at 32K context",
        "context_size": 32768,
        "needle": "The GPU temperature limit before thermal throttling is set to 83 degrees Celsius.",
        "needle_position": 0.7,  # 70% through
        "question": "What is the GPU temperature limit before thermal throttling?",
        "expected": "83",
        "max_tokens": 64,
    },
    {
        "id": "ctx-03-needle-128k",
        "category": "long_context",
        "name": "Needle at 128K context (Qwen only)",
        "context_size": 131072,
        "needle": "The maximum number of experts activated per token in the MoE layer is exactly 8 routed plus 1 shared.",
        "needle_position": 0.3,  # 30%
        "question": "How many experts are activated per token in the MoE layer?",
        "expected": "8 routed",
        "max_tokens": 64,
        "skip_model": "nemotron",  # Nemotron ctx is 65K
    },
]

# ═══════════════════════════════════════════════════════════════════════════
# ECOSYSTEM TASKS — Hermes / Obsidian / ACE Agent / MCP / Pipeline
# ═══════════════════════════════════════════════════════════════════════════

HERMES_SKILL_TASKS = [
    {
        "id": "hermes-01-critique",
        "category": "ecosystem",
        "subcategory": "hermes_skill_evolution",
        "name": "Critique an agent skill file",
        "system": (
            "You are a Hermes-style agent skill evaluator. You follow the GEPA "
            "(Generate-Evaluate-Propose-Apply) loop for continuous skill improvement.\n\n"
            "Given a SKILL.md file, produce a structured critique with:\n"
            "1. Strengths (what works well)\n"
            "2. Weaknesses (what fails or is missing)\n"
            "3. Specific improvement proposals (each with expected impact)\n"
            "4. Test cases that would validate the improvements\n\n"
            "Output format: JSON with keys: strengths[], weaknesses[], proposals[], tests[]"
        ),
        "prompt": (
            "Evaluate this platform-health skill:\n\n"
            "```yaml\n"
            "---\n"
            "name: platform-health\n"
            "description: Monitor GPU, containers, services health and resource usage\n"
            "activation_triggers:\n"
            "  - gpu status\n"
            "  - system health\n"
            "  - container status\n"
            "  - resource usage\n"
            "allowed_tools:\n"
            "  - ShellSkill\n"
            "  - DockerSkill\n"
            "---\n\n"
            "# Platform Health Monitoring\n\n"
            "When asked about platform health, check these in order:\n"
            "1. GPU memory usage via nvidia-smi\n"
            "2. Docker container status\n"
            "3. Service health endpoints\n"
            "4. Disk space on /tmp/ray/data\n\n"
            "Report issues if:\n"
            "- GPU memory > 90% and no training active\n"
            "- Any critical container stopped\n"
            "- /tmp/ray/data > 80% full\n"
            "```\n\n"
            "The skill sometimes fails to detect training-vs-inference GPU usage correctly. "
            "It also doesn't check MLflow or Prometheus health. Produce your GEPA critique."
        ),
        "check_contains": [
            "strengths", "weaknesses", "proposals", "tests",
            "mlflow", "prometheus", "training",
        ],
        "max_tokens": 1024,
    },
    {
        "id": "hermes-02-evolve",
        "category": "ecosystem",
        "subcategory": "hermes_skill_evolution",
        "name": "Generate improved skill variant",
        "system": (
            "You are a Hermes self-evolution agent. Given a skill file and a critique, "
            "generate an IMPROVED version of the skill that addresses the weaknesses.\n\n"
            "Rules:\n"
            "- Keep the YAML frontmatter structure\n"
            "- Add new activation triggers for gaps found\n"
            "- Add concrete diagnostic steps\n"
            "- Include error handling guidance\n"
            "- Must remain under 200 lines\n"
            "- Must be backward compatible with existing trigger phrases"
        ),
        "prompt": (
            "Original skill had these weaknesses:\n"
            "1. Doesn't distinguish training GPU usage from inference GPU usage\n"
            "2. Missing MLflow health check\n"
            "3. Missing Prometheus/pushgateway health check\n"
            "4. No Ray cluster status check\n"
            "5. Doesn't report training telemetry when training is active\n\n"
            "Generate the improved SKILL.md with all issues addressed. "
            "Include activation triggers for: 'mlflow status', 'ray status', "
            "'training progress', 'pushgateway'."
        ),
        "check_contains": [
            "mlflow", "prometheus", "ray", "training",
            "activation_triggers", "nvidia-smi",
        ],
        "max_tokens": 1536,
    },
    {
        "id": "hermes-03-test-gen",
        "category": "ecosystem",
        "subcategory": "hermes_skill_evolution",
        "name": "Generate skill validation tests",
        "system": (
            "You are a test engineer for agent skills. Given a skill description, "
            "generate pytest test cases that validate:\n"
            "1. Trigger correctness (skill activates when it should)\n"
            "2. Functional correctness (skill produces correct output format)\n"
            "3. Baseline comparison (improved skill doesn't regress on existing triggers)\n"
            "4. Edge cases (empty inputs, missing services, timeouts)\n\n"
            "Use pytest with mock/patch for external service calls."
        ),
        "prompt": (
            "Write tests for a platform-health skill that:\n"
            "- Activates on 'gpu status', 'system health', 'mlflow status', 'ray status'\n"
            "- Does NOT activate on 'train model', 'run eval', 'search code'\n"
            "- Returns JSON with keys: gpu_status, containers, services, disk_usage\n"
            "- Handles case where nvidia-smi is not available\n"
            "- Handles case where MLflow is unreachable\n"
            "- Reports training status when GPU > 90% usage"
        ),
        "check_contains": [
            "pytest", "def test_", "mock", "activation",
            "nvidia-smi", "mlflow", "assert",
        ],
        "max_tokens": 1536,
    },
]

OBSIDIAN_MEMORY_TASKS = [
    {
        "id": "obsidian-01-ingest",
        "category": "ecosystem",
        "subcategory": "obsidian_memory",
        "name": "Ingest research into atomic notes",
        "system": (
            "You are an Obsidian knowledge architect. Convert unstructured research content "
            "into a set of atomic, linked Obsidian notes.\n\n"
            "Each note must:\n"
            "- Have a clear, descriptive title\n"
            "- Contain exactly ONE concept or claim\n"
            "- Include [[backlinks]] to related notes\n"
            "- Have YAML frontmatter with tags, source, date\n"
            "- End with a ## Related section listing linked notes\n\n"
            "Output: A JSON array of {filename, content} objects."
        ),
        "prompt": (
            "Convert this research finding into atomic Obsidian notes:\n\n"
            "Qwen3.5-35B-A3B uses a Gated DeltaNet hybrid architecture where 30 of 40 "
            "layers use fixed recurrent state (no growing KV cache per token) and only "
            "10 layers use traditional attention. This gives it constant memory usage "
            "regardless of context length, unlike transformer-only models. The model has "
            "256 experts with 8 routed + 1 shared active per token, giving ~3B active "
            "params from 35B total. Community benchmarks show 112 tok/s on RTX 3090 "
            "at full 262K context with no speed degradation. Q4_K_M quantization fits "
            "in ~19.7GB VRAM.\n\n"
            "Create interconnected notes for: architecture, MoE design, memory behavior, "
            "hardware requirements, and benchmark results."
        ),
        "check_contains": [
            "[[", "]]",  # backlinks
            "frontmatter", "tags",  # or check for ---
            "DeltaNet", "MoE", "262K",
            "filename", "content",
        ],
        "max_tokens": 2048,
    },
    {
        "id": "obsidian-02-retrieve",
        "category": "ecosystem",
        "subcategory": "obsidian_memory",
        "name": "Answer from memory context",
        "system": (
            "You are an agent with access to an Obsidian knowledge vault. "
            "Below are the contents of relevant notes retrieved from the vault. "
            "Answer the user's question using ONLY information from these notes. "
            "Cite which note each fact comes from using [[Note Title]] format.\n\n"
            "--- VAULT CONTENTS ---\n\n"
            "## [[Phase 5 Training Results]]\n"
            "tags: #training #phase5 #yolov8\n"
            "Phase 5 achieved mAP50=0.798, Recall=0.716, Precision=0.889 on WIDER Face.\n"
            "Used YOLOv8m-P2 with cosine LR, AdamW optimizer.\n"
            "This was the YOLO champion model until Phase 9.\n\n"
            "## [[Phase 9 Training Results]]\n"
            "tags: #training #phase9 #yolov8 #finetune\n"
            "Phase 9 achieved mAP50=0.814, Recall=0.729, Precision=0.883.\n"
            "Improved over Phase 5 by +0.016 mAP50 and +0.013 recall.\n"
            "Used gradient clipping (max_norm=10.0) and copy-paste augmentation.\n\n"
            "## [[Phase 10 Crash Report]]\n"
            "tags: #training #phase10 #crash #oom\n"
            "Phase 10 attempted progressive training 640→960→1280px.\n"
            "Crashed at 1280px batch=2 due to system memory pressure.\n"
            "Anti-freeze measures: VRAM capping at 90%, cache=False, workers=2.\n"
            "No final metrics were produced.\n\n"
            "## [[Hardware Inventory]]\n"
            "tags: #hardware #gpu\n"
            "RTX 3090 Ti (24GB) on cuda:0, RTX 2070 (8GB) on cuda:1.\n"
            "64GB system RAM, 2TB NVMe.\n"
            "--- END VAULT ---"
        ),
        "prompt": (
            "What was the recall improvement from Phase 5 to Phase 9, and why did "
            "Phase 10 fail to produce better results?"
        ),
        "check_contains": [
            "[[Phase 5", "[[Phase 9", "[[Phase 10",
            "0.013", "1280", "memory",
        ],
        "max_tokens": 512,
    },
    {
        "id": "obsidian-03-update-memory",
        "category": "ecosystem",
        "subcategory": "obsidian_memory",
        "name": "Update MEMORY.md with session events",
        "system": (
            "You maintain a MEMORY.md file that serves as long-term agent memory. "
            "Given a session transcript with decisions and outcomes, update the memory "
            "file by:\n"
            "1. Adding new entries under the appropriate section\n"
            "2. Updating existing entries if information has changed\n"
            "3. Removing outdated information\n"
            "4. Maintaining chronological order\n"
            "5. Keeping the file under 5000 characters\n\n"
            "Output the complete updated MEMORY.md."
        ),
        "prompt": (
            "Current MEMORY.md:\n"
            "```\n"
            "# MEMORY.md\n\n"
            "## Models\n"
            "- Primary coding model: Nemotron-3-Nano-30B-A3B on GPU 0\n"
            "- Vision model: Qwen3-VL on GPU 1\n\n"
            "## Training\n"
            "- Phase 9 is current best (mAP50=0.814)\n"
            "- Phase 10 planned: progressive multi-scale\n\n"
            "## Decisions\n"
            "- 2026-03-01: Switched from Qwen2.5-Coder-32B to Nemotron (better quality)\n"
            "```\n\n"
            "Session events to incorporate:\n"
            "1. Evaluated Qwen3.5-35B-A3B as replacement for Nemotron — pending benchmark\n"
            "2. Phase 10 crashed at 1280px due to memory pressure\n"
            "3. Created autoresearch harness for automated hyperparameter search\n"
            "4. Decision: Use autoresearch instead of manual Phase 11 training\n"
            "5. Hermes GEPA skill evolution framework adopted for skill improvement"
        ),
        "check_contains": [
            "Qwen3.5", "autoresearch", "Phase 10", "crashed",
            "GEPA", "Hermes", "## Models", "## Training",
        ],
        "max_tokens": 1024,
    },
]

ACE_AGENT_TASKS = [
    {
        "id": "ace-01-generator",
        "category": "ecosystem",
        "subcategory": "ace_agent",
        "name": "ACE Generator: plan with tool calls",
        "system": (
            "You are the Generator in an ACE (Agentic Context Engineering) agent.\n\n"
            "Your platform has these skills (shell-first architecture):\n"
            "- ShellSkill: Execute safe shell commands (nvidia-smi, docker ps, curl, etc.)\n"
            "- RayJobSkill: Submit/monitor Ray training jobs\n"
            "- GitHubSkill: Create issues, PRs, manage repos\n"
            "- WebSearchSkill: Search the web\n"
            "- SandboxSkill: Execute code in isolated sandbox\n\n"
            "Tool call format:\n"
            "```\n"
            "Tool: SkillName\n"
            "Operation: operation_name\n"
            "Params: {\"key\": \"value\"}\n"
            "```\n\n"
            "Produce a complete execution plan with tool calls for the user's task. "
            "Include expected outcomes and fallback actions."
        ),
        "prompt": (
            "The user says: 'Check if training is running, and if not, start the "
            "autoresearch hyperparameter search on the face detection model. "
            "Make sure to yield the coding model first, then submit the job. "
            "After submission, check GPU memory to confirm it's using the GPU.'\n\n"
            "Generate your execution plan with tool calls."
        ),
        "check_contains": [
            "ShellSkill", "gpu_status",  # Must check GPU first
            "yield", "RayJobSkill",  # Must yield and submit
            "Tool:", "Operation:", "Params:",  # Correct format
        ],
        "max_tokens": 1536,
    },
    {
        "id": "ace-02-reflector",
        "category": "ecosystem",
        "subcategory": "ace_agent",
        "name": "ACE Reflector: critique generator output",
        "system": (
            "You are the Reflector in an ACE agent. Given the Generator's output, "
            "evaluate it on these rubrics (scoring 1-5 each):\n\n"
            "1. **Task Completeness**: Does it address all parts of the user's request?\n"
            "2. **Tool Correctness**: Are tool calls properly formatted with valid operations?\n"
            "3. **Safety**: Are there any dangerous operations or missing checks?\n"
            "4. **Efficiency**: Could it be done with fewer steps or better tool choices?\n"
            "5. **Error Handling**: Are failure cases considered?\n\n"
            "Output format: JSON with rubric_scores{}, critique (string), "
            "suggestions[] (specific improvements), pass (bool)."
        ),
        "prompt": (
            "Evaluate this Generator output:\n\n"
            "Step 1: Check GPU status\n"
            "```\n"
            "Tool: ShellSkill\n"
            "Operation: gpu_status\n"
            "Params: {\"format\": \"full\"}\n"
            "```\n\n"
            "Step 2: Submit training job\n"
            "```\n"
            "Tool: RayJobSkill\n"
            "Operation: submit_job\n"
            "Params: {\"script\": \"autoresearch_face.py\", \"args\": \"--max-iterations 10\"}\n"
            "```\n\n"
            "This plan is missing the GPU yield step and doesn't check if training "
            "is already running. Produce your Reflector critique."
        ),
        "check_contains": [
            "rubric_scores", "critique", "suggestions",
            "yield", "missing",  # Must catch the missing yield
            "pass",
        ],
        "max_tokens": 1024,
    },
    {
        "id": "ace-03-synthesis",
        "category": "ecosystem",
        "subcategory": "ace_agent",
        "name": "ACE end-to-end: task to final answer",
        "system": (
            "You are a complete ACE agent (Generator + Reflector + Curator combined). "
            "Process the user's request through all three stages:\n\n"
            "1. **GENERATOR**: Analyze the task, determine tool calls needed, plan execution\n"
            "2. **REFLECTOR**: Self-critique your plan on completeness, safety, efficiency\n"
            "3. **SYNTHESIS**: Produce the final answer incorporating reflections\n\n"
            "Available skills: ShellSkill, RayJobSkill, GitHubSkill\n"
            "Tool call format:\n"
            "```\nTool: SkillName\nOperation: op\nParams: {}\n```\n\n"
            "Mark each stage clearly with ## GENERATOR, ## REFLECTOR, ## SYNTHESIS headers."
        ),
        "prompt": (
            "I need to compare the autoresearch results from last night's run against "
            "the Phase 9 baseline. Load the experiment journal, find the best result, "
            "run a FiftyOne evaluation on those weights, and create a summary in the "
            "research docs. If no improvement was found, create a GitHub issue to "
            "investigate why."
        ),
        "check_contains": [
            "## GENERATOR", "## REFLECTOR", "## SYNTHESIS",
            "ShellSkill", "read",  # Must read journal
            "FiftyOne",  # Must run eval
            "GitHubSkill",  # Must plan for issue creation
        ],
        "max_tokens": 2048,
    },
]

MCP_ROUTING_TASKS = [
    {
        "id": "mcp-01-schema-parse",
        "category": "ecosystem",
        "subcategory": "mcp_routing",
        "name": "Parse MCP tool schemas and route",
        "system": (
            "You are an MCP-aware agent. Given the available MCP tools below, "
            "determine which tool(s) to call for the user's request.\n\n"
            "Available MCP tools:\n"
            "```json\n"
            "[\n"
            "  {\"name\": \"training_status\", \"description\": \"Get Ray job status and metrics\", "
            "\"parameters\": [{\"name\": \"job_id\", \"type\": \"string\", \"required\": false}], "
            "\"safe_during_training\": true},\n"
            "  {\"name\": \"gpu_status\", \"description\": \"Check GPU VRAM usage and processes\", "
            "\"parameters\": [{\"name\": \"gpu_index\", \"type\": \"number\", \"required\": false}], "
            "\"safe_during_training\": true},\n"
            "  {\"name\": \"mlflow_query\", \"description\": \"Query MLflow experiments and runs\", "
            "\"parameters\": [{\"name\": \"experiment\", \"type\": \"string\", \"required\": true}, "
            "{\"name\": \"metric\", \"type\": \"string\", \"required\": false}], "
            "\"safe_during_training\": true},\n"
            "  {\"name\": \"vision_analyze\", \"description\": \"Analyze image with Qwen3-VL (RTX 2070)\", "
            "\"parameters\": [{\"name\": \"image_path\", \"type\": \"string\", \"required\": true}, "
            "{\"name\": \"prompt\", \"type\": \"string\", \"required\": false}], "
            "\"gpu_required\": \"cuda:1\", \"safe_during_training\": true},\n"
            "  {\"name\": \"code_generate\", \"description\": \"Generate code with coding model\", "
            "\"parameters\": [{\"name\": \"prompt\", \"type\": \"string\", \"required\": true}], "
            "\"gpu_required\": \"cuda:0\", \"safe_during_training\": false}\n"
            "]\n```\n\n"
            "For each request, output: tool_name, arguments, and whether it's safe "
            "to call during training. If training is active, do NOT call tools that "
            "require cuda:0."
        ),
        "prompt": (
            "Training is currently active on GPU 0. The user wants to:\n"
            "1. Check how the current training run is doing\n"
            "2. Query MLflow for the best Phase 9 recall metric\n"
            "3. Analyze a sample image from the validation set\n"
            "4. Generate a PR description for the changes\n\n"
            "Determine which tools to call and which to skip/defer."
        ),
        "check_contains": [
            "training_status", "mlflow_query", "vision_analyze",
            "code_generate",  # Must mention it
            "safe_during_training",  # Must check safety
            "defer", # or "skip" — must handle the unsafe tool
        ],
        "max_tokens": 1024,
    },
    {
        "id": "mcp-02-failure-recovery",
        "category": "ecosystem",
        "subcategory": "mcp_routing",
        "name": "Handle MCP tool failures gracefully",
        "system": (
            "You are an MCP agent that must handle tool failures gracefully. "
            "When a tool fails, you should:\n"
            "1. Diagnose why it failed\n"
            "2. Try an alternative approach\n"
            "3. Report what you could and couldn't accomplish\n\n"
            "Available tools: training_status, gpu_status, mlflow_query, "
            "vision_analyze, code_generate\n\n"
            "Output your recovery plan with alternative tool calls."
        ),
        "prompt": (
            "Tool results from your previous calls:\n\n"
            "1. gpu_status: SUCCESS — GPU 0: 22.1GB/24GB used (92%), GPU 1: 3.2GB/8GB\n"
            "2. training_status: FAILED — Connection refused (Ray head not responding)\n"
            "3. mlflow_query: FAILED — Timeout after 30s (MLflow nginx unreachable)\n\n"
            "The user asked: 'What's the status of my training and latest metrics?'\n"
            "Recover from the failures and provide the best answer you can."
        ),
        "check_contains": [
            "gpu_status",  # Use successful data
            "92%", "22.1",  # Reference the actual data
            "Ray", "MLflow",  # Acknowledge failures
            "alternative",  # Propose alternatives
        ],
        "max_tokens": 1024,
    },
]

PIPELINE_ORCHESTRATION_TASKS = [
    {
        "id": "pipe-01-full-cycle",
        "category": "ecosystem",
        "subcategory": "pipeline_orchestration",
        "name": "Orchestrate training → eval → analysis pipeline",
        "system": (
            "You are a pipeline orchestration agent for an ML platform. "
            "You must produce a complete, ordered execution plan for multi-step "
            "ML workflows. Each step must specify:\n"
            "- What to run (command or tool call)\n"
            "- Expected duration\n"
            "- Success criteria\n"
            "- Failure action\n"
            "- Dependencies (which steps must complete first)\n\n"
            "Hardware: RTX 3090 Ti (24GB), RTX 2070 (8GB), 64GB RAM\n"
            "Services: Ray, MLflow, FiftyOne, Prometheus, Nessie, Nemotron/Qwen coding model\n"
            "Constraint: Coding model must be stopped before training (GPU yield)"
        ),
        "prompt": (
            "Create a complete pipeline for:\n"
            "1. Run autoresearch with 10 iterations at 640px (budget: 10 min/iter)\n"
            "2. Take the best weights and run FiftyOne eval with Brain computations\n"
            "3. Compare mAP50 and recall against Phase 9 baseline\n"
            "4. If improved: tag in Nessie, log to MLflow, create GitHub PR\n"
            "5. If not improved: create GitHub issue with analysis\n"
            "6. Restart the coding model after training completes\n\n"
            "Include GPU yield, error handling for OOM, and disk space checks."
        ),
        "check_contains": [
            "yield", "GPU",  # GPU management
            "autoresearch", "640",  # Training spec
            "FiftyOne", "Brain",  # Evaluation
            "Phase 9", "baseline",  # Comparison
            "Nessie", "MLflow",  # Success path
            "GitHub", "issue",  # Failure path
            "restart", "coding model",  # Cleanup
        ],
        "max_tokens": 2048,
    },
    {
        "id": "pipe-02-crash-recovery",
        "category": "ecosystem",
        "subcategory": "pipeline_orchestration",
        "name": "Recover from training crash mid-pipeline",
        "system": (
            "You are a pipeline recovery agent. A training pipeline has crashed "
            "and you need to diagnose, recover, and continue.\n\n"
            "Available diagnostics:\n"
            "- Telemetry CSV: /tmp/ray/data/phase10_resource_telemetry.csv\n"
            "- Training logs: /tmp/ray/checkpoints/face_detection/\n"
            "- nvidia-smi for current GPU state\n"
            "- /proc/meminfo for system memory\n"
            "- MLflow for partial run metrics"
        ),
        "prompt": (
            "The autoresearch iteration 7 ('imgsz_960_b1') crashed with this error:\n"
            "```\n"
            "torch.cuda.OutOfMemoryError: CUDA out of memory. Tried to allocate 1.2 GiB\n"
            "  GPU 0: 23.8 GiB total, 22.9 GiB reserved, 512 MiB free\n"
            "```\n\n"
            "The script has OOM retry logic (halves batch), but batch was already 1.\n"
            "Iterations 1-6 completed successfully at 640px/batch=2.\n\n"
            "Diagnose the issue and produce a recovery plan that:\n"
            "1. Determines if results from iterations 1-6 are salvageable\n"
            "2. Adjusts the remaining schedule to avoid the OOM config\n"
            "3. Checks if cached memory can be freed\n"
            "4. Restarts from the last successful state\n"
            "5. Ensures the coding model is reclaimed if training is done"
        ),
        "check_contains": [
            "960px", "OOM",  # Identify the problem config
            "iterations 1-6", "salvage",  # Save good results
            "skip", "remove",  # Adjust schedule
            "torch.cuda.empty_cache",  # Memory cleanup
            "reclaim",  # GPU reclaim
        ],
        "max_tokens": 1536,
    },
]

# Combined ecosystem tasks
ECOSYSTEM_TASKS = (
    HERMES_SKILL_TASKS
    + OBSIDIAN_MEMORY_TASKS
    + ACE_AGENT_TASKS
    + MCP_ROUTING_TASKS
    + PIPELINE_ORCHESTRATION_TASKS
)


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class TaskResult:
    task_id: str
    task_name: str
    category: str
    model: str
    response: str = ""
    reasoning_content: str = ""  # Thinking/reasoning tokens (Qwen3.5 <think> blocks)
    tokens_generated: int = 0
    reasoning_tokens: int = 0  # How many tokens were thinking
    time_to_first_token_ms: float = 0.0
    total_time_ms: float = 0.0
    tokens_per_second: float = 0.0
    checks_passed: int = 0
    checks_total: int = 0
    check_results: dict = field(default_factory=dict)
    error: str = ""
    vram_before_mb: float = 0.0
    vram_after_mb: float = 0.0
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class ModelProfile:
    name: str
    url: str
    context_window: int
    total_params: str
    active_params: str
    quantization: str
    architecture: str


NEMOTRON_PROFILE = ModelProfile(
    name="Nemotron-3-Nano-30B-A3B",
    url="",
    context_window=65536,
    total_params="30B",
    active_params="3B",
    quantization="Q4_K_XL (GGUF)",
    architecture="MoE (llama-server)",
)

QWEN_PROFILE = ModelProfile(
    name="Qwen3.5-35B-A3B",
    url="",
    context_window=131072,
    total_params="35B",
    active_params="~3B",
    quantization="Q4_K_M (GGUF)",
    architecture="Gated DeltaNet MoE (llama-server)",
)


# ═══════════════════════════════════════════════════════════════════════════
# HAYSTACK GENERATION
# ═══════════════════════════════════════════════════════════════════════════

_FILLER_PARAGRAPHS = [
    "The training pipeline processes batches of images through the detection backbone, "
    "extracting multi-scale feature maps at P2 through P5 levels. Each feature map captures "
    "different spatial resolutions, enabling the model to detect faces ranging from 8x8 pixels "
    "to full-frame.",
    "Data augmentation includes mosaic composition, mixup blending, copy-paste operations, "
    "and geometric transforms. These are progressively reduced in later training phases to "
    "allow the model to converge on fine details rather than learning augmentation artifacts.",
    "The gradient clipping callback monitors the L2 norm of all parameter gradients and "
    "clips them when the total exceeds the configured threshold. This prevents gradient "
    "explosion which was observed in earlier training phases, particularly during high-"
    "resolution fine-tuning at 1280px.",
    "Resource telemetry runs on a background thread, sampling system memory, GPU utilization, "
    "temperature, and PyTorch allocator statistics at configurable intervals. The CSV output "
    "enables post-mortem analysis of training crashes and memory pressure events.",
    "The FiftyOne evaluation pipeline computes COCO-style metrics including mAP at IoU "
    "thresholds from 0.50 to 0.95. It also runs Brain computations for CLIP-based similarity, "
    "uniqueness scoring, and hardness estimation to identify challenging samples.",
    "MLflow tracks all training runs with parameters, metrics, artifacts, and tags. "
    "Each phase of progressive training logs its own metric series, enabling per-phase "
    "analysis and comparison against baseline runs.",
    "The Nessie data versioning service creates branches for each training run, allowing "
    "reproducible dataset snapshots. When a model exceeds baseline recall, the branch "
    "is tagged for preservation.",
    "Prometheus metrics are pushed after each epoch via the pushgateway. Grafana dashboards "
    "display live training progress including loss curves, validation metrics, GPU memory "
    "utilization, and gradient clipping frequency.",
]


def build_haystack(target_tokens: int, needle: str, position: float) -> str:
    """Build a haystack document with a needle at the specified position.

    Args:
        target_tokens: Target context size in tokens (~4 chars/token heuristic).
        needle: The fact to embed.
        position: Where to place needle (0.0 = start, 1.0 = end).
    """
    target_chars = target_tokens * 4
    paragraphs = []
    current_chars = 0

    while current_chars < target_chars:
        for p in _FILLER_PARAGRAPHS:
            paragraphs.append(p)
            current_chars += len(p) + 2
            if current_chars >= target_chars:
                break

    # Insert needle at position
    insert_idx = max(1, int(len(paragraphs) * position))
    paragraphs.insert(insert_idx, f"\n**Important note:** {needle}\n")

    return "\n\n".join(paragraphs)


# ═══════════════════════════════════════════════════════════════════════════
# INFERENCE CLIENT
# ═══════════════════════════════════════════════════════════════════════════


# Global config set from CLI args
_REQUEST_TIMEOUT = 300
_THINKING_HEADROOM = 1.0  # Multiplier for thinking models (thinking tokens count against max_tokens)


def query_model(
    base_url: str,
    prompt: str,
    system: str = "You are a helpful coding assistant.",
    max_tokens: int = 1024,
    temperature: float = 0.1,
    stream: bool = True,
) -> tuple[str, str, float, float, int, int]:
    """Query an OpenAI-compatible endpoint.

    Handles thinking/reasoning models (e.g. Qwen3.5 with <think> blocks).
    Separates reasoning_content from content in the response.
    Applies _THINKING_HEADROOM multiplier to max_tokens to give thinking models
    enough budget for reasoning + actual content.

    Returns:
        (response_text, reasoning_text, time_to_first_token_ms, total_time_ms,
         content_tokens, reasoning_tokens)
    """
    url = f"{base_url}/chat/completions"
    effective_max_tokens = int(max_tokens * _THINKING_HEADROOM)
    payload = {
        "model": "default",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": effective_max_tokens,
        "temperature": temperature,
        "stream": stream,
    }

    t0 = time.perf_counter()
    ttft = 0.0
    content_tokens = 0
    reasoning_tokens = 0
    response_text = ""
    reasoning_text = ""
    first_any_token = False

    if stream:
        with requests.post(url, json=payload, stream=True, timeout=_REQUEST_TIMEOUT) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                line = line.decode("utf-8")
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    # Content tokens (the actual answer)
                    # Note: thinking models send content=null in first chunk
                    content = delta.get("content") or ""
                    if content:
                        if not first_any_token:
                            ttft = (time.perf_counter() - t0) * 1000
                            first_any_token = True
                        response_text += content
                        content_tokens += 1
                    # Reasoning/thinking tokens (Qwen3.5, DeepSeek, etc.)
                    reasoning = delta.get("reasoning_content") or ""
                    if reasoning:
                        if not first_any_token:
                            ttft = (time.perf_counter() - t0) * 1000
                            first_any_token = True
                        reasoning_text += reasoning
                        reasoning_tokens += 1
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
    else:
        resp = requests.post(url, json=payload, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        result = resp.json()
        msg = result["choices"][0]["message"]
        response_text = msg.get("content", "") or ""
        reasoning_text = msg.get("reasoning_content", "") or ""
        usage = result.get("usage", {})
        content_tokens = usage.get("completion_tokens", len(response_text) // 4)
        # llama.cpp doesn't split reasoning vs content in usage, estimate from text
        if reasoning_text:
            reasoning_tokens = len(reasoning_text) // 4
        ttft = (time.perf_counter() - t0) * 1000

    total_ms = (time.perf_counter() - t0) * 1000
    return response_text, reasoning_text, ttft, total_ms, content_tokens, reasoning_tokens


def get_vram_usage_mb(gpu_id: int = 0) -> float:
    """Get GPU VRAM usage via nvidia-smi."""
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
                f"--id={gpu_id}",
            ],
            text=True,
            timeout=5,
        ).strip()
        return float(out)
    except Exception:
        return 0.0


# ═══════════════════════════════════════════════════════════════════════════
# TASK RUNNERS
# ═══════════════════════════════════════════════════════════════════════════


def _populate_result(result: TaskResult, response: str, reasoning: str,
                     ttft: float, total_ms: float,
                     content_tokens: int, reasoning_tokens: int) -> None:
    """Fill common fields in a TaskResult from query_model output."""
    result.response = response
    result.reasoning_content = reasoning
    result.time_to_first_token_ms = ttft
    result.total_time_ms = total_ms
    result.tokens_generated = content_tokens + reasoning_tokens
    result.reasoning_tokens = reasoning_tokens
    total_tokens = content_tokens + reasoning_tokens
    result.tokens_per_second = total_tokens / (total_ms / 1000) if total_ms > 0 else 0
    result.vram_after_mb = get_vram_usage_mb()


def _check_patterns(result: TaskResult, checks: list[str], searchable: str) -> None:
    """Check for expected patterns in the searchable text (content + reasoning)."""
    result.checks_total += len(checks)
    for pattern in checks:
        found = pattern.lower() in searchable.lower()
        result.check_results[pattern] = found
        if found:
            result.checks_passed += 1


def run_coding_task(task: dict, model_name: str, base_url: str) -> TaskResult:
    """Run a coding task and check for expected patterns."""
    result = TaskResult(
        task_id=task["id"],
        task_name=task["name"],
        category=task["category"],
        model=model_name,
    )

    try:
        result.vram_before_mb = get_vram_usage_mb()
        response, reasoning, ttft, total_ms, c_tok, r_tok = query_model(
            base_url,
            task["prompt"],
            max_tokens=task.get("max_tokens", 1024),
        )
        _populate_result(result, response, reasoning, ttft, total_ms, c_tok, r_tok)

        # Check for expected patterns in both content and reasoning
        searchable = response + "\n" + reasoning
        _check_patterns(result, task.get("check_contains", []), searchable)

    except Exception as e:
        result.error = str(e)

    return result


def run_tool_use_task(task: dict, model_name: str, base_url: str) -> TaskResult:
    """Run a tool-use task and check for expected tool calls."""
    result = TaskResult(
        task_id=task["id"],
        task_name=task["name"],
        category=task["category"],
        model=model_name,
    )

    try:
        result.vram_before_mb = get_vram_usage_mb()
        response, reasoning, ttft, total_ms, c_tok, r_tok = query_model(
            base_url,
            task["prompt"],
            system=task.get("system", "You are a helpful coding assistant."),
            max_tokens=task.get("max_tokens", 768),
        )
        _populate_result(result, response, reasoning, ttft, total_ms, c_tok, r_tok)

        # Check for expected tool mentions in both content and reasoning
        searchable = response + "\n" + reasoning
        _check_patterns(result, task.get("check_contains", []), searchable)

    except Exception as e:
        result.error = str(e)

    return result


def run_ecosystem_task(task: dict, model_name: str, base_url: str) -> TaskResult:
    """Run an ecosystem task (Hermes/Obsidian/ACE/MCP/Pipeline) with structured output checks."""
    result = TaskResult(
        task_id=task["id"],
        task_name=task["name"],
        category=task["category"],
        model=model_name,
    )

    try:
        result.vram_before_mb = get_vram_usage_mb()
        response, reasoning, ttft, total_ms, c_tok, r_tok = query_model(
            base_url,
            task["prompt"],
            system=task.get("system", "You are a helpful assistant."),
            max_tokens=task.get("max_tokens", 1536),
        )
        _populate_result(result, response, reasoning, ttft, total_ms, c_tok, r_tok)

        # Standard pattern checks — search content + reasoning
        searchable = response + "\n" + reasoning
        _check_patterns(result, task.get("check_contains", []), searchable)

        # Bonus: structural quality checks for ecosystem tasks
        # For thinking models, structural output may appear in reasoning too
        subcategory = task.get("subcategory", "")
        structural_checks = []
        combined = response + "\n" + reasoning

        if subcategory == "hermes_skill_evolution":
            # Check for valid JSON structure in response
            structural_checks.append(("json_structure", "{" in combined and "}" in combined))
            # Check for structured proposal format
            structural_checks.append(("numbered_items", any(
                line.strip().startswith(("1.", "- ", "* "))
                for line in combined.split("\n")
            )))

        elif subcategory == "obsidian_memory":
            # Check for Obsidian linking syntax
            structural_checks.append(("backlinks", "[[" in combined and "]]" in combined))
            # Check for YAML frontmatter
            structural_checks.append(("yaml_frontmatter", combined.count("---") >= 2 or "tags:" in combined))

        elif subcategory == "ace_agent":
            # Check for correct tool call format (any of the 3 patterns)
            has_multiline = "Tool:" in combined and "Operation:" in combined
            has_inline = "[TOOL:" in combined
            structural_checks.append(("tool_format", has_multiline or has_inline))
            # Check for staged thinking
            structural_checks.append(("staged_output", any(
                marker in combined
                for marker in ["## GENERATOR", "## REFLECTOR", "Step 1", "Step 2"]
            )))

        elif subcategory == "mcp_routing":
            # Check for explicit safe/unsafe reasoning
            structural_checks.append(("safety_reasoning", any(
                kw in combined.lower()
                for kw in ["safe", "unsafe", "skip", "defer", "block", "not safe"]
            )))

        elif subcategory == "pipeline_orchestration":
            # Check for dependency/ordering awareness
            structural_checks.append(("has_ordering", any(
                kw in combined.lower()
                for kw in ["step", "then", "after", "before", "first", "finally"]
            )))
            # Check for error handling
            structural_checks.append(("error_handling", any(
                kw in combined.lower()
                for kw in ["if fail", "error", "recovery", "retry", "fallback"]
            )))

        for check_name, passed in structural_checks:
            result.checks_total += 1
            result.check_results[f"structural:{check_name}"] = passed
            if passed:
                result.checks_passed += 1

    except Exception as e:
        result.error = str(e)

    return result


def run_long_context_task(
    task: dict, model_name: str, base_url: str, model_ctx: int
) -> TaskResult:
    """Run a needle-in-haystack retrieval task."""
    result = TaskResult(
        task_id=task["id"],
        task_name=task["name"],
        category=task["category"],
        model=model_name,
    )

    # Check skip conditions
    skip_model = task.get("skip_model", "")
    if skip_model and skip_model.lower() in model_name.lower():
        result.skipped = True
        result.skip_reason = f"Task exceeds {model_name} context window"
        return result

    ctx_size = task["context_size"]
    if ctx_size > model_ctx:
        result.skipped = True
        result.skip_reason = f"Context {ctx_size} > model max {model_ctx}"
        return result

    try:
        haystack = build_haystack(ctx_size, task["needle"], task["needle_position"])
        prompt = f"{haystack}\n\nQuestion: {task['question']}\nAnswer concisely:"

        result.vram_before_mb = get_vram_usage_mb()
        response, reasoning, ttft, total_ms, c_tok, r_tok = query_model(
            base_url,
            prompt,
            max_tokens=task.get("max_tokens", 64),
        )
        _populate_result(result, response, reasoning, ttft, total_ms, c_tok, r_tok)

        # Check if needle was retrieved — search both content and reasoning
        expected = task.get("expected", "")
        searchable = response + "\n" + reasoning
        result.checks_total = 1
        if expected.lower() in searchable.lower():
            result.checks_passed = 1
            result.check_results["needle_found"] = True
        else:
            result.check_results["needle_found"] = False

    except Exception as e:
        result.error = str(e)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# EVALUATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════


def evaluate_model(
    profile: ModelProfile,
    base_url: str,
    tasks: dict[str, list],
) -> list[TaskResult]:
    """Run all evaluation tasks against a single model."""
    results = []
    total = sum(len(v) for v in tasks.values())
    done = 0

    print(f"\n{'═' * 70}")
    print(f"  Evaluating: {profile.name}")
    print(f"  Endpoint:   {base_url}")
    print(f"  Context:    {profile.context_window:,} tokens")
    print(f"  Tasks:      {total}")
    print(f"{'═' * 70}\n")

    for task in tasks.get("coding", []):
        done += 1
        print(f"  [{done}/{total}] {task['name']}...", end=" ", flush=True)
        r = run_coding_task(task, profile.name, base_url)
        think_info = f" | 🧠{r.reasoning_tokens}tok" if r.reasoning_tokens else ""
        print(
            f"{'✓' if r.checks_passed == r.checks_total else '△'} "
            f"{r.checks_passed}/{r.checks_total} checks | "
            f"{r.tokens_per_second:.0f} tok/s | "
            f"TTFT={r.time_to_first_token_ms:.0f}ms{think_info}"
        )
        results.append(r)

    for task in tasks.get("tool_use", []):
        done += 1
        print(f"  [{done}/{total}] {task['name']}...", end=" ", flush=True)
        r = run_tool_use_task(task, profile.name, base_url)
        think_info = f" | 🧠{r.reasoning_tokens}tok" if r.reasoning_tokens else ""
        print(
            f"{'✓' if r.checks_passed == r.checks_total else '△'} "
            f"{r.checks_passed}/{r.checks_total} checks | "
            f"{r.tokens_per_second:.0f} tok/s{think_info}"
        )
        results.append(r)

    for task in tasks.get("long_context", []):
        done += 1
        print(f"  [{done}/{total}] {task['name']}...", end=" ", flush=True)
        r = run_long_context_task(task, profile.name, base_url, profile.context_window)
        if r.skipped:
            print(f"⏭ SKIPPED ({r.skip_reason})")
        else:
            think_info = f" | 🧠{r.reasoning_tokens}tok" if r.reasoning_tokens else ""
            print(
                f"{'✓' if r.checks_passed == r.checks_total else '✗'} "
                f"needle={'found' if r.check_results.get('needle_found') else 'MISSED'} | "
                f"{r.tokens_per_second:.0f} tok/s | "
                f"TTFT={r.time_to_first_token_ms:.0f}ms{think_info}"
            )
        results.append(r)

    for task in tasks.get("ecosystem", []):
        done += 1
        subcat = task.get("subcategory", "ecosystem")
        print(f"  [{done}/{total}] [{subcat}] {task['name']}...", end=" ", flush=True)
        r = run_ecosystem_task(task, profile.name, base_url)
        if r.error:
            print(f"✗ ERROR: {r.error[:60]}")
        else:
            struct_checks = [
                k for k, v in r.check_results.items()
                if k.startswith("structural:") and v
            ]
            think_info = f" | 🧠{r.reasoning_tokens}tok" if r.reasoning_tokens else ""
            print(
                f"{'✓' if r.checks_passed == r.checks_total else '△'} "
                f"{r.checks_passed}/{r.checks_total} checks "
                f"(+{len(struct_checks)} structural) | "
                f"{r.tokens_per_second:.0f} tok/s{think_info}"
            )
        results.append(r)

    return results


def print_comparison(
    nemotron_results: list[TaskResult],
    qwen_results: list[TaskResult],
) -> None:
    """Print side-by-side comparison table."""
    print(f"\n{'═' * 90}")
    print(f"  HEAD-TO-HEAD COMPARISON")
    print(f"{'═' * 90}")

    categories = ["coding", "tool_use", "long_context", "ecosystem"]
    cat_labels = {
        "coding": "Coding",
        "tool_use": "Tool Use",
        "long_context": "Long Context",
        "ecosystem": "Ecosystem (Hermes/Obsidian/ACE/MCP/Pipeline)",
    }

    for cat in categories:
        n_tasks = [r for r in nemotron_results if r.category == cat and not r.skipped]
        q_tasks = [r for r in qwen_results if r.category == cat and not r.skipped]

        if not n_tasks and not q_tasks:
            continue

        print(f"\n  ── {cat_labels[cat]} ──")
        print(f"  {'Task':<30s} {'Nemotron':>12s} {'Qwen':>12s} {'Winner':>10s}")
        print(f"  {'─' * 66}")

        for nt in n_tasks:
            qt = next((q for q in q_tasks if q.task_id == nt.task_id), None)
            n_score = f"{nt.checks_passed}/{nt.checks_total}"
            q_score = f"{qt.checks_passed}/{qt.checks_total}" if qt else "N/A"
            winner = ""
            if qt:
                if nt.checks_passed > qt.checks_passed:
                    winner = "Nemotron"
                elif qt.checks_passed > nt.checks_passed:
                    winner = "Qwen"
                else:
                    winner = "Tie"
            print(f"  {nt.task_name:<30s} {n_score:>12s} {q_score:>12s} {winner:>10s}")

    # Throughput comparison
    n_all = [r for r in nemotron_results if not r.skipped and not r.error]
    q_all = [r for r in qwen_results if not r.skipped and not r.error]

    if n_all and q_all:
        n_avg_tps = sum(r.tokens_per_second for r in n_all) / len(n_all)
        q_avg_tps = sum(r.tokens_per_second for r in q_all) / len(q_all)
        n_avg_ttft = sum(r.time_to_first_token_ms for r in n_all) / len(n_all)
        q_avg_ttft = sum(r.time_to_first_token_ms for r in q_all) / len(q_all)

        print(f"\n  ── Throughput ──")
        print(f"  {'Metric':<30s} {'Nemotron':>12s} {'Qwen':>12s} {'Winner':>10s}")
        print(f"  {'─' * 66}")
        tps_winner = "Nemotron" if n_avg_tps > q_avg_tps else "Qwen"
        ttft_winner = "Nemotron" if n_avg_ttft < q_avg_ttft else "Qwen"
        print(
            f"  {'Avg tok/s':<30s} {n_avg_tps:>12.1f} {q_avg_tps:>12.1f} {tps_winner:>10s}"
        )
        print(
            f"  {'Avg TTFT (ms)':<30s} {n_avg_ttft:>12.0f} {q_avg_ttft:>12.0f} {ttft_winner:>10s}"
        )

        # Thinking stats
        n_think = sum(r.reasoning_tokens for r in n_all)
        q_think = sum(r.reasoning_tokens for r in q_all)
        if n_think or q_think:
            n_total_tok = sum(r.tokens_generated for r in n_all)
            q_total_tok = sum(r.tokens_generated for r in q_all)
            n_think_pct = n_think / max(1, n_total_tok) * 100
            q_think_pct = q_think / max(1, q_total_tok) * 100
            print(f"\n  ── Thinking Overhead ──")
            print(f"  {'Metric':<30s} {'Nemotron':>12s} {'Qwen':>12s}")
            print(f"  {'─' * 56}")
            print(f"  {'Reasoning tokens':<30s} {n_think:>12,d} {q_think:>12,d}")
            print(f"  {'% tokens on thinking':<30s} {n_think_pct:>11.1f}% {q_think_pct:>11.1f}%")

        # VRAM
        n_vram = max(r.vram_after_mb for r in n_all) if n_all else 0
        q_vram = max(r.vram_after_mb for r in q_all) if q_all else 0
        vram_winner = "Nemotron" if n_vram < q_vram else "Qwen"
        print(f"\n  ── VRAM (peak) ──")
        print(
            f"  {'Peak VRAM (MB)':<30s} {n_vram:>12.0f} {q_vram:>12.0f} {vram_winner:>10s}"
        )

    print(f"\n{'═' * 90}")

    # Overall summary
    n_total_checks = sum(r.checks_passed for r in nemotron_results if not r.skipped)
    n_total_possible = sum(r.checks_total for r in nemotron_results if not r.skipped)
    q_total_checks = sum(r.checks_passed for r in qwen_results if not r.skipped)
    q_total_possible = sum(r.checks_total for r in qwen_results if not r.skipped)

    n_pct = n_total_checks / max(1, n_total_possible) * 100
    q_pct = q_total_checks / max(1, q_total_possible) * 100

    print(f"\n  OVERALL ACCURACY:")
    print(f"    Nemotron: {n_total_checks}/{n_total_possible} ({n_pct:.0f}%)")
    print(f"    Qwen:     {q_total_checks}/{q_total_possible} ({q_pct:.0f}%)")
    recommendation = "Qwen" if q_pct > n_pct else "Nemotron" if n_pct > q_pct else "Tie"
    print(f"\n  → Recommendation: {recommendation}")
    print(f"{'═' * 90}\n")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════


def parse_args():
    parser = argparse.ArgumentParser(
        description="Qwen vs Nemotron coding model evaluation"
    )
    parser.add_argument(
        "--nemotron-url",
        type=str,
        default="http://localhost:8010/v1",
        help="Nemotron OpenAI-compatible endpoint",
    )
    parser.add_argument(
        "--qwen-url",
        type=str,
        default="http://localhost:8020/v1",
        help="Qwen OpenAI-compatible endpoint",
    )
    parser.add_argument(
        "--target",
        type=str,
        choices=["both", "nemotron", "qwen"],
        default="both",
        help="Which model(s) to evaluate",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON path for results",
    )
    parser.add_argument(
        "--category",
        type=str,
        choices=["all", "coding", "tool_use", "long_context", "ecosystem"],
        default="all",
        help="Which task category to run (ecosystem = Hermes/Obsidian/ACE/MCP/Pipeline)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Request timeout in seconds (300 recommended for thinking models)",
    )
    parser.add_argument(
        "--thinking-headroom",
        type=float,
        default=1.0,
        help="Multiply max_tokens by this factor to give thinking models room for reasoning + content. "
             "Use 4.0-6.0 for thinking models like Qwen3.5. Non-thinking models are unaffected "
             "(they stop at natural completion). Default: 1.0",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print tasks without running")
    return parser.parse_args()


def main():
    args = parse_args()

    tasks = {}
    if args.category in ("all", "coding"):
        tasks["coding"] = CODING_TASKS
    if args.category in ("all", "tool_use"):
        tasks["tool_use"] = TOOL_USE_TASKS
    if args.category in ("all", "long_context"):
        tasks["long_context"] = LONG_CONTEXT_TASKS
    if args.category in ("all", "ecosystem"):
        tasks["ecosystem"] = ECOSYSTEM_TASKS

    if args.dry_run:
        print("DRY RUN — tasks that would execute:\n")
        for cat, cat_tasks in tasks.items():
            print(f"  {cat}:")
            for t in cat_tasks:
                print(f"    - {t['id']}: {t['name']}")
        return 0

    nemotron_results = []
    qwen_results = []

    global _REQUEST_TIMEOUT, _THINKING_HEADROOM
    _REQUEST_TIMEOUT = args.timeout
    _THINKING_HEADROOM = args.thinking_headroom

    NEMOTRON_PROFILE.url = args.nemotron_url
    QWEN_PROFILE.url = args.qwen_url

    if args.target in ("both", "nemotron"):
        nemotron_results = evaluate_model(NEMOTRON_PROFILE, args.nemotron_url, tasks)

    if args.target in ("both", "qwen"):
        qwen_results = evaluate_model(QWEN_PROFILE, args.qwen_url, tasks)

    if args.target == "both" and nemotron_results and qwen_results:
        print_comparison(nemotron_results, qwen_results)

    # Save results
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        report = {
            "timestamp": datetime.now().isoformat(),
            "models": {
                "nemotron": asdict(NEMOTRON_PROFILE),
                "qwen": asdict(QWEN_PROFILE),
            },
            "results": {
                "nemotron": [asdict(r) for r in nemotron_results],
                "qwen": [asdict(r) for r in qwen_results],
            },
        }
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"Results saved: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
