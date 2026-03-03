"""
SHML Training SDK - Usage Examples
License: Apache 2.0

Complete examples for using the Python SDK.
"""

from shml_training.sdk import (
    TrainingClient,
    TrainingConfig,
    save_credentials,
    QuotaError,
    JobError,
)
import time
import os


# ==================== Setup ====================


def example_setup():
    """Setup credentials for first-time use"""

    # Option 1: Save credentials to file
    save_credentials(api_url="https://api.shml.ai", api_key="your-api-key-here")

    # Option 2: Load from file
    client = TrainingClient.from_credentials()

    # Option 3: Direct initialization
    client = TrainingClient(
        api_url="https://api.shml.ai", api_key=os.environ["SHML_API_KEY"]
    )

    return client


# ==================== Basic Training ====================


def example_basic_training():
    """Submit a basic training job"""

    client = TrainingClient.from_credentials()

    # Create training configuration
    config = TrainingConfig(
        name="face-detection-basic",
        model="yolov8l",
        dataset="wider_face",
        epochs=100,
        batch_size=16,
        learning_rate=0.01,
    )

    # Submit job
    job_id = client.submit_training(config)
    print(f"Job submitted: {job_id}")

    # Wait for completion with progress updates
    final_status = client.wait_for_completion(job_id, verbose=True)

    if final_status.is_successful():
        print(f"✓ Training completed successfully!")
        print(f"MLflow run: {final_status.mlflow_run_id}")
        print(f"Final metrics: {final_status.latest_metrics}")
    else:
        print(f"✗ Training failed: {final_status.error}")


# ==================== Advanced Training (Pro Features) ====================


def example_advanced_training():
    """Submit training with proprietary techniques (Pro/Enterprise)"""

    client = TrainingClient.from_credentials()

    config = TrainingConfig(
        name="face-detection-advanced",
        model="yolov8x",  # Largest model
        dataset="wider_face",
        epochs=200,
        # Use all proprietary techniques
        use_sapo=True,  # Pro tier
        use_advantage_filter=True,  # Pro tier
        use_curriculum_learning=True,  # Enterprise tier
        # Higher compute resources
        gpu_fraction=1.0,  # Full GPU
        cpu_cores=8,
        memory_gb=16,
        # Custom hyperparameters
        learning_rate=0.001,
        batch_size=32,
        optimizer="AdamW",
        # MLflow integration
        mlflow_experiment="production-face-detection",
        mlflow_tags={
            "team": "vision",
            "project": "face-recognition",
            "version": "v2.0",
        },
    )

    job_id = client.submit_training(config)

    # Monitor with custom polling
    print(f"Job submitted: {job_id}")

    while True:
        status = client.get_job_status(job_id)

        print(f"Status: {status.status}")
        print(f"Progress: {status.progress_percent}%")
        print(f"Epoch: {status.current_epoch}/{status.total_epochs}")

        if status.latest_metrics:
            print(f"Metrics: {status.latest_metrics}")

        if status.is_complete():
            break

        time.sleep(15)

    return status


# ==================== Batch Training ====================


def example_batch_training():
    """Submit multiple training jobs"""

    client = TrainingClient.from_credentials()

    # Different model sizes
    models = ["yolov8n", "yolov8s", "yolov8m", "yolov8l", "yolov8x"]

    jobs = {}

    for model in models:
        config = TrainingConfig(
            name=f"face-detection-{model}",
            model=model,
            dataset="wider_face",
            epochs=100,
            use_curriculum_learning=True,
        )

        try:
            job_id = client.submit_training(config)
            jobs[model] = job_id
            print(f"Submitted {model}: {job_id}")
        except QuotaError as e:
            print(f"Quota exceeded for {model}: {e}")
            break

    # Monitor all jobs
    while jobs:
        for model, job_id in list(jobs.items()):
            status = client.get_job_status(job_id)

            if status.is_complete():
                print(f"✓ {model} completed: {status.status}")
                del jobs[model]

        if jobs:
            print(f"Still running: {list(jobs.keys())}")
            time.sleep(30)


# ==================== Queue Management ====================


def example_queue_monitoring():
    """Monitor queue position and ETA"""

    client = TrainingClient.from_credentials()

    # Submit job
    config = TrainingConfig(
        name="face-detection-queue",
        model="yolov8l",
        dataset="wider_face",
        epochs=100,
    )

    job_id = client.submit_training(config)

    # Check queue status
    queue_status = client.get_queue_status(job_id)

    print(f"Queue position: {queue_status.queue_position}")
    print(f"Priority score: {queue_status.priority_score}")
    print(f"Estimated start: {queue_status.estimated_start_time}")

    # Get overall queue overview
    overview = client.get_queue_overview()

    print(f"Total queued: {overview['total_queued']}")
    print(f"Total running: {overview['total_running']}")


# ==================== Quota Management ====================


def example_quota_management():
    """Check and manage quota"""

    client = TrainingClient.from_credentials()

    # Check daily quota
    daily = client.get_quota(period="day")

    print(f"Tier: {daily.tier_name}")
    print(
        f"GPU usage: {daily.gpu_used:.2f}/{daily.gpu_limit:.2f} hours ({daily.gpu_remaining:.2f} remaining)"
    )
    print(
        f"CPU usage: {daily.cpu_used:.2f}/{daily.cpu_limit:.2f} hours ({daily.cpu_remaining:.2f} remaining)"
    )
    print(f"Concurrent jobs: {daily.concurrent_jobs}/{daily.concurrent_jobs_limit}")
    print(f"Usage: {daily.percent_used:.1f}%")

    # Check monthly quota
    monthly = client.get_quota(period="month")

    print(f"\nMonthly GPU usage: {monthly.gpu_used:.2f}/{monthly.gpu_limit:.2f} hours")

    # Submit job with quota check
    if daily.gpu_remaining > 1.0:
        config = TrainingConfig(
            name="face-detection-checked",
            model="yolov8l",
            dataset="wider_face",
            epochs=50,
        )

        try:
            job_id = client.submit_training(config)
            print(f"Job submitted: {job_id}")
        except QuotaError as e:
            print(f"Quota exceeded: {e}")
    else:
        print("Insufficient quota remaining")


# ==================== Error Handling ====================


def example_error_handling():
    """Robust error handling"""

    client = TrainingClient.from_credentials()

    config = TrainingConfig(
        name="face-detection-robust",
        model="yolov8l",
        dataset="wider_face",
        epochs=100,
        use_curriculum_learning=True,
    )

    try:
        # Submit job
        job_id = client.submit_training(config)
        print(f"Job submitted: {job_id}")

        # Wait for completion
        status = client.wait_for_completion(job_id, poll_interval=10)

        if status.is_successful():
            print("✓ Training completed!")
            return status.mlflow_run_id
        else:
            print(f"✗ Training failed: {status.error}")
            return None

    except QuotaError as e:
        print(f"Quota exceeded: {e}")
        print("Please upgrade your plan or wait for quota reset")
        return None

    except JobError as e:
        print(f"Job execution error: {e}")
        return None

    except Exception as e:
        print(f"Unexpected error: {e}")
        return None


# ==================== Custom Dataset ====================


def example_custom_dataset():
    """Train with custom dataset from GCS/S3"""

    client = TrainingClient.from_credentials()

    # Option 1: GCS bucket
    config_gcs = TrainingConfig(
        name="face-detection-custom-gcs",
        model="yolov8l",
        dataset="custom_gcs",
        dataset_url="gs://my-bucket/datasets/faces/",
        epochs=100,
    )

    # Option 2: S3 bucket
    config_s3 = TrainingConfig(
        name="face-detection-custom-s3",
        model="yolov8l",
        dataset="custom_s3",
        dataset_url="s3://my-bucket/datasets/faces/",
        epochs=100,
    )

    # Option 3: HTTP URL
    config_http = TrainingConfig(
        name="face-detection-custom-http",
        model="yolov8l",
        dataset="custom_http",
        dataset_url="https://storage.example.com/faces.zip",
        epochs=100,
    )

    job_id = client.submit_training(config_gcs)
    print(f"Job submitted with custom dataset: {job_id}")


# ==================== Quick Training ====================


def example_quick_training():
    """Quick training with one-liner convenience method"""

    client = TrainingClient.from_credentials()

    # Submit and get job_id immediately
    job_id = client.quick_train(
        name="quick-test",
        model="yolov8m",
        epochs=50,
        use_techniques=True,  # Enable all proprietary techniques
    )

    print(f"Quick job submitted: {job_id}")


# ==================== List Resources ====================


def example_list_resources():
    """List available models, techniques, and tiers"""

    client = TrainingClient.from_credentials()

    # List models
    models = client.list_models()
    print("Available models:")
    for model in models:
        print(f"  - {model['name']}: {model['description']}")

    # List techniques
    techniques = client.list_techniques()
    print("\nAvailable techniques:")
    for tech in techniques:
        print(f"  - {tech['name']} ({tech['tier']}): {tech['description']}")

    # List tiers
    tiers = client.list_tiers()
    print("\nSubscription tiers:")
    for tier in tiers:
        print(f"  - {tier['name']} (${tier['price_monthly']}/mo):")
        print(f"    GPU: {tier['limits']['gpu_hours_daily']} hours/day")
        print(f"    Concurrent jobs: {tier['limits']['concurrent_jobs']}")


# ==================== Production Pipeline ====================


def example_production_pipeline():
    """Complete production training pipeline"""

    client = TrainingClient.from_credentials()

    # 1. Check quota
    quota = client.get_quota(period="day")
    if quota.gpu_remaining < 2.0:
        print("Insufficient quota for production training")
        return

    # 2. List queue
    queue_overview = client.get_queue_overview()
    print(
        f"Queue status: {queue_overview['total_queued']} queued, {queue_overview['total_running']} running"
    )

    # 3. Configure training
    config = TrainingConfig(
        name=f"production-{int(time.time())}",
        model="yolov8x",
        dataset="wider_face",
        epochs=200,
        # All proprietary techniques
        use_sapo=True,
        use_advantage_filter=True,
        use_curriculum_learning=True,
        # Full resources
        gpu_fraction=1.0,
        cpu_cores=8,
        memory_gb=16,
        priority="high",
        # MLflow tracking
        mlflow_experiment="production",
        mlflow_tags={
            "environment": "production",
            "version": "2.0",
            "auto_deployed": "true",
        },
    )

    # 4. Submit job
    try:
        job_id = client.submit_training(config)
        print(f"✓ Production job submitted: {job_id}")
    except QuotaError as e:
        print(f"✗ Quota exceeded: {e}")
        return

    # 5. Monitor progress
    final_status = client.wait_for_completion(job_id, poll_interval=30, verbose=True)

    # 6. Post-processing
    if final_status.is_successful():
        print(f"✓ Production training completed!")
        print(f"MLflow run: {final_status.mlflow_run_id}")
        print(f"GPU hours used: {final_status.gpu_hours_used:.2f}")
        print(f"Duration: {final_status.duration_seconds/3600:.2f} hours")

        # Get final metrics
        print(f"Final metrics: {final_status.latest_metrics}")

        return final_status.mlflow_run_id
    else:
        print(f"✗ Production training failed: {final_status.error}")

        # Get logs for debugging
        logs = client.get_job_logs(job_id, tail=100)
        print(f"Last 100 log lines:\n{logs}")

        return None


# ==================== Main ====================

if __name__ == "__main__":
    # Run examples
    print("=== SHML Training SDK Examples ===\n")

    # Uncomment to run specific examples:

    # example_basic_training()
    # example_advanced_training()
    # example_batch_training()
    # example_queue_monitoring()
    # example_quota_management()
    # example_error_handling()
    # example_custom_dataset()
    # example_quick_training()
    # example_list_resources()
    # example_production_pipeline()

    print("\nSee examples.py for complete usage examples")
