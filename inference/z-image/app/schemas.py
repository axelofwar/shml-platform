"""Pydantic schemas for Z-Image API."""
from typing import Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime


class ImageGenerationRequest(BaseModel):
    """Image generation request."""
    prompt: str = Field(..., min_length=1, max_length=4096)
    negative_prompt: Optional[str] = Field(default=None, max_length=2048)
    width: int = Field(default=1024, ge=256, le=2048)
    height: int = Field(default=1024, ge=256, le=2048)
    num_inference_steps: int = Field(default=8, ge=1, le=50)
    guidance_scale: float = Field(default=0.0, ge=0, le=20)  # 0 for Turbo
    seed: Optional[int] = Field(default=None)


class ImageGenerationResponse(BaseModel):
    """Image generation response."""
    id: str
    created: int
    prompt: str  # Metadata only, not the actual prompt content
    width: int
    height: int
    seed: int
    inference_time_seconds: float
    image_base64: str  # Base64 encoded PNG
    image_url: Optional[str] = None  # If saved to disk


class HealthResponse(BaseModel):
    """Health check response."""
    status: Literal["healthy", "loading", "unloaded", "error"]
    model: str
    device: str
    vram_used_gb: Optional[float] = None
    vram_total_gb: Optional[float] = None
    uptime_seconds: float


class ModelStatusResponse(BaseModel):
    """Detailed model status."""
    loaded: bool
    loading: bool
    last_used: Optional[datetime] = None
    images_generated: int
    average_generation_time_seconds: float
    yielded_to_training: bool
