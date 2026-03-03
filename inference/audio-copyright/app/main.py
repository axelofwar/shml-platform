"""
Audio Copyright Detection & AI Replacement Service

Detects copyrighted music in videos using audio fingerprinting against
public music databases (Free Music Archive, Jamendo, ccMixter).

Replaces copyrighted segments with AI-generated music matching style/tempo.

NO legal issues - generative solution vs DMCA takedowns.
"""

import asyncio
import os
import time
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any
import logging
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
import librosa
import numpy as np
import soundfile as sf
from pydub import AudioSegment

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings"""

    # Audio fingerprinting
    fingerprint_hop_length: int = 512
    fingerprint_n_mels: int = 128
    match_threshold: float = 0.85  # 85% similarity = copyrighted

    # AI music generation
    musicgen_model: str = "facebook/musicgen-small"  # 300M params
    generation_duration: int = 30  # seconds

    # Processing limits
    max_audio_duration_seconds: int = 3600  # 1 hour
    max_audio_size_mb: int = 100

    # Database
    postgres_host: str = "shml-postgres"
    postgres_port: int = 5432
    postgres_db: str = "inference"
    postgres_user: str = "inference"
    postgres_password: str = ""

    redis_host: str = "shml-redis"
    redis_port: int = 6379
    redis_db: int = 4

    # Music database path
    music_db_path: str = "/app/music_database"

    class Config:
        env_file = ".env"


settings = Settings()


class AudioFingerprintDB:
    """
    Audio fingerprinting database for copyright detection

    Uses chromaprint (acoustic fingerprinting) to match audio against
    public domain music libraries.
    """

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.fingerprints: Dict[str, np.ndarray] = {}
        self.metadata: Dict[str, Dict] = {}

    async def load_database(self):
        """Load pre-computed fingerprints from disk"""
        logger.info(f"Loading audio fingerprint database from {self.db_path}")

        # TODO: Load pre-computed fingerprints
        # For MVP, we'll compute on-the-fly from music files

        music_files = list(self.db_path.glob("**/*.mp3"))
        logger.info(f"Found {len(music_files)} music files in database")

        for music_file in music_files[:100]:  # Limit for MVP
            try:
                fingerprint = await self.compute_fingerprint(str(music_file))
                track_id = music_file.stem
                self.fingerprints[track_id] = fingerprint
                self.metadata[track_id] = {
                    "title": music_file.stem,
                    "path": str(music_file),
                    "license": "Unknown",  # Parse from metadata
                }
            except Exception as e:
                logger.warning(f"Failed to fingerprint {music_file}: {e}")

        logger.info(f"Loaded {len(self.fingerprints)} fingerprints")

    async def compute_fingerprint(self, audio_path: str) -> np.ndarray:
        """
        Compute chromaprint fingerprint for audio file

        Uses mel-frequency cepstral coefficients (MFCCs) as fingerprint.
        """
        # Load audio
        y, sr = librosa.load(audio_path, sr=22050, duration=30)  # First 30s

        # Compute MFCCs
        mfccs = librosa.feature.mfcc(
            y=y,
            sr=sr,
            n_mfcc=settings.fingerprint_n_mels,
            hop_length=settings.fingerprint_hop_length,
        )

        # Average over time to get compact representation
        fingerprint = np.mean(mfccs, axis=1)

        return fingerprint

    async def find_matches(
        self, query_fingerprint: np.ndarray, threshold: float = 0.85
    ) -> List[Dict[str, Any]]:
        """
        Find copyrighted tracks matching query fingerprint

        Returns list of matches with similarity scores.
        """
        matches = []

        for track_id, db_fingerprint in self.fingerprints.items():
            # Cosine similarity
            similarity = np.dot(query_fingerprint, db_fingerprint) / (
                np.linalg.norm(query_fingerprint) * np.linalg.norm(db_fingerprint)
            )

            if similarity >= threshold:
                matches.append(
                    {
                        "track_id": track_id,
                        "similarity": float(similarity),
                        "metadata": self.metadata.get(track_id, {}),
                    }
                )

        # Sort by similarity (highest first)
        matches.sort(key=lambda x: x["similarity"], reverse=True)

        return matches


class MusicGenerator:
    """AI music generation using Meta's AudioCraft MusicGen"""

    def __init__(self):
        self.model = None
        self.processor = None

    async def load_model(self):
        """Load MusicGen model"""
        if self.model is None:
            logger.info("Loading MusicGen model...")
            from transformers import AutoProcessor, MusicgenForConditionalGeneration

            self.processor = AutoProcessor.from_pretrained(settings.musicgen_model)
            self.model = MusicgenForConditionalGeneration.from_pretrained(
                settings.musicgen_model
            )
            logger.info("MusicGen model loaded")

    async def generate_replacement(
        self,
        duration: float,
        style_prompt: str = "upbeat background music",
        tempo: Optional[int] = None,
    ) -> np.ndarray:
        """
        Generate AI music to replace copyrighted segment

        Args:
            duration: Length in seconds
            style_prompt: Text description of desired style
            tempo: Optional tempo in BPM

        Returns:
            Audio waveform as numpy array
        """
        await self.load_model()

        # Add tempo to prompt if specified
        if tempo:
            style_prompt = f"{style_prompt}, {tempo} BPM"

        # Generate audio
        inputs = self.processor(
            text=[style_prompt],
            padding=True,
            return_tensors="pt",
        )

        audio_values = self.model.generate(
            **inputs, max_new_tokens=int(duration * 50)  # 50 tokens/sec
        )

        # Convert to numpy
        audio_np = audio_values[0, 0].cpu().numpy()

        return audio_np


# Global instances
fingerprint_db = AudioFingerprintDB(settings.music_db_path)
music_generator = MusicGenerator()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan"""
    logger.info("Starting Audio Copyright Detection API...")

    # Load fingerprint database
    await fingerprint_db.load_database()

    yield

    logger.info("Shutting down...")


app = FastAPI(
    title="Audio Copyright Detection & Replacement API",
    version="1.0.0",
    description="Detect copyrighted music and replace with AI-generated alternatives",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "CORS_ORIGINS",
        "https://shml-platform.tail38b60a.ts.net,http://localhost:3000,http://localhost:8080",
    ).split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Models
# =============================================================================


class CopyrightMatch(BaseModel):
    track_id: str
    similarity: float
    start_time: float
    end_time: float
    metadata: Dict[str, Any]


class DetectionResult(BaseModel):
    has_copyright: bool
    matches: List[CopyrightMatch]
    processing_time_ms: float
    total_copyrighted_seconds: float


class ReplacementRequest(BaseModel):
    style_prompt: Optional[str] = Field(default="upbeat background music")
    preserve_timing: bool = Field(default=True)
    fade_duration: float = Field(default=1.0)


# =============================================================================
# Endpoints
# =============================================================================


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "fingerprints_loaded": len(fingerprint_db.fingerprints),
        "music_generator_ready": music_generator.model is not None,
    }


@app.post("/api/v1/detect", response_model=DetectionResult)
async def detect_copyright(
    audio: UploadFile = File(...), threshold: float = Form(0.85)
):
    """
    Detect copyrighted music in audio file

    Returns list of matching tracks with timestamps.
    """
    start_time = time.time()

    try:
        # Save uploaded file
        temp_path = f"/tmp/{audio.filename}"
        with open(temp_path, "wb") as f:
            f.write(await audio.read())

        # Compute fingerprint
        query_fingerprint = await fingerprint_db.compute_fingerprint(temp_path)

        # Find matches
        matches = await fingerprint_db.find_matches(query_fingerprint, threshold)

        # TODO: Implement timestamp detection for segments
        # For MVP, assume full audio matches
        matches_with_time = [
            CopyrightMatch(
                track_id=m["track_id"],
                similarity=m["similarity"],
                start_time=0.0,
                end_time=30.0,  # TODO: actual duration
                metadata=m["metadata"],
            )
            for m in matches
        ]

        processing_time = (time.time() - start_time) * 1000

        return DetectionResult(
            has_copyright=len(matches) > 0,
            matches=matches_with_time,
            processing_time_ms=processing_time,
            total_copyrighted_seconds=sum(
                m.end_time - m.start_time for m in matches_with_time
            ),
        )

    except Exception as e:
        logger.error(f"Detection failed: {e}")
        raise HTTPException(500, f"Detection failed: {str(e)}")

    finally:
        # Cleanup
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.post("/api/v1/replace")
async def replace_copyright(
    audio: UploadFile = File(...),
    style_prompt: str = Form("upbeat background music"),
    preserve_timing: bool = Form(True),
):
    """
    Replace copyrighted music with AI-generated alternatives

    1. Detect copyrighted segments
    2. Generate AI music matching style/tempo
    3. Replace segments seamlessly with crossfades
    4. Return new audio file
    """
    # TODO: Implement replacement logic
    raise HTTPException(501, "Audio replacement endpoint not yet implemented")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
