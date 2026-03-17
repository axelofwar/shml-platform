#!/usr/bin/env python3
"""
T4.3 — Research ingestion pipeline.
Converts docs/research/*.md into atomic Obsidian notes with backlinks,
tags, and a manifest index written to docs/obsidian-vault/research/.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from typing import NamedTuple

# ── Paths ──────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = REPO_ROOT / "docs" / "research"
VAULT_RESEARCH = REPO_ROOT / "docs" / "obsidian-vault" / "10-Research"
VAULT_HOME = REPO_ROOT / "docs" / "obsidian-vault" / "00-Dashboard"

# Files to skip (already have dedicated vault homes or are generated)
SKIP = {"IMPLEMENTATION_TASK_BOARD.md"}

# ── Extraction helpers ──────────────────────────────────────────────────────
H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
H2_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
ACTION_RE = re.compile(
    r"(?m)^[\*\-]\s+\*{0,2}(TODO|Action|Step|Next|Implement|Build|Run|Deploy|Create|Setup)[\:：]?\*{0,2}\s+(.+)$",
    re.IGNORECASE,
)
CLAIM_RE = re.compile(
    r"(?m)^[\*\-]\s+(?:Key|Finding|Insight|Result|Lesson)[\:：]\s+(.+)$",
    re.IGNORECASE,
)


class ParsedDoc(NamedTuple):
    source_path: Path
    title: str
    sections: list[str]       # h2 heading text
    action_items: list[str]
    claims: list[str]
    external_links: list[tuple[str, str]]  # (label, url)
    raw: str


def parse_md(path: Path) -> ParsedDoc:
    raw = path.read_text(encoding="utf-8")

    # title: first H1, else filename
    m = H1_RE.search(raw)
    title = m.group(1).strip() if m else path.stem.replace("_", " ").title()

    sections = [h.strip() for h in H2_RE.findall(raw)]
    action_items = [f"{m.group(1)}: {m.group(2).strip()}" for m in ACTION_RE.finditer(raw)]
    claims = [c.strip() for c in CLAIM_RE.findall(raw)]
    external_links = [
        (label, url)
        for label, url in LINK_RE.findall(raw)
        if url.startswith("http")
    ]

    return ParsedDoc(
        source_path=path,
        title=title,
        sections=sections,
        action_items=action_items,
        claims=claims,
        external_links=external_links,
        raw=raw,
    )


# ── Note generation ────────────────────────────────────────────────────────
def slug(title: str) -> str:
    """Convert title to safe filename slug."""
    s = re.sub(r"[^a-zA-Z0-9\s_-]", "", title)
    s = re.sub(r"\s+", "_", s.strip())
    return s[:60]


def make_note(doc: ParsedDoc, today: str) -> str:
    lines: list[str] = []

    # Frontmatter
    tags = _infer_tags(doc)
    lines.append("---")
    lines.append(f"title: \"{doc.title}\"")
    lines.append(f"source: [[{doc.source_path.name}]]")
    lines.append(f"ingested: {today}")
    lines.append(f"tags: [{', '.join(tags)}]")
    lines.append("---")
    lines.append("")

    # Title
    lines.append(f"# {doc.title}")
    lines.append("")
    lines.append(f"> Source: `docs/research/{doc.source_path.name}`  |  Ingested: {today}")
    lines.append("")

    # Table of contents (sections)
    if doc.sections:
        lines.append("## Sections")
        for sec in doc.sections:
            lines.append(f"- {sec}")
        lines.append("")

    # Key claims / findings
    if doc.claims:
        lines.append("## Key Findings")
        for claim in doc.claims[:10]:
            lines.append(f"- {claim}")
        lines.append("")

    # Action items
    if doc.action_items:
        lines.append("## Action Items")
        for item in doc.action_items[:15]:
            lines.append(f"- [ ] {item}")
        lines.append("")

    # External references
    if doc.external_links:
        lines.append("## External Links")
        seen: set[str] = set()
        for label, url in doc.external_links[:20]:
            if url not in seen:
                lines.append(f"- [{label}]({url})")
                seen.add(url)
        lines.append("")

    # Backlinks
    lines.append("## Backlinks")
    lines.append("- [[10-Research/INDEX]]")
    lines.append("- [[00-Dashboard/HOME]]")
    lines.append("")

    return "\n".join(lines)


def _infer_tags(doc: ParsedDoc) -> list[str]:
    tags = ["research"]
    title_lower = doc.title.lower()
    text_lower = doc.raw.lower()
    mapping = {
        "qwen": "qwen",
        "hermes": "hermes",
        "obsidian": "obsidian",
        "yolo": "yolo",
        "face": "face-detection",
        "training": "training",
        "autoresearch": "autoresearch",
        "eval": "evaluation",
        "sota": "sota",
        "chat": "chat-ui",
        "deploy": "deployment",
        "plan": "planning",
    }
    for kw, tag in mapping.items():
        if kw in title_lower or kw in text_lower[:2000]:
            tags.append(tag)
    return list(dict.fromkeys(tags))  # dedup, preserve order


# ── Index ──────────────────────────────────────────────────────────────────
def make_index(docs: list[ParsedDoc], today: str) -> str:
    lines = [
        "---",
        "title: \"Research Index\"",
        f"updated: {today}",
        "tags: [research, index]",
        "---",
        "",
        "# Research Index",
        "",
        "| Note | Sections | Actions |",
        "|------|----------|---------|",
    ]
    for doc in docs:
        note_name = slug(doc.title)
        n_actions = len(doc.action_items)
        n_sections = len(doc.sections)
        lines.append(f"| [[{note_name}]] | {n_sections} | {n_actions} |")
    lines += [
        "",
        "## Backlinks",
        "- [[HOME]]",
        "",
    ]
    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────
def main() -> None:
    VAULT_RESEARCH.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()

    md_files = sorted(RESEARCH_DIR.glob("*.md"))
    docs: list[ParsedDoc] = []
    created: list[str] = []
    skipped: list[str] = []

    for path in md_files:
        if path.name in SKIP:
            skipped.append(path.name)
            continue
        doc = parse_md(path)
        docs.append(doc)

        note_slug = slug(doc.title)
        note_path = VAULT_RESEARCH / f"{note_slug}.md"
        note_content = make_note(doc, today)
        note_path.write_text(note_content, encoding="utf-8")
        created.append(note_path.name)
        print(f"  ✓ {path.name}  →  10-Research/{note_path.name}")

    # NOTE: INDEX.md is Dataview-powered — do not overwrite it.
    # Dataview automatically lists all notes in 10-Research via frontmatter.
    print(f"  ℹ  INDEX.md managed by Dataview (skipped) — {len(docs)} notes in vault")

    # Update HOME.md to link research index (new path: 00-Dashboard/HOME.md)
    home_path = VAULT_HOME / "HOME.md"
    if home_path.exists():
        home = home_path.read_text(encoding="utf-8")
        marker = "*Research index last ingested"
        if marker not in home:
            home_path.write_text(home.rstrip() + f"\n\n---\n*Research index last ingested: {today} — {len(docs)} notes*\n", encoding="utf-8")
            print("  ✓ Updated HOME.md ingestion timestamp")

    print(f"\nDone. Created {len(created)} notes, skipped {len(skipped)}.")
    if skipped:
        print(f"  Skipped: {', '.join(skipped)}")


if __name__ == "__main__":
    sys.exit(main())
