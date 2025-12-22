#!/usr/bin/env python3
"""
SHML Platform CLI - Clean interface for agentic development.

Usage:
    shml agent run "Create a new API endpoint"
    shml agent status
    shml gpu status
    shml training status
    shml mcp call gpu_status

Install:
    pip install typer rich httpx
    chmod +x cli/shml.py
    ln -sf $(pwd)/cli/shml.py ~/.local/bin/shml

Authentication:
    shml auth login              # OAuth login (opens browser)
    shml auth login --api-key    # Use API key
    shml auth status             # Check auth status
    shml auth logout             # Clear stored credentials
"""

import typer
import httpx
import json
import os
import sys
import subprocess
import webbrowser
import secrets
import hashlib
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
import socket
import threading

# Try rich for pretty output, fallback to plain
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.markdown import Markdown
    from rich.prompt import Prompt, Confirm

    RICH_AVAILABLE = True
    console = Console()
except ImportError:
    RICH_AVAILABLE = False
    console = None

# Create CLI app
app = typer.Typer(
    name="shml",
    help="🚀 SHML Platform CLI - Agentic Development Tools",
    add_completion=True,
    rich_markup_mode="rich" if RICH_AVAILABLE else None,
)

# Sub-apps
agent_app = typer.Typer(help="🤖 Agent service commands")
gpu_app = typer.Typer(help="🎮 GPU management commands")
training_app = typer.Typer(help="🏋️ Training job commands")
mcp_app = typer.Typer(help="🔧 MCP tools commands")
platform_app = typer.Typer(help="🖥️ Platform management")
auth_app = typer.Typer(help="🔐 Authentication commands")

app.add_typer(agent_app, name="agent")
app.add_typer(gpu_app, name="gpu")
app.add_typer(training_app, name="training")
app.add_typer(mcp_app, name="mcp")
app.add_typer(platform_app, name="platform")
app.add_typer(auth_app, name="auth")

# Configuration paths
CONFIG_DIR = Path.home() / ".config" / "shml"
CONFIG_FILE = CONFIG_DIR / "config.json"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"

# Default URLs - routes that bypass OAuth
AGENT_URL_EXTERNAL = os.environ.get("SHML_AGENT_URL", "http://localhost/api/agent")
# These endpoints don't require OAuth:
AGENT_CLI_URL = os.environ.get(
    "SHML_AGENT_CLI_URL", "http://localhost/cli"
)  # CLI access (no OAuth)
AGENT_OPENAI_URL = os.environ.get(
    "SHML_AGENT_OPENAI_URL", "http://localhost/v1/chat"
)  # OpenAI-compatible
AGENT_HEALTH_URL = os.environ.get(
    "SHML_AGENT_HEALTH_URL", "http://localhost/agent-health"
)  # Health check
NEMOTRON_URL = os.environ.get("SHML_NEMOTRON_URL", "http://localhost:8010")
OAUTH_URL = os.environ.get("SHML_OAUTH_URL", "http://localhost/oauth2-proxy")
PLATFORM_DIR = Path(__file__).parent.parent


# =============================================================================
# CONFIGURATION & CREDENTIALS MANAGEMENT
# =============================================================================


def load_config() -> Dict[str, Any]:
    """Load CLI configuration."""
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {
        "use_internal_api": True,  # Default to internal (no auth needed)
        "default_model": "nemotron",
    }


def save_config(config: Dict[str, Any]):
    """Save CLI configuration."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def load_credentials() -> Dict[str, Any]:
    """Load stored credentials (API key or OAuth token)."""
    if CREDENTIALS_FILE.exists():
        creds = json.loads(CREDENTIALS_FILE.read_text())
        # Check token expiry
        if creds.get("expires_at"):
            expires = datetime.fromisoformat(creds["expires_at"])
            if datetime.now() > expires:
                return {}  # Expired
        return creds
    return {}


def save_credentials(creds: Dict[str, Any]):
    """Save credentials securely."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.chmod(0o600) if CREDENTIALS_FILE.exists() else None
    CREDENTIALS_FILE.write_text(json.dumps(creds, indent=2))
    CREDENTIALS_FILE.chmod(0o600)


def clear_credentials():
    """Clear stored credentials."""
    if CREDENTIALS_FILE.exists():
        CREDENTIALS_FILE.unlink()


def get_agent_url() -> str:
    """Get the appropriate agent URL based on config."""
    config = load_config()
    if config.get("use_internal_api", True):
        # Use CLI endpoint (no auth required, DEV_MODE handles auth)
        return AGENT_CLI_URL
    return AGENT_URL_EXTERNAL


def get_auth_headers() -> Dict[str, str]:
    """Get authentication headers for requests."""
    creds = load_credentials()
    headers = {}

    if creds.get("api_key"):
        headers["X-API-Key"] = creds["api_key"]
    elif creds.get("access_token"):
        headers["Authorization"] = f"Bearer {creds['access_token']}"
    elif creds.get("session_cookie"):
        headers["Cookie"] = creds["session_cookie"]

    return headers


def get_mcp_url() -> str:
    """Get MCP URL based on config."""
    return f"{get_agent_url()}/mcp"


def print_success(msg: str):
    if RICH_AVAILABLE:
        console.print(f"[green]✓[/green] {msg}")
    else:
        print(f"✓ {msg}")


def print_error(msg: str):
    if RICH_AVAILABLE:
        console.print(f"[red]✗[/red] {msg}")
    else:
        print(f"✗ {msg}")


def print_info(msg: str):
    if RICH_AVAILABLE:
        console.print(f"[blue]ℹ[/blue] {msg}")
    else:
        print(f"ℹ {msg}")


def print_warning(msg: str):
    if RICH_AVAILABLE:
        console.print(f"[yellow]⚠[/yellow] {msg}")
    else:
        print(f"⚠ {msg}")


def print_json_result(data: dict, title: str = "Result"):
    if RICH_AVAILABLE:
        json_str = json.dumps(data, indent=2)
        syntax = Syntax(json_str, "json", theme="monokai", line_numbers=False)
        console.print(Panel(syntax, title=title, border_style="blue"))
    else:
        print(json.dumps(data, indent=2))


# =============================================================================
# AUTHENTICATION COMMANDS
# =============================================================================


@auth_app.command("login")
def auth_login(
    api_key: bool = typer.Option(False, "--api-key", "-k", help="Login with API key"),
    internal: bool = typer.Option(
        True, "--internal/--external", help="Use internal API (no auth)"
    ),
):
    """
    🔐 Login to SHML Platform.

    By default uses internal API which doesn't require authentication.

    Examples:
        shml auth login                    # Use internal API (no auth)
        shml auth login --external         # Use OAuth (opens browser)
        shml auth login --api-key          # Enter API key manually
    """
    config = load_config()

    if internal:
        # Internal API - no auth needed, just configure
        config["use_internal_api"] = True
        save_config(config)
        print_success("Configured to use CLI endpoint (no OAuth required)")
        print_info(f"CLI URL: {AGENT_CLI_URL}")

        # Test connection
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{AGENT_HEALTH_URL}")
                if response.status_code == 200:
                    print_success("Connection verified!")
                else:
                    print_warning(f"Service returned status {response.status_code}")
        except httpx.ConnectError:
            print_warning("Cannot connect to agent service. Is it running?")
            print_info("Try: shml platform start inference")
        return

    if api_key:
        # API key login
        if RICH_AVAILABLE:
            key = Prompt.ask("Enter API key", password=True)
        else:
            import getpass

            key = getpass.getpass("Enter API key: ")

        if not key:
            print_error("API key cannot be empty")
            raise typer.Exit(1)

        # Test the API key
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(
                    f"{AGENT_URL_EXTERNAL}/health", headers={"X-API-Key": key}
                )
                if response.status_code == 200:
                    save_credentials({"api_key": key, "type": "api_key"})
                    config["use_internal_api"] = False
                    save_config(config)
                    print_success("API key authenticated successfully!")
                else:
                    print_error(f"Authentication failed: {response.status_code}")
                    raise typer.Exit(1)
        except httpx.ConnectError:
            print_error("Cannot connect to agent service")
            raise typer.Exit(1)
    else:
        # OAuth login - device flow
        config["use_internal_api"] = False
        save_config(config)
        print_info("Starting OAuth login...")
        print_info("Opening browser for authentication...")

        # Generate PKCE challenge
        code_verifier = secrets.token_urlsafe(32)
        code_challenge = hashlib.sha256(code_verifier.encode()).hexdigest()
        state = secrets.token_urlsafe(16)

        # Start local server to receive callback
        callback_received = threading.Event()
        auth_result = {"code": None, "error": None}

        def handle_callback(conn, addr):
            try:
                request = conn.recv(4096).decode()
                if "GET /callback" in request:
                    # Parse the callback URL
                    path = request.split(" ")[1]
                    query = parse_qs(urlparse(path).query)

                    if "code" in query:
                        auth_result["code"] = query["code"][0]
                        response = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<html><body><h1>✓ Authentication successful!</h1><p>You can close this window.</p></body></html>"
                    else:
                        auth_result["error"] = query.get("error", ["Unknown error"])[0]
                        response = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<html><body><h1>✗ Authentication failed</h1></body></html>"

                    conn.sendall(response.encode())
                callback_received.set()
            finally:
                conn.close()

        # For now, simplified approach - use session cookie from browser
        print_warning("Full OAuth flow not implemented yet.")
        print_info("Use one of these alternatives:")
        print_info("  1. shml auth login --internal    (recommended for local use)")
        print_info("  2. shml auth login --api-key     (for remote/external access)")


@auth_app.command("status")
def auth_status():
    """📊 Check authentication status."""
    config = load_config()
    creds = load_credentials()

    if RICH_AVAILABLE:
        table = Table(title="🔐 Authentication Status")
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="white")

        table.add_row(
            "Mode",
            (
                "Internal API"
                if config.get("use_internal_api", True)
                else "External API (authenticated)"
            ),
        )
        table.add_row("Agent URL", get_agent_url())
        table.add_row("Config File", str(CONFIG_FILE))

        if creds:
            cred_type = creds.get("type", "unknown")
            table.add_row("Credential Type", cred_type)
            if creds.get("expires_at"):
                table.add_row("Expires", creds["expires_at"])
        else:
            table.add_row(
                "Credentials",
                (
                    "None stored"
                    if not config.get("use_internal_api")
                    else "Not required (internal)"
                ),
            )

        console.print(table)
    else:
        print(
            f"Mode: {'Internal API' if config.get('use_internal_api', True) else 'External API'}"
        )
        print(f"Agent URL: {get_agent_url()}")
        if creds:
            print(f"Credential Type: {creds.get('type', 'unknown')}")

    # Test connection
    try:
        with httpx.Client(timeout=5.0) as client:
            headers = get_auth_headers()
            response = client.get(f"{get_agent_url()}/health", headers=headers)
            if response.status_code == 200:
                print_success("Connection: OK")
            else:
                print_error(f"Connection: Failed ({response.status_code})")
    except httpx.ConnectError:
        print_error("Connection: Cannot reach service")


@auth_app.command("logout")
def auth_logout():
    """🚪 Clear stored credentials and reset to internal API."""
    clear_credentials()
    config = load_config()
    config["use_internal_api"] = True
    save_config(config)
    print_success("Logged out and reset to internal API mode")


@auth_app.command("config")
def auth_config(
    internal: bool = typer.Option(
        None, "--internal/--external", help="Use internal or external API"
    ),
    show: bool = typer.Option(False, "--show", "-s", help="Show current config"),
):
    """⚙️ Configure authentication settings."""
    config = load_config()

    if show:
        print_json_result(config, "Current Configuration")
        return

    if internal is not None:
        config["use_internal_api"] = internal
        save_config(config)
        mode = "internal" if internal else "external"
        print_success(f"Switched to {mode} API mode")
        print_info(f"Agent URL: {get_agent_url()}")


# =============================================================================
# AGENT COMMANDS
# =============================================================================


@agent_app.command("run")
def agent_run(
    task: str = typer.Argument(..., help="Task description for the agent"),
    category: str = typer.Option("coding", "-c", "--category", help="Task category"),
    user_id: str = typer.Option("cli-user", "-u", "--user", help="User ID"),
    stream: bool = typer.Option(False, "-s", "--stream", help="Stream output"),
    simple: bool = typer.Option(
        False, "--simple", help="Skip ACE workflow, direct chat response"
    ),
    max_tokens: int = typer.Option(
        4096, "-m", "--max-tokens", help="Max output tokens"
    ),
):
    """
    🚀 Run an agentic task with full ACE workflow.

    The ACE workflow (Generator-Reflector-Curator) analyzes tasks and executes
    tools. For simple questions, use --simple or 'shml agent chat' instead.

    Examples:
        shml agent run "Create a health check endpoint"
        shml agent run "Fix the bug in auth.py" -c debugging
        shml agent run "What is Python?" --simple   # Direct response
        shml agent chat "What is Python?"           # Same as --simple
    """
    session_id = f"cli-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    agent_url = get_agent_url()
    headers = get_auth_headers()

    # If simple mode, redirect to chat (call the underlying function directly)
    if simple:
        return _do_chat(task, "qwen-coder")

    if RICH_AVAILABLE:
        console.print(
            Panel(
                f"[bold]Task:[/bold] {task}\n"
                f"[bold]Category:[/bold] {category}\n"
                f"[bold]Session:[/bold] {session_id}\n"
                f"[bold]API:[/bold] {agent_url}",
                title="🤖 Agent Execution (ACE Workflow)",
                border_style="cyan",
            )
        )
    else:
        print(f"\n🤖 Agent Execution")
        print(f"   Task: {task}")
        print(f"   Category: {category}")
        print(f"   Session: {session_id}\n")

    try:
        with httpx.Client(timeout=300.0) as client:
            if stream:
                # Streaming via OpenAI endpoint (direct to Nemotron, no auth needed)
                response = client.post(
                    f"{NEMOTRON_URL}/v1/chat/completions",
                    json={
                        "model": "qwen-coder",
                        "messages": [
                            {
                                "role": "system",
                                "content": f"You are an expert developer. Complete this {category} task thoroughly.",
                            },
                            {"role": "user", "content": task},
                        ],
                        "stream": True,
                        "max_tokens": max_tokens,
                    },
                    headers={"Accept": "text/event-stream", **headers},
                )

                print_info("Streaming response...")
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            content = (
                                chunk.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                            if content:
                                print(content, end="", flush=True)
                        except:
                            pass
                print("\n")
            else:
                # Full ACE workflow
                if RICH_AVAILABLE:
                    with Progress(
                        SpinnerColumn(),
                        TextColumn("[progress.description]{task.description}"),
                        console=console,
                    ) as progress:
                        progress.add_task("Executing agent workflow...", total=None)
                        response = client.post(
                            f"{agent_url}/api/v1/agent/execute",
                            json={
                                "task": task,
                                "user_id": user_id,
                                "session_id": session_id,
                                "category": category,
                            },
                            headers=headers,
                        )
                else:
                    print("Executing agent workflow...")
                    response = client.post(
                        f"{agent_url}/api/v1/agent/execute",
                        json={
                            "task": task,
                            "user_id": user_id,
                            "session_id": session_id,
                            "category": category,
                        },
                        headers=headers,
                    )

                if response.status_code == 200:
                    result = response.json()

                    if RICH_AVAILABLE:
                        # === TOOL RESULTS (what was executed) ===
                        if result.get("tool_results"):
                            for tr in result["tool_results"]:
                                status = "✓" if tr.get("success") else "✗"
                                color = "green" if tr.get("success") else "red"
                                tool_name = tr.get("tool", "unknown")
                                operation = tr.get("operation", "")

                                # Format the result
                                if tr.get("success") and tr.get("result"):
                                    result_content = (
                                        json.dumps(tr["result"], indent=2)
                                        if isinstance(tr["result"], dict)
                                        else str(tr["result"])
                                    )
                                elif tr.get("result", {}).get("error"):
                                    result_content = f"Error: {tr['result']['error']}"
                                else:
                                    result_content = str(tr.get("result", "No result"))

                                console.print(
                                    Panel(
                                        Syntax(
                                            result_content,
                                            (
                                                "json"
                                                if isinstance(tr.get("result"), dict)
                                                else "text"
                                            ),
                                            theme="monokai",
                                        ),
                                        title=f"{status} Tool: {tool_name}.{operation}",
                                        border_style=color,
                                    )
                                )

                        # === WORKFLOW DETAILS (COLLAPSED/DIM) ===
                        # Generator output (analysis) - dim since final_answer is the main output
                        if result.get("generator_output") and not result.get(
                            "final_answer"
                        ):
                            # Only show generator if no final answer (fallback)
                            console.print(
                                Panel(
                                    Markdown(result["generator_output"]),
                                    title="📝 Generator Analysis",
                                    border_style="dim",
                                )
                            )

                        # Reflector analysis - only show if verbose or no final answer
                        if result.get("reflector_output") and not result.get(
                            "final_answer"
                        ):
                            console.print(
                                Panel(
                                    result["reflector_output"],
                                    title="🔍 Reflector Analysis",
                                    border_style="dim",
                                )
                            )

                        # Lessons learned
                        if result.get("curator_lessons"):
                            lessons = "\n".join(
                                f"• {l}" for l in result["curator_lessons"]
                            )
                            console.print(
                                Panel(
                                    lessons,
                                    title="💡 Lessons Learned",
                                    border_style="dim",
                                )
                            )

                        # Execution stats (with quality score)
                        stats_parts = [
                            f"Execution time: {result.get('execution_time_ms', 0)}ms"
                        ]
                        if result.get("iterations"):
                            stats_parts.append(
                                f"Iterations: {result.get('iterations')}"
                            )
                        if result.get("quality_score") is not None:
                            score = result["quality_score"]
                            score_color = (
                                "green"
                                if score >= 0.75
                                else "yellow" if score >= 0.5 else "red"
                            )
                            stats_parts.append(
                                f"Quality: [{score_color}]{score:.2f}[/{score_color}]"
                            )
                        console.print(f"\n[dim]{' | '.join(stats_parts)}[/dim]")

                        # === FINAL ANSWER (BOTTOM - Last thing user sees) ===
                        if result.get("final_answer"):
                            console.print()
                            task_complete = result.get("task_complete", True)
                            border_style = "green" if task_complete else "yellow"
                            title_text = (
                                "✨ [bold green]Answer[/bold green]"
                                if task_complete
                                else "⚠️ [bold yellow]Partial Answer[/bold yellow]"
                            )
                            console.print(
                                Panel(
                                    Markdown(result["final_answer"]),
                                    title=title_text,
                                    border_style=border_style,
                                    padding=(1, 2),
                                )
                            )

                        # === NEXT ACTIONS (if any suggested) ===
                        next_actions = result.get("next_actions", [])
                        if next_actions:
                            console.print()
                            console.print(
                                "[bold cyan]📋 Suggested Next Actions:[/bold cyan]"
                            )
                            for i, action in enumerate(next_actions, 1):
                                action_type = action.get("type", "suggestion")
                                message = action.get("message", "")
                                suggestion = action.get("suggestion", "")
                                console.print(f"  [{i}] [yellow]{message}[/yellow]")
                                if suggestion:
                                    console.print(f"      [dim]{suggestion}[/dim]")

                        # === INTERACTIVE PROMPT (universal for all responses) ===
                        console.print()

                        # Handle task-complete vs incomplete differently
                        task_complete = result.get("task_complete", True)
                        continue_prompt = result.get("continue_prompt")

                        if not task_complete and continue_prompt:
                            # Task not complete - prompt for continuation
                            if Confirm.ask(f"[yellow]{continue_prompt}[/yellow]"):
                                # Check if there's an auto-command to run
                                for action in next_actions:
                                    if action.get("auto_command"):
                                        import subprocess

                                        cmd = action["auto_command"]
                                        console.print(f"[dim]Running: {cmd}[/dim]")
                                        result = subprocess.run(
                                            cmd,
                                            shell=True,
                                            capture_output=True,
                                            text=True,
                                        )
                                        if result.stdout:
                                            console.print(
                                                f"[green]{result.stdout}[/green]"
                                            )
                                        if result.returncode == 0:
                                            console.print(
                                                "[green]✓ Command succeeded. Re-run your task to continue.[/green]"
                                            )
                                        break
                                else:
                                    console.print(
                                        "[dim]Run your task again to continue iteration.[/dim]"
                                    )
                        elif next_actions:
                            # Task complete but suggestions available
                            if Confirm.ask(
                                "[cyan]Would you like to take any of the suggested actions?[/cyan]"
                            ):
                                # Let user pick action
                                console.print(
                                    "[dim]Enter action number or press Enter to skip:[/dim]"
                                )
                                try:
                                    choice = input().strip()
                                    if choice.isdigit():
                                        idx = int(choice) - 1
                                        if 0 <= idx < len(next_actions):
                                            action = next_actions[idx]
                                            if action.get("auto_command"):
                                                import subprocess

                                                cmd = action["auto_command"]
                                                console.print(
                                                    f"[dim]Running: {cmd}[/dim]"
                                                )
                                                subprocess.run(cmd, shell=True)
                                except (ValueError, EOFError):
                                    pass
                        else:
                            # Task complete, no suggestions - offer general follow-up
                            final_answer = result.get("final_answer", "")
                            # Check for install/missing suggestions in answer text
                            if (
                                "install" in final_answer.lower()
                                or "missing" in final_answer.lower()
                            ):
                                if Confirm.ask(
                                    "[yellow]Would you like me to help with the suggested action?[/yellow]"
                                ):
                                    import re

                                    cmd_match = re.search(r"`([^`]+)`", final_answer)
                                    if cmd_match:
                                        suggested_cmd = cmd_match.group(1)
                                        console.print(
                                            f"[dim]Suggested command: {suggested_cmd}[/dim]"
                                        )
                                        if Confirm.ask(
                                            f"Run: [cyan]{suggested_cmd}[/cyan]?"
                                        ):
                                            import subprocess

                                            subprocess.run(suggested_cmd, shell=True)
                                            console.print(
                                                "[green]Command executed. Re-run your original task to continue.[/green]"
                                            )

                        console.print()  # Final newline
                    else:
                        print_json_result(result, "Agent Result")

                    print_success("Agent execution completed!")
                else:
                    print_error(f"Agent execution failed: {response.status_code}")
                    print(response.text)

    except httpx.ConnectError:
        print_error("Cannot connect to agent service. Is it running?")
        print_info("Start with: ./start_all_safe.sh start inference")
        raise typer.Exit(1)
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


def _do_chat(message: str, model: str = "qwen-coder"):
    """Internal chat function for reuse."""
    headers = get_auth_headers()

    try:
        with httpx.Client(timeout=120.0) as client:
            # Use direct Nemotron endpoint for chat (no auth needed)
            response = client.post(
                f"{NEMOTRON_URL}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": message}],
                    "max_tokens": 2048,
                },
                headers=headers,
            )

            if response.status_code == 200:
                result = response.json()
                content = (
                    result.get("choices", [{}])[0].get("message", {}).get("content", "")
                )

                if RICH_AVAILABLE:
                    console.print(
                        Panel(
                            Markdown(content), title=f"🤖 {model}", border_style="blue"
                        )
                    )
                else:
                    print(f"\n{content}\n")
            else:
                print_error(f"Chat failed: {response.status_code}")

    except httpx.ConnectError:
        print_error("Cannot connect to agent service")
        raise typer.Exit(1)


@agent_app.command("chat")
def agent_chat(
    message: str = typer.Argument(..., help="Message to send"),
    model: str = typer.Option("qwen-coder", "-m", "--model", help="Model to use"),
):
    """
    💬 Quick chat with the coding model (no ACE workflow).

    Examples:
        shml agent chat "Explain async/await in Python"
        shml agent chat "How do I optimize this SQL query?" -m nemotron
    """
    _do_chat(message, model)


@agent_app.command("status")
def agent_status():
    """📊 Check agent service status and health."""
    agent_url = get_agent_url()
    headers = get_auth_headers()

    try:
        with httpx.Client(timeout=10.0) as client:
            # Agent service health
            response = client.get(f"{agent_url}/health", headers=headers)
            agent_health = (
                response.json() if response.status_code == 200 else {"status": "error"}
            )

            # Nemotron health
            try:
                nem_response = client.get(f"{NEMOTRON_URL}/health")
                nemotron_health = (
                    nem_response.json()
                    if nem_response.status_code == 200
                    else {"status": "error"}
                )
            except:
                nemotron_health = {"status": "not running"}

            if RICH_AVAILABLE:
                table = Table(title="🤖 Agent Service Status")
                table.add_column("Service", style="cyan")
                table.add_column("Status", style="green")
                table.add_column("Details")

                agent_status = (
                    "✓ healthy"
                    if agent_health.get("status") == "healthy"
                    else "✗ unhealthy"
                )
                table.add_row("Agent Service", agent_status, str(agent_health))

                nem_status = (
                    "✓ running"
                    if nemotron_health.get("status") == "ok"
                    else "✗ not running"
                )
                table.add_row("Nemotron Model", nem_status, str(nemotron_health))

                console.print(table)
            else:
                print(f"Agent Service: {agent_health}")
                print(f"Nemotron Model: {nemotron_health}")

    except httpx.ConnectError:
        print_error("Cannot connect to services")
        raise typer.Exit(1)


# =============================================================================
# GPU COMMANDS
# =============================================================================


@gpu_app.command("status")
def gpu_status():
    """📊 Show GPU status and memory usage."""
    try:
        # Try nvidia-smi directly
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            if RICH_AVAILABLE:
                table = Table(title="🎮 GPU Status")
                table.add_column("GPU", style="cyan")
                table.add_column("Name", style="white")
                table.add_column("Memory Used", style="yellow")
                table.add_column("Memory Total", style="dim")
                table.add_column("Utilization", style="green")
                table.add_column("Temp", style="red")

                for line in result.stdout.strip().split("\n"):
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 6:
                        used_pct = int(parts[2]) / int(parts[3]) * 100
                        mem_bar = "█" * int(used_pct / 10) + "░" * (
                            10 - int(used_pct / 10)
                        )
                        table.add_row(
                            f"cuda:{parts[0]}",
                            parts[1],
                            f"{parts[2]}MB ({used_pct:.0f}%)",
                            f"{parts[3]}MB",
                            f"{parts[4]}%",
                            f"{parts[5]}°C",
                        )

                console.print(table)
            else:
                print("GPU Status:")
                print(result.stdout)
        else:
            print_error("nvidia-smi failed")

    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@gpu_app.command("yield")
def gpu_yield(
    gpu_id: int = typer.Option(0, "-g", "--gpu", help="GPU ID to yield"),
    job_id: str = typer.Option("cli-task", "-j", "--job", help="Job ID for tracking"),
):
    """🔄 Yield GPU from inference for training."""
    print_info(f"Requesting GPU {gpu_id} yield for job: {job_id}")

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                "http://nemotron-manager:8000/training/start",
                json={"job_id": job_id, "gpus": [gpu_id]},
            )

            if response.status_code == 200:
                print_success("GPU yielded successfully")
                print_json_result(response.json())
            else:
                # Try localhost fallback
                response = client.post(
                    "http://localhost:8011/training/start",
                    json={"job_id": job_id, "gpus": [gpu_id]},
                )
                if response.status_code == 200:
                    print_success("GPU yielded successfully (via localhost)")
                    print_json_result(response.json())
                else:
                    print_error(f"GPU yield failed: {response.status_code}")

    except Exception as e:
        print_error(f"Error: {e}")


@gpu_app.command("reclaim")
def gpu_reclaim(
    gpu_id: int = typer.Option(0, "-g", "--gpu", help="GPU ID to reclaim"),
    job_id: str = typer.Option("cli-task", "-j", "--job", help="Job ID"),
):
    """🔄 Reclaim GPU after training completes."""
    print_info(f"Reclaiming GPU {gpu_id} from job: {job_id}")

    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                "http://localhost:8011/training/end",
                json={"job_id": job_id},
            )

            if response.status_code == 200:
                print_success("GPU reclaimed - inference model restarting")
                print_json_result(response.json())
            else:
                print_error(f"GPU reclaim failed: {response.status_code}")

    except Exception as e:
        print_error(f"Error: {e}")


# =============================================================================
# TRAINING COMMANDS
# =============================================================================


@training_app.command("status")
def training_status():
    """📊 Check active training jobs."""
    try:
        with httpx.Client(timeout=10.0) as client:
            # Check via MCP tool
            response = client.post(
                f"{MCP_URL}/call", json={"tool": "training_status", "arguments": {}}
            )

            if response.status_code == 200:
                result = response.json()
                print_json_result(result, "Training Status")
            else:
                # Fallback to nemotron-manager
                response = client.get("http://localhost:8011/status")
                if response.status_code == 200:
                    print_json_result(response.json(), "Training Status")
                else:
                    print_info("No training jobs found")

    except Exception as e:
        print_error(f"Error: {e}")


@training_app.command("submit")
def training_submit(
    script: str = typer.Argument(..., help="Training script path"),
    gpu: int = typer.Option(0, "-g", "--gpu", help="GPU to use"),
):
    """🚀 Submit a training job (yields GPU automatically)."""
    script_path = Path(script)
    if not script_path.exists():
        print_error(f"Script not found: {script}")
        raise typer.Exit(1)

    print_info(f"Submitting training job: {script_path.name}")
    print_info(f"GPU: cuda:{gpu}")

    # First yield GPU
    gpu_yield(gpu_id=gpu, job_id=f"train-{script_path.stem}")

    # Run training script
    print_info("Starting training...")
    subprocess.run([sys.executable, str(script_path), f"--device={gpu}"])

    # Reclaim GPU after
    gpu_reclaim(gpu_id=gpu, job_id=f"train-{script_path.stem}")


# =============================================================================
# MCP COMMANDS
# =============================================================================


@mcp_app.command("tools")
def mcp_tools():
    """📋 List available MCP tools."""
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{MCP_URL}/tools")

            if response.status_code == 200:
                tools = response.json()

                if RICH_AVAILABLE:
                    table = Table(title="🔧 Available MCP Tools")
                    table.add_column("Tool", style="cyan")
                    table.add_column("Description", style="white")
                    table.add_column("GPU", style="yellow")

                    for tool in tools.get("tools", []):
                        table.add_row(
                            tool.get("name", ""),
                            tool.get("description", "")[:60] + "...",
                            tool.get("gpu", "None"),
                        )

                    console.print(table)
                else:
                    print_json_result(tools, "MCP Tools")
            else:
                print_error(f"Failed to list tools: {response.status_code}")

    except httpx.ConnectError:
        print_error("Cannot connect to MCP endpoint")
        raise typer.Exit(1)


@mcp_app.command("call")
def mcp_call(
    tool: str = typer.Argument(..., help="Tool name to call"),
    args: str = typer.Option("{}", "-a", "--args", help="JSON arguments"),
):
    """
    🔧 Call an MCP tool directly.

    Examples:
        shml mcp call gpu_status
        shml mcp call training_status
        shml mcp call mlflow_query -a '{"query_type": "experiments"}'
    """
    try:
        arguments = json.loads(args)
    except json.JSONDecodeError:
        print_error("Invalid JSON arguments")
        raise typer.Exit(1)

    print_info(f"Calling tool: {tool}")

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{MCP_URL}/call", json={"tool": tool, "arguments": arguments}
            )

            if response.status_code == 200:
                print_json_result(response.json(), f"Tool: {tool}")
            else:
                print_error(f"Tool call failed: {response.status_code}")
                print(response.text)

    except Exception as e:
        print_error(f"Error: {e}")


# =============================================================================
# PLATFORM COMMANDS
# =============================================================================


@platform_app.command("status")
def platform_status():
    """📊 Show full platform status."""
    subprocess.run([str(PLATFORM_DIR / "check_platform_status.sh")])


@platform_app.command("start")
def platform_start(
    stack: str = typer.Argument(
        "all", help="Stack to start: all, inference, mlflow, ray"
    ),
):
    """🚀 Start platform services."""
    subprocess.run([str(PLATFORM_DIR / "start_all_safe.sh"), "start", stack])


@platform_app.command("stop")
def platform_stop(
    stack: str = typer.Argument(
        "all", help="Stack to stop: all, inference, mlflow, ray"
    ),
):
    """🛑 Stop platform services."""
    subprocess.run([str(PLATFORM_DIR / "start_all_safe.sh"), "stop", stack])


@platform_app.command("restart")
def platform_restart(
    stack: str = typer.Argument("inference", help="Stack to restart"),
):
    """🔄 Restart platform services."""
    subprocess.run([str(PLATFORM_DIR / "start_all_safe.sh"), "restart", stack])


@platform_app.command("logs")
def platform_logs(
    service: str = typer.Argument(..., help="Service name"),
    follow: bool = typer.Option(False, "-f", "--follow", help="Follow logs"),
    lines: int = typer.Option(50, "-n", "--lines", help="Number of lines"),
):
    """📜 View service logs."""
    cmd = ["docker", "logs", service, f"--tail={lines}"]
    if follow:
        cmd.append("-f")
    subprocess.run(cmd)


# =============================================================================
# CONVENIENCE ALIASES
# =============================================================================


@app.command("run")
def quick_run(
    task: str = typer.Argument(..., help="Task for the agent"),
):
    """🚀 Quick alias for 'shml agent run'."""
    agent_run(task)


@app.command("chat")
def quick_chat(
    message: str = typer.Argument(..., help="Message to send"),
):
    """💬 Quick alias for 'shml agent chat'."""
    agent_chat(message)


@app.command("status")
def quick_status():
    """📊 Quick status overview."""
    agent_status()
    print()
    gpu_status()


# =============================================================================
# MAIN
# =============================================================================


@app.callback()
def main():
    """
    🚀 SHML Platform CLI

    Clean interface for agentic development, GPU management, and training.

    Quick examples:

        shml run "Create a REST API endpoint"
        shml chat "Explain this code"
        shml status
        shml gpu status
        shml mcp call training_status
    """
    pass


if __name__ == "__main__":
    app()
