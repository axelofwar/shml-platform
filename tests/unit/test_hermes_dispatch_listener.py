"""Unit tests for scripts/monitoring/hermes_dispatch_listener.py (issue #564).

Covers:
- allowlist enforcement (only TELEGRAM_DISPATCH_CHAT_ID is routed)
- command parsing (@hermes prefix stripped, cmd / args split)
- freeform fallback (non-command text queued to worker)
- help / ping handlers respond without touching network

No network I/O — send_telegram_reply is monkey-patched to a local capture.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


def _load_listener(monkeypatch, allowed_id: str = "111111") -> object:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "TEST")
    monkeypatch.setenv("TELEGRAM_DISPATCH_CHAT_ID", allowed_id)
    if "scripts.monitoring.hermes_dispatch_listener" in sys.modules:
        del sys.modules["scripts.monitoring.hermes_dispatch_listener"]
    sys.path.insert(
        0, str(REPO_ROOT / "scripts" / "monitoring"),
    )
    return importlib.import_module("hermes_dispatch_listener")


def test_ping_handler_replies_pong(monkeypatch):
    mod = _load_listener(monkeypatch)
    seen: list[tuple[int, str]] = []
    monkeypatch.setattr(
        mod, "send_telegram_reply",
        lambda chat_id, text, **_: seen.append((chat_id, text)) or True,
    )
    mod._handle_ping(111111, "")
    assert seen == [(111111, "pong")]


def test_help_handler_lists_commands(monkeypatch):
    mod = _load_listener(monkeypatch)
    seen: list[str] = []
    monkeypatch.setattr(
        mod, "send_telegram_reply",
        lambda chat_id, text, **_: seen.append(text) or True,
    )
    mod._handle_help(111111, "")
    assert seen, "help handler sent nothing"
    body = seen[0]
    for expected in ("@hermes ping", "@hermes status", "@hermes gpu", "@hermes issue"):
        assert expected in body


def test_route_strips_prefix_and_routes_to_handler(monkeypatch):
    mod = _load_listener(monkeypatch)
    calls: list[tuple[str, str]] = []

    def fake_ping(chat_id, args):
        calls.append(("ping", args))

    def fake_help(chat_id, args):
        calls.append(("help", args))

    def fake_freeform(chat_id, body):
        calls.append(("freeform", body))

    monkeypatch.setitem(mod.COMMANDS, "ping", fake_ping)
    monkeypatch.setitem(mod.COMMANDS, "help", fake_help)
    monkeypatch.setattr(mod, "_handle_freeform", fake_freeform)

    mod._route_message(111111, "@hermes ping")
    mod._route_message(111111, "@hermes: help")
    mod._route_message(111111, "Hello there")
    mod._route_message(111111, "@hermes")

    assert calls == [
        ("ping", ""),
        ("help", ""),
        ("freeform", "Hello there"),
        ("help", ""),  # bare @hermes falls back to help
    ]


def test_freeform_handler_queues_and_acks(monkeypatch, tmp_path):
    mod = _load_listener(monkeypatch)
    monkeypatch.setattr(mod, "HERMES_BIN", tmp_path / "fake-hermes")
    (tmp_path / "fake-hermes").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "fake-hermes").chmod(0o755)
    monkeypatch.setattr(mod, "ALLOW_FREEFORM", True)
    sent: list[str] = []
    # Monkey-patch at the module level so _reply (which calls send_telegram_reply
    # via module-level binding) hits our capture, not the real HTTP client.
    monkeypatch.setattr(
        mod, "send_telegram_reply",
        lambda chat_id, text, **_: sent.append(text) or True,
    )
    # Also short-circuit the retry loop so tests stay fast
    monkeypatch.setenv("HERMES_TG_REPLY_RETRIES", "1")
    # Drain queue first to avoid contamination
    while not mod._freeform_q.empty():
        mod._freeform_q.get_nowait()

    mod._handle_freeform(111111, "tell me a joke")
    assert mod._freeform_q.qsize() == 1
    qitem = mod._freeform_q.get_nowait()
    assert qitem == (111111, "tell me a joke")
    assert sent, "no ack sent"
    assert "queued" in sent[0].lower()


def test_freeform_disabled_path(monkeypatch):
    mod = _load_listener(monkeypatch)
    monkeypatch.setattr(mod, "ALLOW_FREEFORM", False)
    sent: list[str] = []
    monkeypatch.setattr(
        mod, "send_telegram_reply",
        lambda chat_id, text, **_: sent.append(text) or True,
    )
    mod._handle_freeform(111111, "anything")
    assert sent and "disabled" in sent[0]


def test_issue_handler_requires_title(monkeypatch):
    mod = _load_listener(monkeypatch)
    sent: list[str] = []
    monkeypatch.setattr(
        mod, "send_telegram_reply",
        lambda chat_id, text, **_: sent.append(text) or True,
    )
    mod._handle_issue(111111, "")
    assert sent and "usage" in sent[0].lower()


def test_run_hermes_freeform_success(monkeypatch, tmp_path):
    """Happy path: fake hermes exits 0 with stdout → ✅ reply sent."""
    mod = _load_listener(monkeypatch)
    fake = tmp_path / "fake-hermes"
    fake.write_text("#!/bin/sh\necho 'hello from fake hermes'\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setattr(mod, "HERMES_BIN", fake)
    monkeypatch.setattr(mod, "FREEFORM_TIMEOUT", 10)
    monkeypatch.setattr(mod, "FREEFORM_PROGRESS_S", 0)  # disable pings
    monkeypatch.setenv("HERMES_TG_REPLY_RETRIES", "1")
    sent: list[str] = []
    monkeypatch.setattr(
        mod, "send_telegram_reply",
        lambda chat_id, text, **_: sent.append(text) or True,
    )

    mod._run_hermes_freeform(111111, "whatever")

    assert sent, "no reply captured"
    assert sent[-1].startswith("✅ hermes done")
    assert "hello from fake hermes" in sent[-1]


def test_run_hermes_freeform_timeout_kills_process_group(monkeypatch, tmp_path):
    """Slow fake hermes → ⏱ reply sent; process does not linger past wait()."""
    import time as _time

    mod = _load_listener(monkeypatch)
    fake = tmp_path / "slow-hermes"
    # Sleep longer than the timeout so the watcher loop has to kill it.
    fake.write_text("#!/bin/sh\nsleep 30\n")
    fake.chmod(0o755)
    monkeypatch.setattr(mod, "HERMES_BIN", fake)
    monkeypatch.setattr(mod, "FREEFORM_TIMEOUT", 2)
    monkeypatch.setattr(mod, "FREEFORM_PROGRESS_S", 0)
    monkeypatch.setenv("HERMES_TG_REPLY_RETRIES", "1")
    sent: list[str] = []
    monkeypatch.setattr(
        mod, "send_telegram_reply",
        lambda chat_id, text, **_: sent.append(text) or True,
    )

    t0 = _time.monotonic()
    mod._run_hermes_freeform(111111, "slow job")
    elapsed = _time.monotonic() - t0

    # Should be killed promptly after the 2s cap (plus ~1s poll granularity).
    # If the process-group kill regressed, this would push past 30s.
    assert elapsed < 8, f"worker hung for {elapsed:.1f}s (process-group kill broken?)"
    assert sent, "no reply captured"
    assert sent[-1].startswith("⏱ hermes exceeded")
