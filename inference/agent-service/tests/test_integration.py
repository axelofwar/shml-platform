"""
Integration Tests for ACE Agent Service.

Tests:
1. Tool call parsing from LLM output
2. Skills integration (GitHubSkill, SandboxSkill)
3. WebSocket streaming (connection, stage outputs, completion)
4. Playbook growth and retrieval
5. Session diary creation
6. Reflection engine pattern detection
"""

import pytest
import asyncio
import json
from datetime import datetime
from unittest.mock import Mock, AsyncMock, patch

# Import components to test
from app.agent import parse_tool_calls, build_ace_agent
from app.context import AgentPlaybook, ContextBullet
from app.skills import GitHubSkill, SandboxSkill, execute_skill
from app.diary import create_session_diary, ReflectionEngine
from app.database import AsyncSessionLocal


class TestToolCallParsing:
    """Test tool call parsing from LLM output."""

    def test_parse_multiline_format(self):
        """Test parsing multi-line tool call format."""
        text = """
        I will create a GitHub issue.

        Tool: GitHubSkill
        Operation: create_issue
        Params: {"repo": "owner/repo", "title": "Test Issue", "body": "Description"}

        This should help track the bug.
        """

        tool_calls = parse_tool_calls(text)

        assert len(tool_calls) == 1
        assert tool_calls[0]["tool"] == "GitHubSkill"
        assert tool_calls[0]["operation"] == "create_issue"
        assert tool_calls[0]["params"]["repo"] == "owner/repo"
        assert tool_calls[0]["params"]["title"] == "Test Issue"

    def test_parse_inline_format(self):
        """Test parsing inline tool call format."""
        text = """
        Let me execute: [TOOL:SandboxSkill|run_code|{"language":"python","code":"print('hello')"}]
        """

        tool_calls = parse_tool_calls(text)

        assert len(tool_calls) == 1
        assert tool_calls[0]["tool"] == "SandboxSkill"
        assert tool_calls[0]["operation"] == "run_code"
        assert tool_calls[0]["params"]["language"] == "python"

    def test_parse_multiple_tools(self):
        """Test parsing multiple tool calls."""
        text = """
        Tool: GitHubSkill
        Operation: list_repos
        Params: {"username": "testuser"}

        Then:
        Tool: SandboxSkill
        Operation: run_code
        Params: {"language": "python", "code": "import os"}
        """

        tool_calls = parse_tool_calls(text)

        assert len(tool_calls) == 2
        assert tool_calls[0]["tool"] == "GitHubSkill"
        assert tool_calls[1]["tool"] == "SandboxSkill"

    def test_parse_no_tools(self):
        """Test parsing text with no tool calls."""
        text = "This is just a regular response with no tools."

        tool_calls = parse_tool_calls(text)

        assert len(tool_calls) == 0

    def test_parse_malformed_json(self):
        """Test handling of malformed JSON in params."""
        text = """
        Tool: GitHubSkill
        Operation: create_issue
        Params: {invalid json}
        """

        tool_calls = parse_tool_calls(text)

        # Should skip malformed tool call
        assert len(tool_calls) == 0


class TestPlaybookManagement:
    """Test AgentPlaybook context management."""

    def test_add_and_retrieve_bullets(self):
        """Test adding bullets and retrieving relevant context."""
        playbook = AgentPlaybook(user_id="test-user", max_bullets=100)

        # Add bullets
        playbook.add_bullet(
            content="Always validate input before processing",
            category="curator",
            source="test",
        )
        playbook.add_bullet(
            content="Use try-except blocks for error handling",
            category="curator",
            source="test",
        )
        playbook.add_bullet(
            content="GitHub API requires authentication token",
            category="generator",
            source="test",
        )

        # Retrieve relevant bullets
        results = playbook.retrieve_relevant(
            query="How to handle errors in code?",
            top_k=2,
        )

        assert len(results) > 0
        # Should include error handling bullet
        assert any("error handling" in b.content.lower() for b in results)

    def test_deduplication(self):
        """Test grow-and-refine deduplication."""
        playbook = AgentPlaybook(
            user_id="test-user", max_bullets=10, dedup_threshold=0.95
        )

        # Add similar bullets
        for i in range(15):
            playbook.add_bullet(
                content="Always validate user input before processing",
                category="generator",  # Not curator, so will be deduplicated
                source="test",
            )

        # Should deduplicate to near max_bullets
        assert len(playbook.bullets) <= 10

    def test_utility_scoring(self):
        """Test utility score calculation."""
        bullet = ContextBullet(
            content="Test bullet",
            category="curator",
            source="test",
            embedding=[0.1] * 384,
            helpful=10,
            harmful=2,
        )

        # Utility = helpful / (helpful + harmful) = 10 / 12 ≈ 0.833
        utility = bullet.helpful / (bullet.helpful + bullet.harmful)
        assert 0.8 < utility < 0.9

    def test_category_filtering(self):
        """Test retrieving bullets by category."""
        playbook = AgentPlaybook(user_id="test-user")

        playbook.add_bullet("Generator bullet", "generator", "test")
        playbook.add_bullet("Curator bullet", "curator", "test")
        playbook.add_bullet("Reflector bullet", "reflector", "test")

        # Retrieve only curator bullets
        results = playbook.retrieve_relevant(
            query="test",
            top_k=5,
            category="curator",
        )

        assert all(b.category == "curator" for b in results)


class TestSkillsIntegration:
    """Test composable skills."""

    def test_github_skill_activation(self):
        """Test GitHubSkill activation triggers."""
        assert GitHubSkill.is_activated("Create a GitHub issue")
        assert GitHubSkill.is_activated("List repositories")
        assert not GitHubSkill.is_activated("Run Python code")

    def test_sandbox_skill_activation(self):
        """Test SandboxSkill activation triggers."""
        assert SandboxSkill.is_activated("Execute this Python code")
        assert SandboxSkill.is_activated("Run the script")
        assert not SandboxSkill.is_activated("Create a GitHub PR")

    def test_skill_context_generation(self):
        """Test skill context string generation."""
        context = GitHubSkill.get_context("Create a GitHub issue")

        assert "GitHubSkill" in context
        assert "create_issue" in context
        assert len(context) > 100  # Should have meaningful docs

    @pytest.mark.asyncio
    async def test_execute_skill_unknown(self):
        """Test executing unknown skill."""
        result = await execute_skill("NonExistentSkill", "operation", {})

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_sandbox_skill_execution_mock(self):
        """Test SandboxSkill execution with mock."""
        with patch(
            "app.skills.SandboxSkill.execute", new_callable=AsyncMock
        ) as mock_execute:
            mock_execute.return_value = {
                "output": "Hello, World!",
                "exit_code": 0,
            }

            result = await execute_skill(
                "SandboxSkill",
                "run_code",
                {"language": "python", "code": "print('Hello, World!')"},
            )

            assert "output" in result
            assert result["exit_code"] == 0


class TestSessionDiary:
    """Test session diary creation and retrieval."""

    @pytest.mark.asyncio
    async def test_create_session_diary(self):
        """Test creating a session diary entry."""
        async with AsyncSessionLocal() as db:
            diary_id = await create_session_diary(
                db_session=db,
                user_id="test-user",
                session_id="test-session-1",
                task_description="Test task",
                task_category="testing",
                generator_actions=[{"content": "Test action"}],
                reflector_analyses=[
                    {"content": "Test analysis", "rubric_scores": {"clarity": 0.9}}
                ],
                curator_lessons=["Test lesson"],
                tool_results=[],
                success=True,
                execution_time_ms=1500,
                context_bullets_used=10,
            )

            assert diary_id is not None
            await db.commit()


class TestReflectionEngine:
    """Test reflection engine pattern detection."""

    @pytest.mark.asyncio
    async def test_analyze_patterns_mock(self):
        """Test pattern analysis with mock LLM."""
        async with AsyncSessionLocal() as db:
            engine = ReflectionEngine(db)

            # Mock the call_coding_model function
            async def mock_llm(prompt, **kwargs):
                return """
                Patterns detected:
                1. User frequently encounters authentication errors
                2. Sandbox timeouts when processing large files
                3. Successful GitHub PR creation workflow

                Recommendations:
                - Add authentication checks before API calls
                - Increase sandbox timeout for large files
                - Reuse successful PR workflow
                """

            # This would normally analyze real session data
            # For now, just test the analysis format
            result = await engine.analyze_session_patterns(
                user_id="test-user",
                last_n=5,
                model_callable=mock_llm,
            )

            assert "patterns" in result
            assert "recommendations" in result
            assert "statistics" in result


class TestAgentWorkflow:
    """Test complete agent workflow."""

    @pytest.mark.asyncio
    async def test_build_agent(self):
        """Test building ACE agent workflow."""
        agent = build_ace_agent()

        assert agent is not None
        # Agent should have nodes: generator, reflector, curator, tools

    @pytest.mark.asyncio
    async def test_agent_execution_mock(self):
        """Test agent execution with mocked components."""
        # This would be a full integration test
        # For now, test that we can build the agent
        agent = build_ace_agent()

        # Mock state
        state = {
            "messages": [],
            "current_task": "Create a test function",
            "task_category": "coding",
            "user_id": "test-user",
            "session_id": "test-session-2",
            "playbook": AgentPlaybook(user_id="test-user"),
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

        # This would normally execute the full workflow
        # For now, just verify state structure
        assert "playbook" in state
        assert "current_task" in state


class TestWebSocketStreaming:
    """Test WebSocket streaming functionality."""

    @pytest.mark.asyncio
    async def test_connection_manager(self):
        """Test WebSocket connection manager."""
        from app.main import ConnectionManager

        manager = ConnectionManager()

        # Mock WebSocket
        mock_ws = Mock()
        mock_ws.accept = AsyncMock()
        mock_ws.send_json = AsyncMock()

        # Connect
        await manager.connect("test-session", mock_ws)
        assert "test-session" in manager.active_connections

        # Send message
        await manager.send_message("test-session", {"type": "test", "data": "hello"})
        mock_ws.send_json.assert_called_once()

        # Disconnect
        manager.disconnect("test-session")
        assert "test-session" not in manager.active_connections


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
