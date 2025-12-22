"""
SHML CLI - Command-line interface for SHML Platform.

Usage:
    shml auth login          # OAuth login
    shml auth service-account developer  # Impersonate
    shml run script.py --gpu 0.5
    shml status job-123
    shml logs job-123
    shml cancel job-123
    shml keys list
    shml keys create my-key
"""

import os
import sys
import webbrowser
from pathlib import Path
from datetime import datetime
from typing import Optional

import click

from .client import Client, SHMLError, AuthenticationError
from .config import save_credentials, get_config, CREDENTIALS_FILE


@click.group()
@click.version_option(version="0.1.0")
def main():
    """SHML Platform CLI - Submit and manage Ray compute jobs."""
    pass


# ============================================================================
# Auth Commands
# ============================================================================


@main.group()
def auth():
    """Authentication commands."""
    pass


@auth.command("login")
@click.option("--base-url", envvar="SHML_BASE_URL", help="Platform URL")
@click.option("--profile", default="default", help="Profile name to save")
def auth_login(base_url: Optional[str], profile: str):
    """
    Login via OAuth (opens browser).

    After login, you can use the CLI without specifying credentials.
    """
    config = get_config(base_url=base_url, profile=profile)

    click.echo(f"Opening browser to login at {config.base_url}...")
    click.echo("After login, copy the token and paste it below.")
    click.echo()

    # Open OAuth login page
    login_url = f"{config.base_url}/auth/login?cli=true"
    webbrowser.open(login_url)

    # Get token from user
    token = click.prompt("Paste your access token", hide_input=True)

    if not token:
        click.echo("No token provided. Login cancelled.", err=True)
        sys.exit(1)

    # Verify token works
    try:
        client = Client(base_url=config.base_url, oauth_token=token)
        user = client.me()
        client.close()
    except AuthenticationError:
        click.echo("Invalid token. Login failed.", err=True)
        sys.exit(1)

    # Save credentials
    save_credentials(
        oauth_token=token,
        base_url=config.base_url,
        profile=profile,
    )

    click.echo(f"✓ Logged in as {user.email} ({user.role})")
    click.echo(f"  Credentials saved to {CREDENTIALS_FILE}")


@auth.command("service-account")
@click.argument(
    "account", type=click.Choice(["admin", "elevated_developer", "developer", "viewer"])
)
@click.option("--profile", default="default", help="Profile to read credentials from")
def auth_service_account(account: str, profile: str):
    """
    Impersonate a service account.

    Requires membership in the 'impersonation-enabled' FusionAuth group.
    """
    config = get_config(profile=profile)

    if not config.api_key and not config.oauth_token:
        click.echo("Not logged in. Run 'shml auth login' first.", err=True)
        sys.exit(1)

    try:
        client = Client(
            base_url=config.base_url,
            api_key=config.api_key,
            oauth_token=config.oauth_token,
        )

        # Get impersonation token
        impersonated = client.impersonate(account)

        # Get the impersonated user's info
        user = impersonated.me()

        click.echo(f"✓ Impersonating: {user.email} ({user.role})")
        click.echo(f"  Token saved to profile '{profile}-impersonate'")

        # Save to a separate profile
        save_credentials(
            oauth_token=impersonated.config.oauth_token,
            base_url=config.base_url,
            profile=f"{profile}-impersonate",
        )

        click.echo()
        click.echo(f"Use '--profile {profile}-impersonate' or set:")
        click.echo(f"  export SHML_PROFILE={profile}-impersonate")

    except SHMLError as e:
        click.echo(f"Impersonation failed: {e}", err=True)
        sys.exit(1)


@auth.command("status")
@click.option("--profile", default="default", help="Profile to check")
def auth_status(profile: str):
    """Show current authentication status."""
    config = get_config(profile=profile)

    click.echo(f"Profile: {profile}")
    click.echo(f"Base URL: {config.base_url}")
    click.echo(
        f"API Key: {'***' + config.api_key[-4:] if config.api_key else 'Not set'}"
    )
    click.echo(f"OAuth Token: {'Set' if config.oauth_token else 'Not set'}")

    if config.api_key or config.oauth_token:
        try:
            client = Client(
                base_url=config.base_url,
                api_key=config.api_key,
                oauth_token=config.oauth_token,
            )
            user = client.me()
            client.close()
            click.echo(f"User: {user.email} ({user.role})")
            click.echo("Status: ✓ Authenticated")
        except AuthenticationError:
            click.echo("Status: ✗ Authentication failed", err=True)
    else:
        click.echo("Status: Not authenticated")


@auth.command("logout")
@click.option("--profile", default="default", help="Profile to logout")
def auth_logout(profile: str):
    """Remove saved credentials."""
    # Clear credentials
    save_credentials(api_key="", oauth_token="", profile=profile)
    click.echo(f"✓ Logged out from profile '{profile}'")


# ============================================================================
# Job Commands
# ============================================================================


@main.command("run")
@click.argument("script", type=click.Path(exists=True))
@click.option("--name", "-n", help="Job name")
@click.option("--gpu", "-g", type=float, default=0.0, help="GPU fraction (0.0-1.0)")
@click.option("--cpu", "-c", type=int, default=2, help="CPU cores")
@click.option("--memory", "-m", type=int, default=8, help="Memory in GB")
@click.option("--timeout", "-t", type=int, default=2, help="Timeout in hours")
@click.option("--profile", default="default", help="Credentials profile")
@click.option("--key", "-k", envvar="SHML_API_KEY", help="API key")
@click.option("--impersonate", "-i", help="Service account to impersonate")
@click.option("--wait", "-w", is_flag=True, help="Wait for job to complete")
def run(
    script: str,
    name: Optional[str],
    gpu: float,
    cpu: int,
    memory: int,
    timeout: int,
    profile: str,
    key: Optional[str],
    impersonate: Optional[str],
    wait: bool,
):
    """
    Submit a job from a Python script.

    Example:
        shml run train.py --gpu 0.5
    """
    # Read script
    script_path = Path(script)
    with open(script_path) as f:
        code = f.read()

    # Default name from filename
    if not name:
        name = f"{script_path.stem}-{datetime.now().strftime('%H%M%S')}"

    # Get client
    config = get_config(api_key=key, profile=profile)
    client = Client(
        base_url=config.base_url,
        api_key=config.api_key,
        oauth_token=config.oauth_token,
    )

    try:
        # Impersonate if requested
        if impersonate:
            client = client.impersonate(impersonate)

        # Submit job
        job = client.submit(
            code=code,
            name=name,
            gpu=gpu,
            cpu=cpu,
            memory_gb=memory,
            timeout_hours=timeout,
        )

        click.echo(f"✓ Job submitted: {job.job_id}")
        click.echo(f"  Name: {job.name}")
        click.echo(f"  Status: {job.status}")

        if wait:
            click.echo()
            click.echo("Waiting for job to complete...")

            import time

            terminal_states = {"SUCCEEDED", "FAILED", "STOPPED", "CANCELLED"}

            while True:
                status = client.status(job.job_id)
                click.echo(f"  Status: {status.status}", nl=False)

                if status.status in terminal_states:
                    click.echo()
                    break

                click.echo(" (waiting...)", nl=False)
                click.echo("\r", nl=False)
                time.sleep(5)

            click.echo()
            if status.status == "SUCCEEDED":
                click.echo("✓ Job completed successfully")
            else:
                click.echo(f"✗ Job ended with status: {status.status}", err=True)
                if status.error_message:
                    click.echo(f"  Error: {status.error_message}", err=True)

    except SHMLError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        client.close()


@main.command("status")
@click.argument("job_id")
@click.option("--profile", default="default", help="Credentials profile")
@click.option("--key", "-k", envvar="SHML_API_KEY", help="API key")
def status(job_id: str, profile: str, key: Optional[str]):
    """Get job status."""
    config = get_config(api_key=key, profile=profile)

    try:
        with Client(
            base_url=config.base_url,
            api_key=config.api_key,
            oauth_token=config.oauth_token,
        ) as client:
            job = client.status(job_id)

            click.echo(f"Job: {job.job_id}")
            click.echo(f"Name: {job.name}")
            click.echo(f"Status: {job.status}")
            click.echo(f"Created: {job.created_at}")

            if job.started_at:
                click.echo(f"Started: {job.started_at}")
            if job.ended_at:
                click.echo(f"Ended: {job.ended_at}")

            click.echo(
                f"Resources: {job.cpu_requested} CPU, {job.memory_gb_requested}GB RAM, {job.gpu_requested} GPU"
            )

            if job.error_message:
                click.echo(f"Error: {job.error_message}", err=True)

    except SHMLError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command("logs")
@click.argument("job_id")
@click.option("--profile", default="default", help="Credentials profile")
@click.option("--key", "-k", envvar="SHML_API_KEY", help="API key")
@click.option("--follow", "-f", is_flag=True, help="Follow logs (not implemented)")
def logs(job_id: str, profile: str, key: Optional[str], follow: bool):
    """Get job logs."""
    config = get_config(api_key=key, profile=profile)

    try:
        with Client(
            base_url=config.base_url,
            api_key=config.api_key,
            oauth_token=config.oauth_token,
        ) as client:
            log_content = client.logs(job_id)
            click.echo(log_content)

    except SHMLError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command("cancel")
@click.argument("job_id")
@click.option("--reason", "-r", help="Cancellation reason")
@click.option("--profile", default="default", help="Credentials profile")
@click.option("--key", "-k", envvar="SHML_API_KEY", help="API key")
def cancel(job_id: str, reason: Optional[str], profile: str, key: Optional[str]):
    """Cancel a running job."""
    config = get_config(api_key=key, profile=profile)

    try:
        with Client(
            base_url=config.base_url,
            api_key=config.api_key,
            oauth_token=config.oauth_token,
        ) as client:
            job = client.cancel(job_id, reason=reason)
            click.echo(f"✓ Job {job_id} cancelled")
            click.echo(f"  Status: {job.status}")

    except SHMLError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command("list")
@click.option("--status", "-s", help="Filter by status")
@click.option("--limit", "-l", type=int, default=20, help="Number of jobs to show")
@click.option("--profile", default="default", help="Credentials profile")
@click.option("--key", "-k", envvar="SHML_API_KEY", help="API key")
def list_jobs(status: Optional[str], limit: int, profile: str, key: Optional[str]):
    """List jobs."""
    config = get_config(api_key=key, profile=profile)

    try:
        with Client(
            base_url=config.base_url,
            api_key=config.api_key,
            oauth_token=config.oauth_token,
        ) as client:
            jobs = client.list_jobs(page_size=limit, status=status)

            if not jobs:
                click.echo("No jobs found.")
                return

            # Table header
            click.echo(f"{'JOB ID':<20} {'NAME':<25} {'STATUS':<12} {'CREATED':<20}")
            click.echo("-" * 80)

            for job in jobs:
                created = job.created_at.strftime("%Y-%m-%d %H:%M")
                click.echo(
                    f"{job.job_id:<20} {job.name[:24]:<25} {job.status:<12} {created:<20}"
                )

    except SHMLError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# ============================================================================
# API Key Commands
# ============================================================================


@main.group()
def keys():
    """API key management commands."""
    pass


@keys.command("list")
@click.option("--profile", default="default", help="Credentials profile")
def keys_list(profile: str):
    """List your API keys."""
    config = get_config(profile=profile)

    try:
        with Client(
            base_url=config.base_url,
            api_key=config.api_key,
            oauth_token=config.oauth_token,
        ) as client:
            api_keys = client.list_api_keys()

            if not api_keys:
                click.echo("No API keys found.")
                click.echo("Create one with: shml keys create <name>")
                return

            click.echo(f"{'NAME':<20} {'PREFIX':<15} {'CREATED':<20} {'EXPIRES':<20}")
            click.echo("-" * 80)

            for key in api_keys:
                created = key.created_at.strftime("%Y-%m-%d %H:%M")
                expires = (
                    key.expires_at.strftime("%Y-%m-%d %H:%M")
                    if key.expires_at
                    else "Never"
                )
                revoked = " (revoked)" if key.revoked_at else ""
                click.echo(
                    f"{key.name:<20} {key.key_prefix:<15} {created:<20} {expires:<20}{revoked}"
                )

    except SHMLError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@keys.command("create")
@click.argument("name")
@click.option("--expires", "-e", type=int, help="Days until expiration")
@click.option("--description", "-d", help="Key description")
@click.option("--profile", default="default", help="Credentials profile")
def keys_create(
    name: str, expires: Optional[int], description: Optional[str], profile: str
):
    """Create a new API key."""
    config = get_config(profile=profile)

    try:
        with Client(
            base_url=config.base_url,
            api_key=config.api_key,
            oauth_token=config.oauth_token,
        ) as client:
            key = client.create_api_key(
                name=name,
                expires_in_days=expires,
                description=description,
            )

            click.echo("✓ API key created")
            click.echo()
            click.echo("=" * 60)
            click.echo(f"  Key: {key.key}")
            click.echo("=" * 60)
            click.echo()
            click.echo("⚠️  SAVE THIS KEY NOW - it cannot be retrieved again!")
            click.echo()
            click.echo(f"Name: {key.name}")
            click.echo(f"Expires: {key.expires_at or 'Never'}")

    except SHMLError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@keys.command("rotate")
@click.argument("key_id")
@click.option("--profile", default="default", help="Credentials profile")
def keys_rotate(key_id: str, profile: str):
    """Rotate an API key (24h grace period)."""
    config = get_config(profile=profile)

    try:
        with Client(
            base_url=config.base_url,
            api_key=config.api_key,
            oauth_token=config.oauth_token,
        ) as client:
            result = client.rotate_api_key(key_id)

            click.echo("✓ API key rotated")
            click.echo()
            click.echo("=" * 60)
            click.echo(f"  New Key: {result['new_key']}")
            click.echo("=" * 60)
            click.echo()
            click.echo(f"Old key valid until: {result['old_key_valid_until']}")
            click.echo()
            click.echo("⚠️  SAVE THIS KEY NOW - it cannot be retrieved again!")

    except SHMLError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@keys.command("revoke")
@click.argument("key_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.option("--profile", default="default", help="Credentials profile")
def keys_revoke(key_id: str, yes: bool, profile: str):
    """Revoke an API key immediately."""
    if not yes:
        click.confirm(f"Revoke API key {key_id}? This cannot be undone.", abort=True)

    config = get_config(profile=profile)

    try:
        with Client(
            base_url=config.base_url,
            api_key=config.api_key,
            oauth_token=config.oauth_token,
        ) as client:
            client.revoke_api_key(key_id)
            click.echo(f"✓ API key {key_id} revoked")

    except SHMLError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
