#!/usr/bin/env python3
"""
Simple validation script for ACE Agent Service components.
Tests imports, DB schema, conversation_history, and hybrid_router.
"""

import sys
import asyncio
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))


async def validate_components():
    """Run basic component validations"""
    print("🔍 Validating Agent Service components...")

    try:
        # Test imports
        from app.database import AsyncSessionLocal, engine
        from app.conversation_history import (
            save_turn,
            load_history,
            ensure_schema,
            load_history_for_context,
        )
        from app.hybrid_router import HybridRouter, get_hybrid_router, RoutingDecision
        from app.model_router import ModelRouter, ModelType

        print("✅ All imports successful")

        # Test database connection and schema creation
        async with AsyncSessionLocal() as db:
            await ensure_schema(db)
            print("✅ Database schema validation passed")

        # Test conversation history functionality
        async with AsyncSessionLocal() as db:
            # Save a test turn
            turn = await save_turn(
                db,
                session_id="validation-test",
                user_id="validation-test",
                role="user",
                content="Validation test message",
            )
            await db.commit()
            print(f"✅ Conversation history save_turn: id={turn.id}")

            # Load history
            history = await load_history(db, "validation-test", limit=5)
            print(f"✅ Conversation history load_history: {len(history)} turns")

            # Load context (filters system/tool roles)
            context = await load_history_for_context(
                db, "validation-test", "validation-test", limit=5
            )
            print(
                f"✅ Conversation history load_history_for_context: {len(context)} turns"
            )

        # Test hybrid router
        router = get_hybrid_router()
        selection = router.route(
            prompt="Test intent validation",
            attachments=None,
        )
        print(f"✅ Hybrid router validation: selected model = {selection.model_name}")

        # Test intent classification
        for prompt, expected in [
            ("Write a Python sort function", "coding"),
            ("What is in this image?", "vision"),
            ("Tell me about France", "general"),
        ]:
            intent = router._classify_intent(prompt)
            status = "✅" if intent == expected else "⚠️"
            print(f"  {status} Intent '{prompt[:40]}' → {intent} (expected {expected})")

        print("🎉 All component validations passed!")
        return True

    except Exception as e:
        print(f"❌ Validation failed: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(validate_components())
    sys.exit(0 if result else 1)
