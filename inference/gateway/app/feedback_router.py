from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import logging
import os
import json
import aiofiles
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    image_id: Optional[str] = None
    image_url: Optional[str] = None
    conversation_id: Optional[str] = None
    correction_type: str  # "missed_face", "wrong_box", "false_positive"
    bbox: Optional[List[float]] = None  # [x, y, w, h] or [x1, y1, x2, y2]
    comment: Optional[str] = None
    user_id: Optional[str] = None


class FeedbackResponse(BaseModel):
    status: str
    feedback_id: str
    message: str


FEEDBACK_DIR = os.getenv("FEEDBACK_DIR", "/app/data/feedback")
os.makedirs(FEEDBACK_DIR, exist_ok=True)


async def save_feedback_to_disk(feedback: FeedbackRequest, feedback_id: str):
    """Save feedback to disk for later processing (e.g., upload to Roboflow)."""
    try:
        timestamp = datetime.utcnow().isoformat()
        filename = f"{FEEDBACK_DIR}/{timestamp}_{feedback_id}.json"

        data = feedback.dict()
        data["timestamp"] = timestamp
        data["feedback_id"] = feedback_id

        async with aiofiles.open(filename, mode="w") as f:
            await f.write(json.dumps(data, indent=2))

        logger.info(f"Saved feedback {feedback_id} to {filename}")

        # TODO: Trigger async upload to Roboflow project "Hard Negatives"

    except Exception as e:
        logger.error(f"Failed to save feedback {feedback_id}: {e}")


@router.post("/correction", response_model=FeedbackResponse)
async def submit_correction(
    feedback: FeedbackRequest, background_tasks: BackgroundTasks
):
    """
    Submit a correction (feedback) for a model prediction.

    This endpoint enables the 'Data Flywheel':
    1. User reports an error (missed face, wrong box).
    2. We save it.
    3. (Future) We upload it to Roboflow as a 'Hard Example'.
    4. We retrain the model.
    """
    feedback_id = f"fb_{int(datetime.utcnow().timestamp())}"

    # Offload saving to background task to keep API fast
    background_tasks.add_task(save_feedback_to_disk, feedback, feedback_id)

    return FeedbackResponse(
        status="received",
        feedback_id=feedback_id,
        message="Feedback received and queued for processing.",
    )
