"""Dataset utilities for QLoRA fine-tuning of Qwen3-VL.

Supports two formats:
  - sharegpt: {"conversations": [{"from": "human"|"gpt", "value": "..."}]}
  - alpaca:   {"instruction": "...", "input": "...", "output": "..."}

Also provides streaming loader for very large JSONL files.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Generator, Iterator

logger = logging.getLogger(__name__)

# Roles → ChatML speaker tokens
_SHAREGPT_ROLE_MAP = {
    "system": "system",
    "human": "user",
    "gpt": "assistant",
    "tool": "tool",
}


def _fmt_sharegpt(sample: dict) -> list[dict[str, str]]:
    """Convert ShareGPT sample → list of {role, content} dicts."""
    messages = []
    for turn in sample.get("conversations", []):
        role = _SHAREGPT_ROLE_MAP.get(turn.get("from", ""), "user")
        messages.append({"role": role, "content": turn.get("value", "")})
    return messages


def _fmt_alpaca(sample: dict) -> list[dict[str, str]]:
    """Convert Alpaca sample → list of {role, content} dicts."""
    instruction = sample.get("instruction", "")
    inp = sample.get("input", "")
    output = sample.get("output", "")
    user_content = f"{instruction}\n\n{inp}".strip() if inp else instruction
    return [
        {"role": "user", "content": user_content},
        {"role": "assistant", "content": output},
    ]


def format_sample(sample: dict, fmt: str = "sharegpt") -> list[dict[str, str]]:
    """Format a raw sample dict into a messages list.

    Args:
        sample: Raw dict loaded from JSONL.
        fmt: "sharegpt" or "alpaca".

    Returns:
        List of {"role": ..., "content": ...} dicts.
    """
    if fmt == "sharegpt":
        return _fmt_sharegpt(sample)
    if fmt == "alpaca":
        return _fmt_alpaca(sample)
    raise ValueError(f"Unknown dataset format: {fmt!r}")


def iter_jsonl(path: str | Path) -> Generator[dict, None, None]:
    """Yield raw dicts from a JSONL file."""
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("Skipping malformed JSON at line %d: %s", lineno, exc)


def stream_from_hf(
    repo_id: str,
    split: str = "train",
    fmt: str = "sharegpt",
    token: str | None = None,
) -> Iterator[list[dict[str, str]]]:
    """Stream a HuggingFace dataset as formatted messages.

    Requires TRANSFORMERS_OFFLINE=0 or a locally cached repo.

    Args:
        repo_id: HuggingFace dataset repo (e.g. "teknium/OpenHermes-2.5").
        split:   Dataset split name.
        fmt:     "sharegpt" or "alpaca".
        token:   HF token (reads HF_TOKEN env var if None).

    Yields:
        Formatted messages list per sample.
    """
    import os
    from datasets import load_dataset  # type: ignore[import]

    hf_token = token or os.getenv("HF_TOKEN")
    ds = load_dataset(repo_id, split=split, streaming=True, token=hf_token)
    for sample in ds:
        try:
            yield format_sample(sample, fmt=fmt)
        except Exception as exc:
            logger.warning("Skipping sample due to formatting error: %s", exc)


def load_jsonl_dataset(
    path: str | Path,
    fmt: str = "sharegpt",
    max_samples: int | None = None,
) -> list[list[dict[str, str]]]:
    """Load a JSONL file into a list of formatted message lists.

    Args:
        path:        Path to JSONL file.
        fmt:         "sharegpt" or "alpaca".
        max_samples: Cap the number of samples loaded (None = all).

    Returns:
        List of formatted conversation lists.
    """
    samples = []
    for i, raw in enumerate(iter_jsonl(path)):
        if max_samples is not None and i >= max_samples:
            break
        try:
            samples.append(format_sample(raw, fmt=fmt))
        except Exception as exc:
            logger.warning("Skipping sample %d: %s", i, exc)
    logger.info("Loaded %d samples from %s", len(samples), path)
    return samples
