#!/usr/bin/env python3
"""
SHML Training CLI
License: Apache 2.0

Command-line interface for SHML Training Platform.
"""

import sys
import json
import argparse
from typing import Optional
from pathlib import Path

from shml_training.sdk import (
    TrainingClient,
    TrainingConfig,
    save_credentials,
    QuotaError,
    AuthError,
    APIError,
)


def cmd_setup(args):
    """Setup credentials"""
    api_url = (
        args.api_url
        or input("API URL [http://localhost]: ").strip()
        or "http://localhost"
    )
    api_key = args.api_key or input("API Key: ").strip()

    if not api_key:
        print("Error: API key required")
        sys.exit(1)

    save_credentials(api_url, api_key)
    print(f"✓ Credentials saved to ~/.shml/credentials")


def cmd_submit(args):
    """Submit training job"""
    client = TrainingClient.from_credentials()

    # Load config from file if provided
    if args.config_file:
        with open(args.config_file) as f:
            config_data = json.load(f)

        config = TrainingConfig(**config_data)
    else:
        # Build from CLI arguments
        config = TrainingConfig(
            name=args.name,
            model=args.model,
            dataset=args.dataset,
            dataset_url=args.dataset_url,
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.learning_rate,
            use_sapo=args.use_sapo,
            use_advantage_filter=args.use_advantage_filter,
            use_curriculum_learning=args.use_curriculum_learning,
            gpu_fraction=args.gpu_fraction,
            cpu_cores=args.cpu_cores,
            mlflow_experiment=args.mlflow_experiment,
        )

    try:
        job_id = client.submit_training(config)
        print(f"✓ Job submitted: {job_id}")

        if args.wait:
            print("Waiting for completion...")
            status = client.wait_for_completion(job_id, verbose=True)

            if status.is_successful():
                print(f"✓ Training completed successfully!")
                if status.mlflow_run_id:
                    print(f"MLflow run: {status.mlflow_run_id}")
            else:
                print(f"✗ Training failed: {status.error}")
                sys.exit(1)

    except QuotaError as e:
        print(f"✗ Quota exceeded: {e}")
        sys.exit(1)
    except AuthError as e:
        print(f"✗ Authentication error: {e}")
        sys.exit(1)
    except APIError as e:
        print(f"✗ API error: {e}")
        sys.exit(1)


def cmd_status(args):
    """Get job status"""
    client = TrainingClient.from_credentials()

    try:
        status = client.get_job_status(args.job_id)

        print(f"Job: {status.job_id}")
        print(f"Name: {status.name}")
        print(f"Status: {status.status}")
        print(f"Created: {status.created_at}")

        if status.started_at:
            print(f"Started: {status.started_at}")

        if status.ended_at:
            print(f"Ended: {status.ended_at}")

        if status.duration_seconds:
            print(f"Duration: {status.duration_seconds/3600:.2f} hours")

        if status.current_epoch and status.total_epochs:
            print(
                f"Progress: {status.current_epoch}/{status.total_epochs} epochs ({status.progress_percent:.1f}%)"
            )

        if status.latest_metrics:
            print(f"Latest metrics:")
            for key, value in status.latest_metrics.items():
                print(f"  {key}: {value}")

        if status.mlflow_run_id:
            print(f"MLflow run: {status.mlflow_run_id}")

        if status.gpu_hours_used:
            print(f"GPU hours: {status.gpu_hours_used:.2f}")

        if status.error:
            print(f"Error: {status.error}")

        # Output JSON if requested
        if args.json:
            import json
            from dataclasses import asdict

            print("\n" + json.dumps(asdict(status), indent=2))

    except APIError as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


def cmd_logs(args):
    """Get job logs"""
    client = TrainingClient.from_credentials()

    try:
        logs = client.get_job_logs(args.job_id, tail=args.tail)
        print(logs)
    except APIError as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


def cmd_cancel(args):
    """Cancel job"""
    client = TrainingClient.from_credentials()

    try:
        client.cancel_job(args.job_id)
        print(f"✓ Job cancelled: {args.job_id}")
    except APIError as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


def cmd_quota(args):
    """Check quota"""
    client = TrainingClient.from_credentials()

    try:
        quota = client.get_quota(period=args.period)

        print(f"Tier: {quota.tier_name}")
        print(f"Period: {quota.period}")
        print(f"\nGPU Hours:")
        print(f"  Used: {quota.gpu_used:.2f}")
        print(f"  Limit: {quota.gpu_limit:.2f}")
        print(f"  Remaining: {quota.gpu_remaining:.2f}")
        print(f"\nCPU Hours:")
        print(f"  Used: {quota.cpu_used:.2f}")
        print(f"  Limit: {quota.cpu_limit:.2f}")
        print(f"  Remaining: {quota.cpu_remaining:.2f}")
        print(f"\nConcurrent Jobs:")
        print(f"  Current: {quota.concurrent_jobs}")
        print(f"  Limit: {quota.concurrent_jobs_limit}")
        print(f"\nOverall Usage: {quota.percent_used:.1f}%")

    except APIError as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


def cmd_queue(args):
    """Check queue status"""
    client = TrainingClient.from_credentials()

    try:
        if args.job_id:
            # Specific job queue status
            queue_status = client.get_queue_status(args.job_id)

            print(f"Job: {queue_status.job_id}")
            print(f"Status: {queue_status.status}")
            print(f"Priority: {queue_status.priority_score}")
            print(f"Position: {queue_status.queue_position or 'Running'}")
            print(f"Queued at: {queue_status.queued_at}")

            if queue_status.estimated_start_time:
                print(f"Estimated start: {queue_status.estimated_start_time}")
        else:
            # Overall queue overview
            overview = client.get_queue_overview()

            print(f"Total Queued: {overview['total_queued']}")
            print(f"Total Running: {overview['total_running']}")

            if overview.get("queue"):
                print("\nQueue:")
                for i, job in enumerate(overview["queue"][:10], 1):
                    print(
                        f"  {i}. {job['job_id']} ({job['user_tier']}) - Priority: {job['priority_score']}"
                    )

    except APIError as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


def cmd_models(args):
    """List available models"""
    client = TrainingClient.from_credentials()

    try:
        models = client.list_models()

        print("Available Models:")
        for model in models:
            print(f"\n{model['name']}")
            print(f"  Description: {model['description']}")
            print(f"  Parameters: {model.get('params', 'N/A')}")
            print(f"  Speed: {model.get('speed', 'N/A')}")

    except APIError as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


def cmd_techniques(args):
    """List available techniques"""
    client = TrainingClient.from_credentials()

    try:
        techniques = client.list_techniques()

        print("Available Techniques:")
        for tech in techniques:
            print(f"\n{tech['name']} ({tech['tier']} tier)")
            print(f"  Description: {tech['description']}")
            print(f"  License: {tech['license']}")

    except APIError as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


def cmd_tiers(args):
    """List subscription tiers"""
    client = TrainingClient.from_credentials()

    try:
        tiers = client.list_tiers()

        print("Subscription Tiers:")
        for tier in tiers:
            print(f"\n{tier['name']} - ${tier['price_monthly']}/month")
            print(
                f"  GPU Hours: {tier['limits']['gpu_hours_daily']}/day, {tier['limits']['gpu_hours_monthly']}/month"
            )
            print(
                f"  CPU Hours: {tier['limits']['cpu_hours_daily']}/day, {tier['limits']['cpu_hours_monthly']}/month"
            )
            print(f"  Concurrent Jobs: {tier['limits']['concurrent_jobs']}")

            if tier.get("features"):
                print(f"  Features: {', '.join(tier['features'])}")

    except APIError as e:
        print(f"✗ Error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="SHML Training CLI - Remote training via SHML Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Setup command
    setup_parser = subparsers.add_parser("setup", help="Setup credentials")
    setup_parser.add_argument("--api-url", help="API URL")
    setup_parser.add_argument("--api-key", help="API key")
    setup_parser.set_defaults(func=cmd_setup)

    # Submit command
    submit_parser = subparsers.add_parser("submit", help="Submit training job")
    submit_parser.add_argument("--config-file", help="Config JSON file")
    submit_parser.add_argument("--name", required=True, help="Job name")
    submit_parser.add_argument("--model", default="yolov8l", help="Model architecture")
    submit_parser.add_argument("--dataset", default="wider_face", help="Dataset name")
    submit_parser.add_argument("--dataset-url", help="Custom dataset URL")
    submit_parser.add_argument(
        "--epochs", type=int, default=100, help="Number of epochs"
    )
    submit_parser.add_argument("--batch-size", type=int, default=16, help="Batch size")
    submit_parser.add_argument(
        "--learning-rate", type=float, default=0.01, help="Learning rate"
    )
    submit_parser.add_argument(
        "--use-sapo", action="store_true", help="Enable SAPO technique"
    )
    submit_parser.add_argument(
        "--use-advantage-filter", action="store_true", help="Enable Advantage Filter"
    )
    submit_parser.add_argument(
        "--use-curriculum-learning",
        action="store_true",
        help="Enable Curriculum Learning",
    )
    submit_parser.add_argument(
        "--gpu-fraction", type=float, default=0.25, help="GPU fraction"
    )
    submit_parser.add_argument("--cpu-cores", type=int, default=4, help="CPU cores")
    submit_parser.add_argument("--mlflow-experiment", help="MLflow experiment name")
    submit_parser.add_argument(
        "--wait", action="store_true", help="Wait for completion"
    )
    submit_parser.set_defaults(func=cmd_submit)

    # Status command
    status_parser = subparsers.add_parser("status", help="Get job status")
    status_parser.add_argument("job_id", help="Job ID")
    status_parser.add_argument("--json", action="store_true", help="Output JSON")
    status_parser.set_defaults(func=cmd_status)

    # Logs command
    logs_parser = subparsers.add_parser("logs", help="Get job logs")
    logs_parser.add_argument("job_id", help="Job ID")
    logs_parser.add_argument("--tail", type=int, default=100, help="Number of lines")
    logs_parser.set_defaults(func=cmd_logs)

    # Cancel command
    cancel_parser = subparsers.add_parser("cancel", help="Cancel job")
    cancel_parser.add_argument("job_id", help="Job ID")
    cancel_parser.set_defaults(func=cmd_cancel)

    # Quota command
    quota_parser = subparsers.add_parser("quota", help="Check quota")
    quota_parser.add_argument(
        "--period", choices=["day", "month"], default="day", help="Period"
    )
    quota_parser.set_defaults(func=cmd_quota)

    # Queue command
    queue_parser = subparsers.add_parser("queue", help="Check queue")
    queue_parser.add_argument("job_id", nargs="?", help="Job ID (optional)")
    queue_parser.set_defaults(func=cmd_queue)

    # Models command
    models_parser = subparsers.add_parser("models", help="List models")
    models_parser.set_defaults(func=cmd_models)

    # Techniques command
    techniques_parser = subparsers.add_parser("techniques", help="List techniques")
    techniques_parser.set_defaults(func=cmd_techniques)

    # Tiers command
    tiers_parser = subparsers.add_parser("tiers", help="List subscription tiers")
    tiers_parser.set_defaults(func=cmd_tiers)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
