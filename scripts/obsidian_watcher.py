#!/usr/bin/env python3
"""
Obsidian Research Watcher
==========================
Watches docs/research/ for new or changed *.md files
and automatically re-runs the ingestion pipeline so the
Obsidian vault stays in sync — no manual steps required.

Designed to run:
  • AS A STANDALONE DAEMON:  python scripts/obsidian_watcher.py
  • AS AN AGENT-SERVICE THREAD:  imported by scheduler.py

Usage (standalone):
    cd /opt/shml-platform
    python scripts/obsidian_watcher.py           # foreground
    python scripts/obsidian_watcher.py &          # background
    python scripts/obsidian_watcher.py --debounce 30  # 30-second debounce

Requires:
    pip install watchdog
"""
from __future__ import annotations

import argparse
import importlib.util
import logging
import sys
import threading
import time
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[1]
RESEARCH_DIR = REPO_ROOT / "docs" / "research"
INGEST_SCRIPT = REPO_ROOT / "scripts" / "ingest_research_to_obsidian.py"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [obsidian-watcher] %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("obsidian-watcher")


CONN_MAP_SCRIPT = REPO_ROOT / "scripts" / "generate_connection_map.py"


# ── Lazy-load ingestion module ─────────────────────────────────────────────────────────────
def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_ingestion() -> None:
    """Run the ingest pipeline + refresh connection map, log the result."""
    try:
        logger.info("Change detected — running Obsidian ingestion pipeline…")
        mod = _load_module(INGEST_SCRIPT, "ingest")
        mod.main()
        logger.info("Ingestion complete.")
    except Exception as exc:
        logger.error(f"Ingestion failed: {exc}", exc_info=True)

    # Regenerate connection map so the vault always has an up-to-date snapshot
    try:
        if CONN_MAP_SCRIPT.exists():
            cm = _load_module(CONN_MAP_SCRIPT, "connection_map")
            cm.main()
            logger.info("Connection map refreshed.")
    except Exception as exc:
        logger.warning(f"Connection map refresh failed (non-fatal): {exc}", exc_info=True)


# ── Debounced event handler ────────────────────────────────────────────────
class _DebounceHandler:
    """
    Coalesces rapid file events (e.g. editor save + backup write) into
    a single ingestion run after `debounce_secs` of quiet time.
    """

    def __init__(self, debounce_secs: float = 10.0):
        self._debounce = debounce_secs
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def trigger(self, path: str) -> None:
        logger.debug(f"File event: {path}")
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._debounce, run_ingestion)
            self._timer.daemon = True
            self._timer.start()

    def cancel(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


# ── watchdog integration ───────────────────────────────────────────────────
def _build_watchdog_handler(debounce: _DebounceHandler):
    """Build a watchdog FileSystemEventHandler that only tracks *.md files."""
    try:
        from watchdog.events import FileSystemEventHandler  # type: ignore
    except ImportError:
        raise RuntimeError("watchdog not installed — run: pip install watchdog")

    class _Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            if event.is_directory:
                return
            src = getattr(event, "src_path", "") or ""
            dest = getattr(event, "dest_path", "") or ""
            for p in (src, dest):
                if p.endswith(".md"):
                    debounce.trigger(p)
                    break

    return _Handler()


def start_watcher(debounce_secs: float = 10.0) -> None:
    """Start a blocking watchdog observer over docs/research/. Never returns."""
    try:
        from watchdog.observers import Observer  # type: ignore
    except ImportError:
        raise RuntimeError("watchdog not installed — run: pip install watchdog")

    if not RESEARCH_DIR.exists():
        logger.warning(f"Research dir not found: {RESEARCH_DIR} — watcher idle")
        while True:
            time.sleep(60)

    debounce = _DebounceHandler(debounce_secs)
    handler = _build_watchdog_handler(debounce)

    observer = Observer()
    observer.schedule(handler, str(RESEARCH_DIR), recursive=False)
    observer.start()

    logger.info(
        f"Watching {RESEARCH_DIR} for *.md changes "
        f"(debounce={debounce_secs}s)…"
    )

    # Run initial ingestion on start to catch any files added while offline
    run_ingestion()

    try:
        while observer.is_alive():
            observer.join(timeout=5)
    except KeyboardInterrupt:
        logger.info("Interrupt received — stopping watcher")
    finally:
        debounce.cancel()
        observer.stop()
        observer.join()
        logger.info("Watcher stopped.")


# ── Async-friendly wrapper for scheduler.py ───────────────────────────────
def start_watcher_thread(debounce_secs: float = 10.0) -> threading.Thread:
    """
    Spin up the watcher in a daemon thread.
    Safe to call from asyncio code (scheduler.py).

    Returns the thread handle.
    """
    t = threading.Thread(
        target=start_watcher,
        args=(debounce_secs,),
        name="obsidian-watcher",
        daemon=True,
    )
    t.start()
    logger.info(f"Obsidian watcher thread started (tid={t.ident})")
    return t


# ── CLI entry point ────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Watch docs/research/ and auto-sync Obsidian vault"
    )
    parser.add_argument(
        "--debounce",
        type=float,
        default=10.0,
        metavar="SECONDS",
        help="Seconds of quiet time before triggering ingestion (default: 10)",
    )
    args = parser.parse_args()
    start_watcher(debounce_secs=args.debounce)


if __name__ == "__main__":
    sys.exit(main())
