"""
Smart tool selection for context-constrained local models.

When Hermes sends 105 tool schemas (~24K tokens), a local model with 8K context
can't fit them all. This module selects the most relevant tools based on the
user's prompt, staying within a configurable token budget.

Strategy:
1. Classify prompt into tool categories using keyword matching
2. Always include essential tools (file, clarify)
3. Score remaining categories by keyword overlap
4. Fill budget with top-scoring categories
5. Include a meta-tool so the model can request more tools if needed
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Approximate tokens per character (conservative estimate for JSON tool schemas)
CHARS_PER_TOKEN = 3.5

# Default token budget for tool schemas (leaves room for system prompt + messages + output)
DEFAULT_TOOL_TOKEN_BUDGET = 3000

# Maximum number of tools to forward regardless of budget
MAX_TOOLS = 20

# Tools to ALWAYS include (essential for basic agent operation)
ESSENTIAL_TOOLS = {
    "clarify",
    "read_file",
    "write_file",
    "search_files",
    "patch",
    "execute_code",
}

# Category → (keywords, priority_boost)
# Higher priority_boost means the category is included more eagerly
TOOL_CATEGORIES: Dict[str, Tuple[List[str], float]] = {
    "file": (
        ["file", "read", "write", "edit", "patch", "create", "delete", "search",
         "directory", "folder", "path", "code", "script", "module", "class",
         "function", "refactor", "rename"],
        0.3,  # boost — file ops are almost always useful
    ),
    "browser": (
        ["browse", "browser", "web", "click", "navigate", "page", "url", "http",
         "website", "scrape", "screenshot", "html", "dom"],
        0.0,
    ),
    "code_execution": (
        ["execute", "run", "shell", "terminal", "command", "bash", "python",
         "script", "test", "compile", "build", "install", "pip", "npm"],
        0.1,
    ),
    "delegation": (
        ["delegate", "agent", "subagent", "task", "parallel", "background"],
        0.0,
    ),
    "image_gen": (
        ["image", "generate", "picture", "photo", "draw", "art", "visual",
         "illustration", "diagram", "render"],
        0.0,
    ),
    "homeassistant": (
        ["home", "assistant", "light", "switch", "sensor", "automation",
         "smart home", "iot", "device", "thermostat"],
        0.0,
    ),
    "cronjob": (
        ["cron", "schedule", "timer", "periodic", "recurring", "interval"],
        0.0,
    ),
    "memory": (
        ["memory", "remember", "recall", "forget", "history", "context",
         "conversation", "session", "past"],
        0.0,
    ),
    "search": (
        ["search", "find", "look up", "query", "google", "web search",
         "research", "investigate", "tavily"],
        0.0,
    ),
    "git": (
        ["git", "commit", "branch", "merge", "pull", "push", "diff", "log",
         "repository", "repo", "github", "gitlab"],
        0.0,
    ),
    "mcp": (
        ["mcp", "prometheus", "metrics", "grafana", "monitor", "obsidian",
         "vault", "note", "gitnexus", "impact", "gitlab", "issue", "board",
         "pipeline"],
        0.0,
    ),
    "coding": (
        ["code", "program", "develop", "debug", "fix", "implement", "design",
         "architect", "algorithm", "data structure", "api", "endpoint",
         "function", "class", "module", "library", "framework", "test",
         "unit test", "integration", "refactor", "optimize", "performance",
         "rl", "reinforcement", "training", "model", "neural", "ml",
         "machine learning", "deep learning", "pytorch", "tensorflow",
         "ray", "distributed"],
        0.2,
    ),
}


def _estimate_tool_tokens(tool: Dict[str, Any]) -> int:
    """Estimate token count for a single tool schema."""
    schema_str = json.dumps(tool)
    return int(len(schema_str) / CHARS_PER_TOKEN)


def _score_category(prompt_lower: str, keywords: List[str], boost: float) -> float:
    """Score how relevant a tool category is to the prompt."""
    score = boost
    for keyword in keywords:
        if keyword in prompt_lower:
            # Longer keyword matches are more specific = higher value
            score += 0.5 + (len(keyword) / 20.0)
    return score


def _get_tool_category(tool: Dict[str, Any]) -> str:
    """Infer which category a tool belongs to based on its name and description."""
    func = tool.get("function", {})
    name = func.get("name", "").lower()
    desc = (func.get("description") or "").lower()
    combined = f"{name} {desc}"

    best_category = "other"
    best_score = 0.0

    for category, (keywords, _) in TOOL_CATEGORIES.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > best_score:
            best_score = score
            best_category = category

    return best_category


def select_tools(
    tools: List[Dict[str, Any]],
    messages: List[Dict[str, Any]],
    token_budget: int = DEFAULT_TOOL_TOKEN_BUDGET,
    max_tools: int = MAX_TOOLS,
) -> List[Dict[str, Any]]:
    """
    Select the most relevant tools for the given prompt within token budget.

    Args:
        tools: Full list of tool schemas from Hermes
        messages: Conversation messages (used to extract prompt context)
        token_budget: Maximum tokens to allocate for tool schemas
        max_tools: Hard cap on number of tools

    Returns:
        Filtered list of tool schemas that fit within budget
    """
    if not tools:
        return []

    # If tools already fit, return all
    total_tokens = sum(_estimate_tool_tokens(t) for t in tools)
    if total_tokens <= token_budget and len(tools) <= max_tools:
        logger.info(
            "All %d tools fit within budget (%d tokens <= %d), forwarding all",
            len(tools), total_tokens, token_budget,
        )
        return tools

    # Extract prompt context from messages
    prompt_parts = []
    for msg in messages:
        if msg.get("role") in ("user", "system"):
            content = msg.get("content", "")
            if isinstance(content, str):
                prompt_parts.append(content)
    prompt_lower = " ".join(prompt_parts).lower()

    # Score each category
    category_scores: Dict[str, float] = {}
    for category, (keywords, boost) in TOOL_CATEGORIES.items():
        category_scores[category] = _score_category(prompt_lower, keywords, boost)

    # Classify each tool into a category
    tool_categories: Dict[str, List[Dict[str, Any]]] = {}
    for tool in tools:
        func = tool.get("function", {})
        name = func.get("name", "")

        # Essential tools always included
        if name in ESSENTIAL_TOOLS:
            tool_categories.setdefault("_essential", []).append(tool)
            continue

        category = _get_tool_category(tool)
        tool_categories.setdefault(category, []).append(tool)

    # Build selected tools list, starting with essentials
    selected: List[Dict[str, Any]] = list(tool_categories.get("_essential", []))
    used_tokens = sum(_estimate_tool_tokens(t) for t in selected)

    # Sort categories by score (highest first), skip essentials
    sorted_categories = sorted(
        [(cat, score) for cat, score in category_scores.items() if score > 0],
        key=lambda x: x[1],
        reverse=True,
    )

    for category, score in sorted_categories:
        if len(selected) >= max_tools:
            break

        cat_tools = tool_categories.get(category, [])
        if not cat_tools:
            continue

        # Check if adding this category stays within budget
        cat_tokens = sum(_estimate_tool_tokens(t) for t in cat_tools)
        if used_tokens + cat_tokens <= token_budget and len(selected) + len(cat_tools) <= max_tools:
            selected.extend(cat_tools)
            used_tokens += cat_tokens
            logger.debug(
                "Added category '%s' (%d tools, %d tokens, score=%.2f)",
                category, len(cat_tools), cat_tokens, score,
            )
        else:
            # Try adding individual tools from this category
            for tool in cat_tools:
                tool_tokens = _estimate_tool_tokens(tool)
                if used_tokens + tool_tokens <= token_budget and len(selected) < max_tools:
                    selected.append(tool)
                    used_tokens += tool_tokens

    # Also add tools from zero-scored categories if there's room (catch-all)
    for category in tool_categories:
        if category == "_essential":
            continue
        if category_scores.get(category, 0) > 0:
            continue
        for tool in tool_categories[category]:
            tool_tokens = _estimate_tool_tokens(tool)
            if used_tokens + tool_tokens <= token_budget and len(selected) < max_tools:
                selected.append(tool)
                used_tokens += tool_tokens

    selected_names = [t.get("function", {}).get("name", "?") for t in selected]
    logger.info(
        "Tool selection: %d/%d tools (%d tokens), categories=%s, tools=%s",
        len(selected),
        len(tools),
        used_tokens,
        [c for c, s in sorted_categories if s > 0],
        selected_names,
    )

    return selected
