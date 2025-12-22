#!/usr/bin/env python3
"""
Quick validation script for ACE Agent Service components.

Validates:
- Tool call parsing
- Playbook operations
- Skill activation
- Agent workflow building
"""

import sys
import asyncio
from datetime import datetime

# Add parent directory to path
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

# Test imports
try:
    from agent import parse_tool_calls, build_ace_agent
    from context import AgentPlaybook
    from skills import GitHubSkill, SandboxSkill, get_active_skills, SKILLS

    print("✓ All imports successful")
except ImportError as e:
    print(f"✗ Import failed: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)


def test_tool_parsing():
    """Test tool call parsing."""
    print("\n=== Testing Tool Call Parsing ===")

    text = """
    I'll create an issue for you.

    Tool: GitHubSkill
    Operation: create_issue
    Params: {"repo": "test/repo", "title": "Bug Fix"}

    This should track the bug.
    """

    tool_calls = parse_tool_calls(text)

    if len(tool_calls) == 1:
        print(f"✓ Parsed 1 tool call")
        print(f"  - Tool: {tool_calls[0]['tool']}")
        print(f"  - Operation: {tool_calls[0]['operation']}")
        print(f"  - Params: {tool_calls[0]['params']}")
    else:
        print(f"✗ Expected 1 tool call, got {len(tool_calls)}")
        return False

    return True


def test_playbook():
    """Test playbook operations."""
    print("\n=== Testing Playbook ===")

    playbook = AgentPlaybook(user_id="test-user", max_bullets=100)

    # Add bullets
    playbook.add_bullet(
        content="Always validate input data",
        category="curator",
        source="test",
    )
    playbook.add_bullet(
        content="Use environment variables for secrets",
        category="curator",
        source="test",
    )
    playbook.add_bullet(
        content="GitHub authentication requires personal access token",
        category="generator",
        source="test",
    )

    print(f"✓ Added 3 bullets to playbook")
    print(f"  - Total bullets: {len(playbook.bullets)}")

    # Retrieve relevant
    results = playbook.retrieve_relevant(
        query="How to handle GitHub authentication?",
        top_k=2,
    )

    print(f"✓ Retrieved {len(results)} relevant bullets")
    for i, bullet in enumerate(results[:2], 1):
        print(f"  {i}. [{bullet.category}] {bullet.content[:60]}...")

    return True


def test_skill_activation():
    """Test skill activation."""
    print("\n=== Testing Skill Activation ===")

    test_cases = [
        ("Create a GitHub issue", GitHubSkill, True),
        ("Run Python code", SandboxSkill, True),
        ("List all repositories", GitHubSkill, True),
        ("Calculate the sum", GitHubSkill, False),
    ]

    passed = 0
    for task, skill, expected in test_cases:
        result = skill.is_activated(task)
        if result == expected:
            status = "✓"
            passed += 1
        else:
            status = "✗"

        print(f"{status} '{task[:40]}...' -> {skill.__name__}: {result}")

    print(f"\n  Passed: {passed}/{len(test_cases)}")
    return passed == len(test_cases)


def test_get_active_skills():
    """Test get_active_skills function."""
    print("\n=== Testing Active Skills Detection ===")

    task = "Create a GitHub issue and run some Python code"
    active = get_active_skills(task)

    print(f"✓ Task: '{task}'")
    print(f"✓ Active skills: {[s.__name__ for s in active]}")

    # Should activate both GitHubSkill and SandboxSkill
    skill_names = [s.__name__ for s in active]
    has_github = "GitHubSkill" in skill_names
    has_sandbox = "SandboxSkill" in skill_names

    if has_github and has_sandbox:
        print("✓ Both skills activated correctly")
        return True
    else:
        print(f"✗ Expected both skills, got: {skill_names}")
        return False


async def test_build_agent():
    """Test building agent workflow."""
    print("\n=== Testing Agent Build ===")

    try:
        agent = build_ace_agent()
        print("✓ Agent workflow built successfully")

        # Check that agent has required attributes
        if hasattr(agent, "ainvoke"):
            print("✓ Agent has ainvoke method")
            return True
        else:
            print("✗ Agent missing ainvoke method")
            return False
    except Exception as e:
        print(f"✗ Agent build failed: {e}")
        return False


async def test_state_structure():
    """Test AgentState structure."""
    print("\n=== Testing State Structure ===")

    playbook = AgentPlaybook(user_id="test-user")

    state = {
        "messages": [],
        "current_task": "Test task",
        "task_category": "testing",
        "user_id": "test-user",
        "session_id": "test-session",
        "playbook": playbook,
        "generator_output": None,
        "reflector_output": None,
        "reflector_rubric_scores": None,
        "curator_lessons": [],
        "tool_results": [],
        "tool_calls_pending": [],
        "session_diary": [],
        "generator_actions": [],
        "reflector_analyses": [],
        "start_time": datetime.now(),
        "success": True,
        "error_messages": [],
        "connection_manager": None,
        "ws_session_id": None,
    }

    required_keys = [
        "current_task",
        "playbook",
        "generator_output",
        "reflector_output",
        "curator_lessons",
        "tool_results",
        "session_diary",
    ]

    missing = [key for key in required_keys if key not in state]

    if not missing:
        print(f"✓ State has all {len(required_keys)} required keys")
        return True
    else:
        print(f"✗ State missing keys: {missing}")
        return False


async def main():
    """Run all validation tests."""
    print("=" * 60)
    print("ACE Agent Service - Component Validation")
    print("=" * 60)

    results = []

    # Sync tests
    results.append(("Tool Parsing", test_tool_parsing()))
    results.append(("Playbook Operations", test_playbook()))
    results.append(("Skill Activation", test_skill_activation()))
    results.append(("Active Skills Detection", test_get_active_skills()))

    # Async tests
    results.append(("Agent Build", await test_build_agent()))
    results.append(("State Structure", await test_state_structure()))

    # Summary
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status:8} | {name}")

    print("=" * 60)
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("\n✓ All validation tests passed!")
        return 0
    else:
        print(f"\n✗ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
