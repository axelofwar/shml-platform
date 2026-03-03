"""
Shell Tools - Command execution and testing

Provides safe command execution for:
- Running tests
- Building projects
- Executing scripts
"""

import subprocess
import os
import shlex
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
import asyncio


@dataclass
class CommandResult:
    """Result of a shell command"""

    command: str
    stdout: str
    stderr: str
    returncode: int
    duration_ms: int
    success: bool

    @property
    def output(self) -> str:
        """Combined stdout and stderr"""
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(self.stderr)
        return "\n".join(parts)


class ShellTools:
    """
    Safe shell command execution.

    Provides controlled access to shell commands
    with timeout and output capture.
    """

    # Commands that are allowed
    ALLOWED_COMMANDS = {
        # Testing
        "pytest",
        "python",
        "python3",
        "npm",
        "yarn",
        "pnpm",
        # Building
        "make",
        "cargo",
        "go",
        "docker",
        "docker-compose",
        # Linting/formatting
        "black",
        "ruff",
        "eslint",
        "prettier",
        "mypy",
        # Git (read-only operations)
        "git",
        # Utilities
        "ls",
        "cat",
        "head",
        "tail",
        "grep",
        "find",
        "wc",
        "echo",
        "pwd",
        "which",
        "env",
        # Platform specific
        "shml-router",
        "opencode",
    }

    # Commands that are explicitly blocked
    BLOCKED_COMMANDS = {
        "rm",
        "rmdir",
        "mv",  # Use FileTools instead
        "sudo",
        "su",  # No privilege escalation
        "curl",
        "wget",  # Network operations need review
        "ssh",
        "scp",  # Remote access
        "kill",
        "pkill",  # Process control
        ">",
        ">>",  # Redirects (handled separately)
    }

    def __init__(
        self,
        working_dir: str,
        timeout: int = 300,
        allow_all: bool = False,
    ):
        self.working_dir = Path(working_dir).resolve()
        self.timeout = timeout
        self.allow_all = allow_all
        self.history: List[CommandResult] = []

    def _validate_command(self, command: str) -> bool:
        """Check if command is allowed"""
        if self.allow_all:
            return True

        # Parse command to get the base command
        parts = shlex.split(command)
        if not parts:
            return False

        base_cmd = parts[0]

        # Check blocked list first
        if base_cmd in self.BLOCKED_COMMANDS:
            return False

        # Check allowed list
        return base_cmd in self.ALLOWED_COMMANDS

    def run(
        self,
        command: str,
        timeout: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
        capture_output: bool = True,
    ) -> CommandResult:
        """
        Run a shell command.

        Args:
            command: Command to run
            timeout: Override default timeout
            env: Additional environment variables
            capture_output: Whether to capture stdout/stderr

        Returns:
            CommandResult
        """
        if not self._validate_command(command):
            return CommandResult(
                command=command,
                stdout="",
                stderr=f"Command not allowed: {command.split()[0]}",
                returncode=-1,
                duration_ms=0,
                success=False,
            )

        # Prepare environment
        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        start_time = datetime.now()

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.working_dir,
                capture_output=capture_output,
                text=True,
                timeout=timeout or self.timeout,
                env=run_env,
            )

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            cmd_result = CommandResult(
                command=command,
                stdout=result.stdout if capture_output else "",
                stderr=result.stderr if capture_output else "",
                returncode=result.returncode,
                duration_ms=duration_ms,
                success=result.returncode == 0,
            )

        except subprocess.TimeoutExpired:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            cmd_result = CommandResult(
                command=command,
                stdout="",
                stderr=f"Command timed out after {timeout or self.timeout}s",
                returncode=-1,
                duration_ms=duration_ms,
                success=False,
            )

        except Exception as e:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            cmd_result = CommandResult(
                command=command,
                stdout="",
                stderr=str(e),
                returncode=-1,
                duration_ms=duration_ms,
                success=False,
            )

        self.history.append(cmd_result)
        return cmd_result

    async def run_async(
        self,
        command: str,
        timeout: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> CommandResult:
        """Run command asynchronously"""
        if not self._validate_command(command):
            return CommandResult(
                command=command,
                stdout="",
                stderr=f"Command not allowed: {command.split()[0]}",
                returncode=-1,
                duration_ms=0,
                success=False,
            )

        run_env = os.environ.copy()
        if env:
            run_env.update(env)

        start_time = datetime.now()

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=self.working_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=run_env,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout or self.timeout,
            )

            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            cmd_result = CommandResult(
                command=command,
                stdout=stdout.decode() if stdout else "",
                stderr=stderr.decode() if stderr else "",
                returncode=proc.returncode or 0,
                duration_ms=duration_ms,
                success=proc.returncode == 0,
            )

        except asyncio.TimeoutError:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            cmd_result = CommandResult(
                command=command,
                stdout="",
                stderr=f"Command timed out after {timeout or self.timeout}s",
                returncode=-1,
                duration_ms=duration_ms,
                success=False,
            )

        self.history.append(cmd_result)
        return cmd_result

    def run_tests(
        self,
        test_path: Optional[str] = None,
        framework: str = "pytest",
        extra_args: Optional[List[str]] = None,
    ) -> CommandResult:
        """
        Run tests with specified framework.

        Args:
            test_path: Specific test file/dir
            framework: pytest, npm, cargo, etc.
            extra_args: Additional arguments

        Returns:
            CommandResult
        """
        if framework == "pytest":
            cmd = ["pytest", "-v"]
            if test_path:
                cmd.append(test_path)
            if extra_args:
                cmd.extend(extra_args)
            return self.run(" ".join(cmd))

        elif framework == "npm":
            cmd = ["npm", "test"]
            if extra_args:
                cmd.extend(["--"] + extra_args)
            return self.run(" ".join(cmd))

        elif framework == "cargo":
            cmd = ["cargo", "test"]
            if extra_args:
                cmd.extend(extra_args)
            return self.run(" ".join(cmd))

        else:
            return CommandResult(
                command=f"test:{framework}",
                stdout="",
                stderr=f"Unknown test framework: {framework}",
                returncode=-1,
                duration_ms=0,
                success=False,
            )

    def lint(
        self,
        files: Optional[List[str]] = None,
        fix: bool = False,
    ) -> CommandResult:
        """Run linting"""
        cmd = ["ruff", "check"]
        if fix:
            cmd.append("--fix")
        if files:
            cmd.extend(files)
        else:
            cmd.append(".")

        return self.run(" ".join(cmd))

    def format_code(
        self,
        files: Optional[List[str]] = None,
        check_only: bool = False,
    ) -> CommandResult:
        """Run code formatter"""
        cmd = ["black"]
        if check_only:
            cmd.append("--check")
        if files:
            cmd.extend(files)
        else:
            cmd.append(".")

        return self.run(" ".join(cmd))

    def get_history(self) -> List[Dict[str, Any]]:
        """Get command history"""
        return [
            {
                "command": r.command,
                "success": r.success,
                "returncode": r.returncode,
                "duration_ms": r.duration_ms,
                "output_length": len(r.output),
            }
            for r in self.history
        ]
