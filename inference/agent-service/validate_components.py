#!/usr/bin/env python3
"""
Quick validation script for ACE Agent Service components.

Validates:
- All P1 module imports
- Hybrid router intent classification
- Model router selection
- Conversation history module structure
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))


def validate_components():
    """Run component validations (no DB required)."""
    print("🔍 Validating Agent Service components...")
    passed = 0
    failed = 0

    # 1. Import validation
    try:
        from app.hybrid_router import get_hybrid_router, HybridRouter, RoutingDecision
        from app.model_router import ModelRouter, ModelType, ModelSelection
        from app.conversation_history import (
            ConversationTurn,
            save_turn,
            save_turns_batch,
            load_history,
            load_history_for_context,
            ensure_schema,
            MAX_HISTORY_TURNS,
        )
        from app.agent import build_ace_agent, parse_tool_calls

        print("  ✅ All P1 module imports successful")
        passed += 1
    except ImportError as e:
        print(f"  ❌ Import error: {e}")
        failed += 1
        return False

    # 2. Hybrid router
    try:
        router = get_hybrid_router()
        assert isinstance(router, HybridRouter)

        selection = router.route(prompt="Test intent validation", attachments=None)
        assert isinstance(selection, ModelSelection)
        assert selection.model_name
        assert selection.gpu.startswith("cuda:")
        print(
            f"  ✅ Hybrid router: model={selection.model_type.value}, gpu={selection.gpu}"
        )
        passed += 1
    except Exception as e:
        print(f"  ❌ Hybrid router failed: {e}")
        failed += 1

    # 3. Intent classification
    try:
        cases = [
            ("Write a Python sort function", "coding"),
            # Vision keywords alone score 0.3 (below threshold), needs attachment
            ("What do you see in this photo?", "general"),
            ("Generate an image of a sunset over mountains", "image_gen"),
            ("Tell me about France", "general"),
            # Vision + image attachment → vision
            (
                "Describe what you see",
                "vision",
                [{"type": "image", "mime_type": "image/png"}],
            ),
        ]
        for item in cases:
            prompt, expected = item[0], item[1]
            attach = item[2] if len(item) > 2 else None
            got = router._classify_intent(prompt, attach)
            assert got == expected, f"'{prompt}' → {got}, expected {expected}"
        print(f"  ✅ Intent classification: {len(cases)}/{len(cases)} correct")
        passed += 1
    except (AssertionError, Exception) as e:
        print(f"  ❌ Intent classification: {e}")
        failed += 1

    # 4. Attachment override
    try:
        sel = router.route(
            "Write Python code",
            [{"type": "image", "mime_type": "image/png"}],
        )
        assert sel.model_type == ModelType.QWEN3_VL
        print("  ✅ Image attachment overrides code intent → vision model")
        passed += 1
    except Exception as e:
        print(f"  ❌ Attachment override: {e}")
        failed += 1

    # 5. ConversationTurn model
    try:
        assert hasattr(ConversationTurn, "session_id")
        assert hasattr(ConversationTurn, "user_id")
        assert hasattr(ConversationTurn, "role")
        assert hasattr(ConversationTurn, "content")
        assert hasattr(ConversationTurn, "created_at")
        assert ConversationTurn.__table_args__[2]["schema"] == "inference"
        print("  ✅ ConversationTurn model: all columns present, schema=inference")
        passed += 1
    except Exception as e:
        print(f"  ❌ ConversationTurn model: {e}")
        failed += 1

    # 6. RoutingDecision dataclass fields
    try:
        from dataclasses import fields as dc_fields

        field_names = {f.name for f in dc_fields(RoutingDecision)}
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
        assert required <= field_names
        print(f"  ✅ RoutingDecision: all {len(required)} required fields present")
        passed += 1
    except Exception as e:
        print(f"  ❌ RoutingDecision fields: {e}")
        failed += 1

    # Summary
    total = passed + failed
    print(f"\n  Results: {passed}/{total} passed, {failed} failed")
    if failed:
        print("  ❌ SOME VALIDATIONS FAILED")
    else:
        print("  ✅ ALL VALIDATIONS PASSED")
    return failed == 0


if __name__ == "__main__":
    success = validate_components()
    sys.exit(0 if success else 1)
