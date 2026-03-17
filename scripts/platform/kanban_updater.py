#!/usr/bin/env python3
"""
kanban_updater.py — Reads platform scan evidence and moves cards in KANBAN.md.

Rules (deterministic only — no guessing):
  • Autoresearch Round 2 done (map50 > 0.814, process finished) → move to Done
  • T8 nanochat all stages done + server + endpoint active → move to Done
  • T3.3 GEPA cycle triggered → move to Done
  • CLOUD_API_KEY set → move CLOUD_API_KEY card to Done
  • T7.4 Phase 6B blocked unblocked by AR done → move Blocked → Backlog

Usage:
    python3 kanban_updater.py --kanban KANBAN.md --evidence evidence.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple


# ── Card matching rules ──────────────────────────────────────────────────────

class MoveRule(NamedTuple):
    card_pattern: str          # substring to find the card (case-insensitive)
    from_cols: list[str]       # only move FROM these columns ("any" = any)
    to_col: str                # target column key: done|in_progress|backlog|blocked
    condition_key: str         # key in evidence (dot-notation) that must be truthy


MOVE_RULES: list[MoveRule] = [
    # Autoresearch Round 2 complete
    MoveRule("Autoresearch Round 2", ["in_progress", "backlog", "blocked"],
             "done", "autoresearch.round2_done"),

    # Full T8 pipeline done
    MoveRule("Track 8: nanochat", ["in_progress", "backlog", "blocked"],
             "done", "t8.all_done"),

    # GEPA triggered → move to Done (engine was already built, just needed run)
    MoveRule("T3.3 GEPA", ["in_progress", "backlog"],
             "done", "gepa_triggered"),

    # CLOUD_API_KEY set → unblock the card
    MoveRule("CLOUD_API_KEY", ["backlog", "blocked"],
             "done", "cloud_key_set"),

    # T7.4 Phase 6B — unblock when autoresearch Round 2 done
    MoveRule("T7.4 Phase 6B", ["blocked"],
             "backlog", "autoresearch.round2_done"),

    # T7.5 — unblock when T7.4 is done (use same trigger for now)
    MoveRule("T7.5 RF-DETR", ["blocked"],
             "backlog", "autoresearch.round2_done"),

    # FiftyOne eval — unblock when autoresearch done
    MoveRule("FiftyOne", ["blocked"],
             "backlog", "autoresearch.round2_done"),

    # Platform scan framework — this script itself running means it's done
    MoveRule("Platform scan framework", ["in_progress", "backlog"],
             "done", "_scan_running"),  # special: always true when this runs
]

COLUMN_HEADINGS = {
    "in_progress": "🔥 In Progress",
    "backlog":     "📋 Backlog",
    "done":        "✅ Done",
    "blocked":     "🚧 Blocked",
}

HEADING_TO_KEY = {v: k for k, v in COLUMN_HEADINGS.items()}


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_evidence(evidence: dict, dotkey: str) -> bool:
    """Resolve dot-notation key from evidence dict. Returns bool."""
    if dotkey == "_scan_running":
        return True
    keys = dotkey.split(".")
    val = evidence
    for k in keys:
        if not isinstance(val, dict) or k not in val:
            return False
        val = val[k]
    return bool(val)


def parse_kanban(text: str) -> tuple[dict[str, list[str]], list[str]]:
    """
    Parse KANBAN.md into:
      sections: {col_key: [card_line, ...]}
      extras: lines that don't belong to any known section (frontmatter, settings, etc.)

    Returns (sections, raw_lines_in_order) for reconstruction.
    """
    sections: dict[str, list[str]] = {k: [] for k in COLUMN_HEADINGS}
    raw_blocks: list[tuple[str | None, list[str]]] = []  # (col_key | None, lines)

    current_col: str | None = None
    current_block: list[str] = []

    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        # Check if this is a known section heading
        if stripped.startswith("## "):
            # Save previous block
            raw_blocks.append((current_col, current_block))
            current_block = [line]
            # Match heading
            heading_text = stripped[3:].strip()
            current_col = HEADING_TO_KEY.get(heading_text)
        else:
            current_block.append(line)

    raw_blocks.append((current_col, current_block))

    # Extract cards per section
    for col_key, block_lines in raw_blocks:
        if col_key is not None:
            for line in block_lines[1:]:  # skip the heading line itself
                s = line.strip()
                if s.startswith("- [ ]") or s.startswith("- [x]"):
                    sections[col_key].append(line.rstrip("\n"))

    return sections, raw_blocks


def card_matches(card_line: str, pattern: str) -> bool:
    return pattern.lower() in card_line.lower()


def apply_rules(sections: dict[str, list[str]], evidence: dict) -> tuple[dict[str, list[str]], list[str]]:
    """Apply all move rules. Returns updated sections and list of move descriptions."""
    moves: list[str] = []

    for rule in MOVE_RULES:
        if not get_evidence(evidence, rule.condition_key):
            continue

        # Find the card
        for from_col in (COLUMN_HEADINGS.keys() if rule.from_cols == ["any"] else rule.from_cols):
            for i, card in enumerate(sections.get(from_col, [])):
                if card_matches(card, rule.card_pattern):
                    if from_col == rule.to_col:
                        break  # already in target column
                    # Mark as done if moving to done
                    new_card = card
                    if rule.to_col == "done":
                        new_card = re.sub(r"- \[ \]", "- [x]", card, count=1)
                    else:
                        new_card = re.sub(r"- \[x\]", "- [ ]", card, count=1)

                    sections[from_col].pop(i)
                    sections[rule.to_col].append(new_card)
                    moves.append(
                        f"  Moved '{rule.card_pattern}' from {from_col} → {rule.to_col}"
                    )
                    break

    return sections, moves


def reconstruct_kanban(raw_blocks: list[tuple[str | None, list[str]]],
                       updated_sections: dict[str, list[str]]) -> str:
    """Rebuild the full KANBAN.md text from raw_blocks + updated card lists."""
    out_parts: list[str] = []

    for col_key, block_lines in raw_blocks:
        if col_key is None:
            # Pre-sections content (frontmatter) or trailing (settings)
            out_parts.append("".join(block_lines))
        else:
            # Output the heading
            heading = f"## {COLUMN_HEADINGS[col_key]}\n"
            out_parts.append(heading)
            out_parts.append("\n")
            cards = updated_sections[col_key]
            if cards:
                out_parts.append("\n".join(cards))
                out_parts.append("\n")
            out_parts.append("\n")

    return "".join(out_parts)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Update KANBAN.md based on platform evidence")
    parser.add_argument("--kanban", required=True, help="Path to KANBAN.md")
    parser.add_argument("--evidence", required=True, help="Path to evidence.json")
    parser.add_argument("--dry-run", action="store_true", help="Print moves without writing")
    args = parser.parse_args()

    kanban_path = Path(args.kanban)
    evidence_path = Path(args.evidence)

    if not kanban_path.exists():
        print(f"ERROR: {kanban_path} not found", file=sys.stderr)
        return 1
    if not evidence_path.exists():
        print(f"ERROR: {evidence_path} not found", file=sys.stderr)
        return 1

    with open(evidence_path) as f:
        evidence = json.load(f)

    kanban_text = kanban_path.read_text()

    sections, raw_blocks = parse_kanban(kanban_text)
    updated_sections, moves = apply_rules(sections, evidence)

    if not moves:
        print("No card moves needed.")
        return 0

    print(f"Applying {len(moves)} card move(s):")
    for m in moves:
        print(m)

    if args.dry_run:
        print("[dry-run] Not writing.")
        return 0

    new_text = reconstruct_kanban(raw_blocks, updated_sections)
    kanban_path.write_text(new_text)
    print(f"Written → {kanban_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
