#!/usr/bin/env python3
"""Research discovery pipeline for the SHML knowledge graph.

Scans arXiv and HuggingFace for papers/models relevant to platform topics,
writes discovery notes to the Obsidian vault with wikilinks, and maintains
a research index for the intelligence layer.

Topics tracked (configurable via RESEARCH_TOPICS env or topics.json):
  - Reinforcement learning + robotics
  - MLOps / experiment tracking
  - LLM inference optimization (quantization, serving)
  - Vision models / face detection
  - Sim-to-real transfer

Usage:
    # Daily scan (intended for systemd timer)
    python3 scripts/knowledge/research_discovery.py

    # Scan specific topic
    python3 scripts/knowledge/research_discovery.py --topic "reinforcement learning robotics"

    # Dry run (print, don't write to vault)
    python3 scripts/knowledge/research_discovery.py --dry-run

    # Force rescan (ignore last-seen dates)
    python3 scripts/knowledge/research_discovery.py --force
"""
from __future__ import annotations

import json
import logging
import os
import sys
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Add platform libs to path for shared utilities
_PLATFORM_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from libs.notify import send_telegram

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

PLATFORM_ROOT = Path(__file__).resolve().parent.parent.parent
VAULT_DIR = PLATFORM_ROOT / "docs" / "obsidian-vault"
RESEARCH_DIR = VAULT_DIR / "10-Research"
STATE_FILE = PLATFORM_ROOT / "scripts" / "knowledge" / "discovery_state.json"

DEFAULT_TOPICS = [
    {
        "name": "rl-robotics",
        "label": "Reinforcement Learning & Robotics",
        "arxiv_query": "cat:cs.RO+AND+(reinforcement+learning+OR+sim-to-real+OR+robot+policy)",
        "hf_query": "reinforcement-learning robotics",
        "tags": ["rl", "robotics", "sim2real"],
    },
    {
        "name": "mlops",
        "label": "MLOps & Experiment Tracking",
        "arxiv_query": "cat:cs.LG+AND+(experiment+tracking+OR+mlops+OR+model+registry+OR+ml+pipeline)",
        "hf_query": "mlops experiment-tracking",
        "tags": ["mlops", "tracking"],
    },
    {
        "name": "llm-inference",
        "label": "LLM Inference Optimization",
        "arxiv_query": "cat:cs.CL+AND+(quantization+OR+model+serving+OR+inference+optimization+OR+speculative+decoding)",
        "hf_query": "quantization inference-optimization",
        "tags": ["llm", "inference", "quantization"],
    },
    {
        "name": "vision-detection",
        "label": "Vision & Face Detection",
        "arxiv_query": "cat:cs.CV+AND+(face+detection+OR+object+detection+OR+vision+transformer+OR+yolo)",
        "hf_query": "object-detection face-detection",
        "tags": ["vision", "detection", "face"],
    },
    {
        "name": "sim2real",
        "label": "Sim-to-Real Transfer",
        "arxiv_query": "cat:cs.RO+AND+(sim-to-real+OR+domain+randomization+OR+digital+twin+OR+simulation+transfer)",
        "hf_query": "sim-to-real simulation",
        "tags": ["sim2real", "robotics", "simulation"],
    },
]


@dataclass
class Paper:
    title: str
    authors: list[str]
    abstract: str
    arxiv_id: str
    published: str
    categories: list[str] = field(default_factory=list)
    url: str = ""
    relevance_tags: list[str] = field(default_factory=list)


@dataclass
class HFModel:
    model_id: str
    author: str
    downloads: int
    likes: int
    pipeline_tag: str
    tags: list[str] = field(default_factory=list)
    url: str = ""


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_scan": {}, "seen_ids": []}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def search_arxiv(query: str, max_results: int = 10) -> list[Paper]:
    """Search arXiv API for recent papers."""
    base_url = "http://export.arxiv.org/api/query"
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{base_url}?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SHML-Platform/0.1 research-discovery"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read().decode("utf-8")
    except Exception as e:
        logger.warning("arXiv API error: %s", e)
        return []

    # Simple XML parsing (avoid lxml dependency)
    papers = []
    entries = data.split("<entry>")[1:]  # Skip feed header
    for entry in entries:
        title = _extract_xml(entry, "title").strip().replace("\n", " ")
        abstract = _extract_xml(entry, "summary").strip().replace("\n", " ")[:500]
        arxiv_id = _extract_xml(entry, "id").split("/abs/")[-1] if "/abs/" in _extract_xml(entry, "id") else ""
        published = _extract_xml(entry, "published")[:10]

        # Extract authors
        authors = []
        for author_block in entry.split("<author>")[1:]:
            name = _extract_xml(author_block, "name")
            if name:
                authors.append(name)

        if title and arxiv_id:
            papers.append(Paper(
                title=title,
                authors=authors[:5],
                abstract=abstract,
                arxiv_id=arxiv_id,
                published=published,
                url=f"https://arxiv.org/abs/{arxiv_id}",
            ))

    return papers


def search_huggingface(query: str, max_results: int = 5) -> list[HFModel]:
    """Search HuggingFace Hub for trending models."""
    url = f"https://huggingface.co/api/models?search={urllib.parse.quote(query)}&sort=downloads&direction=-1&limit={max_results}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SHML-Platform/0.1 research-discovery"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        logger.warning("HuggingFace API error: %s", e)
        return []

    models = []
    for item in data:
        model_id = item.get("modelId", "")
        if not model_id:
            continue
        models.append(HFModel(
            model_id=model_id,
            author=item.get("author", ""),
            downloads=item.get("downloads", 0),
            likes=item.get("likes", 0),
            pipeline_tag=item.get("pipeline_tag", ""),
            tags=item.get("tags", [])[:10],
            url=f"https://huggingface.co/{model_id}",
        ))

    return models


def _extract_xml(text: str, tag: str) -> str:
    """Extract text between XML tags (simple, no namespace handling)."""
    start = text.find(f"<{tag}>")
    if start == -1:
        start = text.find(f"<{tag} ")
        if start == -1:
            return ""
        start = text.find(">", start) + 1
    else:
        start += len(f"<{tag}>")
    end = text.find(f"</{tag}>", start)
    if end == -1:
        return ""
    return text[start:end]


def generate_vault_note(topic: dict, papers: list[Paper], models: list[HFModel], date: str) -> str:
    """Generate Obsidian-flavored markdown note for discoveries."""
    tags_str = " ".join(f"#{t}" for t in topic["tags"])
    lines = [
        "---",
        f'title: "{topic["label"]} — {date}"',
        f'date: {date}',
        f'type: research-discovery',
        f'topic: {topic["name"]}',
        f'tags: [{", ".join(topic["tags"])}]',
        "---",
        "",
        f"# {topic['label']} — {date}",
        "",
        f"> [!info] Auto-discovered by [[Research Discovery Pipeline]]",
        f"> Scanned arXiv + HuggingFace for: {topic['label']}",
        "",
    ]

    if papers:
        lines.append("## arXiv Papers")
        lines.append("")
        for p in papers:
            authors_str = ", ".join(p.authors[:3])
            if len(p.authors) > 3:
                authors_str += " et al."
            lines.append(f"### [{p.title}]({p.url})")
            lines.append(f"**Authors:** {authors_str} | **Published:** {p.published}")
            lines.append(f"")
            lines.append(f"> {p.abstract}")
            lines.append("")
            # Relevance assessment placeholder
            lines.append(f"**Platform relevance:** *To be assessed* {tags_str}")
            lines.append("")

    if models:
        lines.append("## HuggingFace Models")
        lines.append("")
        for m in models:
            lines.append(f"### [{m.model_id}]({m.url})")
            lines.append(f"**Downloads:** {m.downloads:,} | **Likes:** {m.likes} | **Pipeline:** {m.pipeline_tag}")
            if m.tags:
                lines.append(f"**Tags:** {', '.join(m.tags[:5])}")
            lines.append("")

    # Cross-references to platform
    lines.extend([
        "## Platform Cross-References",
        "",
        f"- [[CONNECTION_MAP]] — Service topology",
        f"- [[Architecture Overview]] — Platform architecture",
    ])

    if "rl" in topic["tags"] or "robotics" in topic["tags"]:
        lines.append("- [[shml-robotics]] — Robotics simulation project")
    if "llm" in topic["tags"] or "inference" in topic["tags"]:
        lines.append("- [[Inference Stack]] — LLM/Image inference services")
    if "vision" in topic["tags"] or "detection" in topic["tags"]:
        lines.append("- [[Face Detection Training]] — SAPO curriculum learning")
    if "mlops" in topic["tags"]:
        lines.append("- [[MLflow Operations]] — Experiment tracking")

    lines.append("")
    return "\n".join(lines)


def run_discovery(
    topics: Optional[list[dict]] = None,
    dry_run: bool = False,
    force: bool = False,
    single_topic: Optional[str] = None,
) -> dict:
    """Run the full discovery pipeline."""
    if topics is None:
        topics = DEFAULT_TOPICS

    if single_topic:
        topics = [t for t in topics if single_topic.lower() in t["name"].lower() or single_topic.lower() in t["label"].lower()]
        if not topics:
            logger.error("No matching topic for: %s", single_topic)
            return {"error": "No matching topic"}

    state = load_state()
    today = datetime.now().strftime("%Y-%m-%d")
    results: dict[str, dict] = {}

    for topic in topics:
        topic_name = topic["name"]

        # Skip if already scanned today (unless forced)
        if not force and state.get("last_scan", {}).get(topic_name) == today:
            logger.info("Skipping %s (already scanned today)", topic_name)
            continue

        logger.info("Scanning: %s", topic["label"])

        # Search arXiv
        papers = search_arxiv(topic["arxiv_query"], max_results=5)
        # Filter out previously seen
        seen = set(state.get("seen_ids", []))
        new_papers = [p for p in papers if p.arxiv_id not in seen]

        # Search HuggingFace
        models = search_huggingface(topic.get("hf_query", ""), max_results=3)

        results[topic_name] = {
            "papers": len(new_papers),
            "models": len(models),
            "total_papers_found": len(papers),
        }

        if not new_papers and not models:
            logger.info("  No new discoveries for %s", topic_name)
            state.setdefault("last_scan", {})[topic_name] = today
            continue

        # Generate vault note
        note = generate_vault_note(topic, new_papers, models, today)

        if dry_run:
            print(f"\n{'='*60}")
            print(f"TOPIC: {topic['label']}")
            print(f"Papers: {len(new_papers)} new / {len(papers)} total | Models: {len(models)}")
            print(f"{'='*60}")
            print(note[:1000])
            print("...")
        else:
            # Write to Obsidian vault
            note_filename = f"{today}_{topic_name}.md"
            note_path = RESEARCH_DIR / note_filename
            RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
            note_path.write_text(note)
            logger.info("  Wrote: %s", note_path.relative_to(PLATFORM_ROOT))

        # Update state
        for p in new_papers:
            state.setdefault("seen_ids", []).append(p.arxiv_id)
        state.setdefault("last_scan", {})[topic_name] = today

    # Keep seen_ids list bounded (last 1000)
    if len(state.get("seen_ids", [])) > 1000:
        state["seen_ids"] = state["seen_ids"][-1000:]

    if not dry_run:
        save_state(state)

    return results


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="SHML Research Discovery Pipeline")
    parser.add_argument("--topic", default=None, help="Scan a specific topic only")
    parser.add_argument("--dry-run", action="store_true", help="Print discoveries, don't write to vault")
    parser.add_argument("--force", action="store_true", help="Ignore last-scanned dates")
    args = parser.parse_args()

    results = run_discovery(
        single_topic=args.topic,
        dry_run=args.dry_run,
        force=args.force,
    )

    total_papers = sum(r.get("papers", 0) for r in results.values())
    total_models = sum(r.get("models", 0) for r in results.values())
    logger.info("Discovery complete: %d new papers, %d models across %d topics", total_papers, total_models, len(results))

    # Send Telegram summary
    if results and not args.dry_run:
        _send_discovery_telegram(results, total_papers, total_models)

    return 0


def _send_discovery_telegram(results: dict, total_papers: int, total_models: int) -> None:
    """Send a Telegram summary of today's research discoveries."""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [f"🔬 *Research Discovery — {today}*"]
    lines.append(f"{total_papers} new papers, {total_models} models across {len(results)} topics")
    lines.append("")

    for topic_name, stats in results.items():
        new = stats.get("papers", 0)
        total = stats.get("total_papers_found", 0)
        models = stats.get("models", 0)
        status = "✅" if new > 0 or models > 0 else "—"
        lines.append(f"{status} *{topic_name}*: {new} new papers (of {total}), {models} models")

    if total_papers == 0 and total_models == 0:
        lines.append("\nNo new discoveries today.")
    else:
        lines.append(f"\n📁 Notes written to `docs/obsidian-vault/10-Research/`")

    send_telegram("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
