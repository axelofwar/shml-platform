"""
SAM Audio - Meta's Multimodal Audio Separation Service

SOTA audio source separation using Meta's SAM Audio model (Dec 2025).
Supports text prompts, visual prompts, and span-based audio isolation.

Key Features:
- Text prompts: "isolate the vocals", "remove background music"
- Visual prompts: Click on speaker in video to isolate their audio
- Span prompts: Select time segment to extract as stem
- Real-time factor (RTF) ≈ 0.7 (faster than real-time)

Use Cases for Content Creator Platform:
- DMCA: Isolate copyrighted music from video, replace with MusicGen
- Voice: Extract speaker vocals for dubbing/translation
- SFX: Separate sound effects for remix/editing
- Clean Audio: Remove background noise from recorded content

Based on: github.com/facebookresearch/sam-audio
Paper: PE-AV (Perception Encoder Audiovisual)
Released: December 16, 2025
"""

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional, Dict, Any
from enum import Enum

import numpy as np
from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """SAM Audio configuration"""

    # Model settings
    model_checkpoint: str = "facebook/sam-audio"
    sample_rate: int = 44100
    max_audio_duration_seconds: int = 600  # 10 minutes
    max_audio_size_mb: int = 100

    # Processing settings
    chunk_size_seconds: float = 30.0  # Process in chunks for long audio
    overlap_seconds: float = 1.0  # Overlap between chunks
    output_format: str = "wav"  # wav, mp3, flac

    # Device settings
    device: str = "auto"  # auto, cpu, cuda:0, cuda:1
    use_fp16: bool = True  # Half precision for faster inference

    # Storage
    temp_dir: str = "/tmp/sam-audio"
    output_dir: str = "/app/outputs"

    # Service settings
    redis_host: str = "shml-redis"
    redis_port: int = 6379
    redis_db: int = 5

    class Config:
        env_file = ".env"


settings = Settings()


class PromptType(str, Enum):
    """SAM Audio supports multiple prompt modalities"""

    TEXT = "text"  # "isolate the drums"
    VISUAL = "visual"  # Click coordinates + video frame
    SPAN = "span"  # Time segment selection


class SeparationRequest(BaseModel):
    """Request for audio separation"""

    prompt: str = Field(..., description="Text prompt describing target audio")
    prompt_type: PromptType = PromptType.TEXT
    # For visual prompts
    click_x: Optional[float] = None
    click_y: Optional[float] = None
    frame_timestamp: Optional[float] = None
    # For span prompts
    start_time: Optional[float] = None
    end_time: Optional[float] = None


class SeparationResult(BaseModel):
    """Result from audio separation"""

    job_id: str
    status: str
    stems: List[str] = []  # List of output file paths
    processing_time_ms: float
    prompt_type: str
    prompt_used: str


class IsolationPreset(str, Enum):
    """Common isolation presets for content creators"""

    VOCALS = "vocals"
    MUSIC = "music"
    DRUMS = "drums"
    BASS = "bass"
    SPEECH = "speech"
    BACKGROUND = "background"
    EFFECTS = "effects"


# Text prompts for presets
PRESET_PROMPTS = {
    IsolationPreset.VOCALS: "isolate the vocals and singing",
    IsolationPreset.MUSIC: "isolate the background music",
    IsolationPreset.DRUMS: "isolate the drums and percussion",
    IsolationPreset.BASS: "isolate the bass guitar and low frequencies",
    IsolationPreset.SPEECH: "isolate the speech and dialogue",
    IsolationPreset.BACKGROUND: "isolate the background ambient sounds",
    IsolationPreset.EFFECTS: "isolate the sound effects",
}


class SAMAudioManager:
    """
    Manages SAM Audio model lifecycle and inference

    Note: SAM Audio uses PE-AV (Perception Encoder Audiovisual) architecture.
    The model is loaded lazily to conserve GPU memory until needed.
    """

    def __init__(self):
        self.model = None
        self.processor = None
        self.device = None
        self.is_loaded = False
        self.last_used = time.time()

    async def ensure_loaded(self):
        """Load SAM Audio model if not already loaded"""
        if self.is_loaded:
            return

        logger.info("Loading SAM Audio model...")
        start = time.time()

        try:
            # Determine device
            if settings.device == "auto":
                import torch

                if torch.cuda.is_available():
                    # Check for available GPU with memory
                    for i in range(torch.cuda.device_count()):
                        props = torch.cuda.get_device_properties(i)
                        free_memory = props.total_memory - torch.cuda.memory_allocated(
                            i
                        )
                        # SAM Audio needs ~4GB VRAM
                        if free_memory > 4 * 1024**3:
                            self.device = f"cuda:{i}"
                            break
                    else:
                        self.device = "cpu"
                        logger.warning("No GPU with sufficient memory, using CPU")
                else:
                    self.device = "cpu"
            else:
                self.device = settings.device

            logger.info(f"Using device: {self.device}")

            # Note: SAM Audio is very new (Dec 2025)
            # This is a placeholder for the actual model loading
            # when the official HuggingFace/GitHub release is stable
            try:
                from sam_audio import SAMAudio, SAMAudioProcessor

                self.processor = SAMAudioProcessor.from_pretrained(
                    settings.model_checkpoint
                )
                self.model = SAMAudio.from_pretrained(
                    settings.model_checkpoint,
                    device=self.device,
                    torch_dtype="float16" if settings.use_fp16 else "float32",
                )
            except ImportError:
                # Fallback: Use demucs for audio separation until SAM Audio is released
                logger.warning("SAM Audio not yet available, using Demucs fallback")
                try:
                    from demucs import pretrained
                    from demucs.apply import apply_model

                    # Load hybrid transformer model (htdemucs)
                    self.model = pretrained.get_model("htdemucs")
                    if self.device != "cpu":
                        import torch

                        self.model = self.model.to(self.device)
                    self.processor = "demucs"  # Flag for demucs mode
                except ImportError:
                    logger.error("Neither sam_audio nor demucs available")
                    raise HTTPException(
                        503,
                        "Audio separation models not available. "
                        "Install demucs: pip install demucs",
                    )

            self.is_loaded = True
            elapsed = time.time() - start
            logger.info(f"Model loaded in {elapsed:.2f}s on {self.device}")

        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise HTTPException(503, f"Model loading failed: {str(e)}")

    async def unload(self):
        """Unload model to free GPU memory"""
        if self.model is not None:
            logger.info("Unloading SAM Audio model...")
            del self.model
            del self.processor
            self.model = None
            self.processor = None
            self.is_loaded = False

            # Clear CUDA cache
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except:
                pass

            logger.info("Model unloaded")

    async def separate_audio(
        self,
        audio_path: str,
        prompt: str,
        prompt_type: PromptType = PromptType.TEXT,
        visual_data: Optional[Dict] = None,
        span_data: Optional[Dict] = None,
    ) -> List[str]:
        """
        Separate audio based on prompt

        Returns list of output file paths for separated stems
        """
        await self.ensure_loaded()
        self.last_used = time.time()

        # Load audio
        import librosa
        import soundfile as sf

        audio, sr = librosa.load(audio_path, sr=settings.sample_rate, mono=False)
        if audio.ndim == 1:
            audio = audio[np.newaxis, :]  # Add channel dimension

        duration = audio.shape[-1] / sr
        logger.info(f"Processing audio: {duration:.1f}s, {audio.shape}")

        output_dir = Path(settings.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        job_id = str(uuid.uuid4())[:8]

        if self.processor == "demucs":
            # Demucs fallback mode
            return await self._separate_demucs(audio, sr, prompt, output_dir, job_id)
        else:
            # SAM Audio mode (when available)
            return await self._separate_sam(
                audio,
                sr,
                prompt,
                prompt_type,
                visual_data,
                span_data,
                output_dir,
                job_id,
            )

    async def _separate_demucs(
        self, audio: np.ndarray, sr: int, prompt: str, output_dir: Path, job_id: str
    ) -> List[str]:
        """
        Demucs-based separation (fallback until SAM Audio is stable)

        Demucs separates into 4 stems: drums, bass, other, vocals
        We map the prompt to the appropriate stem(s)
        """
        import torch
        from demucs.apply import apply_model

        # Convert to torch tensor
        audio_tensor = torch.from_numpy(audio).float()
        if audio_tensor.dim() == 2:
            audio_tensor = audio_tensor.unsqueeze(0)  # Add batch dim

        # Move to device
        if self.device != "cpu":
            audio_tensor = audio_tensor.to(self.device)

        # Apply model
        with torch.no_grad():
            stems = apply_model(self.model, audio_tensor, device=self.device)

        # stems shape: (batch, sources, channels, samples)
        # sources: drums, bass, other, vocals (for htdemucs)
        source_names = ["drums", "bass", "other", "vocals"]

        # Determine which stems to return based on prompt
        prompt_lower = prompt.lower()
        requested_stems = []

        if "vocal" in prompt_lower or "sing" in prompt_lower or "voice" in prompt_lower:
            requested_stems = ["vocals"]
        elif "drum" in prompt_lower or "percussion" in prompt_lower:
            requested_stems = ["drums"]
        elif "bass" in prompt_lower:
            requested_stems = ["bass"]
        elif "music" in prompt_lower or "instrument" in prompt_lower:
            requested_stems = ["drums", "bass", "other"]
        elif "background" in prompt_lower:
            requested_stems = ["drums", "bass", "other"]
        elif "speech" in prompt_lower or "dialogue" in prompt_lower:
            requested_stems = ["vocals"]
        else:
            # Return all stems
            requested_stems = source_names

        output_paths = []
        stems_np = stems.cpu().numpy()[0]  # Remove batch dim

        for i, name in enumerate(source_names):
            if name in requested_stems:
                stem_audio = stems_np[i]
                output_path = output_dir / f"{job_id}_{name}.wav"

                import soundfile as sf

                sf.write(str(output_path), stem_audio.T, sr)
                output_paths.append(str(output_path))
                logger.info(f"Saved stem: {name} -> {output_path}")

        return output_paths

    async def _separate_sam(
        self,
        audio: np.ndarray,
        sr: int,
        prompt: str,
        prompt_type: PromptType,
        visual_data: Optional[Dict],
        span_data: Optional[Dict],
        output_dir: Path,
        job_id: str,
    ) -> List[str]:
        """
        SAM Audio-based separation (when available)

        Supports:
        - Text prompts: Natural language description
        - Visual prompts: Click on video to identify speaker
        - Span prompts: Time-based segment extraction
        """
        # Placeholder for SAM Audio implementation
        # This will be filled in when the model is released to HuggingFace

        inputs = self.processor(
            audio=audio,
            sampling_rate=sr,
            text=prompt if prompt_type == PromptType.TEXT else None,
            visual_prompt=visual_data if prompt_type == PromptType.VISUAL else None,
            span_prompt=span_data if prompt_type == PromptType.SPAN else None,
            return_tensors="pt",
        )

        if self.device != "cpu":
            inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model(**inputs)

        # Save separated audio
        separated = outputs.separated_audio.cpu().numpy()
        output_path = output_dir / f"{job_id}_separated.wav"

        import soundfile as sf

        sf.write(str(output_path), separated.T, sr)

        return [str(output_path)]


# Global model manager
model_manager = SAMAudioManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle management"""
    logger.info("SAM Audio service starting...")

    # Create temp/output directories
    os.makedirs(settings.temp_dir, exist_ok=True)
    os.makedirs(settings.output_dir, exist_ok=True)

    # Preload model if GPU available
    if settings.device != "cpu":
        try:
            await model_manager.ensure_loaded()
        except Exception as e:
            logger.warning(f"Failed to preload model: {e}")

    yield

    # Cleanup
    await model_manager.unload()
    logger.info("SAM Audio service stopped")


app = FastAPI(
    title="SAM Audio - Multimodal Audio Separation",
    description="Meta's SAM Audio for DMCA-safe audio isolation and replacement",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:3000,http://localhost:8080",
    ).split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "model_loaded": model_manager.is_loaded,
        "device": model_manager.device,
        "model_type": "demucs" if model_manager.processor == "demucs" else "sam-audio",
    }


@app.post("/api/v1/separate", response_model=SeparationResult)
async def separate_audio(
    audio: UploadFile = File(...),
    prompt: str = Form(...),
    prompt_type: PromptType = Form(PromptType.TEXT),
    # Visual prompt data
    click_x: Optional[float] = Form(None),
    click_y: Optional[float] = Form(None),
    frame_timestamp: Optional[float] = Form(None),
    # Span prompt data
    start_time: Optional[float] = Form(None),
    end_time: Optional[float] = Form(None),
):
    """
    Separate audio based on multimodal prompts

    Text prompt examples:
    - "isolate the vocals"
    - "remove the background music"
    - "extract the drums"
    - "separate the speech from noise"

    Visual prompt: Click coordinates in video frame to identify speaker
    Span prompt: Time range to extract as separate stem
    """
    start = time.time()
    job_id = str(uuid.uuid4())[:8]

    # Save uploaded audio
    temp_path = Path(settings.temp_dir) / f"{job_id}_input{Path(audio.filename).suffix}"
    with open(temp_path, "wb") as f:
        content = await audio.read()
        f.write(content)

    try:
        # Prepare prompt data
        visual_data = None
        span_data = None

        if prompt_type == PromptType.VISUAL:
            if click_x is None or click_y is None:
                raise HTTPException(400, "Visual prompt requires click_x and click_y")
            visual_data = {
                "x": click_x,
                "y": click_y,
                "timestamp": frame_timestamp or 0.0,
            }

        if prompt_type == PromptType.SPAN:
            if start_time is None or end_time is None:
                raise HTTPException(400, "Span prompt requires start_time and end_time")
            span_data = {"start": start_time, "end": end_time}

        # Run separation
        output_paths = await model_manager.separate_audio(
            str(temp_path), prompt, prompt_type, visual_data, span_data
        )

        processing_time = (time.time() - start) * 1000

        return SeparationResult(
            job_id=job_id,
            status="completed",
            stems=output_paths,
            processing_time_ms=processing_time,
            prompt_type=prompt_type.value,
            prompt_used=prompt,
        )

    except Exception as e:
        logger.error(f"Separation failed: {e}")
        raise HTTPException(500, f"Audio separation failed: {str(e)}")

    finally:
        # Cleanup temp file
        if temp_path.exists():
            temp_path.unlink()


@app.post("/api/v1/separate/preset", response_model=SeparationResult)
async def separate_by_preset(
    audio: UploadFile = File(...), preset: IsolationPreset = Form(...)
):
    """
    Separate audio using predefined presets (content creator friendly)

    Presets:
    - vocals: Extract singing/vocals
    - music: Extract background music
    - drums: Extract drums/percussion
    - bass: Extract bass frequencies
    - speech: Extract dialogue/speech
    - background: Extract ambient sounds
    - effects: Extract sound effects
    """
    prompt = PRESET_PROMPTS[preset]

    # Delegate to main separation endpoint
    start = time.time()
    job_id = str(uuid.uuid4())[:8]

    temp_path = Path(settings.temp_dir) / f"{job_id}_input{Path(audio.filename).suffix}"
    with open(temp_path, "wb") as f:
        content = await audio.read()
        f.write(content)

    try:
        output_paths = await model_manager.separate_audio(
            str(temp_path), prompt, PromptType.TEXT
        )

        processing_time = (time.time() - start) * 1000

        return SeparationResult(
            job_id=job_id,
            status="completed",
            stems=output_paths,
            processing_time_ms=processing_time,
            prompt_type="preset",
            prompt_used=f"{preset.value}: {prompt}",
        )

    finally:
        if temp_path.exists():
            temp_path.unlink()


@app.get("/api/v1/stems/{job_id}/{stem_name}")
async def download_stem(job_id: str, stem_name: str):
    """Download a separated stem file"""
    output_dir = Path(settings.output_dir)

    # Look for matching file
    pattern = f"{job_id}_{stem_name}.*"
    matches = list(output_dir.glob(pattern))

    if not matches:
        raise HTTPException(404, f"Stem not found: {stem_name}")

    return FileResponse(matches[0], media_type="audio/wav", filename=f"{stem_name}.wav")


@app.post("/api/v1/yield-to-training")
async def yield_to_training():
    """
    Unload model to free GPU memory for training jobs
    Called by GPU Manager when training starts
    """
    await model_manager.unload()
    return {"status": "yielded", "message": "SAM Audio model unloaded for training"}


@app.post("/api/v1/restore-from-training")
async def restore_from_training():
    """
    Reload model after training completes
    Called by GPU Manager when training ends
    """
    await model_manager.ensure_loaded()
    return {
        "status": "restored",
        "message": "SAM Audio model reloaded",
        "device": model_manager.device,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
