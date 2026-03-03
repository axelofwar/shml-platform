"""
Agent Executor - Autonomous coding agent with file/git/test capabilities

This agent can:
1. Plan tasks using frontier models (Gemini)
2. Write code to files
3. Create git branches and commits
4. Run tests and iterate until passing
5. Open GitHub PRs

Usage:
    executor = AgentExecutor("/path/to/workspace")
    result = await executor.execute_task(
        "Create a Python function that adds two numbers with tests"
    )
"""

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

from ..router import ModelRouter, RouterConfig
from ..base import CompletionRequest, Message
from .file_tools import FileTools
from .git_tools import GitTools
from .github_tools import GitHubTools
from .shell_tools import ShellTools


class TaskStatus(Enum):
    """Task execution status"""

    PENDING = "pending"
    PLANNING = "planning"
    EXECUTING = "executing"
    TESTING = "testing"
    ITERATING = "iterating"
    CREATING_PR = "creating_pr"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ExecutionStep:
    """Record of an execution step"""

    step_type: str  # plan, file_create, file_edit, test, commit, pr
    description: str
    timestamp: datetime
    success: bool
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class ExecutionResult:
    """Result of task execution"""

    task: str
    status: TaskStatus
    steps: List[ExecutionStep]
    branch_name: Optional[str] = None
    pr_url: Optional[str] = None
    files_created: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    test_results: Optional[Dict[str, Any]] = None
    iterations: int = 0
    total_duration_ms: int = 0


class AgentExecutor:
    """
    Autonomous coding agent that can execute tasks end-to-end.

    Combines:
    - Frontier model reasoning (Gemini) for planning
    - Local model (Nemotron) for code generation
    - File/Git/GitHub tools for execution
    - Test running and iteration
    """

    MAX_ITERATIONS = 5

    def __init__(
        self,
        workspace_path: str,
        google_api_key: Optional[str] = None,
        create_branch: bool = True,
        create_pr: bool = True,
        auto_iterate: bool = True,
    ):
        self.workspace_path = Path(workspace_path).resolve()
        self.create_branch = create_branch
        self.create_pr = create_pr
        self.auto_iterate = auto_iterate

        # Initialize tools
        self.file_tools = FileTools(str(self.workspace_path))
        self.shell_tools = ShellTools(str(self.workspace_path))

        # Git/GitHub tools (may fail if not a repo)
        try:
            self.git_tools = GitTools(str(self.workspace_path))
            self.github_tools = GitHubTools(str(self.workspace_path))
        except Exception as e:
            print(f"Git/GitHub tools unavailable: {e}")
            self.git_tools = None
            self.github_tools = None
            self.create_branch = False
            self.create_pr = False

        # Initialize router
        api_key = (
            google_api_key
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("AXELOFWAR_GOOGLE_API_KEY")
        )
        self.router = ModelRouter(RouterConfig(google_api_key=api_key))

        # Execution state
        self.steps: List[ExecutionStep] = []
        self.current_status = TaskStatus.PENDING

    async def initialize(self):
        """Initialize the router"""
        await self.router.initialize()

    def _add_step(
        self,
        step_type: str,
        description: str,
        success: bool,
        details: Optional[Dict] = None,
        error: Optional[str] = None,
    ):
        """Record an execution step"""
        self.steps.append(
            ExecutionStep(
                step_type=step_type,
                description=description,
                timestamp=datetime.now(),
                success=success,
                details=details or {},
                error=error,
            )
        )

    def _generate_branch_name(self, task: str) -> str:
        """Generate a branch name from task description"""
        # Extract key words
        words = re.findall(r"\w+", task.lower())
        key_words = [w for w in words if len(w) > 3][:4]

        timestamp = datetime.now().strftime("%m%d")
        return f"agent/{'-'.join(key_words)}-{timestamp}"

    async def _plan_task(self, task: str) -> Dict[str, Any]:
        """Use Gemini to plan the task"""
        self.current_status = TaskStatus.PLANNING

        planning_prompt = f"""You are a coding agent planning a task. Analyze and create an execution plan.

Task: {task}

Workspace: {self.workspace_path}

Output a JSON plan with:
{{
    "summary": "Brief task summary",
    "files_to_create": [
        {{"path": "relative/path/file.py", "purpose": "what this file does"}}
    ],
    "files_to_modify": [
        {{"path": "existing/file.py", "changes": "what changes to make"}}
    ],
    "test_file": "path/to/test_file.py",
    "test_command": "pytest path/to/test_file.py -v",
    "branch_name": "feature/descriptive-name",
    "pr_title": "Short PR title",
    "pr_body": "Detailed PR description with changes"
}}

Be specific about file paths and what each file should contain.
Output ONLY valid JSON, no markdown."""

        response = await self.router.complete(
            CompletionRequest(
                messages=[Message(role="user", content=planning_prompt)],
                model="gemini-2.0-flash-exp",
                temperature=0.2,
                max_tokens=2000,
            )
        )

        try:
            # Extract JSON from response
            content = response.content.strip()
            # Handle markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            plan = json.loads(content)
            self._add_step("plan", "Created execution plan", True, {"plan": plan})
            return plan

        except json.JSONDecodeError as e:
            self._add_step("plan", "Failed to parse plan", False, error=str(e))
            # Return minimal fallback plan
            return {
                "summary": task,
                "files_to_create": [],
                "files_to_modify": [],
                "test_command": "pytest -v",
                "branch_name": self._generate_branch_name(task),
                "pr_title": task[:50],
                "pr_body": task,
            }

    async def _generate_file_content(
        self,
        file_path: str,
        purpose: str,
        context: str = "",
    ) -> str:
        """Use local model to generate file content"""

        prompt = f"""Generate the complete content for this file:

File: {file_path}
Purpose: {purpose}

{f"Context: {context}" if context else ""}

Requirements:
- Write complete, working code
- Include proper imports
- Add docstrings and comments
- Follow best practices for the language

Output ONLY the file content, no explanation or markdown."""

        response = await self.router.complete(
            CompletionRequest(
                messages=[Message(role="user", content=prompt)],
                model="nemotron-mini-4b",
                temperature=0.7,
                max_tokens=4096,
            )
        )

        content = response.content.strip()

        # Remove markdown code blocks if present
        if content.startswith("```"):
            lines = content.split("\n")
            # Remove first and last lines if they're code fences
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)

        return content

    async def _analyze_error(self, error_message: str) -> Dict[str, Any]:
        """Analyze test error to determine what's missing"""

        prompt = f"""Analyze this test/build error and identify what needs to be fixed:

Error:
```
{error_message[:2000]}
```

Output JSON with:
{{
    "error_type": "import_error|syntax_error|assertion_error|missing_file|missing_dependency|runtime_error|other",
    "missing_module": "module name if import error, else null",
    "missing_file": "file path if file not found, else null",
    "missing_function": "function name if undefined, else null",
    "fix_strategy": "create_file|edit_file|install_package|fix_syntax|fix_logic",
    "suggested_fix": "brief description of what to do"
}}

Output ONLY valid JSON."""

        response = await self.router.complete(
            CompletionRequest(
                messages=[Message(role="user", content=prompt)],
                model="gemini-2.0-flash-exp",
                temperature=0.1,
                max_tokens=500,
            )
        )

        try:
            content = response.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            return json.loads(content)
        except:
            return {
                "error_type": "other",
                "fix_strategy": "edit_file",
                "suggested_fix": "Fix the code",
            }

    async def _create_missing_file(
        self,
        file_path: str,
        context: str,
    ) -> bool:
        """Create a missing file based on context"""

        prompt = f"""Create the content for this missing file:

File: {file_path}
Context: {context}

Requirements:
- Write complete, working code
- Include all necessary imports
- Add docstrings
- Make it work with the tests

Output ONLY the file content, no explanation."""

        response = await self.router.complete(
            CompletionRequest(
                messages=[Message(role="user", content=prompt)],
                model="nemotron-mini-4b",
                temperature=0.7,
                max_tokens=4096,
            )
        )

        content = response.content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)

        op = self.file_tools.create_file(file_path, content)
        return op.success

    async def _fix_code(
        self,
        file_path: str,
        current_content: str,
        error_message: str,
        analysis: Optional[Dict] = None,
    ) -> str:
        """Fix code based on test/lint errors"""

        fix_context = ""
        if analysis:
            fix_context = f"""
Error Analysis:
- Type: {analysis.get('error_type', 'unknown')}
- Strategy: {analysis.get('fix_strategy', 'edit_file')}
- Suggestion: {analysis.get('suggested_fix', 'Fix the error')}
"""

        prompt = f"""Fix the following code based on the error:

File: {file_path}
{fix_context}

Current code:
```
{current_content}
```

Error:
```
{error_message[:1500]}
```

IMPORTANT:
- If the error is an import error, include the missing function/class in this file OR fix the import
- If tests are failing, fix the logic
- Provide the COMPLETE fixed file content

Output ONLY the code, no explanation."""

        response = await self.router.complete(
            CompletionRequest(
                messages=[Message(role="user", content=prompt)],
                model="nemotron-mini-4b",
                temperature=0.5,
                max_tokens=4096,
            )
        )

        content = response.content.strip()

        # Remove markdown code blocks
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)

        return content

    async def execute_task(
        self,
        task: str,
        context: Optional[str] = None,
    ) -> ExecutionResult:
        """
        Execute a task end-to-end.

        Args:
            task: Description of what to do
            context: Additional context

        Returns:
            ExecutionResult with all details
        """
        start_time = datetime.now()
        self.steps = []
        files_created = []
        files_modified = []
        branch_name = None
        pr_url = None
        iterations = 0

        try:
            # Initialize
            await self.initialize()

            # 1. Plan the task
            print(f"🧠 Planning task...")
            plan = await self._plan_task(task)
            print(f"   Plan: {plan.get('summary', task)[:60]}...")

            # 2. Create branch if enabled
            if self.create_branch and self.git_tools:
                self.current_status = TaskStatus.EXECUTING
                branch_name = plan.get("branch_name", self._generate_branch_name(task))

                print(f"🌿 Creating branch: {branch_name}")
                result = self.git_tools.create_branch(branch_name)

                if result.success:
                    self._add_step("git", f"Created branch {branch_name}", True)
                else:
                    # Branch might exist, try checkout
                    self.git_tools.checkout_branch(branch_name)
                    self._add_step(
                        "git", f"Checked out existing branch {branch_name}", True
                    )

            # 3. Create new files
            for file_info in plan.get("files_to_create", []):
                file_path = file_info["path"]
                purpose = file_info.get("purpose", "")

                print(f"📝 Creating: {file_path}")

                content = await self._generate_file_content(
                    file_path, purpose, context or ""
                )
                op = self.file_tools.create_file(file_path, content)

                if op.success:
                    files_created.append(file_path)
                    self._add_step("file_create", f"Created {file_path}", True)
                else:
                    self._add_step(
                        "file_create",
                        f"Failed to create {file_path}",
                        False,
                        error=op.error,
                    )

            # 4. Modify existing files
            for file_info in plan.get("files_to_modify", []):
                file_path = file_info["path"]
                changes = file_info.get("changes", "")

                print(f"✏️ Modifying: {file_path}")

                try:
                    current = self.file_tools.read_file(file_path)
                    # Generate modified content
                    modified = await self._generate_file_content(
                        file_path,
                        f"Modify to: {changes}",
                        f"Current content:\n{current}",
                    )

                    op = self.file_tools.create_file(file_path, modified)
                    if op.success:
                        files_modified.append(file_path)
                        self._add_step("file_edit", f"Modified {file_path}", True)

                except FileNotFoundError:
                    # File doesn't exist, create it
                    content = await self._generate_file_content(
                        file_path, changes, context or ""
                    )
                    op = self.file_tools.create_file(file_path, content)
                    if op.success:
                        files_created.append(file_path)

            # 5. Run tests and iterate (only for code files)
            test_command = plan.get("test_command")
            test_passed = True  # Default to true if no tests

            # Only run tests if there's a test command and we have code files
            code_extensions = {".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go"}
            has_code_files = any(
                Path(f).suffix in code_extensions
                for f in files_created + files_modified
            )

            if test_command and has_code_files and self.auto_iterate:
                test_passed = False

                while iterations < self.MAX_ITERATIONS:
                    iterations += 1
                    self.current_status = TaskStatus.TESTING

                    print(f"🧪 Running tests (iteration {iterations})...")
                    test_result = self.shell_tools.run(test_command)

                    if test_result.success:
                        test_passed = True
                        self._add_step(
                            "test",
                            "Tests passed",
                            True,
                            {
                                "output": (
                                    test_result.stdout[:500]
                                    if test_result.stdout
                                    else ""
                                ),
                            },
                        )
                        print(f"   ✅ Tests passed!")
                        break
                    else:
                        error_output = test_result.output or test_result.stderr or ""
                        self._add_step(
                            "test",
                            f"Tests failed (iteration {iterations})",
                            False,
                            {
                                "output": error_output[:500],
                            },
                        )
                        print(f"   ❌ Tests failed, analyzing error...")

                        # Analyze the error
                        self.current_status = TaskStatus.ITERATING
                        analysis = await self._analyze_error(error_output)

                        print(
                            f"   📊 Error type: {analysis.get('error_type', 'unknown')}"
                        )
                        print(
                            f"   💡 Strategy: {analysis.get('fix_strategy', 'edit_file')}"
                        )

                        # Handle missing file/module
                        if analysis.get("error_type") in (
                            "import_error",
                            "missing_file",
                        ):
                            missing = analysis.get("missing_module") or analysis.get(
                                "missing_file"
                            )
                            if missing:
                                # Convert module to path if needed
                                if "/" not in missing:
                                    missing_path = os.path.join(
                                        self.workspace_path,
                                        f"{missing.replace('.', '/')}.py",
                                    )
                                else:
                                    missing_path = os.path.join(
                                        self.workspace_path, missing
                                    )

                                # Check if we haven't created this yet
                                if missing_path not in files_created:
                                    print(
                                        f"   📄 Creating missing file: {missing_path}"
                                    )
                                    success = await self._create_missing_file(
                                        missing_path,
                                        f"Missing module needed by tests. Error: {error_output[:500]}",
                                    )
                                    if success:
                                        files_created.append(missing_path)
                                        self._add_step(
                                            "file_create",
                                            f"Created missing {missing_path}",
                                            True,
                                        )
                                        continue  # Retry tests with new file

                        # Try to fix existing files
                        # Start with test file if tests failing, then source files
                        files_to_try = []

                        # If it's a test assertion error, fix the test
                        if analysis.get("error_type") == "assertion_error":
                            test_files = [
                                f for f in files_created if "test" in f.lower()
                            ]
                            files_to_try.extend(test_files)

                        # Otherwise fix source files first
                        source_files = [
                            f for f in files_created if "test" not in f.lower()
                        ]
                        files_to_try.extend(source_files)

                        # Fall back to any file
                        if not files_to_try:
                            files_to_try = files_created

                        fixed_any = False
                        for file_to_fix in files_to_try:
                            try:
                                current = self.file_tools.read_file(file_to_fix)
                                fixed = await self._fix_code(
                                    file_to_fix,
                                    current,
                                    error_output,
                                    analysis,
                                )

                                # Only update if content changed
                                if fixed != current:
                                    self.file_tools.create_file(file_to_fix, fixed)
                                    self._add_step("fix", f"Fixed {file_to_fix}", True)
                                    print(f"   🔧 Fixed: {file_to_fix}")
                                    fixed_any = True
                                    break  # Try one fix at a time

                            except Exception as e:
                                self._add_step(
                                    "fix",
                                    f"Fix failed for {file_to_fix}",
                                    False,
                                    error=str(e),
                                )

                        if not fixed_any:
                            print(
                                f"   ⚠️ Could not determine fix, trying general approach..."
                            )
                            # Last resort: ask model to fix anything
                            if files_created:
                                file_to_fix = files_created[0]
                                current = self.file_tools.read_file(file_to_fix)
                                fixed = await self._fix_code(
                                    file_to_fix, current, error_output, analysis
                                )
                                self.file_tools.create_file(file_to_fix, fixed)
                                self._add_step(
                                    "fix", f"General fix applied to {file_to_fix}", True
                                )
            else:
                # No tests needed for documentation
                self._add_step("skip", "Skipped tests (documentation only)", True)

            # 6. Commit changes
            if self.git_tools and (files_created or files_modified):
                print(f"💾 Committing changes...")
                commit_msg = (
                    f"feat: {plan.get('summary', task)[:50]}\n\nGenerated by AI Agent"
                )
                result = self.git_tools.commit(commit_msg)

                if result.success:
                    self._add_step("git", "Committed changes", True)
                else:
                    self._add_step("git", "Commit failed", False, error=result.stderr)

                # Push branch
                if branch_name:
                    print(f"⬆️ Pushing branch...")
                    result = self.git_tools.push(branch_name)
                    if result.success:
                        self._add_step("git", f"Pushed {branch_name}", True)

            # 7. Create PR
            if self.create_pr and self.github_tools and branch_name:
                self.current_status = TaskStatus.CREATING_PR

                print(f"📬 Creating pull request...")
                pr = self.github_tools.create_pr(
                    title=plan.get("pr_title", task[:50]),
                    body=plan.get("pr_body", task),
                    head_branch=branch_name,
                    draft=not test_passed,  # Draft if tests didn't pass
                )

                if pr:
                    pr_url = pr.url
                    self._add_step(
                        "pr", f"Created PR #{pr.number}", True, {"url": pr_url}
                    )
                    print(f"   ✅ PR created: {pr_url}")
                else:
                    self._add_step("pr", "PR creation failed", False)

            # Final status
            if test_passed or not self.auto_iterate:
                self.current_status = TaskStatus.COMPLETED
            else:
                self.current_status = TaskStatus.FAILED

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            return ExecutionResult(
                task=task,
                status=self.current_status,
                steps=self.steps,
                branch_name=branch_name,
                pr_url=pr_url,
                files_created=files_created,
                files_modified=files_modified,
                test_results={"passed": test_passed, "iterations": iterations},
                iterations=iterations,
                total_duration_ms=duration_ms,
            )

        except Exception as e:
            self.current_status = TaskStatus.FAILED
            self._add_step("error", str(e), False, error=str(e))

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            return ExecutionResult(
                task=task,
                status=TaskStatus.FAILED,
                steps=self.steps,
                branch_name=branch_name,
                pr_url=pr_url,
                files_created=files_created,
                files_modified=files_modified,
                iterations=iterations,
                total_duration_ms=duration_ms,
            )

    async def close(self):
        """Cleanup resources"""
        await self.router.close()
