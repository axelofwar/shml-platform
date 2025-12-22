"""
Log Streaming API Endpoints
Real-time log streaming via WebSocket for job monitoring
"""

import os
import asyncio
import glob
from pathlib import Path
from typing import Optional
from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
    WebSocket,
    WebSocketDisconnect,
    Query,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .auth import get_current_user
from .database import get_db
from .models import User, Job as JobModel

# Initialize router
router = APIRouter(prefix="/logs", tags=["logs"])

# Ray log directory pattern
RAY_LOG_DIR = os.getenv("RAY_LOG_DIR", "/tmp/ray/session_latest/logs")
JOB_LOG_PATTERN = "job-driver-raysubmit_{job_id}.log"


def get_job_log_path(job_id: str) -> Optional[Path]:
    """
    Find the log file for a specific job
    Searches in Ray's session logs directory
    """
    # Try exact match first
    exact_path = Path(RAY_LOG_DIR) / f"job-driver-{job_id}.log"
    if exact_path.exists():
        return exact_path

    # Try with raysubmit prefix
    raysubmit_path = Path(RAY_LOG_DIR) / f"job-driver-raysubmit_{job_id}.log"
    if raysubmit_path.exists():
        return raysubmit_path

    # Search for any matching log file
    pattern = f"{RAY_LOG_DIR}/*{job_id}*.log"
    matches = glob.glob(pattern)
    if matches:
        return Path(matches[0])

    # Try in session subdirectories
    pattern = f"/tmp/ray/session_*/logs/*{job_id}*.log"
    matches = glob.glob(pattern)
    if matches:
        # Return most recent
        return Path(sorted(matches, key=os.path.getmtime, reverse=True)[0])

    return None


def check_job_access(job_id: str, current_user: User, db: Session) -> JobModel:
    """
    Verify user has access to the job
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
            status_code=403,
            detail="You don't have permission to access this job's logs",
        )

    return job


@router.get("/{job_id}")
async def get_job_logs(
    job_id: str,
    tail: int = Query(
        1000, ge=1, le=10000, description="Number of lines to return from end"
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Get job logs (last N lines)
    Returns the most recent log entries for efficient loading
    """
    job = check_job_access(job_id, current_user, db)

    # Try to get logs from Ray job client first
    ray_job_id = job.ray_job_id or job_id

    # Find the log file
    log_path = get_job_log_path(ray_job_id)

    if not log_path or not log_path.exists():
        # Try to get from Ray API
        try:
            from ray.job_submission import JobSubmissionClient

            RAY_ADDRESS = os.getenv("RAY_DASHBOARD_ADDRESS", "http://ray-head:8265")
            job_client = JobSubmissionClient(RAY_ADDRESS)
            logs = job_client.get_job_logs(ray_job_id)

            if logs:
                lines = logs.split("\n")
                if len(lines) > tail:
                    lines = lines[-tail:]
                return {
                    "job_id": job_id,
                    "source": "ray_api",
                    "lines": lines,
                    "total_lines": len(lines),
                    "truncated": len(logs.split("\n")) > tail,
                }
        except Exception:
            pass

        return {
            "job_id": job_id,
            "source": "none",
            "lines": [],
            "total_lines": 0,
            "message": "No logs available yet. Job may not have started or logs are not accessible.",
        }

    # Read from log file
    try:
        with open(log_path, "r", errors="replace") as f:
            all_lines = f.readlines()

        total_lines = len(all_lines)
        lines = all_lines[-tail:] if len(all_lines) > tail else all_lines

        return {
            "job_id": job_id,
            "source": "file",
            "path": str(log_path),
            "lines": [line.rstrip("\n") for line in lines],
            "total_lines": total_lines,
            "truncated": total_lines > tail,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading log file: {str(e)}")


@router.get("/{job_id}/stream")
async def stream_job_logs(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Stream job logs as Server-Sent Events
    Alternative to WebSocket for simpler client implementation
    """
    job = check_job_access(job_id, current_user, db)
    ray_job_id = job.ray_job_id or job_id

    log_path = get_job_log_path(ray_job_id)

    async def log_generator():
        """Generate log lines as SSE events"""
        if not log_path or not log_path.exists():
            yield f"data: Waiting for log file to be created...\n\n"

            # Wait for file to appear (up to 30 seconds)
            for _ in range(30):
                await asyncio.sleep(1)
                log_path_check = get_job_log_path(ray_job_id)
                if log_path_check and log_path_check.exists():
                    break
            else:
                yield f"data: Log file not found after 30 seconds\n\n"
                return

        # Start tailing the file
        current_path = get_job_log_path(ray_job_id)
        if not current_path:
            return

        try:
            with open(current_path, "r", errors="replace") as f:
                # Go to end of file
                f.seek(0, 2)

                while True:
                    line = f.readline()
                    if line:
                        yield f"data: {line.rstrip()}\n\n"
                    else:
                        await asyncio.sleep(0.1)  # Small delay when no new lines

        except Exception as e:
            yield f"data: Error reading logs: {str(e)}\n\n"

    return StreamingResponse(
        log_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.websocket("/{job_id}/ws")
async def websocket_logs(
    websocket: WebSocket,
    job_id: str,
    db: Session = Depends(get_db),
):
    """
    WebSocket endpoint for real-time log streaming

    Messages sent to client:
    - {"type": "log", "line": "...", "timestamp": "..."}
    - {"type": "status", "message": "..."}
    - {"type": "error", "message": "..."}
    """
    await websocket.accept()

    try:
        # Note: For WebSocket, we skip auth check for now since the page is already auth'd
        # In production, you'd validate a token in the connection params

        # Find the job
        job = db.query(JobModel).filter(JobModel.job_id == job_id).first()
        if not job:
            await websocket.send_json(
                {"type": "error", "message": f"Job {job_id} not found"}
            )
            await websocket.close()
            return

        ray_job_id = job.ray_job_id or job_id

        await websocket.send_json(
            {"type": "status", "message": f"Starting log stream for job {job_id}"}
        )

        # Find log file
        log_path = get_job_log_path(ray_job_id)

        if not log_path or not log_path.exists():
            await websocket.send_json(
                {"type": "status", "message": "Waiting for log file..."}
            )

            # Wait for file to appear
            for _ in range(60):  # Wait up to 60 seconds
                await asyncio.sleep(1)
                log_path = get_job_log_path(ray_job_id)
                if log_path and log_path.exists():
                    break
            else:
                await websocket.send_json(
                    {"type": "error", "message": "Log file not found after 60 seconds"}
                )
                await websocket.close()
                return

        await websocket.send_json(
            {"type": "status", "message": f"Connected to log file: {log_path.name}"}
        )

        # Stream existing content first (last 100 lines)
        with open(log_path, "r", errors="replace") as f:
            lines = f.readlines()
            for line in lines[-100:]:
                await websocket.send_json(
                    {
                        "type": "log",
                        "line": line.rstrip("\n"),
                        "historical": True,
                    }
                )

        await websocket.send_json(
            {"type": "status", "message": "Now streaming live logs..."}
        )

        # Now tail the file for new content
        with open(log_path, "r", errors="replace") as f:
            f.seek(0, 2)  # Go to end

            while True:
                # Check for client disconnect
                try:
                    # Non-blocking check for messages (like ping/pong)
                    message = await asyncio.wait_for(
                        websocket.receive_text(), timeout=0.1
                    )
                    if message == "ping":
                        await websocket.send_json({"type": "pong"})
                except asyncio.TimeoutError:
                    pass  # No message, continue
                except WebSocketDisconnect:
                    break

                # Read new lines
                line = f.readline()
                if line:
                    await websocket.send_json(
                        {
                            "type": "log",
                            "line": line.rstrip("\n"),
                            "historical": False,
                        }
                    )
                else:
                    await asyncio.sleep(0.1)  # Small delay when no new content

    except WebSocketDisconnect:
        pass  # Client disconnected normally
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
    finally:
        try:
            await websocket.close()
        except:
            pass


@router.get("/{job_id}/files")
async def list_job_log_files(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    List all log files associated with a job
    """
    job = check_job_access(job_id, current_user, db)
    ray_job_id = job.ray_job_id or job_id

    log_files = []

    # Search for all related log files
    patterns = [
        f"{RAY_LOG_DIR}/*{ray_job_id}*",
        f"/tmp/ray/session_*/logs/*{ray_job_id}*",
    ]

    for pattern in patterns:
        for path in glob.glob(pattern):
            p = Path(path)
            if p.is_file():
                log_files.append(
                    {
                        "name": p.name,
                        "path": str(p),
                        "size_bytes": p.stat().st_size,
                        "modified": p.stat().st_mtime,
                    }
                )

    # Remove duplicates by path
    seen = set()
    unique_files = []
    for f in log_files:
        if f["path"] not in seen:
            seen.add(f["path"])
            unique_files.append(f)

    return {
        "job_id": job_id,
        "files": sorted(unique_files, key=lambda x: x["modified"], reverse=True),
        "total": len(unique_files),
    }
