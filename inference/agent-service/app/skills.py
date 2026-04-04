"""
Shell-First Composable Skills - All skills route through ShellSkill.

Architecture:
- ShellSkill is the PRIMARY executor for ALL operations
- Other skills provide context and translate to shell commands
- Reasoning model determines appropriate shell commands
- Iterative execution until quality threshold met

Agent Skills Standard: https://agentskills.io/specification
"""

from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
import logging
import asyncio
import json

from .security import (
    is_command_safe_for_role,
    filter_skills_for_role,
    filter_output,
)

logger = logging.getLogger(__name__)


class Skill(ABC):
    """Base class for composable skills.

    All skills should:
    1. Provide context for the reasoning model
    2. Translate operations to shell commands when possible
    3. Return structured results with next_action suggestions
    """

    ACTIVATION_TRIGGERS: List[str] = []

    @classmethod
    def is_activated(cls, user_task: str) -> bool:
        """Check if skill is activated by user task."""
        task_lower = user_task.lower()
        return any(trigger in task_lower for trigger in cls.ACTIVATION_TRIGGERS)

    @classmethod
    @abstractmethod
    def get_context(cls, user_task: str) -> str:
        """Return skill context if activated."""
        pass

    @classmethod
    @abstractmethod
    async def execute(cls, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute skill operation - should route through ShellSkill when possible."""
        pass

    @classmethod
    def suggest_next_action(
        cls, result: Dict[str, Any], original_task: str
    ) -> Optional[Dict[str, str]]:
        """Suggest next action based on result. Override in subclasses."""
        return None


class ShellSkill(Skill):
    """PRIMARY Shell command execution skill.

    This is the CORE executor - all other skills should route through here.

    Capabilities:
    - Execute any safe shell command
    - GPU monitoring via nvidia-smi
    - Docker container management
    - System diagnostics
    - File operations
    - API calls via curl

    The reasoning model should determine the appropriate shell commands
    for any task and iterate until the answer meets quality threshold.
    """

    ACTIVATION_TRIGGERS = [
        "shell",
        "terminal",
        "command",
        "bash",
        "nvidia-smi",
        "gpu",
        "system",
        "docker",
        "container",
        "file",
        "disk",
        "memory",
        "cpu",
        "process",
        "curl",
        "http",
        "api",
        "check",
        "status",
        "monitor",
        "list",
        "find",
        "grep",
    ]

    # Allowed command prefixes (safe operations)
    # Allowed command prefixes (safe operations)
    ALLOWED_COMMANDS = [
        "nvidia-smi",
        "docker ps",
        "docker stats",
        "docker logs",
        "docker inspect",
        "df",
        "free",
        "top -bn1",
        "cat /proc/cpuinfo",
        "cat /proc/meminfo",
        "ls",
        "pwd",
        "whoami",
        "hostname",
        "uptime",
        "uname",
        "which",
        "echo",
        "date",
        "wc",
        "head",
        "tail",
        "grep",
        "find",
        "curl",  # For internal API calls
        "ray",
    ]

    # Blocked patterns (dangerous)
    BLOCKED_PATTERNS = [
        "rm -rf",
        "rm -r /",
        "mkfs",
        "dd if=",
        ":(){",  # Fork bomb
        "chmod 777",
        "sudo",
        "su -",
        "> /dev/",
        "| sh",
        "| bash",
        "; sh",
        "; bash",
        "eval",
        "exec",
        "wget http",  # Only allow internal curls
        "curl -o",  # No downloading
    ]

    @classmethod
    def get_context(cls, user_task: str) -> str:
        """Return shell skill context."""
        if not cls.is_activated(user_task):
            return ""

        return """# Shell Skill

**Purpose:** Execute safe shell commands for system information and diagnostics.

**Available Operations:**

- `run`: Execute a shell command
  - Params: command (str), timeout (int, default: 30)
  - Returns: {"stdout": "...", "stderr": "...", "exit_code": 0}

- `gpu_status`: Get detailed GPU information via nvidia-smi
  - Params: format (str: "full" | "brief" | "json", default: "full")
  - Returns: Detailed GPU metrics including memory, temperature, utilization

- `docker_status`: Get running containers status
  - Params: filter (str, optional), stats (bool, default: False)
  - Returns: Container list and optional resource stats

- `system_info`: Get system information
  - Params: component (str: "cpu" | "memory" | "disk" | "all")
  - Returns: System metrics

**GPU Status Example:**
```
Tool: ShellSkill
Operation: gpu_status
Params: {"format": "full"}
```

Returns detailed nvidia-smi output:
- GPU name, driver version
- Memory usage (used/total)
- GPU utilization %
- Temperature
- Power usage
- Running processes

**Security:**
- Only safe, read-only commands allowed
- No sudo, rm -rf, or dangerous operations
- Timeout enforced (max 60 seconds)
- Commands logged for audit

**Common Use Cases:**
- Check GPU memory before training: `gpu_status`
- Monitor container health: `docker_status`
- Verify system resources: `system_info`
- Custom diagnostics: `run` with allowed command
"""

    @classmethod
    def _is_command_safe(
        cls, command: str, user_role: str = "admin"
    ) -> tuple[bool, str]:
        """Check if command is safe to execute for the given role."""
        # Use role-based security check from security module
        return is_command_safe_for_role(command, user_role)

    @classmethod
    async def execute(cls, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute shell operation."""

        if operation == "gpu_status":
            # Detailed GPU status - try multiple methods
            format_type = params.get("format", "full")

            # Method 1: Try nvidia-smi directly (if available)
            if format_type == "json":
                cmd = "nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu,utilization.memory,temperature.gpu,power.draw --format=csv,noheader,nounits"
            elif format_type == "brief":
                cmd = "nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu --format=csv,noheader"
            else:
                cmd = "nvidia-smi"

            result = await cls._run_command(cmd, timeout=15)

            # If nvidia-smi not available, try querying via docker
            if (
                result.get("exit_code") != 0
                or "not found" in result.get("stderr", "").lower()
            ):
                # Method 2: Query via docker exec to a GPU container
                # Try multiple containers that might have nvidia-smi
                docker_cmd = "docker exec qwopus-coding nvidia-smi 2>/dev/null || docker exec qwen3-vl-api nvidia-smi 2>/dev/null || docker exec ray-head nvidia-smi 2>/dev/null"
                result = await cls._run_command(docker_cmd, timeout=20)

                if result.get("exit_code") != 0:
                    # Method 3: Query BOTH inference service health endpoints
                    import httpx

                    gpu_info = {"gpus": []}

                    try:
                        async with httpx.AsyncClient(timeout=10.0) as client:
                            # GPU 0: Qwen3-VL (RTX 2070)
                            try:
                                resp = await client.get(
                                    "http://qwen3-vl-api:8000/health"
                                )
                                if resp.status_code == 200:
                                    health = resp.json()
                                    gpu_info["gpus"].append(
                                        {
                                            "index": 0,
                                            "name": "NVIDIA GeForce RTX 2070",
                                            "service": "qwen3-vl-api",
                                            "status": health.get("status", "unknown"),
                                            "model": health.get("model", "unknown"),
                                            "vram_total_gb": health.get(
                                                "vram_total_gb"
                                            ),
                                            "vram_used_gb": health.get("vram_used_gb"),
                                        }
                                    )
                            except Exception:
                                gpu_info["gpus"].append(
                                    {
                                        "index": 0,
                                        "name": "NVIDIA GeForce RTX 2070",
                                        "service": "qwen3-vl-api",
                                        "status": "unreachable",
                                    }
                                )

                            # GPU 1: Nemotron (RTX 3090)
                            try:
                                resp = await client.get(
                                    "http://qwopus-coding:8000/health"
                                )
                                if resp.status_code == 200:
                                    health = resp.json()
                                    gpu_info["gpus"].append(
                                        {
                                            "index": 1,
                                            "name": "NVIDIA GeForce RTX 3090 Ti",
                                            "service": "qwopus-coding",
                                            "status": health.get("status", "unknown"),
                                            "model": health.get("model", "unknown"),
                                            "vram_total_gb": health.get(
                                                "vram_total_gb"
                                            ),
                                            "vram_used_gb": health.get("vram_used_gb"),
                                        }
                                    )
                            except Exception:
                                gpu_info["gpus"].append(
                                    {
                                        "index": 1,
                                        "name": "NVIDIA GeForce RTX 3090 Ti",
                                        "service": "qwopus-coding",
                                        "status": "unreachable",
                                    }
                                )

                        if gpu_info["gpus"]:
                            return {
                                "stdout": f"GPU Status (via inference services):\n{json.dumps(gpu_info, indent=2)}",
                                "stderr": "",
                                "exit_code": 0,
                                "source": "inference-health-apis",
                                "note": "nvidia-smi not accessible, queried inference service health endpoints",
                            }
                    except Exception:
                        pass

                    # Method 4: Return manual info about known GPUs
                    return {
                        "stdout": """Known GPU Configuration:
GPU 0: NVIDIA GeForce RTX 2070 (8GB VRAM)
  - Primary use: Qwen3-VL inference (always loaded)
  - ~6.8GB usable after display overhead

GPU 1: NVIDIA GeForce RTX 3090 Ti (24GB VRAM)
  - Primary use: Training jobs, Z-Image generation
  - Yields to training when idle >5min

Note: nvidia-smi not accessible from agent container.
Use Ray Dashboard at http://localhost:8265 for live metrics.""",
                        "stderr": "",
                        "exit_code": 0,
                        "source": "config",
                        "note": "Based on platform configuration",
                    }

            return result

        elif operation == "docker_status":
            # Docker container status
            filter_str = params.get("filter", "")
            include_stats = params.get("stats", False)

            if include_stats:
                cmd = "docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}'"
            elif filter_str:
                cmd = f"docker ps --filter 'name={filter_str}' --format 'table {{{{.Names}}}}\t{{{{.Status}}}}\t{{{{.Ports}}}}'"
            else:
                cmd = "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"

            return await cls._run_command(cmd, timeout=30)

        elif operation == "system_info":
            # System information
            component = params.get("component", "all")

            results = {}

            if component in ["cpu", "all"]:
                cpu_result = await cls._run_command(
                    "grep 'model name' /proc/cpuinfo | head -1 && nproc", timeout=5
                )
                results["cpu"] = cpu_result.get("stdout", "")

            if component in ["memory", "all"]:
                mem_result = await cls._run_command("free -h", timeout=5)
                results["memory"] = mem_result.get("stdout", "")

            if component in ["disk", "all"]:
                disk_result = await cls._run_command(
                    "df -h / /home 2>/dev/null | tail -n +2", timeout=5
                )
                results["disk"] = disk_result.get("stdout", "")

            if component in ["gpu", "all"]:
                gpu_result = await cls._run_command(
                    "nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv,noheader",
                    timeout=10,
                )
                results["gpu"] = gpu_result.get("stdout", "")

            return {"system_info": results, "component": component}

        elif operation == "run":
            # Generic command execution
            command = params.get("command", "")
            timeout = min(params.get("timeout", 30), 60)  # Max 60s

            if not command:
                return {"error": "No command provided"}

            # Get user role from params (set by agent when invoking skill)
            user_role = params.get("_user_role", "viewer")
            is_safe, reason = cls._is_command_safe(command, user_role)
            if not is_safe:
                return {"error": f"Command blocked: {reason}", "command": command}

            result = await cls._run_command(command, timeout=timeout)

            # Filter output for secrets before returning
            if result.get("stdout"):
                result["stdout"], redacted = filter_output(result["stdout"], user_role)
                if redacted:
                    result["_redacted_count"] = redacted

            return result

        else:
            return {
                "error": f"Unknown operation: {operation}. Available: gpu_status, docker_status, system_info, run"
            }

    @classmethod
    async def _run_command(cls, command: str, timeout: int = 30) -> Dict[str, Any]:
        """Execute a shell command safely."""
        try:
            logger.info(f"Executing shell command: {command[:100]}")

            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                return {
                    "error": f"Command timed out after {timeout}s",
                    "command": command,
                    "exit_code": -1,
                }

            result = {
                "stdout": stdout.decode("utf-8", errors="replace").strip(),
                "stderr": stderr.decode("utf-8", errors="replace").strip(),
                "exit_code": process.returncode,
                "command": command,
            }

            if process.returncode != 0:
                result["error"] = f"Command exited with code {process.returncode}"

            logger.info(f"Shell command completed: exit_code={process.returncode}")
            return result

        except Exception as e:
            logger.error(f"Shell command failed: {e}")
            return {"error": str(e), "command": command}

    @classmethod
    def suggest_next_action(
        cls, result: Dict[str, Any], original_task: str
    ) -> Optional[Dict[str, str]]:
        """Suggest next action based on shell command result."""

        # Check for common errors and suggest fixes
        stderr = result.get("stderr", "").lower()
        stdout = result.get("stdout", "").lower()
        error = result.get("error", "").lower()
        exit_code = result.get("exit_code", 0)

        # Command not found
        if "command not found" in stderr or "not found" in error:
            cmd = (
                result.get("command", "").split()[0]
                if result.get("command")
                else "command"
            )
            return {
                "type": "install_dependency",
                "message": f"'{cmd}' is not installed.",
                "suggestion": f"Install with: apt install {cmd} or check your PATH",
                "prompt": f"Would you like me to help install {cmd}?",
                "auto_command": f"which {cmd} || echo 'Not in PATH'",
            }

        # Permission denied
        if "permission denied" in stderr or "permission denied" in error:
            return {
                "type": "permission_error",
                "message": "Permission denied for this operation.",
                "suggestion": "This may require elevated privileges or different user context.",
                "prompt": "Would you like me to try an alternative approach?",
            }

        # nvidia-smi specific
        if "nvidia-smi" in result.get("command", "") and exit_code != 0:
            return {
                "type": "gpu_unavailable",
                "message": "nvidia-smi failed - GPU may not be accessible.",
                "suggestion": "Try: docker exec <gpu-container> nvidia-smi",
                "prompt": "Would you like me to check GPU status via a container?",
                "auto_command": "docker exec qwopus-coding nvidia-smi 2>/dev/null || docker exec qwen3-vl-api nvidia-smi 2>/dev/null",
            }

        # Docker not running
        if "docker" in result.get("command", "") and (
            "cannot connect" in stderr or "is docker running" in stderr
        ):
            return {
                "type": "docker_unavailable",
                "message": "Docker daemon is not running or not accessible.",
                "suggestion": "Start Docker: sudo systemctl start docker",
                "prompt": "Would you like me to check Docker status?",
            }

        # Empty result when expecting data
        if exit_code == 0 and not stdout and "query" in original_task.lower():
            return {
                "type": "empty_result",
                "message": "Command succeeded but returned no output.",
                "suggestion": "The query may need to be refined or the resource doesn't exist.",
                "prompt": "Would you like me to try a different approach?",
            }

        # Successful but might need follow-up
        if exit_code == 0 and stdout:
            task_lower = original_task.lower()

            # If checking status, might want to monitor or take action
            if "status" in task_lower or "check" in task_lower:
                return {
                    "type": "status_complete",
                    "message": "Status check complete.",
                    "suggestion": "You can monitor continuously or take action based on the results.",
                    "prompt": "Would you like to take any action based on these results?",
                }

            # If listing, might want to inspect specific item
            if "list" in task_lower:
                return {
                    "type": "list_complete",
                    "message": "Listing complete.",
                    "suggestion": "You can inspect specific items or filter the results.",
                    "prompt": "Would you like to inspect any specific item?",
                }

        return None


class GitLabSkill(Skill):
    """GitLab CE issue management skill — Linear-inspired workflow.

    Provides autonomous issue lifecycle management via the local GitLab CE
    instance (shml-gitlab). The agent can pick up, work on, and close issues
    without human interaction.

    Workflow:
      list_agent_queue → claim_issue → [do work] → complete_issue
    """

    ACTIVATION_TRIGGERS = [
        "gitlab",
        "issue",
        "issues",
        "task",
        "tasks",
        "backlog",
        "triage",
        "bug",
        "feature request",
        "sprint",
        "milestone",
        "board",
        "ticket",
        "work item",
        "claim",
        "take on",
        "complete issue",
        "close issue",
        "create issue",
        "list issues",
        "agent queue",
    ]

    @classmethod
    def get_context(cls, user_task: str) -> str:
        if not cls.is_activated(user_task):
            return ""

        return """# GitLab Issue Management Skill

**Purpose:** Autonomous issue lifecycle management on the local GitLab CE instance.
Labels follow a Linear-inspired hierarchy. The agent MUST use this skill to self-assign work.

## Agent Workflow (Linear-inspired)

1. **`list_agent_queue`** — see what is queued for the agent (status::backlog + assignee::agent)
2. **`claim_issue`** — take ownership (status::in-progress, leaves a plan comment)
3. [Do the actual work using other skills]
4. **`complete_issue`** — post summary comment, set status::done, close the issue

## Operations

### list_agent_queue
Issues tagged `assignee::agent` + `status::backlog`, ordered by priority.
Params: `limit` (int, default:10)
Returns: list of {iid, title, labels, url}

### list_issues
Params: `state` ("opened"|"closed"|"all"), `labels` (comma-sep string), `search` (str), `limit` (int)

### get_issue
Params: `iid` (int)
Returns: full issue {iid, title, state, labels, description, url}

### create_issue
Params: `title` (str), `description` (markdown str), `labels` (comma-sep), `milestone_id` (int)
Use templates — see Label Reference below.

### claim_issue
MUST call before starting any work on an issue.
Params: `iid` (int), `plan` (str — your step-by-step plan)
Side effects: status→in-progress, assignee::agent, comment posted.

### complete_issue
MUST call after finishing work.
Params: `iid` (int), `summary` (str — what you did, files changed, outcome)
Side effects: status→done, assignee::agent removed, issue closed.

### triage_issue
Categorise a new/untriaged issue into the backlog.
Params: `iid` (int), `priority` ("critical"|"high"|"medium"|"low"),
        `type_label` ("bug"|"feature"|"chore"|"training"|"security"),
        `component` ("infra"|"ci-cd"|"agent-service"|"chat-ui"|"autoresearch"),
        `comment` (str — optional triage note)

### add_comment
Params: `iid` (int), `body` (markdown str)

### close_issue
Params: `iid` (int)

## Label Reference

| Scope | Values |
|-------|--------|
| status:: | triage · backlog · in-progress · in-review · done · blocked · cancelled |
| priority:: | critical · high · medium · low |
| type:: | bug · feature · chore · training · security |
| component:: | infra · ci-cd · agent-service · chat-ui · autoresearch · fusionauth |
| source:: | watchdog · scan · autoresearch · ci · pipeline |
| assignee:: | agent (Qwen3.5/Nemotron autonomous) |

## Context Window Guidance
Before claiming an issue, check if the task fits your context window.
- Small (< 5 files, < 200 LOC change): safe to claim
- Medium (5-20 files): claim with explicit scope limit in plan comment
- Large (> 20 files, cross-service refactor): triage with `priority::medium` and note the scope; do not claim autonomously

## Tool Call Format

```
Tool: GitLabSkill
Operation: claim_issue
Params: {"iid": 42, "plan": "1. Read the failing test\\n2. Fix the assertion\\n3. Run locally\\n4. Push"}
```
"""

    @classmethod
    async def execute(cls, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        from .gitlab_client import (
            list_issues as _list_issues,
            get_issue as _get_issue,
            create_issue as _create_issue,
            claim_issue as _claim_issue,
            complete_issue as _complete_issue,
            triage_issue as _triage_issue,
            add_comment as _add_comment,
            close_issue as _close_issue,
            list_agent_queue as _list_agent_queue,
        )

        try:
            if operation == "list_agent_queue":
                limit = int(params.get("limit", 10))
                issues = await _list_agent_queue(limit=limit)
                return {"issues": [i.to_summary() for i in issues], "count": len(issues)}

            elif operation == "list_issues":
                issues = await _list_issues(
                    state=params.get("state", "opened"),
                    labels=params.get("labels") or None,
                    search=params.get("search") or None,
                    per_page=int(params.get("limit", 20)),
                )
                return {"issues": [i.to_summary() for i in issues], "count": len(issues)}

            elif operation == "get_issue":
                iid = int(params["iid"])
                issue = await _get_issue(iid)
                return {
                    "iid": issue.iid,
                    "title": issue.title,
                    "state": issue.state,
                    "labels": issue.labels,
                    "description": issue.description[:2000],
                    "url": issue.web_url,
                }

            elif operation == "create_issue":
                label_str = params.get("labels", "")
                labels = [l.strip() for l in label_str.split(",") if l.strip()] if label_str else None
                issue = await _create_issue(
                    params["title"],
                    description=params.get("description", ""),
                    labels=labels,
                    milestone_id=params.get("milestone_id"),
                )
                return issue.to_summary()

            elif operation == "claim_issue":
                iid = int(params["iid"])
                plan = params.get("plan", "")
                issue = await _claim_issue(iid, plan=plan)
                return {"claimed": True, **issue.to_summary()}

            elif operation == "complete_issue":
                iid = int(params["iid"])
                summary = params.get("summary", "")
                issue = await _complete_issue(iid, summary=summary)
                return {"completed": True, **issue.to_summary()}

            elif operation == "triage_issue":
                iid = int(params["iid"])
                issue = await _triage_issue(
                    iid,
                    priority=params.get("priority") or None,
                    type_label=params.get("type_label") or None,
                    component=params.get("component") or None,
                    comment=params.get("comment") or None,
                )
                return {"triaged": True, **issue.to_summary()}

            elif operation == "add_comment":
                iid = int(params["iid"])
                await _add_comment(iid, params["body"])
                return {"commented": True, "iid": iid}

            elif operation == "close_issue":
                iid = int(params["iid"])
                issue = await _close_issue(iid)
                return {"closed": True, **issue.to_summary()}

            else:
                return {"error": f"Unknown GitLabSkill operation: {operation}"}

        except RuntimeError as exc:
            token_missing = "GITLAB_API_TOKEN not set" in str(exc)
            logger.error("GitLabSkill.%s failed: %s", operation, exc)
            return {
                "error": str(exc),
                "hint": "Set GITLAB_API_TOKEN in agent-service docker-compose env" if token_missing else None,
            }
        except Exception as exc:
            logger.error("GitLabSkill.%s unexpected error: %s", operation, exc)
            return {"error": str(exc)}


class GitHubSkill(Skill):
    """GitHub operations skill.

    Provides:
    - Repository management
    - Issue tracking
    - Pull request operations
    - Commit history
    """

    ACTIVATION_TRIGGERS = [
        "github",
        "repository",
        "repo",
        "pull request",
        "pr",
        "issue",
        "commit",
        "push",
        "clone",
        "fork",
    ]

    @classmethod
    def get_context(cls, user_task: str) -> str:
        """Return GitHub skill context."""
        if not cls.is_activated(user_task):
            return ""

        return """# GitHub Skill

**Available Operations:**
- `list_repos`: List user's repositories
  - Params: None
  - Returns: List of repository names and URLs

- `create_issue`: Create a new issue
  - Params: repo (owner/name), title, body
  - Returns: Issue number and URL

- `create_pr`: Create a pull request
  - Params: repo, title, body, head_branch, base_branch
  - Returns: PR number and URL

- `list_commits`: List recent commits
  - Params: repo, branch (optional), limit (default: 10)
  - Returns: List of commit SHAs and messages

- `get_file_content`: Get file content from repo
  - Params: repo, path, branch (optional)
  - Returns: File content as text

**Authentication:**
- Uses user's personal GitHub token from FusionAuth user.data
- Scopes: repo, read:user

**Rate Limits:**
- 5000 requests/hour for authenticated users
- Check X-RateLimit-Remaining header

**Example:**
```python
result = await GitHubSkill.execute("list_repos", {})
# Returns: {"repos": [{"name": "ml-platform", "url": "https://github.com/..."}]}
```

**Common Errors:**
- 401: Invalid or missing token
- 404: Repository not found
- 403: Rate limit exceeded or insufficient permissions
"""

    @classmethod
    async def execute(cls, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute GitHub operation via Composio."""
        # Import here to avoid circular dependency
        from langchain_composio import ComposioToolSet, Action

        # Map operation to Composio action
        action_map = {
            "list_repos": Action.GITHUB_LIST_REPOS,
            "create_issue": Action.GITHUB_CREATE_ISSUE,
            "create_pr": Action.GITHUB_CREATE_PULL_REQUEST,
            "list_commits": Action.GITHUB_LIST_COMMITS,
            "get_file_content": Action.GITHUB_GET_FILE_CONTENT,
        }

        if operation not in action_map:
            return {"error": f"Unknown operation: {operation}"}

        try:
            toolset = ComposioToolSet()
            action = action_map[operation]
            result = await toolset.execute_action(action, params)

            logger.info(f"Executed GitHub operation: {operation}")
            return result
        except Exception as e:
            logger.error(f"GitHub operation failed: {e}")
            return {"error": str(e)}


class SandboxSkill(Skill):
    """Code execution skill.

    Provides:
    - Safe code execution in Kata Containers
    - Multiple language support
    - Resource limits (10min, 10GB)
    - Isolated from production codebase
    """

    ACTIVATION_TRIGGERS = [
        "execute",
        "run",
        "test",
        "sandbox",
        "code",
        "python",
        "node",
        "javascript",
        "go",
        "rust",
    ]

    @classmethod
    def get_context(cls, user_task: str) -> str:
        """Return sandbox skill context."""
        if not cls.is_activated(user_task):
            return ""

        return """# Sandbox Skill

**Execution Environment:**
- Kata Container VM isolation (150MB RAM per container)
- Max containers: 10 concurrent
- Timeout: 10 minutes
- Disk space: 10GB per sandbox
- Network: Isolated (no external access)

**Supported Languages:**
- Python 3.10+ (with pip)
- Node.js 18+ (with npm)
- Go 1.20+
- Rust 1.70+

**Resource Limits:**
- CPU: Shared across containers
- Memory: 150MB per container
- Disk: 10GB per container
- No GPU access (use Ray for GPU jobs)

**Permissions:**
- Requires: elevated-developer or admin role
- Cannot access production codebase
- Cannot make network requests

**Example:**
```python
result = await SandboxSkill.execute("run_code", {
    "code": "print('Hello, World!')",
    "language": "python",
    "timeout_seconds": 30
})
# Returns: {"stdout": "Hello, World!\n", "stderr": "", "exit_code": 0}
```

**Common Errors:**
- 403: Insufficient permissions (requires elevated-developer+)
- 408: Timeout exceeded (>10 minutes)
- 507: Disk space exceeded (>10GB)
- 429: Too many concurrent sandboxes (>10)

**Best Practices:**
- Always set reasonable timeouts
- Clean up after execution
- Use Ray for long-running jobs
- Prefer unit tests over integration tests
"""

    @classmethod
    async def execute(cls, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute code in sandbox."""
        # Import sandbox manager
        from .sandbox import SandboxManager
        from .schemas import UserRole

        if operation != "run_code":
            return {"error": f"Unknown operation: {operation}"}

        code = params.get("code")
        timeout = params.get("timeout_seconds", 600)  # 10min default

        if not code:
            return {"error": "No code provided"}

        try:
            sandbox_manager = SandboxManager()
            sandbox_manager.connect()

            # Create sandbox for agent system user
            sandbox_id = await sandbox_manager.create_sandbox(
                user_id="agent-system", user_roles=[UserRole.ELEVATED_DEVELOPER]
            )

            # Execute code in sandbox
            result = await sandbox_manager.execute_code(
                sandbox_id=sandbox_id, code=code, timeout_seconds=timeout
            )

            # Cleanup sandbox
            sandbox_manager.destroy_sandbox(sandbox_id)

            logger.info(
                f"Executed code in sandbox {sandbox_id}: exit_code={result.get('exit_code')}"
            )
            return result
        except Exception as e:
            logger.error(f"Sandbox execution failed: {e}")
            return {"error": str(e)}


class RayJobSkill(Skill):
    """Ray compute skill.

    Provides:
    - Distributed job submission
    - GPU allocation (RTX 3090, RTX 2070)
    - Training workload management
    - Resource monitoring
    - Face detection training (SOTA curriculum learning)
    """

    ACTIVATION_TRIGGERS = [
        "ray",
        "distribute",
        "distributed",
        "training",
        "train",
        "gpu",
        "cluster",
        "parallel",
        "scale",
        "face detection",
        "yolo",
        "model training",
        "curriculum",
    ]

    @classmethod
    def get_context(cls, user_task: str) -> str:
        """Return Ray job skill context."""
        if not cls.is_activated(user_task):
            return ""

        return """# Ray Job Skill

**Cluster Resources:**
- GPU: RTX 3090 Ti (24GB VRAM, training priority)
- GPU: RTX 2070 (8GB VRAM, ~6.8GB usable after display)
- CPU: 48GB RAM
- Disk: 1.4TB available

**Face Detection Training:**
Submit SOTA face detection training with curriculum learning:

```python
result = await RayJobSkill.execute("submit_face_detection", {
    "epochs": 100,
    "batch_size": 8,
    "imgsz": 1280,
    "curriculum_enabled": True,  # 4-stage curriculum learning
    "recall_focused": True,      # Prioritize recall for privacy
    "download_dataset": False    # Use cached WIDER Face
})
```

**Curriculum Stages:**
1. Presence Detection (20%) - Basic face vs non-face
2. Localization (30%) - Precise bounding boxes
3. Occlusion Handling (25%) - Partial faces, masks
4. Multi-Scale (25%) - Tiny + large faces

**SOTA Features:**
- Online Advantage Filtering (INTELLECT-3)
- Failure Analysis with CLIP clustering
- TTA Validation
- Dataset Quality Auditing

**GPU Allocation Strategy:**
- RTX 3090: Training priority (Z-Image yields after 5min idle)
- RTX 2070: Qwen3-VL always loaded (vision model)
- Request GPU yield before training: `curl -X POST /api/image/yield-to-training`

**Permissions:**
- Requires: elevated-developer or admin role
- Access via OAuth2-Proxy + FusionAuth

**Common Operations:**
- `submit_face_detection`: Start face detection training job
- `submit_job`: Submit generic training job
- `get_status`: Check job status
- `get_metrics`: Get training metrics (mAP50, recall, precision)
- `cancel_job`: Cancel running job
- `get_logs`: Retrieve job logs
- `yield_gpu`: Request Z-Image to free RTX 3090

**Example - Check Training Metrics:**
```python
result = await RayJobSkill.execute("get_metrics", {"job_id": "job-123"})
# Returns: {"mAP50": 0.89, "recall": 0.92, "curriculum_stage": 3}
```

**Common Errors:**
- 403: Insufficient permissions
- 503: No available GPUs
- 507: Insufficient memory/disk

**Best Practices:**
- Always yield Z-Image before training: `yield_gpu`
- Enable curriculum learning for 15-25% faster convergence
- Use recall_focused mode for privacy applications
- Monitor curriculum stage progression
"""

    @classmethod
    async def execute(cls, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Ray job operation."""
        import httpx

        # Ray Compute API endpoint
        ray_api_url = "http://ray-compute-api:8000/api/v1"

        # Extended operation map matching actual Ray API endpoints
        # From: /api/v1/cluster/gpus, /api/v1/cluster/status, /api/v1/jobs, etc.
        operation_map = {
            "submit_job": "/jobs",
            "submit_face_detection": "/jobs",  # Uses specialized payload
            "get_status": "/jobs/{job_id}",
            "get_metrics": "/jobs/{job_id}",  # Metrics in job response
            "cancel_job": "/jobs/{job_id}/cancel",
            "get_logs": "/logs/{job_id}",  # Correct logs endpoint
            "get_gpu_status": "/cluster/gpus",  # Correct GPU endpoint
            "get_cluster_status": "/cluster/status",  # Cluster health
            "get_resource_usage": "/cluster/resource-usage",  # Resource usage
            "list_jobs": "/jobs",  # List all jobs
            "yield_gpu": None,  # Special handling
        }

        if operation not in operation_map:
            return {
                "error": f"Unknown operation: {operation}. Available: {list(operation_map.keys())}"
            }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:

                # Special handling: yield GPU for training
                if operation == "yield_gpu":
                    try:
                        response = await client.post(
                            "http://z-image-api:8000/yield-to-training", timeout=10.0
                        )
                        if response.status_code == 200:
                            logger.info("Z-Image yielded GPU for training")
                            return {
                                "success": True,
                                "message": "Z-Image yielded RTX 3090 for training",
                            }
                        else:
                            return {
                                "success": False,
                                "message": f"Yield request returned {response.status_code}",
                            }
                    except Exception as e:
                        logger.warning(
                            f"Z-Image yield failed (may already be idle): {e}"
                        )
                        return {
                            "success": True,
                            "message": "Z-Image not loaded or already yielded",
                        }

                # Face detection training job
                if operation == "submit_face_detection":
                    # Build face detection job payload
                    job_payload = {
                        "entrypoint": cls._build_face_detection_entrypoint(params),
                        "runtime_env": {
                            "working_dir": "/app/jobs",
                            "pip": [
                                "ultralytics>=8.0.0",
                                "mlflow>=2.0.0",
                                "clip-by-openai",
                            ],
                        },
                        "submission_id": f"face_detection_{int(__import__('time').time())}",
                        "entrypoint_num_gpus": 1,
                        "entrypoint_num_cpus": 8,
                        "metadata": {
                            "job_type": "training",
                            "model_type": "face_detection",
                            "curriculum_enabled": params.get(
                                "curriculum_enabled", True
                            ),
                            "recall_focused": params.get("recall_focused", False),
                        },
                    }

                    response = await client.post(
                        f"{ray_api_url}/jobs", json=job_payload, timeout=30.0
                    )
                    response.raise_for_status()
                    result = response.json()

                    logger.info(
                        f"Submitted face detection training job: {result.get('job_id')}"
                    )
                    return {
                        **result,
                        "training_type": "face_detection",
                        "curriculum_enabled": params.get("curriculum_enabled", True),
                        "message": "Face detection training started with curriculum learning",
                    }

                # Generic job submission
                if operation == "submit_job":
                    response = await client.post(f"{ray_api_url}/jobs", json=params)

                # Get GPU status from cluster endpoint
                elif operation == "get_gpu_status":
                    try:
                        response = await client.get(
                            f"{ray_api_url}/cluster/gpus", timeout=10.0
                        )
                        if response.status_code == 200:
                            return response.json()
                        elif response.status_code == 404:
                            # Try cluster status as fallback
                            cluster_resp = await client.get(
                                f"{ray_api_url}/cluster/status"
                            )
                            return {
                                "status": "available",
                                "cluster": (
                                    cluster_resp.json()
                                    if cluster_resp.status_code == 200
                                    else {}
                                ),
                                "note": "GPU endpoint not available, showing cluster status",
                            }
                    except Exception as e:
                        return {
                            "status": "unknown",
                            "error": f"Could not connect to Ray API: {str(e)}",
                            "suggestion": "Check if ray-compute-api is running",
                        }

                # Get cluster status
                elif operation == "get_cluster_status":
                    response = await client.get(
                        f"{ray_api_url}/cluster/status", timeout=10.0
                    )

                # Get resource usage
                elif operation == "get_resource_usage":
                    response = await client.get(
                        f"{ray_api_url}/cluster/resource-usage", timeout=10.0
                    )

                # List all jobs
                elif operation == "list_jobs":
                    response = await client.get(f"{ray_api_url}/jobs", timeout=10.0)

                # Cancel job
                elif operation == "cancel_job":
                    job_id = params.get("job_id")
                    response = await client.post(  # POST not DELETE
                        f"{ray_api_url}/jobs/{job_id}/cancel"
                    )

                # Get logs
                elif operation == "get_logs":
                    job_id = params.get("job_id")
                    response = await client.get(
                        f"{ray_api_url}/logs/{job_id}", timeout=30.0
                    )

                # Get status, metrics
                else:
                    job_id = params.get("job_id")
                    endpoint = operation_map[operation].format(job_id=job_id)
                    response = await client.get(f"{ray_api_url}{endpoint}")

                response.raise_for_status()
                result = response.json()

                logger.info(f"Executed Ray operation: {operation}")
                return result

        except httpx.HTTPStatusError as e:
            logger.error(
                f"Ray API HTTP error: {e.response.status_code} - {e.response.text}"
            )
            return {
                "error": f"Ray API error: {e.response.status_code}",
                "details": e.response.text[:200],
            }
        except Exception as e:
            logger.error(f"Ray operation failed: {e}")
            return {"error": str(e)}

    @classmethod
    def _build_face_detection_entrypoint(cls, params: Dict[str, Any]) -> str:
        """Build the entrypoint command for face detection training."""
        cmd_parts = ["python", "face_detection_training.py"]

        # Epochs
        if "epochs" in params:
            cmd_parts.extend(["--epochs", str(params["epochs"])])

        # Batch size
        if "batch_size" in params:
            cmd_parts.extend(["--batch-size", str(params["batch_size"])])

        # Image size
        if "imgsz" in params:
            cmd_parts.extend(["--imgsz", str(params["imgsz"])])

        # Curriculum learning (enabled by default)
        if not params.get("curriculum_enabled", True):
            cmd_parts.append("--no-curriculum")

        # Recall-focused mode
        if params.get("recall_focused", False):
            cmd_parts.append("--recall-focused")

        # Download dataset
        if params.get("download_dataset", False):
            cmd_parts.append("--download-dataset")

        # Resume from checkpoint
        if "resume" in params and params["resume"]:
            cmd_parts.extend(["--resume", params["resume"]])

        # Experiment name
        if "experiment" in params:
            cmd_parts.extend(["--experiment", params["experiment"]])

        return " ".join(cmd_parts)


class WebSearchSkill(Skill):
    """Web search skill using DuckDuckGo.

    Provides:
    - Privacy-focused search
    - No tracking or logging
    - Real-time web results
    """

    ACTIVATION_TRIGGERS = [
        "search",
        "google",
        "find",
        "look up",
        "lookup",
        "web",
        "internet",
        "online",
        "duckduckgo",
    ]

    @classmethod
    def get_context(cls, user_task: str) -> str:
        """Return web search skill context."""
        if not cls.is_activated(user_task):
            return ""

        return """# Web Search Skill

**Search Provider:**
- DuckDuckGo (privacy-focused)
- No user tracking
- No search history logging

**Operations:**
- `search`: Perform web search
  - Params: query (str), max_results (int, default: 5)
  - Returns: List of search results with title, URL, snippet

**Example:**
```python
result = await WebSearchSkill.execute("search", {
    "query": "python async await tutorial",
    "max_results": 5
})
# Returns: {"results": [{"title": "...", "url": "...", "snippet": "..."}]}
```

**Best Practices:**
- Be specific in queries
- Use keywords, not full sentences
- Limit results to avoid overwhelming context
- Cite sources in responses
"""

    @classmethod
    async def execute(cls, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute web search."""
        if operation != "search":
            return {"error": f"Unknown operation: {operation}"}

        query = params.get("query")
        max_results = params.get("max_results", 5)

        if not query:
            return {"error": "No query provided"}

        try:
            # Use ddgs directly
            from ddgs import DDGS

            # Execute search
            ddgs = DDGS()
            results = []

            # Use text search
            search_results = ddgs.text(query, max_results=max_results)

            if search_results:
                for result in search_results:
                    results.append(
                        {
                            "title": result.get("title", ""),
                            "url": result.get("href", ""),
                            "snippet": result.get("body", ""),
                        }
                    )

            if not results:
                logger.warning(f"Web search returned 0 results for query: '{query}'")
                return {
                    "results": [],
                    "query": query,
                    "count": 0,
                    "warning": "No results found. Please try a different query or proceed without search results.",
                }

            logger.info(f"Executed web search: query='{query}', results={len(results)}")
            return {"results": results, "query": query, "count": len(results)}
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return {"error": f"Search failed: {str(e)}", "query": query}


# Lazy import for OpenShellSkill (NemoClaw — optional dependency)
try:
    import importlib.util
    _spec = importlib.util.spec_from_file_location(
        "openshell_skill",
        str(__file__).replace("app/skills.py", "skills/openshell-skill/openshell_skill.py"),
    )
    if _spec and _spec.loader:
        _mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)  # type: ignore[union-attr]
        OpenShellSkill = _mod.OpenShellSkill
        _OPENSHELL_AVAILABLE = True
        logger.info("OpenShellSkill loaded (NemoClaw)")
    else:
        OpenShellSkill = None
        _OPENSHELL_AVAILABLE = False
except Exception as _e:
    OpenShellSkill = None
    _OPENSHELL_AVAILABLE = False
    logger.warning(f"OpenShellSkill not available: {_e}")


# Skill registry
# OpenShellSkill is listed BEFORE SandboxSkill so it takes precedence for
# elevated-developer+ when both are allowed. SandboxSkill remains as fallback.
_base_skills: List[type[Skill]] = [
    ShellSkill,  # Shell commands for system info, GPU status, etc.
    GitLabSkill,  # GitLab issue lifecycle — primary task management
    GitHubSkill,
    RayJobSkill,
    WebSearchSkill,
]

if _OPENSHELL_AVAILABLE and OpenShellSkill is not None:
    _base_skills.insert(2, OpenShellSkill)  # Before SandboxSkill

_base_skills.append(SandboxSkill)  # Fallback always registered last

SKILLS: List[type[Skill]] = _base_skills


def get_active_skills(user_task: str, user_role: str = "viewer") -> List[str]:
    """Get context from all activated skills, filtered by user role.

    Args:
        user_task: The user's task description
        user_role: The user's primary role (controls which skills are available)

    Returns:
        List of context strings from activated skills
    """
    # Filter skills based on user role
    allowed_skills = filter_skills_for_role(SKILLS, user_role)

    contexts = []
    # Pattern 26: sort alphabetically for stable KV cache prefix across calls
    for skill_class in sorted(allowed_skills, key=lambda s: s.__name__):
        if skill_class.is_activated(user_task):
            context = skill_class.get_context(user_task)
            if context:
                contexts.append(context)
                logger.info(
                    f"Activated skill: {skill_class.__name__} (role: {user_role})"
                )

    return contexts


def format_skill_contexts(contexts: List[str]) -> str:
    """Format skill contexts for LLM prompt.

    Args:
        contexts: List of skill context strings

    Returns:
        Formatted string with all skill contexts
    """
    if not contexts:
        return ""

    return "\n\n---\n\n".join(contexts)


async def execute_skill(
    skill_name: str, operation: str, params: Dict[str, Any], user_role: str = "viewer"
) -> Dict[str, Any]:
    """Execute a skill operation by name, with role-based access control.

    Args:
        skill_name: Name of the skill (e.g., "GitHubSkill")
        operation: Operation to execute
        params: Operation parameters
        user_role: The user's primary role

    Returns:
        Result dictionary from skill execution
    """
    # Check if skill is allowed for this role
    allowed_skills = filter_skills_for_role(SKILLS, user_role)
    allowed_names = {s.__name__ for s in allowed_skills}

    if skill_name not in allowed_names:
        logger.warning(
            f"SECURITY: Role '{user_role}' denied access to skill '{skill_name}'"
        )
        return {
            "error": f"Skill '{skill_name}' is not available for your role ({user_role})"
        }

    skill_map = {skill.__name__: skill for skill in SKILLS}

    if skill_name not in skill_map:
        return {"error": f"Unknown skill: {skill_name}"}

    # Inject user role into params for role-aware execution
    params["_user_role"] = user_role

    skill_class = skill_map[skill_name]
    result = await skill_class.execute(operation, params)

    # Filter output for secrets
    for key in ("stdout", "output", "content"):
        if isinstance(result.get(key), str):
            result[key], redacted = filter_output(result[key], user_role)
            if redacted:
                result.setdefault("_redacted_count", 0)
                result["_redacted_count"] += redacted

    return result
