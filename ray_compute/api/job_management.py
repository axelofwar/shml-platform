"""
Job Management API Endpoints
Extended endpoints for job control, download, and cleanup operations
"""

import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from ray.job_submission import JobSubmissionClient, JobStatus

from .auth import get_current_user, require_role
from .database import get_db
from .models import User, Job as JobModel

# Initialize router
router = APIRouter(prefix="/jobs", tags=["jobs"])

# Ray client
RAY_ADDRESS = os.getenv("RAY_DASHBOARD_ADDRESS", "http://ray-head:8265")
job_client = JobSubmissionClient(RAY_ADDRESS)


def check_job_ownership(job_id: str, current_user: User, db: Session):
    """
    Check if user owns the job or is an admin
    Raises HTTPException if unauthorized
    """
    job = db.query(JobModel).filter(JobModel.job_id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Admins can access all jobs
    if current_user.role == "admin":
        return job

    # Users can only access their own jobs
    if str(job.user_id) != str(current_user.user_id):
        raise HTTPException(
            status_code=403, detail="You don't have permission to access this job"
        )

    return job


@router.post("/{job_id}/restart")
async def restart_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Restart a job by submitting a new job with the same configuration
    Returns the new job ID
    """
    job = check_job_ownership(job_id, current_user, db)

    try:
        # Get original job info
        job_status = job_client.get_job_status(job_id)
        job_info = job_client.get_job_info(job_id)

        # Extract job submission parameters from metadata
        # This requires job metadata to include submission parameters
        if not job.metadata or "submission_params" not in job.metadata:
            raise HTTPException(
                status_code=400,
                detail="Job cannot be restarted: missing submission parameters in metadata",
            )

        submission_params = job.metadata["submission_params"]

        # Submit new job with same parameters
        new_job_id = job_client.submit_job(
            entrypoint=submission_params.get("entrypoint"),
            runtime_env=submission_params.get("runtime_env"),
            metadata={
                **submission_params.get("metadata", {}),
                "restarted_from": job_id,
                "restart_reason": "manual_restart",
            },
        )

        # Create database entry for new job
        new_job = JobModel(
            job_id=new_job_id,
            ray_job_id=new_job_id,
            user_id=current_user.user_id,
            name=f"{job.name} (Restarted)",
            status="PENDING",
            metadata={
                **job.metadata,
                "restarted_from": job_id,
            },
        )
        db.add(new_job)
        db.commit()

        return {
            "job_id": job_id,
            "new_job_id": new_job_id,
            "status": "restarted",
            "message": f"Job restarted as {new_job_id}",
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to restart job: {str(e)}")


@router.post("/{job_id}/start")
async def start_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Resume a stopped job
    Note: Ray doesn't natively support pause/resume, so this will restart the job
    """
    job = check_job_ownership(job_id, current_user, db)

    try:
        status = job_client.get_job_status(job_id)

        if status not in [JobStatus.STOPPED, JobStatus.FAILED]:
            raise HTTPException(
                status_code=400,
                detail=f"Job cannot be started: current status is {status}",
            )

        # Since Ray doesn't support resume, we restart the job
        return await restart_job(job_id, current_user, db)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start job: {str(e)}")


@router.delete("/{job_id}")
async def delete_job_with_cleanup(
    job_id: str,
    cleanup: bool = Query(
        True, description="Clean up workspace, logs, and checkpoints"
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Delete a job and optionally clean up all associated resources:
    - Workspace files
    - Ray logs
    - Checkpoints
    - Job metadata

    MLflow data is preserved for audit purposes.
    """
    job = check_job_ownership(job_id, current_user, db)

    try:
        # Check job status - must be stopped/completed
        status = job_client.get_job_status(job_id)
        if status not in [JobStatus.STOPPED, JobStatus.SUCCEEDED, JobStatus.FAILED]:
            raise HTTPException(
                status_code=400,
                detail=f"Job must be stopped before deletion. Current status: {status}",
            )

        cleanup_results = {}

        if cleanup:
            # Clean up workspace files
            if job.metadata and "workspace_dir" in job.metadata:
                workspace_dir = Path(job.metadata["workspace_dir"])
                if workspace_dir.exists():
                    shutil.rmtree(workspace_dir)
                    cleanup_results["workspace"] = "deleted"

            # Clean up checkpoints
            if job.metadata and "checkpoint_dir" in job.metadata:
                checkpoint_dir = Path(job.metadata["checkpoint_dir"])
                if checkpoint_dir.exists():
                    shutil.rmtree(checkpoint_dir)
                    cleanup_results["checkpoints"] = "deleted"

            # Clean up Ray logs
            # Ray logs are in /tmp/ray/session_*/logs/
            import glob

            log_pattern = f"/tmp/ray/session_*/logs/*{job_id}*"
            for log_file in glob.glob(log_pattern):
                try:
                    os.remove(log_file)
                except Exception:
                    pass
            cleanup_results["logs"] = "cleaned"

        # Delete from Ray
        job_client.delete_job(job_id)

        # Delete from database
        db.delete(job)
        db.commit()

        return {
            "job_id": job_id,
            "status": "deleted",
            "cleanup": cleanup_results if cleanup else "skipped",
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete job: {str(e)}")


@router.get("/{job_id}/download")
async def download_job(
    job_id: str,
    workspace: bool = Query(True, description="Include workspace files"),
    logs: bool = Query(True, description="Include Ray logs"),
    checkpoints: bool = Query(True, description="Include checkpoints"),
    mlflow: bool = Query(False, description="Include MLflow artifacts"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Download job artifacts as a tar.gz archive
    Users can select which components to include
    """
    job = check_job_ownership(job_id, current_user, db)

    if not any([workspace, logs, checkpoints, mlflow]):
        raise HTTPException(
            status_code=400,
            detail="At least one component must be selected for download",
        )

    try:
        # Create temporary directory for archive - use mkdtemp for manual cleanup
        temp_dir = tempfile.mkdtemp()
        archive_path = Path(temp_dir) / f"{job_id}_artifacts.tar.gz"

        try:
            with tarfile.open(archive_path, "w:gz") as tar:
                files_added = False

                # Add workspace files
                if workspace and job.metadata and "workspace_dir" in job.metadata:
                    workspace_dir = Path(job.metadata["workspace_dir"])
                    if workspace_dir.exists():
                        tar.add(workspace_dir, arcname="workspace")
                        files_added = True

                # Add checkpoints
                if checkpoints and job.metadata and "checkpoint_dir" in job.metadata:
                    checkpoint_dir = Path(job.metadata["checkpoint_dir"])
                    if checkpoint_dir.exists():
                        tar.add(checkpoint_dir, arcname="checkpoints")
                        files_added = True

                # Add Ray logs
                if logs:
                    import glob

                    log_patterns = [
                        f"/tmp/ray/session_*/logs/*{job_id}*",
                        f"/tmp/ray/session_latest/logs/job-driver-{job_id}*",
                    ]
                    log_dir = Path(temp_dir) / "logs"
                    log_dir.mkdir(exist_ok=True)

                    for pattern in log_patterns:
                        for log_file in glob.glob(pattern):
                            log_path = Path(log_file)
                            if log_path.exists() and log_path.is_file():
                                shutil.copy(log_path, log_dir / log_path.name)

                    if log_dir.exists() and any(log_dir.iterdir()):
                        tar.add(log_dir, arcname="logs")
                        files_added = True

                # Add MLflow artifacts
                if mlflow and hasattr(job, "mlflow_run_id") and job.mlflow_run_id:
                    mlflow_dir = Path(
                        os.getenv("MLFLOW_ARTIFACT_ROOT", "/mlflow/artifacts")
                    )
                    experiment_id = getattr(job, "mlflow_experiment_id", None) or "0"
                    run_dir = (
                        mlflow_dir / experiment_id / job.mlflow_run_id / "artifacts"
                    )

                    if run_dir.exists():
                        tar.add(run_dir, arcname="mlflow_artifacts")
                        files_added = True

                # Add a README if no files were found
                if not files_added:
                    readme_path = Path(temp_dir) / "README.txt"
                    readme_path.write_text(
                        f"Job: {job_id}\n"
                        f"Name: {job.name}\n"
                        f"Status: {job.status}\n\n"
                        "No artifact files were found for this job.\n"
                        "This may happen if:\n"
                        "- The job did not create any output files\n"
                        "- The job workspace was already cleaned up\n"
                        "- Log files have been rotated\n"
                    )
                    tar.add(readme_path, arcname="README.txt")

            # Read the entire archive into memory for streaming
            # This allows us to clean up the temp dir immediately
            with open(archive_path, "rb") as f:
                archive_data = f.read()

            # Clean up temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)

            # Stream from memory
            from io import BytesIO

            return StreamingResponse(
                iter([archive_data]),
                media_type="application/gzip",
                headers={
                    "Content-Disposition": f'attachment; filename="{job.name}_{job_id}_artifacts.tar.gz"',
                    "Content-Length": str(len(archive_data)),
                },
            )

        except Exception as e:
            # Clean up on error
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to create download: {str(e)}"
        )
