"""
Claude Diary Pattern - Session capture and reflection engine.

Implements continual learning through:
- Session diary: Capture all agent actions, reflections, outcomes
- Reflection engine: Analyze patterns across sessions
- Playbook updates: Extract lessons learned and improve over time
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from .database import Base

logger = logging.getLogger(__name__)


class SessionDiary(Base):
    """Claude Diary pattern for continual learning.

    Captures complete session context:
    - Task description and user intent
    - Generator actions (what the agent proposed)
    - Reflector analyses (self-critique and rubric scores)
    - Curator lessons (knowledge extracted)
    - Tool results (execution outcomes)
    - User feedback (corrections, preferences)
    """

    __tablename__ = "session_diaries"

    id = Column(String, primary_key=True)
    user_id = Column(String, index=True, nullable=False)
    session_id = Column(String, index=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.now, index=True)

    # Task context
    task_description = Column(Text, nullable=False)
    task_category = Column(String, index=True)  # coding, debugging, analysis, etc.

    # Generator stage
    generator_actions = Column(JSONB)  # List[Dict] of actions proposed
    generator_token_count = Column(Integer, default=0)

    # Reflector stage
    reflector_analyses = Column(JSONB)  # List[Dict] of critiques
    reflector_rubric_scores = Column(JSONB)  # Dict of average rubric scores

    # Curator stage
    curator_lessons = Column(JSONB)  # List[str] of lessons learned

    # Tool execution
    tool_results = Column(JSONB)  # List[Dict] of tool calls and results
    tool_count = Column(Integer, default=0)

    # Outcomes
    success = Column(Boolean, default=False)
    error_messages = Column(JSONB, nullable=True)
    execution_time_ms = Column(Integer)  # Total execution time

    # User feedback
    user_feedback = Column(Text, nullable=True)
    user_rating = Column(Integer, nullable=True)  # 1-5 scale

    # Metadata
    model_used = Column(String)  # Which LLM was used
    context_bullets_used = Column(Integer, default=0)  # How many bullets retrieved


class ReflectionEngine:
    """Cross-session pattern analysis for continual improvement.

    Analyzes session diaries to:
    - Detect repeated mistakes
    - Identify successful strategies
    - Track tool usage patterns
    - Generate improvement recommendations
    """

    def __init__(self, db_session):
        self.db = db_session

    async def analyze_session_patterns(
        self,
        user_id: str,
        last_n: int = 10,
        model_callable=None,
    ) -> Dict[str, Any]:
        """Analyze last N sessions for patterns.

        Args:
            user_id: User to analyze sessions for
            last_n: Number of recent sessions to analyze
            model_callable: Function to call LLM for analysis

        Returns:
            Dict with patterns, recommendations, and statistics
        """
        # Query recent sessions
        from sqlalchemy import select

        stmt = (
            select(SessionDiary)
            .where(SessionDiary.user_id == user_id)
            .order_by(SessionDiary.timestamp.desc())
            .limit(last_n)
        )
        result = await self.db.execute(stmt)
        sessions = result.scalars().all()

        if not sessions:
            logger.info(f"No sessions found for user {user_id}")
            return {
                "user_id": user_id,
                "sessions_analyzed": 0,
                "patterns": [],
                "recommendations": [],
            }

        # Calculate statistics
        stats = self._calculate_statistics(sessions)

        # Format sessions for LLM analysis
        sessions_text = self._format_sessions(sessions)

        # Generate analysis using LLM (if provided)
        analysis = None
        if model_callable:
            prompt = f"""Analyze these {len(sessions)} agent sessions for user {user_id}:

{sessions_text}

Statistics:
- Success rate: {stats['success_rate']:.1%}
- Avg execution time: {stats['avg_execution_time_ms']:.0f}ms
- Avg tools used: {stats['avg_tool_count']:.1f}
- Avg user rating: {stats['avg_user_rating']:.1f}/5

Identify patterns and provide recommendations:

1. **Repeated Mistakes**: What errors or failures occur frequently?
2. **Successful Strategies**: What approaches lead to success?
3. **Tool Usage Patterns**: Are tools used effectively?
4. **Areas for Improvement**: What should change?

Provide 3-5 concrete, actionable recommendations."""

            try:
                analysis = await model_callable(prompt)
                logger.info(f"Generated reflection analysis for user {user_id}")
            except Exception as e:
                logger.error(f"Failed to generate analysis: {e}")

        return {
            "user_id": user_id,
            "sessions_analyzed": len(sessions),
            "statistics": stats,
            "patterns": self._extract_patterns(sessions),
            "recommendations": (
                self._parse_recommendations(analysis) if analysis else []
            ),
            "raw_analysis": analysis,
        }

    def _calculate_statistics(self, sessions: List[SessionDiary]) -> Dict[str, Any]:
        """Calculate aggregate statistics across sessions."""
        total = len(sessions)
        successful = sum(1 for s in sessions if s.success)

        return {
            "total_sessions": total,
            "success_rate": successful / total if total > 0 else 0.0,
            "avg_execution_time_ms": sum(s.execution_time_ms or 0 for s in sessions)
            / total,
            "avg_tool_count": sum(s.tool_count for s in sessions) / total,
            "avg_user_rating": (
                sum(s.user_rating or 0 for s in sessions if s.user_rating)
                / sum(1 for s in sessions if s.user_rating)
                if any(s.user_rating for s in sessions)
                else 0.0
            ),
            "category_distribution": self._count_categories(sessions),
        }

    def _count_categories(self, sessions: List[SessionDiary]) -> Dict[str, int]:
        """Count sessions by task category."""
        counts = {}
        for session in sessions:
            cat = session.task_category or "unknown"
            counts[cat] = counts.get(cat, 0) + 1
        return counts

    def _format_sessions(self, sessions: List[SessionDiary]) -> str:
        """Format sessions as text for LLM analysis."""
        lines = []
        for i, session in enumerate(sessions, 1):
            lines.append(
                f"\n## Session {i} ({session.timestamp.strftime('%Y-%m-%d %H:%M')})"
            )
            lines.append(f"**Task**: {session.task_description[:200]}...")
            lines.append(f"**Category**: {session.task_category}")
            lines.append(f"**Success**: {session.success}")

            if session.generator_actions:
                lines.append(f"**Actions**: {len(session.generator_actions)} generated")

            if session.reflector_rubric_scores:
                rubric_str = ", ".join(
                    [f"{k}={v:.2f}" for k, v in session.reflector_rubric_scores.items()]
                )
                lines.append(f"**Rubric Scores**: {rubric_str}")

            if session.curator_lessons:
                lines.append(f"**Lessons**: {len(session.curator_lessons)} extracted")
                for lesson in session.curator_lessons[:2]:  # Show first 2
                    lines.append(f"  - {lesson[:100]}...")

            if session.error_messages:
                lines.append(f"**Errors**: {len(session.error_messages)}")
                for error in session.error_messages[:2]:
                    lines.append(f"  - {str(error)[:100]}...")

            if session.user_feedback:
                lines.append(f"**User Feedback**: {session.user_feedback[:100]}...")

        return "\n".join(lines)

    def _extract_patterns(self, sessions: List[SessionDiary]) -> List[Dict[str, Any]]:
        """Extract patterns from sessions (rule-based)."""
        patterns = []

        # Pattern: Repeated errors
        error_types = {}
        for session in sessions:
            if session.error_messages:
                for error in session.error_messages:
                    error_type = str(error).split(":")[0]  # Get error type
                    error_types[error_type] = error_types.get(error_type, 0) + 1

        for error_type, count in error_types.items():
            if count >= 3:  # Repeated 3+ times
                patterns.append(
                    {
                        "type": "repeated_error",
                        "description": f"Error '{error_type}' occurred {count} times",
                        "severity": "high" if count >= 5 else "medium",
                    }
                )

        # Pattern: Low rubric scores
        low_rubric_categories = {}
        for session in sessions:
            if session.reflector_rubric_scores:
                for rubric, score in session.reflector_rubric_scores.items():
                    if score < 0.6:  # Below threshold
                        low_rubric_categories[rubric] = (
                            low_rubric_categories.get(rubric, 0) + 1
                        )

        for rubric, count in low_rubric_categories.items():
            if count >= 3:
                patterns.append(
                    {
                        "type": "low_quality",
                        "description": f"Rubric '{rubric}' scored low in {count} sessions",
                        "severity": "medium",
                    }
                )

        # Pattern: Tool misuse
        tool_errors = 0
        for session in sessions:
            if session.tool_results:
                for result in session.tool_results:
                    if isinstance(result, dict) and result.get("error"):
                        tool_errors += 1

        if tool_errors >= 3:
            patterns.append(
                {
                    "type": "tool_misuse",
                    "description": f"{tool_errors} tool execution errors across sessions",
                    "severity": "high",
                }
            )

        return patterns

    def _parse_recommendations(self, analysis: str) -> List[str]:
        """Parse recommendations from LLM analysis text."""
        if not analysis:
            return []

        recommendations = []
        lines = analysis.split("\n")

        for line in lines:
            # Look for numbered lists or bullet points
            stripped = line.strip()
            if stripped and (
                stripped[0].isdigit()
                or stripped.startswith("-")
                or stripped.startswith("*")
            ):
                # Remove numbering/bullets
                rec = stripped.lstrip("0123456789.-* ")
                if len(rec) > 20:  # Meaningful recommendation
                    recommendations.append(rec)

        return recommendations[:10]  # Limit to top 10

    async def update_playbook_from_reflection(
        self,
        analysis: Dict[str, Any],
        playbook,
    ):
        """Update playbook with lessons from reflection analysis.

        Args:
            analysis: Output from analyze_session_patterns()
            playbook: AgentPlaybook instance to update
        """
        recommendations = analysis.get("recommendations", [])
        patterns = analysis.get("patterns", [])

        # Add high-severity patterns as curator bullets
        for pattern in patterns:
            if pattern.get("severity") == "high":
                playbook.add_bullet(
                    content=f"Pattern detected: {pattern['description']}",
                    category="curator",
                    source="reflection_engine",
                    rubric_scores={"importance": 0.95, "accuracy": 1.0},
                )

        # Add recommendations as curator bullets
        for rec in recommendations:
            playbook.add_bullet(
                content=f"Recommendation: {rec}",
                category="curator",
                source="reflection_engine",
                rubric_scores={"importance": 0.90, "actionable": 1.0},
            )

        logger.info(
            f"Updated playbook with {len(patterns)} patterns and {len(recommendations)} recommendations"
        )


async def create_session_diary(
    db_session,
    user_id: str,
    session_id: str,
    task_description: str,
    task_category: str,
    generator_actions: List[Dict],
    reflector_analyses: List[Dict],
    curator_lessons: List[str],
    tool_results: List[Dict],
    success: bool,
    execution_time_ms: int,
    error_messages: Optional[List[str]] = None,
    user_feedback: Optional[str] = None,
    user_rating: Optional[int] = None,
    model_used: str = "qwen2.5-coder-32b",
    context_bullets_used: int = 0,
) -> SessionDiary:
    """Create and persist a session diary entry.

    Args:
        db_session: Database session
        user_id: User identifier
        session_id: Session identifier
        task_description: The user's task/request
        task_category: Category of task (coding, debugging, analysis, etc.)
        generator_actions: List of actions proposed by generator
        reflector_analyses: List of critiques from reflector
        curator_lessons: Lessons learned by curator
        tool_results: Results from tool executions
        success: Whether the task succeeded
        execution_time_ms: Total execution time
        error_messages: Optional error messages
        user_feedback: Optional user feedback text
        user_rating: Optional user rating (1-5)
        model_used: Which LLM was used
        context_bullets_used: Number of context bullets retrieved

    Returns:
        The created SessionDiary instance
    """
    # Calculate rubric scores from reflector analyses
    rubric_scores = {}
    if reflector_analyses:
        all_rubrics = {}
        for analysis in reflector_analyses:
            if isinstance(analysis, dict) and "rubric_scores" in analysis:
                for rubric, score in analysis["rubric_scores"].items():
                    if rubric not in all_rubrics:
                        all_rubrics[rubric] = []
                    all_rubrics[rubric].append(score)

        rubric_scores = {
            rubric: sum(scores) / len(scores) for rubric, scores in all_rubrics.items()
        }

    # Create diary entry
    diary = SessionDiary(
        id=f"{user_id}_{session_id}",
        user_id=user_id,
        session_id=session_id,
        timestamp=datetime.now(),
        task_description=task_description,
        task_category=task_category,
        generator_actions=generator_actions,
        generator_token_count=sum(len(a.get("content", "")) for a in generator_actions),
        reflector_analyses=reflector_analyses,
        reflector_rubric_scores=rubric_scores,
        curator_lessons=curator_lessons,
        tool_results=tool_results,
        tool_count=len(tool_results),
        success=success,
        error_messages=error_messages,
        execution_time_ms=execution_time_ms,
        user_feedback=user_feedback,
        user_rating=user_rating,
        model_used=model_used,
        context_bullets_used=context_bullets_used,
    )

    db_session.add(diary)
    await db_session.commit()

    logger.info(
        f"Created session diary {diary.id} (success={success}, tools={len(tool_results)})"
    )

    return diary
