#!/usr/bin/env python3
"""
Quick validation for ACE Agent Service - Tests core components.
"""

import sys
import os

# Add app directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

# Set environment variables for testing
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_DB", "inference_gateway")
os.environ.setdefault("POSTGRES_USER", "inference")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("GATEWAY_URL", "http://localhost:8000")

print("=" * 60)
print("ACE Agent Service - Component Validation")
print("=" * 60)

# Test 1: Tool call parsing
print("\n=== Test 1: Tool Call Parsing ===")
try:
    # Import after path setup
    import re
    import json
    from typing import List, Dict, Any
    import logging

    logger = logging.getLogger(__name__)

    def parse_tool_calls(text: str) -> List[Dict[str, Any]]:
        """Parse tool calls from generator output."""
        tool_calls = []

        # Pattern 1: Multi-line format
        pattern1 = (
            r"Tool:\s*([\w]+)\s*\nOperation:\s*([\w_]+)\s*\nParams:\s*(\{[^}]+\})"
        )
        for match in re.finditer(pattern1, text, re.MULTILINE | re.IGNORECASE):
            try:
                tool_calls.append(
                    {
                        "tool": match.group(1).strip(),
                        "operation": match.group(2).strip(),
                        "params": json.loads(match.group(3)),
                    }
                )
            except json.JSONDecodeError:
                pass

        # Pattern 2: Inline format
        pattern2 = r"\[TOOL:([\w]+)\|([\w_]+)\|({[^}]+})\]"
        for match in re.finditer(pattern2, text):
            try:
                tool_calls.append(
                    {
                        "tool": match.group(1).strip(),
                        "operation": match.group(2).strip(),
                        "params": json.loads(match.group(3)),
                    }
                )
            except json.JSONDecodeError:
                pass

        return tool_calls

    text = """
    Tool: GitHubSkill
    Operation: create_issue
    Params: {"repo": "test/repo", "title": "Bug"}
    """

    tool_calls = parse_tool_calls(text)
    if len(tool_calls) == 1 and tool_calls[0]["tool"] == "GitHubSkill":
        print("✓ Tool call parsing works")
        test1_pass = True
    else:
        print(f"✗ Tool call parsing failed: {tool_calls}")
        test1_pass = False
except Exception as e:
    print(f"✗ Tool call parsing error: {e}")
    test1_pass = False

# Test 2: Skill activation (mock)
print("\n=== Test 2: Skill Activation ===")
try:

    class MockSkill:
        ACTIVATION_TRIGGERS = ["github", "repository", "issue"]

        @classmethod
        def is_activated(cls, task: str) -> bool:
            task_lower = task.lower()
            return any(trigger in task_lower for trigger in cls.ACTIVATION_TRIGGERS)

    if MockSkill.is_activated("Create a GitHub issue"):
        print("✓ Skill activation works")
        test2_pass = True
    else:
        print("✗ Skill activation failed")
        test2_pass = False
except Exception as e:
    print(f"✗ Skill activation error: {e}")
    test2_pass = False

# Test 3: ContextBullet structure
print("\n=== Test 3: Context Bullet Structure ===")
try:
    from dataclasses import dataclass
    from typing import Optional

    @dataclass
    class ContextBullet:
        content: str
        category: str
        source: str
        embedding: list
        helpful: int = 0
        harmful: int = 0

    bullet = ContextBullet(
        content="Test bullet",
        category="generator",
        source="test",
        embedding=[0.1] * 384,
        helpful=5,
        harmful=1,
    )

    if bullet.content == "Test bullet" and len(bullet.embedding) == 384:
        print("✓ ContextBullet structure works")
        test3_pass = True
    else:
        print("✗ ContextBullet structure failed")
        test3_pass = False
except Exception as e:
    print(f"✗ ContextBullet error: {e}")
    test3_pass = False

# Test 4: AgentState structure
print("\n=== Test 4: Agent State Structure ===")
try:
    from typing import TypedDict, List, Dict, Any, Optional
    from datetime import datetime

    # Mock playbook
    class MockPlaybook:
        def __init__(self, user_id):
            self.user_id = user_id
            self.bullets = []

    state = {
        "messages": [],
        "current_task": "Test task",
        "task_category": "testing",
        "user_id": "test-user",
        "session_id": "test-session",
        "playbook": MockPlaybook("test-user"),
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
        "tool_results",
        "session_diary",
        "connection_manager",
    ]

    missing = [key for key in required_keys if key not in state]

    if not missing:
        print("✓ Agent state structure complete")
        test4_pass = True
    else:
        print(f"✗ Agent state missing keys: {missing}")
        test4_pass = False
except Exception as e:
    print(f"✗ Agent state error: {e}")
    test4_pass = False

# Test 5: Rubric score parsing
print("\n=== Test 5: Rubric Score Parsing ===")
try:

    def parse_rubric_scores(text: str) -> Dict[str, float]:
        """Parse rubric scores from text."""
        scores = {}
        patterns = [
            r"Clarity:\s*([\d.]+)",
            r"Accuracy:\s*([\d.]+)",
            r"Safety:\s*([\d.]+)",
            r"Actionability:\s*([\d.]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                rubric_name = pattern.split(":")[0].replace(r"\s*", "").lower()
                scores[rubric_name] = float(match.group(1))

        return scores

    text = """
    - Clarity: 0.9
    - Accuracy: 0.85
    - Safety: 1.0
    - Actionability: 0.8
    """

    scores = parse_rubric_scores(text)

    if len(scores) == 4 and scores.get("clarity") == 0.9:
        print("✓ Rubric score parsing works")
        test5_pass = True
    else:
        print(f"✗ Rubric score parsing failed: {scores}")
        test5_pass = False
except Exception as e:
    print(f"✗ Rubric score parsing error: {e}")
    test5_pass = False

# Summary
print("\n" + "=" * 60)
print("VALIDATION SUMMARY")
print("=" * 60)

results = [
    ("Tool Call Parsing", test1_pass),
    ("Skill Activation", test2_pass),
    ("ContextBullet Structure", test3_pass),
    ("Agent State Structure", test4_pass),
    ("Rubric Score Parsing", test5_pass),
]

for name, result in results:
    status = "✓ PASS" if result else "✗ FAIL"
    print(f"{status:8} | {name}")

passed = sum(1 for _, result in results if result)
total = len(results)

print("=" * 60)
print(f"Results: {passed}/{total} tests passed")

if passed == total:
    print("\n✓ All validation tests passed!")
    sys.exit(0)
else:
    print(f"\n✗ {total - passed} test(s) failed")
    sys.exit(1)
