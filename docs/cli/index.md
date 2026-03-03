# CLI Overview

The `shml` command-line interface provides unified access to training, GPU management, platform operations, and authentication for the SHML Platform.

## Installation

Install the SDK (which includes the CLI) from the project root:

```bash
pip install -e sdk/
```

Verify the installation:

```bash
shml --help
```

!!! tip "Rich output"
    Install `rich` for colored, tabular output: `pip install rich`. The CLI falls back to plain text if Rich is not available.

## Global Options

| Option            | Description                  |
|-------------------|------------------------------|
| `--help`          | Show help and exit           |
| `--install-completion` | Install shell completion |
| `--show-completion`    | Show shell completion script |

## Command Reference

| Command | Description |
|---------|-------------|
| [`shml train`](train.md) | Submit a training job from a profile or explicit parameters |
| [`shml status <job_id>`](jobs.md#shml-status) | Get job status |
| [`shml logs <job_id>`](jobs.md#shml-logs) | Get job logs |
| [`shml cancel <job_id>`](jobs.md#shml-cancel) | Cancel a running job |
| [`shml list`](jobs.md#shml-list) | List recent jobs |
| [`shml gpu status`](gpu.md#shml-gpu-status) | Show GPU utilization and memory |
| [`shml gpu yield`](gpu.md#shml-gpu-yield) | Yield GPU resources for training |
| [`shml gpu reclaim`](gpu.md#shml-gpu-reclaim) | Reclaim GPU resources |
| [`shml platform status`](gpu.md) | Check health of all platform services |
| [`shml config show`](config-commands.md#shml-config-show) | Show current platform configuration |
| [`shml config list-profiles`](config-commands.md#shml-config-list-profiles) | List available training profiles |
| [`shml config validate`](config-commands.md#shml-config-validate) | Validate a training profile |
| [`shml auth login`](auth.md#shml-auth-login) | Store authentication credentials |
| [`shml auth status`](auth.md#shml-auth-status) | Show current authentication status |
| [`shml auth logout`](auth.md#shml-auth-logout) | Clear stored credentials |

## Quick Start

```bash
# Authenticate
shml auth login --api-key sk-your-key-here

# List available training profiles
shml config list-profiles

# Submit a training job
shml train --profile balanced --epochs 10

# Check job status
shml status <job_id>

# View GPU utilization
shml gpu status
```

!!! info "Environment"
    The CLI reads connection settings from environment variables and `~/.shml/credentials`. See [Authentication](auth.md) for details.
