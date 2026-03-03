"""
SHML Platform CLI — unified command-line interface.

Usage:
    shml train --profile balanced --epochs 10
    shml train --profile quick-test
    shml status <job_id>
    shml logs <job_id>
    shml gpu status
    shml gpu yield
    shml gpu reclaim
    shml platform status
    shml config show
    shml config list-profiles
    shml auth login
    shml auth status
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    RICH = True
except ImportError:
    console = None  # type: ignore[assignment]
    RICH = False

app = typer.Typer(
    name="shml",
    help="SHML Platform CLI — training, GPU management, platform operations.",
    add_completion=True,
    no_args_is_help=True,
)

# ── Sub-commands ─────────────────────────────────────────────────────────

gpu_app = typer.Typer(help="GPU management commands.", no_args_is_help=True)
platform_app = typer.Typer(help="Platform management.", no_args_is_help=True)
config_app = typer.Typer(help="Configuration management.", no_args_is_help=True)
auth_app = typer.Typer(help="Authentication commands.", no_args_is_help=True)

app.add_typer(gpu_app, name="gpu")
app.add_typer(platform_app, name="platform")
app.add_typer(config_app, name="config")
app.add_typer(auth_app, name="auth")


def _out(msg: str, style: str = "") -> None:
    """Print with optional Rich styling."""
    if RICH and console:
        console.print(msg, style=style)
    else:
        print(msg)


def _err(msg: str) -> None:
    _out(f"[red]Error:[/red] {msg}" if RICH else f"Error: {msg}")


def _ok(msg: str) -> None:
    _out(f"[green]✓[/green] {msg}" if RICH else f"OK: {msg}")


def _client():
    """Build a Client from env / credentials."""
    from shml.client import Client

    return Client()


# ============================================================================
# TRAIN
# ============================================================================


@app.command()
def train(
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        "-p",
        help="Training profile name (e.g. balanced, quick-test).",
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="Model checkpoint."
    ),
    epochs: Optional[int] = typer.Option(
        None, "--epochs", "-e", help="Number of epochs."
    ),
    batch_size: Optional[int] = typer.Option(
        None, "--batch-size", "-b", help="Batch size."
    ),
    imgsz: Optional[int] = typer.Option(None, "--imgsz", help="Image size."),
    data: Optional[str] = typer.Option(None, "--data", "-d", help="Path to data.yaml."),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show config without submitting."
    ),
) -> None:
    """Submit a training job from a profile or explicit parameters."""
    from shml.config import JobConfig, TrainingConfig

    overrides: dict = {}
    if model:
        overrides["model"] = model
    if epochs is not None:
        overrides["epochs"] = epochs
    if batch_size is not None:
        overrides["batch"] = batch_size
    if imgsz is not None:
        overrides["imgsz"] = imgsz
    if data:
        overrides["data_yaml"] = data

    if profile:
        try:
            job_cfg = JobConfig.from_profile(profile, **overrides)
            cfg = job_cfg.training
        except Exception as e:
            _err(f"Failed to load profile '{profile}': {e}")
            raise typer.Exit(1)
    else:
        cfg = TrainingConfig(**overrides)

    if dry_run:
        _out(
            "[bold]Training Configuration (dry run):[/bold]"
            if RICH
            else "Training Configuration (dry run):"
        )
        import yaml

        _out(cfg.to_yaml())
        raise typer.Exit(0)

    _out(
        f"Submitting training: model={cfg.model}, epochs={cfg.epochs}, "
        f"batch={cfg.batch}, imgsz={cfg.imgsz}"
    )

    try:
        client = _client()
        job = client.submit_training(config=cfg)
        _ok(f"Job submitted: {job.job_id} ({job.name})")
    except Exception as e:
        _err(str(e))
        raise typer.Exit(1)


# ============================================================================
# STATUS / LOGS / CANCEL
# ============================================================================


@app.command()
def status(
    job_id: str = typer.Argument(..., help="Job ID to check."),
) -> None:
    """Get job status."""
    try:
        client = _client()
        job = client.job_status(job_id)
        if RICH and console:
            table = Table(title=f"Job {job_id}")
            table.add_column("Field", style="bold")
            table.add_column("Value")
            table.add_row("Name", job.name)
            table.add_row("Status", job.status)
            for k, v in job.extra.items():
                table.add_row(k, str(v))
            console.print(table)
        else:
            print(f"{job.name}: {job.status}")
    except Exception as e:
        _err(str(e))
        raise typer.Exit(1)


@app.command()
def logs(
    job_id: str = typer.Argument(..., help="Job ID to get logs for."),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output."),
) -> None:
    """Get job logs."""
    try:
        client = _client()
        log_text = client.job_logs(job_id)
        print(log_text)
    except Exception as e:
        _err(str(e))
        raise typer.Exit(1)


@app.command()
def cancel(
    job_id: str = typer.Argument(..., help="Job ID to cancel."),
    reason: Optional[str] = typer.Option(
        None, "--reason", "-r", help="Cancellation reason."
    ),
) -> None:
    """Cancel a running job."""
    try:
        client = _client()
        job = client.cancel_job(job_id, reason=reason)
        _ok(f"Job {job_id} cancelled (status: {job.status})")
    except Exception as e:
        _err(str(e))
        raise typer.Exit(1)


@app.command(name="list")
def list_jobs(
    status_filter: Optional[str] = typer.Option(
        None, "--status", "-s", help="Filter by status."
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of jobs to show."),
) -> None:
    """List recent jobs."""
    try:
        client = _client()
        jobs = client.list_jobs(page_size=limit, status=status_filter)
        if RICH and console:
            table = Table(title="Jobs")
            table.add_column("ID", style="dim")
            table.add_column("Name")
            table.add_column("Status")
            for j in jobs:
                color = {
                    "SUCCEEDED": "green",
                    "FAILED": "red",
                    "RUNNING": "yellow",
                }.get(j.status, "")
                table.add_row(
                    j.job_id[:12],
                    j.name,
                    f"[{color}]{j.status}[/{color}]" if color else j.status,
                )
            console.print(table)
        else:
            for j in jobs:
                print(f"{j.job_id[:12]}  {j.status:12s}  {j.name}")
    except Exception as e:
        _err(str(e))
        raise typer.Exit(1)


# ============================================================================
# GPU
# ============================================================================


@gpu_app.command(name="status")
def gpu_status() -> None:
    """Show GPU status."""
    try:
        client = _client()
        gpus = client.gpu_status()
        if not gpus:
            _out("No GPU data available (run nvidia-smi for local info)")
            return
        if RICH and console:
            table = Table(title="GPU Status")
            table.add_column("ID")
            table.add_column("Name")
            table.add_column("Utilization")
            table.add_column("Memory")
            table.add_column("Temp")
            for g in gpus:
                table.add_row(
                    str(g.get("id", "")),
                    g.get("name", ""),
                    f"{g.get('utilization', 0)}%",
                    f"{g.get('memory_used', 0)}/{g.get('memory_total', 0)} MB",
                    f"{g.get('temperature', '')}°C",
                )
            console.print(table)
        else:
            for g in gpus:
                print(json.dumps(g))
    except Exception as e:
        _err(str(e))


@gpu_app.command(name="yield")
def gpu_yield() -> None:
    """Yield GPU resources for training (stop inference containers)."""
    try:
        client = _client()
        result = client.gpu_yield()
        _ok(f"GPU yielded: {result}")
    except Exception as e:
        _err(str(e))


@gpu_app.command()
def reclaim() -> None:
    """Reclaim GPU resources (restart inference containers)."""
    try:
        client = _client()
        result = client.gpu_reclaim()
        _ok(f"GPU reclaimed: {result}")
    except Exception as e:
        _err(str(e))


# ============================================================================
# PLATFORM
# ============================================================================


@platform_app.command(name="status")
def platform_status() -> None:
    """Check health of all platform services."""
    try:
        client = _client()
        health = client.health_check()
        if RICH and console:
            table = Table(title="Platform Health")
            table.add_column("Service", style="bold")
            table.add_column("Status")
            for svc, ok in sorted(health.items()):
                status_str = "[green]healthy[/green]" if ok else "[red]down[/red]"
                table.add_row(svc, status_str)
            console.print(table)
        else:
            for svc, ok in sorted(health.items()):
                print(f"{'OK' if ok else 'FAIL':6s}  {svc}")
    except Exception as e:
        _err(str(e))


# ============================================================================
# CONFIG
# ============================================================================


@config_app.command(name="show")
def config_show() -> None:
    """Show current platform configuration."""
    from shml.config import PlatformConfig

    cfg = PlatformConfig.from_env()
    if RICH and console:
        table = Table(title="Platform Configuration")
        table.add_column("Setting", style="bold")
        table.add_column("Value")
        import dataclasses

        for f in dataclasses.fields(cfg):
            val = getattr(cfg, f.name)
            table.add_row(f.name, str(val))
        console.print(table)
    else:
        import dataclasses

        for f in dataclasses.fields(cfg):
            print(f"{f.name}: {getattr(cfg, f.name)}")


@config_app.command(name="list-profiles")
def config_list_profiles() -> None:
    """List available training profiles."""
    from shml.config import list_profiles

    profiles = list_profiles()
    if not profiles:
        _out("No profiles found in config/profiles/")
        return

    if RICH and console:
        table = Table(title="Training Profiles")
        table.add_column("Name", style="bold")
        table.add_column("Model")
        table.add_column("Epochs")
        table.add_column("Batch")
        table.add_column("ImgSz")
        table.add_column("File")
        for p in profiles:
            table.add_row(
                p["name"],
                p.get("model", "—"),
                str(p.get("epochs", "—")),
                str(p.get("batch", "—")),
                str(p.get("imgsz", "—")),
                p.get("path", ""),
            )
        console.print(table)
    else:
        for p in profiles:
            print(
                f"{p['name']:20s}  epochs={p.get('epochs','?'):>4s}  "
                f"batch={p.get('batch','?'):>3s}  {p.get('path','')}"
            )


@config_app.command(name="validate")
def config_validate(
    profile: str = typer.Argument(..., help="Profile name to validate."),
) -> None:
    """Validate a training profile."""
    from shml.config import JobConfig

    try:
        job_cfg = JobConfig.from_profile(profile)
        _ok(f"Profile '{profile}' is valid")
        _out(
            f"  model={job_cfg.training.model}, epochs={job_cfg.training.epochs}, "
            f"batch={job_cfg.training.batch}, imgsz={job_cfg.training.imgsz}"
        )
    except Exception as e:
        _err(f"Profile '{profile}' validation failed: {e}")
        raise typer.Exit(1)


# ============================================================================
# AUTH
# ============================================================================


CREDENTIALS_DIR = Path.home() / ".shml"
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials"


@auth_app.command(name="login")
def auth_login(
    api_key: Optional[str] = typer.Option(None, "--api-key", "-k", help="API key."),
    base_url: Optional[str] = typer.Option(None, "--url", help="Platform URL."),
) -> None:
    """Store authentication credentials."""
    from shml.config import AuthConfig

    if not api_key:
        if RICH:
            from rich.prompt import Prompt

            api_key = Prompt.ask("API Key")
        else:
            api_key = input("API Key: ").strip()

    if not api_key:
        _err("No API key provided")
        raise typer.Exit(1)

    auth = AuthConfig(api_key=api_key, base_url=base_url)
    auth.save()
    _ok("Credentials saved")


@auth_app.command(name="status")
def auth_status() -> None:
    """Show current authentication status."""
    from shml.config import AuthConfig

    auth = AuthConfig()
    if auth.api_key:
        masked = (
            auth.api_key[:8] + "..." + auth.api_key[-4:]
            if len(auth.api_key) > 12
            else "***"
        )
        _ok(f"Authenticated (API key: {masked})")
    elif auth.oauth_token:
        _ok("Authenticated (OAuth token)")
    else:
        _out("Not authenticated. Run: shml auth login")


@auth_app.command(name="logout")
def auth_logout() -> None:
    """Clear stored credentials."""
    creds_file = CREDENTIALS_DIR / "credentials"
    if creds_file.exists():
        creds_file.unlink()
        _ok("Credentials cleared")
    else:
        _out("No credentials to clear")


# ============================================================================
# ENTRY POINT
# ============================================================================


def app_entry() -> None:
    """Package entry point."""
    app()


if __name__ == "__main__":
    app()
