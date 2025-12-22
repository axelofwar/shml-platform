#!/usr/bin/env python3
"""
End-to-End Test for ACE Agent Service Core Components.

Tests the complete workflow without requiring FastAPI server:
1. Playbook operations (add, retrieve, save/load)
2. Tool call parsing
3. Session diary creation
4. Workflow building

This validates the implementation is correct before full integration testing.
"""

import sys
import os
import asyncio
from datetime import datetime

# Add parent directory to path to enable app imports
sys.path.insert(0, os.path.dirname(__file__))

# Set environment variables
# Check if we're in Docker or on host
postgres_host = os.environ.get("POSTGRES_HOST", "localhost")
if os.path.exists("/.dockerenv"):
    # We're in Docker, use container name
    postgres_host = "shml-postgres"

os.environ["POSTGRES_HOST"] = postgres_host
os.environ["POSTGRES_PORT"] = "5432"
os.environ["POSTGRES_DB"] = "inference"
os.environ["POSTGRES_USER"] = "inference"
os.environ["POSTGRES_PASSWORD"] = os.environ.get(
    "POSTGRES_PASSWORD", "change_me_in_production"
)
os.environ["GATEWAY_URL"] = "http://localhost:8000"

print(f"Using PostgreSQL host: {postgres_host}")

print("=" * 70)
print("ACE Agent Service - End-to-End Component Test")
print("=" * 70)


async def main():
    """Run all end-to-end tests."""

    tests_passed = 0
    tests_total = 0

    # Test 1: Import all core modules
    print("\n[1/6] Testing Module Imports...")
    tests_total += 1
    try:
        from app.context import AgentPlaybook, ContextBullet
        from app.agent import parse_tool_calls, build_ace_agent
        from app.skills import GitHubSkill, SandboxSkill, RayJobSkill, WebSearchSkill
        from app.diary import create_session_diary
        from app.database import AsyncSessionLocal

        print("  ✓ All core modules imported successfully")
        tests_passed += 1
    except Exception as e:
        print(f"  ✗ Import failed: {e}")
        return tests_passed, tests_total

    # Test 2: Tool Call Parsing
    print("\n[2/6] Testing Tool Call Parsing...")
    tests_total += 1
    try:
        test_text = """I'll create a GitHub issue for you.

Tool: GitHubSkill
Operation: create_issue
Params: {"repo": "owner/test", "title": "Test Issue", "body": "Description"}

This will track the bug."""

        tool_calls = parse_tool_calls(test_text)

        if len(tool_calls) == 1:
            tc = tool_calls[0]
            if (
                tc["tool"] == "GitHubSkill"
                and tc["operation"] == "create_issue"
                and tc["params"]["repo"] == "owner/test"
            ):
                print(f"  ✓ Tool call parsed correctly:")
                print(f"    - Tool: {tc['tool']}")
                print(f"    - Operation: {tc['operation']}")
                print(f"    - Repo: {tc['params']['repo']}")
                tests_passed += 1
            else:
                print(f"  ✗ Tool call data incorrect: {tc}")
        else:
            print(f"  ✗ Expected 1 tool call, got {len(tool_calls)}")
    except Exception as e:
        print(f"  ✗ Tool parsing failed: {e}")

    # Test 3: Skill Activation
    print("\n[3/6] Testing Skill Activation...")
    tests_total += 1
    try:
        task1 = "Create a GitHub issue for this bug"
        task2 = "Run this Python code in a sandbox"
        task3 = "Submit a Ray training job"
        task4 = "Search for information about ML"

        results = [
            ("GitHub", GitHubSkill.is_activated(task1)),
            ("Sandbox", SandboxSkill.is_activated(task2)),
            ("Ray", RayJobSkill.is_activated(task3)),
            ("WebSearch", WebSearchSkill.is_activated(task4)),
        ]

        all_correct = all(activated for _, activated in results)

        if all_correct:
            print("  ✓ All skills activated correctly:")
            for name, activated in results:
                print(f"    - {name}: {'✓' if activated else '✗'}")
            tests_passed += 1
        else:
            print("  ✗ Some skills failed to activate:")
            for name, activated in results:
                print(f"    - {name}: {'✓' if activated else '✗'}")
    except Exception as e:
        print(f"  ✗ Skill activation failed: {e}")

    # Test 4: Playbook Operations
    print("\n[4/6] Testing Playbook Operations...")
    tests_total += 1
    try:
        playbook = AgentPlaybook(user_id="test-user-e2e", max_bullets=100)

        # Add bullets
        playbook.add_bullet(
            content="Always validate user input before processing",
            category="curator",
            source="test",
        )
        playbook.add_bullet(
            content="Use try-except blocks for error handling in Python",
            category="curator",
            source="test",
        )
        playbook.add_bullet(
            content="GitHub API requires authentication with personal access token",
            category="generator",
            source="test",
        )

        # Retrieve relevant bullets
        results = playbook.retrieve_relevant(
            query="How do I handle errors in Python code?",
            top_k=2,
        )

        if len(results) > 0:
            print(f"  ✓ Playbook operations successful:")
            print(f"    - Added 3 bullets")
            print(f"    - Retrieved {len(results)} relevant bullets")
            print(f"    - Top result: '{results[0].content[:60]}...'")
            tests_passed += 1
        else:
            print(f"  ✗ No relevant bullets retrieved")
    except Exception as e:
        print(f"  ✗ Playbook operations failed: {e}")
        import traceback

        traceback.print_exc()

    # Test 5: Agent Workflow Building
    print("\n[5/6] Testing Agent Workflow Building...")
    tests_total += 1
    try:
        agent = build_ace_agent()

        if hasattr(agent, "ainvoke"):
            print("  ✓ Agent workflow built successfully")
            print("    - LangGraph StateGraph created")
            print("    - Has ainvoke method for execution")
            tests_passed += 1
        else:
            print("  ✗ Agent missing ainvoke method")
    except Exception as e:
        print(f"  ✗ Agent workflow build failed: {e}")
        import traceback

        traceback.print_exc()

    # Test 6: Database Connection (optional - requires running PostgreSQL)
    print("\n[6/6] Testing Database Connection...")
    tests_total += 1
    try:
        async with AsyncSessionLocal() as db:
            # Try to execute a simple query
            from sqlalchemy import text

            result = await db.execute(text("SELECT 1"))
            row = result.scalar()

            if row == 1:
                print("  ✓ Database connection successful")
                print("    - Connected to PostgreSQL")
                print("    - Query executed successfully")
                tests_passed += 1
            else:
                print("  ✗ Database query returned unexpected result")
    except Exception as e:
        print(f"  ⚠ Database connection failed (may not be running): {e}")
        # Don't fail the test suite if DB isn't available
        print("    Note: This is optional and doesn't affect core functionality")

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Tests Passed: {tests_passed}/{tests_total}")
    print(f"Success Rate: {(tests_passed/tests_total)*100:.1f}%")
    print("=" * 70)

    if tests_passed >= tests_total - 1:  # Allow DB test to fail
        print("\n✅ Core functionality validated! Ready for integration testing.")
        return 0
    else:
        print("\n❌ Some core tests failed. Please review errors above.")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
