#!/usr/bin/env python3
"""
Router CLI - Quick test and interactive mode

Usage:
    # Quick test
    python -m inference.router.cli test

    # Interactive mode
    python -m inference.router.cli chat

    # List available models
    python -m inference.router.cli models

    # Single prompt
    python -m inference.router.cli ask "What is 2+2?"

    # With specific model
    python -m inference.router.cli ask "Explain transformers" --model gemini-2.0-flash-exp

    # Reason then execute (hybrid mode)
    python -m inference.router.cli reason "Build a YOLO trainer with augmentation"
"""

import asyncio
import argparse
import os
import sys
from pathlib import Path
from typing import Optional


def load_env():
    """Load environment from .env file in project root."""
    try:
        from dotenv import load_dotenv

        # Find project root (contains .env)
        current = Path(__file__).resolve().parent
        while current != current.parent:
            env_file = current / ".env"
            if env_file.exists():
                load_dotenv(env_file)
                return str(env_file)
            current = current.parent

        # Also check workspace root
        workspace_root = os.environ.get("PLATFORM_ROOT", str(Path.cwd()))
        workspace_env = Path(workspace_root) / ".env"
        if workspace_env.exists():
            load_dotenv(workspace_env)
            return str(workspace_env)
    except ImportError:
        pass
    return None


def get_google_api_key() -> Optional[str]:
    """Get Google API key from various sources."""
    # Try direct env var first
    key = os.environ.get("GOOGLE_API_KEY")
    if key:
        return key

    # Try project-specific keys
    for var in ["AXELOFWAR_GOOGLE_API_KEY", "BNCCYBERSPACE_GOOGLE_API_KEY"]:
        key = os.environ.get(var)
        if key:
            return key

    return None


async def test_providers():
    """Test which providers are available."""
    from .router import ModelRouter, RouterConfig
    from .base import ProviderStatus

    print("🔍 Testing Router Configuration...")
    print("=" * 50)

    # Check environment
    google_key = get_google_api_key()
    openrouter_key = os.environ.get("OPENROUTER_API_KEY")

    print(f"\n📋 Environment:")
    print(f"  GOOGLE_API_KEY: {'✅ Set' if google_key else '❌ Not set'}")
    print(f"  OPENROUTER_API_KEY: {'✅ Set' if openrouter_key else '❌ Not set'}")

    # Check gh copilot
    import subprocess

    try:
        result = subprocess.run(
            ["gh", "copilot", "--version"], capture_output=True, text=True, timeout=5
        )
        gh_copilot = result.returncode == 0
    except:
        gh_copilot = False
    print(
        f"  gh copilot extension: {'✅ Installed' if gh_copilot else '❌ Not installed'}"
    )

    # Check local services
    import httpx

    async with httpx.AsyncClient(timeout=5.0) as client:
        # Qwen3-VL
        try:
            r = await client.get("http://localhost:8100/health")
            qwen_status = (
                "✅ Running" if r.status_code == 200 else f"⚠️ Status {r.status_code}"
            )
        except:
            qwen_status = "❌ Not reachable"

        # Nemotron
        try:
            r = await client.get("http://localhost:8101/health")
            nemotron_status = (
                "✅ Running" if r.status_code == 200 else f"⚠️ Status {r.status_code}"
            )
        except:
            nemotron_status = "❌ Not reachable"

    print(f"\n🖥️ Local Services:")
    print(f"  Qwen3-VL (8100): {qwen_status}")
    print(f"  Nemotron (8101): {nemotron_status}")

    # Initialize router and check
    print(f"\n🚀 Initializing Router...")

    config = RouterConfig(
        google_api_key=google_key,
        openrouter_api_key=openrouter_key,
    )

    router = ModelRouter(config)
    await router.initialize()

    print(f"\n📊 Provider Status:")
    for name, provider in router.providers.items():
        status = await provider.health_check()
        emoji = "✅" if status.available else "❌"
        msg = status.error if status.error else "Ready"
        print(f"  {emoji} {name}: {msg}")
        if status.available:
            models = provider.list_models()
            for model in models[:3]:
                print(f"      - {model.id}")
            if len(models) > 3:
                print(f"      ... and {len(models) - 3} more")

    # Summary
    available = [
        n for n, p in router.providers.items() if (await p.health_check()).available
    ]

    print(f"\n✨ Summary:")
    print(f"  Available providers: {len(available)}/{len(router.providers)}")

    if not available:
        print("\n⚠️  No providers available!")
        print("    To enable Gemini (recommended):")
        print("    export GOOGLE_API_KEY=your-key-from-aistudio.google.com")
        return False
    else:
        print(f"  Ready to use: {', '.join(available)}")
        return True


async def list_models():
    """List all available models."""
    from .router import ModelRouter, RouterConfig

    google_key = get_google_api_key()
    config = RouterConfig(
        google_api_key=google_key,
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
    )
    router = ModelRouter(config)
    await router.initialize()

    print("📚 Available Models:")
    print("=" * 60)

    for name, provider in router.providers.items():
        status = await provider.health_check()
        if not status.available:
            continue

        print(f"\n🔹 {name.upper()}")
        models = provider.list_models()
        for model in models:
            caps = ", ".join(c.value for c in model.capabilities)
            cost = (
                f"${model.cost_per_1k_input:.4f}/1k"
                if model.cost_per_1k_input
                else "Free/Local"
            )
            print(f"  {model.id}")
            print(f"    Capabilities: {caps}")
            print(f"    Cost: {cost}")


async def ask(prompt: str, model: Optional[str] = None, stream: bool = False):
    """Send a single prompt."""
    from .router import ModelRouter, RouterConfig
    from .base import CompletionRequest, Message

    config = RouterConfig(
        google_api_key=os.environ.get("GOOGLE_API_KEY"),
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
    )
    router = ModelRouter(config)
    await router.initialize()

    request = CompletionRequest(
        messages=[Message(role="user", content=prompt)],
        model=model,
        stream=stream,
    )

    if model:
        print(f"🤖 Using model: {model}")
    else:
        print(f"🤖 Auto-selecting best available model...")

    print("-" * 40)

    if stream:
        async for chunk in router.complete_stream(request):
            print(chunk.content, end="", flush=True)
        print()
    else:
        response = await router.complete(request)
        print(response.content)
        print("-" * 40)
        print(
            f"📊 Model: {response.model} | Tokens: {response.usage.get('total_tokens', 'N/A')}"
        )


async def chat():
    """Interactive chat mode."""
    from .router import ModelRouter, RouterConfig
    from .base import CompletionRequest, Message

    config = RouterConfig(
        google_api_key=os.environ.get("GOOGLE_API_KEY"),
        openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
    )
    router = ModelRouter(config)
    await router.initialize()

    print("💬 Interactive Chat Mode")
    print("   Type 'quit' to exit, '/model <name>' to switch models")
    print("=" * 50)

    messages = []
    current_model = None

    while True:
        try:
            user_input = input("\n👤 You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() == "quit":
            break
        if user_input.startswith("/model"):
            parts = user_input.split(maxsplit=1)
            if len(parts) > 1:
                current_model = parts[1]
                print(f"   Switched to: {current_model}")
            else:
                print(f"   Current model: {current_model or 'auto'}")
            continue
        if user_input == "/clear":
            messages = []
            print("   Conversation cleared")
            continue

        messages.append(Message(role="user", content=user_input))

        request = CompletionRequest(
            messages=messages,
            model=current_model,
            stream=True,
        )

        print("\n🤖 Assistant: ", end="", flush=True)
        full_response = ""
        async for chunk in router.complete_stream(request):
            print(chunk.content, end="", flush=True)
            full_response += chunk.content
        print()

        messages.append(Message(role="assistant", content=full_response))

    print("\n👋 Goodbye!")


async def reason(task: str, execute: bool = True, verbose: bool = False):
    """
    Two-phase reasoning workflow:
    1. Use Gemini (frontier) for planning/reasoning
    2. Use local models (Nemotron) for execution
    """
    from .router import ModelRouter, RouterConfig
    from .base import CompletionRequest, Message

    google_key = get_google_api_key()
    if not google_key:
        print("❌ GOOGLE_API_KEY not set. Cannot use frontier reasoning.")
        print("   Set in .env: AXELOFWAR_GOOGLE_API_KEY=your-key")
        return

    config = RouterConfig(google_api_key=google_key)
    router = ModelRouter(config)
    await router.initialize()

    # Phase 1: Planning with Gemini
    print("🧠 Phase 1: Planning with Gemini...")
    print("-" * 50)

    planning_prompt = f"""You are a task planner. Break down the following task into clear, actionable steps.
For each step, indicate if it requires:
- [RESEARCH] - needs web search or knowledge lookup
- [CODE] - needs code generation
- [ANALYSIS] - needs reasoning/analysis
- [EXECUTION] - needs running commands

Task: {task}

Output format:
## Plan
1. [TYPE] Step description
2. [TYPE] Step description
...

## Key Considerations
- Important notes for execution

Be concise but thorough."""

    plan_request = CompletionRequest(
        messages=[Message(role="user", content=planning_prompt)],
        model="gemini-2.0-flash-exp",
        temperature=0.3,
    )

    plan_response = await router.complete(plan_request)
    print(f"\n{plan_response.content}")
    print(f"\n📊 Planning cost: ${plan_response.cost:.6f}")

    if not execute:
        print("\n✅ Plan complete. Use --execute to run with local models.")
        return plan_response.content

    # Phase 2: Execute with local model
    print("\n" + "=" * 50)
    print("⚡ Phase 2: Executing with Nemotron (local)...")
    print("-" * 50)

    execution_prompt = f"""Based on this plan, implement the solution:

{plan_response.content}

Original task: {task}

Provide working code and clear instructions. Be thorough and practical."""

    exec_request = CompletionRequest(
        messages=[Message(role="user", content=execution_prompt)],
        model="nemotron-mini-4b",
        temperature=0.7,
        max_tokens=4096,
    )

    print("\n🤖 Implementation:\n")
    async for chunk in router.complete_stream(exec_request):
        print(chunk.content, end="", flush=True)
    print("\n")

    print("=" * 50)
    print("✅ Hybrid reasoning complete!")
    print(f"   Planning: gemini-2.0-flash-exp (${plan_response.cost:.6f})")
    print(f"   Execution: nemotron-mini-4b (FREE - local)")


async def quick(prompt: str):
    """Quick single-shot with best available model."""
    from .router import ModelRouter, RouterConfig
    from .base import CompletionRequest, Message

    google_key = get_google_api_key()
    config = RouterConfig(google_api_key=google_key)
    router = ModelRouter(config)
    await router.initialize()

    request = CompletionRequest(
        messages=[Message(role="user", content=prompt)],
        stream=True,
    )

    async for chunk in router.complete_stream(request):
        print(chunk.content, end="", flush=True)
    print()


async def execute(
    task: str,
    workspace: str,
    no_branch: bool = False,
    no_pr: bool = False,
    no_iterate: bool = False,
):
    """
    Execute a task with full file/git/PR automation.

    This creates files, runs tests, iterates until passing,
    and opens a GitHub PR.
    """
    from .tools.agent_executor import AgentExecutor, TaskStatus

    print("🤖 Agent Executor - Autonomous Coding")
    print("=" * 50)
    print(f"📋 Task: {task}")
    print(f"📁 Workspace: {workspace}")
    print(f"🌿 Create branch: {not no_branch}")
    print(f"📬 Create PR: {not no_pr}")
    print(f"🔄 Auto-iterate: {not no_iterate}")
    print("=" * 50)

    executor = AgentExecutor(
        workspace_path=workspace,
        create_branch=not no_branch,
        create_pr=not no_pr,
        auto_iterate=not no_iterate,
    )

    result = await executor.execute_task(task)

    print("\n" + "=" * 50)
    print("📊 Execution Summary")
    print("=" * 50)

    status_emoji = "✅" if result.status == TaskStatus.COMPLETED else "❌"
    print(f"\n{status_emoji} Status: {result.status.value}")
    print(f"⏱️  Duration: {result.total_duration_ms}ms")
    print(f"🔄 Iterations: {result.iterations}")

    if result.files_created:
        print(f"\n📝 Files created:")
        for f in result.files_created:
            print(f"   - {f}")

    if result.files_modified:
        print(f"\n✏️  Files modified:")
        for f in result.files_modified:
            print(f"   - {f}")

    if result.branch_name:
        print(f"\n🌿 Branch: {result.branch_name}")

    if result.pr_url:
        print(f"\n📬 Pull Request: {result.pr_url}")

    if result.test_results:
        test_emoji = "✅" if result.test_results.get("passed") else "❌"
        print(
            f"\n🧪 Tests: {test_emoji} {'Passed' if result.test_results.get('passed') else 'Failed'}"
        )

    print("\n📜 Execution Steps:")
    for i, step in enumerate(result.steps, 1):
        emoji = "✅" if step.success else "❌"
        print(f"   {i}. {emoji} [{step.step_type}] {step.description}")
        if step.error:
            print(f"      Error: {step.error[:100]}")

    await executor.close()

    return result


def main():
    # Load environment
    env_file = load_env()

    parser = argparse.ArgumentParser(
        description="Router CLI - Hybrid Cloud/Local Inference"
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # test
    subparsers.add_parser("test", help="Test provider configuration")

    # models
    subparsers.add_parser("models", help="List available models")

    # ask
    ask_parser = subparsers.add_parser("ask", help="Send a single prompt")
    ask_parser.add_argument("prompt", help="The prompt to send")
    ask_parser.add_argument("--model", "-m", help="Specific model to use")
    ask_parser.add_argument(
        "--stream", "-s", action="store_true", help="Stream response"
    )

    # chat
    subparsers.add_parser("chat", help="Interactive chat mode")

    # reason (NEW - hybrid workflow)
    reason_parser = subparsers.add_parser(
        "reason", help="Plan with Gemini, execute with local"
    )
    reason_parser.add_argument("task", help="Task to plan and execute")
    reason_parser.add_argument(
        "--plan-only",
        "-p",
        action="store_true",
        help="Only generate plan, don't execute",
    )
    reason_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed output"
    )

    # execute (NEW - full automation)
    exec_parser = subparsers.add_parser(
        "exec", help="Execute task with file/git/PR automation"
    )
    exec_parser.add_argument("task", help="Task to execute")
    exec_parser.add_argument(
        "--workspace", "-w", default=".", help="Workspace path (default: current dir)"
    )
    exec_parser.add_argument(
        "--no-branch", action="store_true", help="Don't create a git branch"
    )
    exec_parser.add_argument(
        "--no-pr", action="store_true", help="Don't create a GitHub PR"
    )
    exec_parser.add_argument(
        "--no-iterate", action="store_true", help="Don't iterate on test failures"
    )

    # quick (shortcut)
    quick_parser = subparsers.add_parser("q", help="Quick prompt with best model")
    quick_parser.add_argument("prompt", nargs="+", help="The prompt")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "test":
        asyncio.run(test_providers())
    elif args.command == "models":
        asyncio.run(list_models())
    elif args.command == "ask":
        asyncio.run(ask(args.prompt, args.model, args.stream))
    elif args.command == "chat":
        asyncio.run(chat())
    elif args.command == "reason":
        asyncio.run(reason(args.task, execute=not args.plan_only, verbose=args.verbose))
    elif args.command == "exec":
        workspace = os.path.abspath(args.workspace)
        asyncio.run(
            execute(args.task, workspace, args.no_branch, args.no_pr, args.no_iterate)
        )
    elif args.command == "q":
        asyncio.run(quick(" ".join(args.prompt)))


if __name__ == "__main__":
    main()
