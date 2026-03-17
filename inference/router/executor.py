"""
Parallel Executor - Option C Full Parallel with Smart Merge

Executes multiple subtasks in parallel and intelligently merges results.
Implements speculative execution with research-wins fallback.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json

from .router import ModelRouter, RoutingStrategy
from .base import CompletionRequest, CompletionResponse, Message, ModelCapability

logger = logging.getLogger(__name__)


class SubtaskStatus(Enum):
    """Status of a subtask"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SUPERSEDED = "superseded"  # Another task's result made this obsolete


class MergeStrategy(Enum):
    """How to merge parallel results"""

    RESEARCH_WINS = "research_wins"  # Research results override speculative work
    KEEP_BOTH = "keep_both"  # Let user choose
    SMART_MERGE = "smart_merge"  # Adapt code to match research findings
    FIRST_WINS = "first_wins"  # First to complete wins


@dataclass
class Subtask:
    """A subtask to be executed"""

    id: str
    type: str  # "research", "code", "test", "system"
    prompt: str
    dependencies: List[str] = field(default_factory=list)  # Subtask IDs this depends on
    priority: int = 1  # Higher = more important
    speculative: bool = False  # If true, may be discarded
    model: Optional[str] = None  # Override model selection

    # Runtime state
    status: SubtaskStatus = SubtaskStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    @property
    def duration_ms(self) -> Optional[int]:
        if self.start_time and self.end_time:
            return int((self.end_time - self.start_time).total_seconds() * 1000)
        return None


@dataclass
class ExecutionPlan:
    """Plan for parallel execution"""

    task_description: str
    subtasks: List[Subtask]
    merge_strategy: MergeStrategy = MergeStrategy.SMART_MERGE
    max_concurrent: int = 3
    timeout_seconds: int = 120

    def get_ready_subtasks(self) -> List[Subtask]:
        """Get subtasks that are ready to execute (dependencies met)"""
        completed_ids = {
            st.id for st in self.subtasks if st.status == SubtaskStatus.COMPLETED
        }

        return [
            st
            for st in self.subtasks
            if st.status == SubtaskStatus.PENDING
            and all(dep in completed_ids for dep in st.dependencies)
        ]


@dataclass
class MergeResult:
    """Result of merging parallel executions"""

    final_output: str
    used_results: List[str]  # Subtask IDs whose results were used
    discarded_results: List[str]  # Subtask IDs whose results were discarded
    merge_notes: str
    total_cost: float
    total_latency_ms: int


class ParallelExecutor:
    """
    Execute subtasks in parallel with intelligent merging.

    Example workflow:
        Task: "Research SOTA segmentation and implement demo"

        Parallel execution:
        ├─ Research Agent → Found: SAM2, SegGPT, OneFormer
        ├─ Code Agent → Started implementing SAM (guessed)
        └─ Test Agent → Set up eval framework

        Smart merge:
        - Research completed, found SegGPT is best
        - Code agent's SAM work is useful foundation
        - Merge: Adapt SAM code structure for SegGPT
    """

    def __init__(
        self,
        router: ModelRouter,
        merge_strategy: MergeStrategy = MergeStrategy.SMART_MERGE,
    ):
        self.router = router
        self.default_merge_strategy = merge_strategy
        self._running_tasks: Dict[str, asyncio.Task] = {}

    async def create_plan(
        self, task: str, context: Optional[str] = None
    ) -> ExecutionPlan:
        """
        Use reasoning model to create an execution plan.

        Returns an ExecutionPlan with subtasks that can be executed in parallel.
        """
        planning_prompt = f"""Analyze this task and create a parallel execution plan.

Task: {task}

{f"Context: {context}" if context else ""}

Create a JSON execution plan:
{{
    "task_type": "research_and_code|code_only|research_only|system",
    "subtasks": [
        {{
            "id": "unique_id",
            "type": "research|code|test|system",
            "prompt": "Specific instructions for this subtask",
            "dependencies": ["ids of subtasks this depends on"],
            "priority": 1-5,
            "speculative": true/false  // true if this might be discarded
        }}
    ],
    "parallel_groups": [
        ["task1", "task2"],  // These can run in parallel
        ["task3"]  // This depends on above
    ],
    "merge_strategy": "smart_merge|research_wins|keep_both"
}}

Guidelines:
- Research tasks should have high priority and no dependencies
- Code tasks can be speculative (started before research completes)
- Test tasks depend on code tasks
- System tasks (GPU check, etc.) can run in parallel with anything

Output only valid JSON."""

        response = await self.router.complete(
            CompletionRequest(
                messages=[Message(role="user", content=planning_prompt)],
                temperature=0.1,
                max_tokens=1000,
                required_capabilities=[ModelCapability.REASONING],
            ),
            strategy=RoutingStrategy.CLOUD_FIRST,
        )

        try:
            plan_data = json.loads(response.content)
        except json.JSONDecodeError:
            # Fallback: single task
            plan_data = {
                "subtasks": [{"id": "main", "type": "code", "prompt": task}],
                "merge_strategy": "first_wins",
            }

        # Convert to ExecutionPlan
        subtasks = []
        for st_data in plan_data.get("subtasks", []):
            subtasks.append(
                Subtask(
                    id=st_data.get("id", f"task_{len(subtasks)}"),
                    type=st_data.get("type", "code"),
                    prompt=st_data.get("prompt", task),
                    dependencies=st_data.get("dependencies", []),
                    priority=st_data.get("priority", 1),
                    speculative=st_data.get("speculative", False),
                )
            )

        if not subtasks:
            subtasks = [Subtask(id="main", type="code", prompt=task)]

        merge_strategy_str = plan_data.get("merge_strategy", "smart_merge")
        try:
            merge_strategy = MergeStrategy(merge_strategy_str)
        except ValueError:
            merge_strategy = self.default_merge_strategy

        return ExecutionPlan(
            task_description=task,
            subtasks=subtasks,
            merge_strategy=merge_strategy,
        )

    async def execute_subtask(
        self,
        subtask: Subtask,
        context: Optional[str] = None,
        completed_results: Optional[Dict[str, str]] = None,
    ) -> str:
        """Execute a single subtask"""
        subtask.status = SubtaskStatus.RUNNING
        subtask.start_time = datetime.now()

        # Build prompt with context from completed dependencies
        dep_context = ""
        if completed_results and subtask.dependencies:
            dep_results = [
                completed_results.get(dep, "")
                for dep in subtask.dependencies
                if dep in completed_results
            ]
            if dep_results:
                dep_context = f"\n\nResults from previous tasks:\n" + "\n---\n".join(
                    dep_results
                )

        full_prompt = f"{subtask.prompt}{dep_context}"
        if context:
            full_prompt = f"Context: {context}\n\n{full_prompt}"

        # Select model based on subtask type
        if subtask.type == "research":
            # Use cloud model for research
            strategy = RoutingStrategy.CLOUD_FIRST
            capabilities = [ModelCapability.REASONING]
        elif subtask.type == "code":
            # Use local model for code
            strategy = RoutingStrategy.LOCAL_FIRST
            capabilities = [ModelCapability.CODING]
        elif subtask.type == "system":
            # System tasks use local
            strategy = RoutingStrategy.LOCAL_FIRST
            capabilities = []
        else:
            strategy = RoutingStrategy.COST_OPTIMIZED
            capabilities = []

        try:
            response = await self.router.complete(
                CompletionRequest(
                    messages=[Message(role="user", content=full_prompt)],
                    model=subtask.model,
                    temperature=0.7 if subtask.type == "code" else 0.3,
                    max_tokens=4096,
                    required_capabilities=capabilities,
                ),
                strategy=strategy,
            )

            subtask.result = response.content
            subtask.status = SubtaskStatus.COMPLETED
            subtask.end_time = datetime.now()

            return response.content

        except Exception as e:
            subtask.error = str(e)
            subtask.status = SubtaskStatus.FAILED
            subtask.end_time = datetime.now()
            raise

    async def execute_plan(
        self,
        plan: ExecutionPlan,
        context: Optional[str] = None,
        progress_callback: Optional[Callable[[Subtask], Awaitable[None]]] = None,
    ) -> MergeResult:
        """
        Execute a plan with parallel subtasks.

        Args:
            plan: The execution plan
            context: Additional context
            progress_callback: Called when a subtask completes

        Returns:
            MergeResult with final merged output
        """
        completed_results: Dict[str, str] = {}
        total_cost = 0.0
        start_time = datetime.now()

        # Execute in waves (respecting dependencies)
        while True:
            ready = plan.get_ready_subtasks()
            if not ready:
                # Check if all done or stuck
                pending = [
                    st for st in plan.subtasks if st.status == SubtaskStatus.PENDING
                ]
                if pending:
                    logger.warning(
                        f"Stuck with {len(pending)} pending tasks - circular dependency?"
                    )
                break

            # Limit concurrency
            batch = ready[: plan.max_concurrent]

            # Execute batch in parallel
            tasks = []
            for subtask in batch:
                task = asyncio.create_task(
                    self.execute_subtask(subtask, context, completed_results)
                )
                tasks.append((subtask, task))

            # Wait for batch
            for subtask, task in tasks:
                try:
                    result = await asyncio.wait_for(task, timeout=plan.timeout_seconds)
                    completed_results[subtask.id] = result

                    if progress_callback:
                        await progress_callback(subtask)

                    # Check if research completed and we need to invalidate speculative work
                    if (
                        subtask.type == "research"
                        and plan.merge_strategy == MergeStrategy.RESEARCH_WINS
                    ):
                        # Mark speculative tasks as superseded
                        for st in plan.subtasks:
                            if st.speculative and st.status == SubtaskStatus.RUNNING:
                                logger.info(f"Superseding speculative task {st.id}")
                                st.status = SubtaskStatus.SUPERSEDED

                except asyncio.TimeoutError:
                    subtask.status = SubtaskStatus.FAILED
                    subtask.error = "Timeout"
                except Exception as e:
                    logger.error(f"Subtask {subtask.id} failed: {e}")

        # Merge results
        merge_result = await self._merge_results(plan, completed_results, context)
        merge_result.total_latency_ms = int(
            (datetime.now() - start_time).total_seconds() * 1000
        )

        return merge_result

    async def _merge_results(
        self,
        plan: ExecutionPlan,
        completed_results: Dict[str, str],
        context: Optional[str] = None,
    ) -> MergeResult:
        """Merge results from parallel execution"""

        used_results = []
        discarded_results = []

        # Categorize results
        research_results = []
        code_results = []
        other_results = []

        for subtask in plan.subtasks:
            if subtask.id not in completed_results:
                if subtask.status == SubtaskStatus.SUPERSEDED:
                    discarded_results.append(subtask.id)
                continue

            result = completed_results[subtask.id]

            if subtask.status == SubtaskStatus.SUPERSEDED:
                discarded_results.append(subtask.id)
                continue

            used_results.append(subtask.id)

            if subtask.type == "research":
                research_results.append((subtask, result))
            elif subtask.type == "code":
                code_results.append((subtask, result))
            else:
                other_results.append((subtask, result))

        # Apply merge strategy
        if plan.merge_strategy == MergeStrategy.FIRST_WINS:
            # Simple: just concatenate
            final_output = "\n\n---\n\n".join(completed_results.values())
            merge_notes = "Results concatenated (first wins)"

        elif plan.merge_strategy == MergeStrategy.KEEP_BOTH:
            # Keep all results with labels
            sections = []
            for subtask_id, result in completed_results.items():
                sections.append(f"## {subtask_id}\n\n{result}")
            final_output = "\n\n".join(sections)
            merge_notes = "All results preserved for user selection"

        elif plan.merge_strategy == MergeStrategy.RESEARCH_WINS:
            # Research results take priority
            if research_results:
                # Use research to filter/adapt code
                research_summary = "\n\n".join(r[1] for r in research_results)

                if code_results:
                    # Ask model to reconcile
                    final_output = await self._reconcile_with_research(
                        research_summary, code_results[0][1], context
                    )
                    merge_notes = "Code adapted to match research findings"
                else:
                    final_output = research_summary
                    merge_notes = "Research results (no code generated)"
            else:
                final_output = code_results[0][1] if code_results else ""
                merge_notes = "No research results, using code directly"

        else:  # SMART_MERGE
            # Intelligent merge: use research to enhance code
            final_output = await self._smart_merge(
                research_results, code_results, other_results, context
            )
            merge_notes = "Smart merge: research informed code generation"

        return MergeResult(
            final_output=final_output,
            used_results=used_results,
            discarded_results=discarded_results,
            merge_notes=merge_notes,
            total_cost=0.0,  # TODO: track per-subtask costs
            total_latency_ms=0,
        )

    async def _reconcile_with_research(
        self,
        research: str,
        code: str,
        context: Optional[str] = None,
    ) -> str:
        """Adapt code to match research findings"""
        prompt = f"""The following code was written speculatively before research completed.
Now that research is done, adapt the code to match the findings.

## Research Findings:
{research}

## Speculative Code:
{code}

## Instructions:
1. Identify what needs to change based on research
2. Adapt the code structure to match best practices found
3. Keep useful parts of the original code
4. Output the final, corrected code

{f"Context: {context}" if context else ""}

Output only the final code with brief explanations."""

        response = await self.router.complete(
            CompletionRequest(
                messages=[Message(role="user", content=prompt)],
                temperature=0.5,
                max_tokens=4096,
            ),
            strategy=RoutingStrategy.LOCAL_FIRST,  # Use local for code modification
        )

        return response.content

    async def _smart_merge(
        self,
        research_results: List[tuple],
        code_results: List[tuple],
        other_results: List[tuple],
        context: Optional[str] = None,
    ) -> str:
        """Intelligently merge all results"""

        sections = []

        # Add research summary
        if research_results:
            research_text = "\n\n".join(r[1] for r in research_results)
            sections.append(f"## Research Findings\n\n{research_text}")

        # Process code with research context
        if code_results and research_results:
            # Reconcile code with research
            reconciled = await self._reconcile_with_research(
                "\n".join(r[1] for r in research_results), code_results[0][1], context
            )
            sections.append(f"## Implementation\n\n{reconciled}")
        elif code_results:
            sections.append(f"## Implementation\n\n{code_results[0][1]}")

        # Add other results
        for subtask, result in other_results:
            sections.append(f"## {subtask.type.title()}: {subtask.id}\n\n{result}")

        return "\n\n---\n\n".join(sections)


class TaskPlanner:
    """
    High-level task planning interface.

    Simplifies the process of:
    1. Creating execution plans
    2. Running parallel execution
    3. Handling results
    """

    def __init__(self, router: ModelRouter):
        self.router = router
        self.executor = ParallelExecutor(router)

    async def execute(
        self,
        task: str,
        context: Optional[str] = None,
        parallel: bool = True,
        merge_strategy: Optional[MergeStrategy] = None,
        progress_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a task with optional parallel processing.

        Args:
            task: The task description
            context: Additional context
            parallel: Whether to use parallel execution
            merge_strategy: Override merge strategy
            progress_callback: Called with (subtask_id, status) updates

        Returns:
            Dict with results, plan, and metadata
        """
        if not parallel:
            # Simple single-model execution
            result = await self.router.complete_with_reasoning(task, context)
            return {
                "output": result["execution"],
                "plan": result["plan"],
                "total_cost": result["total_cost"],
                "parallel": False,
            }

        # Create parallel execution plan
        plan = await self.executor.create_plan(task, context)

        if merge_strategy:
            plan.merge_strategy = merge_strategy

        # Execute with progress tracking
        async def _progress(subtask: Subtask):
            if progress_callback:
                await progress_callback(subtask.id, subtask.status.value)

        merge_result = await self.executor.execute_plan(plan, context, _progress)

        return {
            "output": merge_result.final_output,
            "plan": {
                "subtasks": [
                    {
                        "id": st.id,
                        "type": st.type,
                        "status": st.status.value,
                        "duration_ms": st.duration_ms,
                    }
                    for st in plan.subtasks
                ],
                "merge_strategy": plan.merge_strategy.value,
            },
            "merge_notes": merge_result.merge_notes,
            "used_results": merge_result.used_results,
            "discarded_results": merge_result.discarded_results,
            "total_cost": merge_result.total_cost,
            "total_latency_ms": merge_result.total_latency_ms,
            "parallel": True,
        }
