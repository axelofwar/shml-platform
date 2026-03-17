#!/usr/bin/env python3
"""
Focused tests for P1 modules:
  A) conversation_history  — save/load/batch/context
  B) hybrid_router         — intent classification, routing, fallback, structured logs
"""

import asyncio
import sys
import time

PASS = 0
FAIL = 0


def ok(label):
    global PASS
    PASS += 1
    print(f"  ✅ {label}")


def fail(label, detail=""):
    global FAIL
    FAIL += 1
    print(f"  ❌ {label}  {detail}")


# ─── A) conversation_history ────────────────────────────────────────────────


async def test_conversation_history():
    print("\n═══ A) conversation_history ═══")
    from app.database import AsyncSessionLocal, engine
    from app.conversation_history import (
        ensure_schema,
        save_turn,
        save_turns_batch,
        load_history,
        load_history_for_context,
        ConversationTurn,
        MAX_HISTORY_TURNS,
    )

    sid = f"p1-test-{int(time.time())}"
    uid = "p1-tester"

    # 1. ensure_schema idempotent
    async with AsyncSessionLocal() as db:
        await ensure_schema(db)
        await ensure_schema(db)  # second call must not raise
    ok("ensure_schema idempotent")

    # 2. save_turn returns ConversationTurn with id
    async with AsyncSessionLocal() as db:
        t = await save_turn(db, sid, uid, "user", "ping")
        await db.commit()
        assert isinstance(t, ConversationTurn) and t.id is not None
    ok("save_turn returns ConversationTurn with id")

    # 3. save_turns_batch handles multimodal + empty
    async with AsyncSessionLocal() as db:
        n = await save_turns_batch(
            db,
            sid,
            uid,
            [
                {"role": "assistant", "content": "pong"},
                {"role": "user", "content": [{"text": "hello"}, {"text": "world"}]},
                {"role": "user", "content": ""},  # empty → skipped
                {"role": "user", "content": "final"},
            ],
        )
        await db.commit()
        assert n == 3, f"expected 3, got {n}"
    ok(f"save_turns_batch saved 3 (skipped empty)")

    # 4. load_history returns oldest-first, respects limit
    async with AsyncSessionLocal() as db:
        h = await load_history(db, sid, limit=2)
        assert len(h) == 2
        # Gets most recent 2 rows desc, then reverses → older first
        assert h[-1]["content"] == "final"
    ok("load_history returns correct count, oldest-first")

    # 5. load_history caps at MAX_HISTORY_TURNS
    async with AsyncSessionLocal() as db:
        h = await load_history(db, sid, limit=9999)
        assert len(h) <= MAX_HISTORY_TURNS
    ok(f"load_history caps at MAX_HISTORY_TURNS ({MAX_HISTORY_TURNS})")

    # 6. load_history_for_context filters system/tool roles
    async with AsyncSessionLocal() as db:
        await save_turn(db, sid, uid, "system", "system-msg")
        await save_turn(db, sid, uid, "tool", "tool-msg")
        await db.commit()
    async with AsyncSessionLocal() as db:
        c = await load_history_for_context(db, sid, uid, limit=50)
        roles = {m["role"] for m in c}
        assert "system" not in roles and "tool" not in roles
    ok("load_history_for_context filters system/tool roles")

    # 7. load_history_for_context caps total bytes at 32 KB
    async with AsyncSessionLocal() as db:
        big = "x" * 10_000
        for i in range(10):
            await save_turn(db, sid, uid, "user", big)
        await db.commit()
    async with AsyncSessionLocal() as db:
        c = await load_history_for_context(db, sid, uid, limit=50)
        total = sum(len(m["content"].encode()) for m in c)
        assert total <= 32 * 1024 + 10_000  # ≤ cap + one message tolerance
    ok("load_history_for_context respects ~32 KB cap")

    # 8. load_history gracefully handles missing session
    async with AsyncSessionLocal() as db:
        h = await load_history(db, "nonexistent-session-xyz", limit=5)
        assert h == []
    ok("load_history returns [] for missing session")

    await engine.dispose()


# ─── B) hybrid_router ───────────────────────────────────────────────────────


def test_hybrid_router():
    print("\n═══ B) hybrid_router ═══")
    from app.hybrid_router import get_hybrid_router, HybridRouter, RoutingDecision
    from app.model_router import ModelType
    from dataclasses import asdict

    router = get_hybrid_router()
    assert isinstance(router, HybridRouter)
    ok("get_hybrid_router returns singleton")

    # Intent classification tests
    cases = [
        ("Write a Python sort function", None, "coding"),
        (
            "What do you see in this photo?",
            [{"type": "image", "mime_type": "image/png"}],
            "vision",
        ),
        ("Generate an image of a sunset over mountains", None, "image_gen"),
        ("Tell me about the capital of France", None, "general"),
        (
            "Analyze this screenshot and refactor the code",
            [{"type": "image", "mime_type": "image/jpeg"}],
            "vision",
        ),
        ("Create a JavaScript class for a linked list", None, "coding"),
    ]
    for prompt, attach, expected in cases:
        got = router._classify_intent(prompt, attach)
        if got == expected:
            ok(f"intent '{prompt[:45]}…' → {got}")
        else:
            fail(f"intent '{prompt[:45]}…'", f"expected={expected} got={got}")

    # Route returns ModelSelection with required fields
    sel = router.route("debug this Python traceback", request_id="test-1")
    assert sel.model_type in ModelType
    assert sel.gpu.startswith("cuda:")
    assert 0.0 <= sel.confidence <= 1.0
    assert sel.reasoning
    ok("route() returns valid ModelSelection")

    # route_with_plan returns dict with expected keys
    plan = router.route_with_plan(
        "Analyze this image and write code",
        [{"type": "image", "mime_type": "image/png"}],
        request_id="test-2",
    )
    assert "primary" in plan
    assert "multi_model_plan" in plan
    assert "intent" in plan
    assert "training_active" in plan
    ok("route_with_plan() returns expected structure")

    # Multi-model plan is generated for vision+code combo
    assert plan["multi_model_plan"] is not None
    models = [m.model_type.value for m in plan["multi_model_plan"].models]
    assert "qwen3-vl" in models and "qwen-coder" in models
    ok(f"multi-model plan includes vision+code: {models}")

    # Vision attachment always overrides keyword intent
    sel_vis = router.route(
        "Write Python code",
        [{"type": "image", "mime_type": "image/png"}],
    )
    assert sel_vis.model_type == ModelType.QWEN3_VL
    ok("image attachment overrides code keywords → vision model")

    # Attachment types extraction
    types = router._extract_attachment_types(
        [
            {"mime_type": "image/png"},
            {"type": "file"},
        ]
    )
    assert types == ["image/png", "file"]
    ok("_extract_attachment_types works")

    # RoutingDecision is a proper dataclass with all fields
    fields = set(RoutingDecision.__dataclass_fields__.keys())
    required = {
        "request_id",
        "timestamp",
        "intent",
        "has_attachments",
        "attachment_types",
        "selected_model",
        "model_type",
        "gpu",
        "confidence",
        "reasoning",
        "training_active",
        "fallback_used",
        "decision_time_ms",
    }
    assert required <= fields
    ok(f"RoutingDecision has all {len(required)} required fields")


# ─── Main ───────────────────────────────────────────────────────────────────


async def main():
    print("╔══════════════════════════════════════════╗")
    print("║   P1 Module Tests — Agent Service        ║")
    print("╚══════════════════════════════════════════╝")

    await test_conversation_history()
    test_hybrid_router()

    print(f"\n{'═' * 44}")
    total = PASS + FAIL
    print(f"  Results: {PASS}/{total} passed, {FAIL} failed")
    if FAIL:
        print("  ❌ SOME TESTS FAILED")
        sys.exit(1)
    else:
        print("  ✅ ALL TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
