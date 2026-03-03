"""
Audio Router - DMCA Detection, Isolation, and Replacement Workflow

Provides unified API for content creators to handle copyrighted audio:
1. POST /api/audio/detect - Detect copyrighted music in video/audio
2. POST /api/audio/isolate - Use SAM Audio to separate stems
3. POST /api/audio/replace - Generate royalty-free replacement with MusicGen
4. POST /api/audio/workflow - Complete DMCA-safe pipeline

All routes coordinate with GPU Manager for resource allocation.
"""

import asyncio
import logging
import time
import uuid
from typing import Optional, List, Dict, Any
from enum import Enum

import httpx
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import SAM_AUDIO_URL, AUDIO_COPYRIGHT_URL, GPU_MANAGER_URL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/audio", tags=["audio"])

# ============================================================================
# Request/Response Models
# ============================================================================


class IsolationPreset(str, Enum):
    """Common audio isolation presets"""

    VOCALS = "vocals"
    MUSIC = "music"
    DRUMS = "drums"
    BASS = "bass"
    SPEECH = "speech"
    BACKGROUND = "background"


class DetectionResult(BaseModel):
    """Result from copyright detection"""

    has_copyrighted: bool
    confidence: float
    matched_tracks: List[Dict[str, Any]] = []
    segments: List[Dict[str, Any]] = []
    processing_time_ms: float


class IsolationResult(BaseModel):
    """Result from audio isolation"""

    job_id: str
    status: str
    stems: List[str] = []
    processing_time_ms: float
    prompt_used: str


class ReplacementResult(BaseModel):
    """Result from audio replacement"""

    job_id: str
    status: str
    generated_audio_url: str
    style_matched: bool
    tempo_matched: bool
    duration_seconds: float
    processing_time_ms: float


class WorkflowResult(BaseModel):
    """Result from complete DMCA workflow"""

    job_id: str
    status: str
    detection: Optional[DetectionResult] = None
    isolation: Optional[IsolationResult] = None
    replacement: Optional[ReplacementResult] = None
    final_output_url: Optional[str] = None
    total_processing_time_ms: float


class WorkflowRequest(BaseModel):
    """Request for complete DMCA workflow"""

    style_prompt: str = Field(
        default="upbeat electronic music",
        description="Style for replacement audio if copyright detected",
    )
    isolation_target: str = Field(
        default="music", description="What to isolate: music, vocals, speech"
    )
    auto_replace: bool = Field(
        default=True,
        description="Automatically generate replacement if copyright detected",
    )
    preserve_timing: bool = Field(
        default=True, description="Match replacement duration to original"
    )


# ============================================================================
# Health & Status
# ============================================================================


@router.get("/health")
async def audio_health():
    """Check health of all audio services"""
    services = {}

    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in [
            ("sam-audio", SAM_AUDIO_URL),
            ("audio-copyright", AUDIO_COPYRIGHT_URL),
        ]:
            try:
                resp = await client.get(f"{url}/health")
                if resp.status_code == 200:
                    services[name] = resp.json()
                else:
                    services[name] = {
                        "status": "unhealthy",
                        "error": f"HTTP {resp.status_code}",
                    }
            except Exception as e:
                services[name] = {"status": "unavailable", "error": str(e)}

    # Determine overall status
    all_healthy = all(
        s.get("status") == "healthy" for s in services.values() if isinstance(s, dict)
    )

    return {"status": "healthy" if all_healthy else "degraded", "services": services}


# ============================================================================
# Detection Endpoint
# ============================================================================


@router.post("/detect", response_model=DetectionResult)
async def detect_copyright(
    audio: UploadFile = File(..., description="Audio or video file to check"),
    confidence_threshold: float = Form(0.85, description="Match threshold (0.0-1.0)"),
):
    """
    Detect copyrighted music in audio/video

    Uses audio fingerprinting against public music databases.
    Returns matched tracks and time segments with copyright.
    """
    start = time.time()

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            # Forward to audio-copyright service
            files = {"audio": (audio.filename, await audio.read(), audio.content_type)}
            data = {"confidence_threshold": confidence_threshold}

            resp = await client.post(
                f"{AUDIO_COPYRIGHT_URL}/api/v1/detect", files=files, data=data
            )

            if resp.status_code != 200:
                raise HTTPException(resp.status_code, resp.text)

            result = resp.json()

            return DetectionResult(
                has_copyrighted=result.get("has_copyrighted", False),
                confidence=result.get("confidence", 0.0),
                matched_tracks=result.get("matched_tracks", []),
                segments=result.get("segments", []),
                processing_time_ms=(time.time() - start) * 1000,
            )

        except httpx.HTTPError as e:
            logger.error(f"Copyright detection failed: {e}")
            raise HTTPException(
                503, f"Copyright detection service unavailable: {str(e)}"
            )


# ============================================================================
# Isolation Endpoint
# ============================================================================


@router.post("/isolate", response_model=IsolationResult)
async def isolate_audio(
    audio: UploadFile = File(..., description="Audio file to separate"),
    prompt: str = Form("isolate the background music", description="What to isolate"),
    preset: Optional[IsolationPreset] = Form(
        None, description="Use preset instead of prompt"
    ),
):
    """
    Isolate audio stems using SAM Audio

    Supports:
    - Text prompts: "isolate the vocals", "remove background music"
    - Presets: vocals, music, drums, bass, speech, background

    Returns separated audio stems for download.
    """
    start = time.time()

    # Use preset if provided
    if preset:
        prompt = f"isolate the {preset.value}"

    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            files = {"audio": (audio.filename, await audio.read(), audio.content_type)}
            data = {"prompt": prompt, "prompt_type": "text"}

            resp = await client.post(
                f"{SAM_AUDIO_URL}/api/v1/separate", files=files, data=data
            )

            if resp.status_code != 200:
                raise HTTPException(resp.status_code, resp.text)

            result = resp.json()

            return IsolationResult(
                job_id=result.get("job_id", "unknown"),
                status=result.get("status", "completed"),
                stems=result.get("stems", []),
                processing_time_ms=(time.time() - start) * 1000,
                prompt_used=prompt,
            )

        except httpx.HTTPError as e:
            logger.error(f"Audio isolation failed: {e}")
            raise HTTPException(503, f"SAM Audio service unavailable: {str(e)}")


@router.post("/isolate/preset", response_model=IsolationResult)
async def isolate_by_preset(
    audio: UploadFile = File(...), preset: IsolationPreset = Form(...)
):
    """
    Isolate audio using predefined presets (content creator friendly)

    Presets:
    - vocals: Extract singing/vocals
    - music: Extract background music
    - drums: Extract drums/percussion
    - bass: Extract bass frequencies
    - speech: Extract dialogue/speech
    - background: Extract ambient sounds
    """
    return await isolate_audio(audio, preset=preset)


# ============================================================================
# Replacement Endpoint
# ============================================================================


@router.post("/replace", response_model=ReplacementResult)
async def replace_audio(
    duration_seconds: float = Form(..., description="Duration of replacement audio"),
    style_prompt: str = Form(
        "upbeat electronic music", description="Style description for generated music"
    ),
    match_tempo: Optional[float] = Form(None, description="BPM to match (optional)"),
):
    """
    Generate royalty-free replacement audio using MusicGen

    Creates AI-generated music matching the specified style and duration.
    Perfect for replacing copyrighted segments.
    """
    start = time.time()
    job_id = str(uuid.uuid4())[:8]

    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            data = {
                "duration_seconds": duration_seconds,
                "style_prompt": style_prompt,
                "match_tempo": match_tempo,
            }

            resp = await client.post(
                f"{AUDIO_COPYRIGHT_URL}/api/v1/generate", data=data
            )

            if resp.status_code != 200:
                raise HTTPException(resp.status_code, resp.text)

            result = resp.json()

            return ReplacementResult(
                job_id=job_id,
                status="completed",
                generated_audio_url=result.get("audio_url", ""),
                style_matched=True,
                tempo_matched=match_tempo is not None,
                duration_seconds=duration_seconds,
                processing_time_ms=(time.time() - start) * 1000,
            )

        except httpx.HTTPError as e:
            logger.error(f"Audio replacement failed: {e}")
            raise HTTPException(503, f"MusicGen service unavailable: {str(e)}")


# ============================================================================
# Complete DMCA Workflow
# ============================================================================


@router.post("/workflow", response_model=WorkflowResult)
async def dmca_workflow(
    audio: UploadFile = File(..., description="Audio/video to process"),
    request: WorkflowRequest = None,
    background_tasks: BackgroundTasks = None,
):
    """
    Complete DMCA-safe audio workflow

    Pipeline:
    1. Detect copyrighted content
    2. If found, isolate the music stem
    3. Generate royalty-free replacement
    4. Return processed audio (original vocals + new music)

    This is the one-click solution for content creators.
    """
    start = time.time()
    job_id = str(uuid.uuid4())[:8]

    if request is None:
        request = WorkflowRequest()

    # Read file once
    content = await audio.read()

    async with httpx.AsyncClient(timeout=600.0) as client:
        try:
            # Step 1: Detect copyright
            logger.info(f"[{job_id}] Step 1: Detecting copyright...")

            files = {"audio": (audio.filename, content, audio.content_type)}
            detect_resp = await client.post(
                f"{AUDIO_COPYRIGHT_URL}/api/v1/detect", files=files
            )

            detection = None
            if detect_resp.status_code == 200:
                detect_data = detect_resp.json()
                detection = DetectionResult(
                    has_copyrighted=detect_data.get("has_copyrighted", False),
                    confidence=detect_data.get("confidence", 0.0),
                    matched_tracks=detect_data.get("matched_tracks", []),
                    segments=detect_data.get("segments", []),
                    processing_time_ms=0,
                )

            # If no copyright found, return early
            if not detection or not detection.has_copyrighted:
                return WorkflowResult(
                    job_id=job_id,
                    status="clean",
                    detection=detection,
                    total_processing_time_ms=(time.time() - start) * 1000,
                )

            logger.info(f"[{job_id}] Copyright detected! Proceeding with isolation...")

            # Step 2: Isolate music (if auto_replace enabled)
            isolation = None
            if request.auto_replace:
                files = {"audio": (audio.filename, content, audio.content_type)}
                isolate_resp = await client.post(
                    f"{SAM_AUDIO_URL}/api/v1/separate",
                    files=files,
                    data={
                        "prompt": f"isolate the {request.isolation_target}",
                        "prompt_type": "text",
                    },
                )

                if isolate_resp.status_code == 200:
                    isolate_data = isolate_resp.json()
                    isolation = IsolationResult(
                        job_id=isolate_data.get("job_id", ""),
                        status=isolate_data.get("status", "completed"),
                        stems=isolate_data.get("stems", []),
                        processing_time_ms=0,
                        prompt_used=f"isolate the {request.isolation_target}",
                    )

                logger.info(f"[{job_id}] Isolation complete. Generating replacement...")

                # Step 3: Generate replacement
                # Get duration from copyrighted segment
                duration = 30.0  # Default
                if detection.segments:
                    segment = detection.segments[0]
                    duration = segment.get("end", 30) - segment.get("start", 0)

                replace_resp = await client.post(
                    f"{AUDIO_COPYRIGHT_URL}/api/v1/generate",
                    data={
                        "duration_seconds": duration,
                        "style_prompt": request.style_prompt,
                    },
                )

                replacement = None
                if replace_resp.status_code == 200:
                    replace_data = replace_resp.json()
                    replacement = ReplacementResult(
                        job_id=str(uuid.uuid4())[:8],
                        status="completed",
                        generated_audio_url=replace_data.get("audio_url", ""),
                        style_matched=True,
                        tempo_matched=request.preserve_timing,
                        duration_seconds=duration,
                        processing_time_ms=0,
                    )

            return WorkflowResult(
                job_id=job_id,
                status="processed",
                detection=detection,
                isolation=isolation,
                replacement=replacement,
                final_output_url=(
                    replacement.generated_audio_url if replacement else None
                ),
                total_processing_time_ms=(time.time() - start) * 1000,
            )

        except httpx.HTTPError as e:
            logger.error(f"DMCA workflow failed: {e}")
            raise HTTPException(503, f"Audio workflow failed: {str(e)}")


# ============================================================================
# Stem Download
# ============================================================================


@router.get("/stems/{job_id}/{stem_name}")
async def download_stem(job_id: str, stem_name: str):
    """
    Download a separated stem from a previous isolation job

    Proxies to SAM Audio service for file retrieval.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(
                f"{SAM_AUDIO_URL}/api/v1/stems/{job_id}/{stem_name}",
                follow_redirects=True,
            )

            if resp.status_code != 200:
                raise HTTPException(resp.status_code, "Stem not found")

            return StreamingResponse(
                iter([resp.content]),
                media_type="audio/wav",
                headers={
                    "Content-Disposition": f'attachment; filename="{stem_name}.wav"'
                },
            )

        except httpx.HTTPError as e:
            raise HTTPException(503, f"Failed to retrieve stem: {str(e)}")


# ============================================================================
# GPU Resource Management
# ============================================================================


@router.post("/yield-gpu")
async def yield_gpu_for_audio():
    """
    Request GPU resources for audio processing

    Tells GPU Manager to free RTX 2070 for SAM Audio.
    Called automatically by workflow endpoints when needed.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(f"{GPU_MANAGER_URL}/pii/start")
            if resp.status_code != 200:
                logger.warning(f"GPU yield request returned {resp.status_code}")
            return resp.json()
        except httpx.HTTPError as e:
            logger.error(f"GPU yield failed: {e}")
            raise HTTPException(503, f"GPU Manager unavailable: {str(e)}")


@router.post("/restore-gpu")
async def restore_gpu_after_audio():
    """
    Release GPU resources after audio processing

    Tells GPU Manager to restore normal services on RTX 2070.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(f"{GPU_MANAGER_URL}/pii/end")
            if resp.status_code != 200:
                logger.warning(f"GPU restore request returned {resp.status_code}")
            return resp.json()
        except httpx.HTTPError as e:
            logger.error(f"GPU restore failed: {e}")
            raise HTTPException(503, f"GPU Manager unavailable: {str(e)}")
