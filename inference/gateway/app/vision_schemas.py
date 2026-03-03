"""Schemas for vision model integration and orchestration."""

from typing import List, Optional, Literal, Union
from pydantic import BaseModel, Field


class TextContent(BaseModel):
    """Text content part."""

    type: Literal["text"] = "text"
    text: str


class ImageURL(BaseModel):
    """Image URL details."""

    url: str  # Base64 data URI, HTTP(S) URL, or file:// path


class ImageContent(BaseModel):
    """Image content part."""

    type: Literal["image_url"] = "image_url"
    image_url: ImageURL


ContentPart = Union[TextContent, ImageContent, str]


class MultimodalMessage(BaseModel):
    """Message with multimodal content support."""

    role: Literal["system", "user", "assistant"]
    content: Union[str, List[ContentPart]]


class ImageAnalysis(BaseModel):
    """Result from vision model analysis."""

    description: str
    detected_objects: List[str] = Field(default_factory=list)
    text_extracted: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    model: str


class OrchestrationRequest(BaseModel):
    """Request that may require vision + coding model orchestration."""

    messages: List[MultimodalMessage]
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = Field(default=4096, ge=1, le=32768)
    top_p: float = Field(default=0.9, ge=0, le=1)
    stream: bool = False
    model: str = "qwen-orchestrated"  # Virtual model for orchestration


class OrchestrationResponse(BaseModel):
    """Response from orchestrated vision + coding pipeline."""

    text: str
    vision_analysis: Optional[ImageAnalysis] = None
    coding_model_used: str
    vision_model_used: Optional[str] = None
    total_tokens: int
    orchestration_path: str  # "vision-then-coding" or "coding-only"
