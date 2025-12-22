"""
GitHub Copilot Provider

Uses the gh copilot CLI extension as a subprocess.
Requires: gh auth login + gh extension install github/gh-copilot

This is a workaround since GitHub Copilot doesn't have a public API.
"""

import os
import asyncio
import logging
import subprocess
from typing import List, Optional, AsyncIterator
from datetime import datetime

from ..base import (
    BaseProvider,
    ProviderType,
    ModelInfo,
    ModelCapability,
    CompletionRequest,
    CompletionResponse,
    ProviderStatus,
    ProviderError,
)

logger = logging.getLogger(__name__)


class GitHubCopilotProvider(BaseProvider):
    """
    GitHub Copilot CLI Provider

    Uses `gh copilot suggest` and `gh copilot explain` commands.

    Setup:
    1. Install GitHub CLI: https://cli.github.com/
    2. Authenticate: gh auth login
    3. Install Copilot extension: gh extension install github/gh-copilot
    4. Accept Copilot terms when prompted

    Limitations:
    - No streaming (subprocess returns full output)
    - Limited to shell/code suggestions
    - Interactive prompts may block
    """

    name = "github_copilot"
    provider_type = ProviderType.CLOUD_FRONTIER

    MODELS = {
        "copilot-suggest": ModelInfo(
            id="copilot-suggest",
            name="GitHub Copilot Suggest",
            provider="github_copilot",
            capabilities=[ModelCapability.CODING, ModelCapability.CHAT],
            provider_type=ProviderType.CLOUD_FRONTIER,
            context_window=8192,
            cost_per_1k_input=0.0,  # Included in subscription
            cost_per_1k_output=0.0,
            supports_streaming=False,
            supports_tools=False,
            max_output_tokens=4096,
        ),
        "copilot-explain": ModelInfo(
            id="copilot-explain",
            name="GitHub Copilot Explain",
            provider="github_copilot",
            capabilities=[ModelCapability.CODING, ModelCapability.REASONING],
            provider_type=ProviderType.CLOUD_FRONTIER,
            context_window=8192,
            cost_per_1k_input=0.0,
            cost_per_1k_output=0.0,
            supports_streaming=False,
            supports_tools=False,
            max_output_tokens=4096,
        ),
    }

    def __init__(self):
        self._copilot_available: Optional[bool] = None

    async def _check_copilot_installed(self) -> bool:
        """Check if gh copilot is installed and available"""
        if self._copilot_available is not None:
            return self._copilot_available

        try:
            proc = await asyncio.create_subprocess_exec(
                "gh",
                "copilot",
                "--help",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            self._copilot_available = proc.returncode == 0
        except FileNotFoundError:
            self._copilot_available = False

        if not self._copilot_available:
            logger.warning(
                "GitHub Copilot CLI not available. "
                "Install with: gh extension install github/gh-copilot"
            )

        return self._copilot_available

    async def _run_copilot(self, command: str, prompt: str, timeout: int = 60) -> str:
        """Run a gh copilot command"""
        if not await self._check_copilot_installed():
            raise ProviderError(
                "GitHub Copilot CLI not installed", self.name, recoverable=False
            )

        # Use --shell-out to avoid interactive prompts
        cmd = ["gh", "copilot", command, "--shell-out", prompt]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

            if proc.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                raise ProviderError(f"Copilot error: {error_msg}", self.name)

            return stdout.decode()

        except asyncio.TimeoutError:
            raise ProviderError("Copilot request timed out", self.name)

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Generate a completion using gh copilot"""
        model_id = request.model or "copilot-suggest"

        # Extract the last user message as prompt
        prompt = ""
        for msg in reversed(request.messages):
            if msg.role == "user":
                prompt = msg.content
                break

        if not prompt:
            raise ProviderError("No user message found", self.name)

        # Choose command based on model
        command = "explain" if "explain" in model_id else "suggest"

        start_time = datetime.now()

        try:
            output = await self._run_copilot(command, prompt)
            latency = int((datetime.now() - start_time).total_seconds() * 1000)

            return CompletionResponse(
                content=output,
                model=model_id,
                provider=self.name,
                usage={
                    "input_tokens": len(prompt) // 4,
                    "output_tokens": len(output) // 4,
                },
                cost=0.0,  # Included in subscription
                latency_ms=latency,
            )

        except Exception as e:
            raise ProviderError(str(e), self.name)

    async def stream(
        self, request: CompletionRequest
    ) -> AsyncIterator[CompletionResponse]:
        """Streaming not supported - yields single complete response"""
        response = await self.complete(request)
        yield response

    async def health_check(self) -> ProviderStatus:
        """Check if gh copilot is available"""
        available = await self._check_copilot_installed()

        if available:
            return ProviderStatus(available=True)
        else:
            return ProviderStatus(
                available=False, error="gh copilot extension not installed"
            )

    def list_models(self) -> List[ModelInfo]:
        return list(self.MODELS.values())

    def get_model(self, model_id: str) -> Optional[ModelInfo]:
        return self.MODELS.get(model_id)


async def install_copilot_extension() -> bool:
    """Helper to install the gh copilot extension"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh",
            "extension",
            "install",
            "github/gh-copilot",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            logger.info("GitHub Copilot extension installed successfully")
            return True
        else:
            logger.error(f"Failed to install: {stderr.decode()}")
            return False
    except Exception as e:
        logger.error(f"Failed to install gh copilot: {e}")
        return False
