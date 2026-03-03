#!/usr/bin/env python3
"""
Ray Job Submission CLI - Authenticated access to Ray Compute Platform
Submits jobs via OAuth-protected API using X-API-Key header (no container access needed)

Usage:
    python3 scripts/submit_ray_job.py submit --script path/to/script.py --name "my-job"

Requirements (auto-installed):
    typer httpx rich
"""

import sys
import os
import base64
from pathlib import Path
from typing import Optional, List
import json

try:
    import typer
    import httpx
    from rich.console import Console
    from rich.table import Table
except ImportError:
    print("Installing required packages...")
    os.system(
        "sudo /home/axelofwar/.local/bin/uv pip install --python /usr/bin/python3 --break-system-packages typer httpx rich"
    )
    import typer
    import httpx
    from rich.console import Console
    from rich.table import Table

app = typer.Typer(help="Ray Compute Platform - Authenticated Job Submission")
console = Console()

# API Configuration - use /api/ray which routes to ray-compute-api
API_BASE_URL = os.getenv("SHML_API_URL", "http://localhost/api/ray")


def get_api_key() -> Optional[str]:
    """Get API key from environment or .env file"""
    # Check environment first
    api_key = os.getenv("SHML_API_KEY")
    if api_key:
        return api_key

    # Try to read from .env files
    env_files = [
        Path(__file__).parent.parent / ".env",  # Root .env
        Path(__file__).parent.parent / "ray_compute" / ".env",  # ray_compute/.env
    ]

    for env_file in env_files:
        if env_file.exists():
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("FUSIONAUTH_CICD_SUPER_KEY="):
                        return line.split("=", 1)[1]
                    if line.startswith("CICD_ADMIN_KEY=") and "=" in line:
                        value = line.split("=", 1)[1]
                        if value:  # Not empty
                            return value

    return None


def get_auth_headers() -> dict:
    """Get authentication headers with API key"""
    api_key = get_api_key()

    if not api_key:
        console.print("[bold red]Error:[/bold red] No API key found!")
        console.print("\n[yellow]Set one of the following:[/yellow]")
        console.print("  1. SHML_API_KEY environment variable")
        console.print("  2. FUSIONAUTH_CICD_SUPER_KEY in .env")
        console.print("  3. CICD_ADMIN_KEY in ray_compute/.env")
        raise typer.Exit(1)

    return {"X-API-Key": api_key}


@app.command()
def submit(
    script: str = typer.Option(
        ..., "--script", "-s", help="Path to Python script to execute"
    ),
    name: str = typer.Option(..., "--name", "-n", help="Job name"),
    entrypoint: Optional[str] = typer.Option(
        None,
        "--entrypoint",
        "-e",
        help="Custom entrypoint command (e.g., 'python train.py --epochs 200')",
    ),
    gpu: float = typer.Option(1.0, "--gpu", "-g", help="GPU fraction (0.0-1.0)"),
    cpu: int = typer.Option(8, "--cpu", "-c", help="CPU cores"),
    memory: int = typer.Option(24, "--memory", "-m", help="RAM in GB"),
    timeout: Optional[int] = typer.Option(
        None, "--timeout", "-t", help="Timeout in hours (None = no limit, admin only)"
    ),
    no_timeout: bool = typer.Option(
        False, "--no-timeout", help="Disable timeout (admin only)"
    ),
    requirements: Optional[List[str]] = typer.Option(
        None, "--req", "-r", help="Python packages (e.g., -r torch -r ultralytics)"
    ),
    mlflow_experiment: Optional[str] = typer.Option(
        None, "--mlflow-exp", help="MLflow experiment name"
    ),
    priority: str = typer.Option(
        "normal", "--priority", "-p", help="Priority: low, normal, high, critical"
    ),
):
    """
    Submit a Python script as a Ray job with OAuth authentication.

    Examples:
        # Submit training job
        python3 scripts/submit_ray_job.py \\
            --script ray_compute/jobs/training/phase1_foundation.py \\
            --name "phase1-wider-200ep" \\
            --gpu 1.0 --cpu 8 --memory 24 \\
            --mlflow-exp "Phase1-WIDER-Balanced"

        # Submit with custom entrypoint
        python3 scripts/submit_ray_job.py \\
            --script train.py \\
            --name "custom-training" \\
            --entrypoint "python train.py --epochs 200 --batch-size 8"
    """
    console.print(f"\n[bold cyan]Submitting Ray Job: {name}[/bold cyan]\n")

    # Read script file
    script_path = Path(script)
    if not script_path.exists():
        console.print(f"[bold red]Error:[/bold red] Script not found: {script}")
        raise typer.Exit(1)

    with open(script_path, "rb") as f:
        script_content = f.read()

    script_b64 = base64.b64encode(script_content).decode("utf-8")
    script_name = script_path.name

    # Build job request
    job_data = {
        "name": name,
        "job_type": "training",  # Required field
        "language": "python",
        "script_content": script_b64,
        "script_name": script_name,
        "cpu": cpu,
        "memory_gb": memory,
        "gpu": gpu,
        "priority": priority,
        "requirements": requirements
        or [
            "ultralytics==8.3.54",
            "mlflow==2.17.2",
            "opencv-python-headless==4.10.0.84",
            "torch==2.1.0",
            "torchvision==0.16.0",
            "prometheus_client==0.21.0",  # For Grafana metrics
        ],
    }

    # Add entrypoint if provided
    if entrypoint:
        job_data["entrypoint"] = entrypoint

    # Add timeout
    if no_timeout:
        job_data["no_timeout"] = True
    elif timeout:
        job_data["timeout_hours"] = timeout
    else:
        job_data["timeout_hours"] = 72  # Default 72 hours for training

    # Add MLflow experiment if provided
    if mlflow_experiment:
        job_data["mlflow_experiment"] = mlflow_experiment
        job_data["output_mode"] = "both"  # Store in both Ray artifacts and MLflow

    # Get auth headers
    headers = get_auth_headers()
    headers["Content-Type"] = "application/json"

    # Submit job
    try:
        console.print("[yellow]Connecting to Ray Compute API...[/yellow]")

        # Debug: show API URL and key presence
        console.print(f"[dim]API URL: {API_BASE_URL}[/dim]")
        console.print(
            f"[dim]API Key: {'✓ Found' if headers.get('X-API-Key') else '✗ Missing'}[/dim]"
        )

        with httpx.Client(timeout=30.0) as client:
            # API URL is /api/ray which rewrites to /api/v1, so we use /api/ray/jobs
            response = client.post(
                f"{API_BASE_URL}/jobs",
                json=job_data,
                headers=headers,
                follow_redirects=False,  # Don't auto-redirect to login
            )

            if response.status_code == 302:
                # Redirect to login - OAuth required
                console.print("\n[bold red]Authentication Required[/bold red]")
                console.print(
                    "[yellow]You need to authenticate first. Please:[/yellow]"
                )
                console.print(
                    f"  1. Visit: [link]{API_BASE_URL.replace('/ray/api', '/ray/ui')}[/link]"
                )
                console.print("  2. Sign in with your OAuth provider")
                console.print("  3. Return here and run the command again")
                console.print(
                    "\n[yellow]Or set SHML_API_KEY for automated access[/yellow]"
                )
                raise typer.Exit(1)

            if response.status_code == 403:
                error_detail = response.json().get("detail", "Permission denied")
                console.print(
                    f"\n[bold red]Permission Denied:[/bold red] {error_detail}"
                )
                console.print(
                    "\n[yellow]Your role may not have permission to submit jobs.[/yellow]"
                )
                console.print(
                    "[yellow]Contact an administrator to upgrade your access to 'developer' role.[/yellow]"
                )
                raise typer.Exit(1)

            response.raise_for_status()
            result = response.json()

            console.print("\n[bold green]✓ Job Submitted Successfully[/bold green]\n")

            # Display job info
            table = Table(show_header=False, box=None)
            table.add_row("[cyan]Job ID:[/cyan]", f"[bold]{result['job_id']}[/bold]")
            table.add_row("[cyan]Name:[/cyan]", result["name"])
            table.add_row("[cyan]Status:[/cyan]", result["status"])
            table.add_row("[cyan]Priority:[/cyan]", result.get("priority", "normal"))
            table.add_row("[cyan]GPU:[/cyan]", f"{result['gpu_requested']:.2f}")
            table.add_row("[cyan]CPU:[/cyan]", f"{result['cpu_requested']} cores")
            table.add_row("[cyan]Memory:[/cyan]", f"{result['memory_gb_requested']} GB")

            console.print(table)

            # Show monitoring URLs
            console.print("\n[bold]Monitoring URLs:[/bold]")
            console.print(f"  • Ray Dashboard: [link]http://localhost/ray/[/link]")
            console.print(f"  • Grafana: [link]http://localhost/grafana/[/link]")
            if mlflow_experiment:
                exp_name = mlflow_experiment.replace(" ", "-")
                console.print(
                    f"  • MLflow: [link]http://localhost/mlflow/#/experiments[/link]"
                )

            console.print(
                f"\n[dim]Expected duration: {job_data.get('timeout_hours', 72)} hours[/dim]"
            )
            console.print(
                "[dim]Metrics will appear in Grafana after ~20 minutes[/dim]\n"
            )

    except httpx.HTTPStatusError as e:
        console.print(f"\n[bold red]Error:[/bold red] HTTP {e.response.status_code}")
        try:
            error_detail = e.response.json().get("detail", str(e))
            console.print(f"[red]{error_detail}[/red]\n")
        except:
            console.print(f"[red]{str(e)}[/red]\n")
        raise typer.Exit(1)
    except httpx.RequestError as e:
        console.print(f"\n[bold red]Connection Error:[/bold red] {str(e)}")
        console.print(f"[yellow]Could not connect to API at: {API_BASE_URL}[/yellow]")
        console.print(
            "[yellow]Is the platform running? Try: ./start_all_safe.sh status[/yellow]\n"
        )
        raise typer.Exit(1)


@app.command()
def status():
    """Check Ray Compute API status and authentication"""
    console.print("[yellow]Checking Ray Compute API...[/yellow]")

    headers = get_auth_headers()

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{API_BASE_URL}/api/v1/health", headers=headers)

            if response.status_code == 200:
                console.print("[bold green]✓ API is reachable[/bold green]")
            else:
                console.print(
                    f"[yellow]API returned status {response.status_code}[/yellow]"
                )

    except Exception as e:
        console.print(f"[bold red]✗ Cannot reach API:[/bold red] {str(e)}\n")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
