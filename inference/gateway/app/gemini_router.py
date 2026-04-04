"""
Gemini Proxy Router — server-side Gemini API wrapper for the SBA Resource Portal.

Keeps the Google API key off the client bundle. The SBA frontend calls these
endpoints; this router forwards to generativelanguage.googleapis.com using the
server-side SBA_GEMINI_API_KEY environment variable.

Endpoints:
  POST /api/gemini/generate  — multimodal Q&A (text + audio + attachments)
  POST /api/gemini/speech    — text-to-speech (Gemini TTS)
"""

import logging
from typing import List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .config import GEMINI_API_KEY, GEMINI_GENERATE_MODEL, GEMINI_TTS_MODEL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gemini", tags=["gemini"])

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

_SBA_SYSTEM_PROMPT = (
    "You are a helpful assistant for the SBA Resource Portal. "
    "Answer questions based on the provided PDF and audio files. "
    "Be concise, professional, and accurate."
)

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class AttachmentPart(BaseModel):
    type: str  # MIME type, e.g. "application/pdf", "audio/mpeg"
    data: str  # base64-encoded bytes


class GenerateRequest(BaseModel):
    text: Optional[str] = None
    audio_base64: Optional[str] = None
    attachments: List[AttachmentPart] = []


class GenerateResponse(BaseModel):
    text: str


class SpeechRequest(BaseModel):
    text: str


class SpeechResponse(BaseModel):
    audio_base64: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_parts(req: GenerateRequest) -> list:
    """Assemble Gemini content parts in priority order: attachments → audio → text."""
    parts: list = []
    for att in req.attachments:
        parts.append({"inlineData": {"mimeType": att.type, "data": att.data}})
    if req.audio_base64:
        parts.append({
            "inlineData": {
                "mimeType": "audio/webm;codecs=opus",
                "data": req.audio_base64,
            }
        })
    if req.text:
        parts.append({"text": req.text})
    return parts


def _gemini_url(model: str) -> str:
    return f"{_GEMINI_BASE}/{model}:generateContent?key={GEMINI_API_KEY}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest) -> GenerateResponse:
    """
    Multimodal Q&A via Gemini.

    Accepts text, audio blob, and file attachments (PDFs, images, etc.).
    Returns the model's text response.
    """
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Gemini API key not configured on server. Set SBA_GEMINI_API_KEY.",
        )

    parts = _build_parts(req)
    if not parts:
        raise HTTPException(status_code=400, detail="No content provided")

    payload = {
        "contents": [{"parts": parts}],
        "systemInstruction": {"parts": [{"text": _SBA_SYSTEM_PROMPT}]},
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(_gemini_url(GEMINI_GENERATE_MODEL), json=payload)
            resp.raise_for_status()
        except httpx.TimeoutException:
            logger.warning("Gemini generate timeout")
            raise HTTPException(status_code=504, detail="Gemini API timeout")
        except httpx.HTTPStatusError as e:
            logger.error("Gemini generate HTTP %s: %s", e.response.status_code, e.response.text[:200])
            raise HTTPException(
                status_code=502,
                detail=f"Gemini API returned {e.response.status_code}",
            )

    data = resp.json()
    text = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    )
    if not text:
        logger.error("Gemini generate returned empty text: %s", data)
        raise HTTPException(status_code=502, detail="Empty response from Gemini")

    return GenerateResponse(text=text)


@router.post("/speech", response_model=SpeechResponse)
async def speech(req: SpeechRequest) -> SpeechResponse:
    """
    Text-to-speech via Gemini TTS (gemini-2.5-flash-preview-tts).

    Returns base64-encoded PCM audio at 24 kHz, mono (same format the
    SBA frontend already decodes and plays back via WebAudio API).
    """
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Gemini API key not configured on server. Set SBA_GEMINI_API_KEY.",
        )

    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="text is required")

    payload = {
        "contents": [{"parts": [{"text": req.text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}
            },
        },
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(_gemini_url(GEMINI_TTS_MODEL), json=payload)
            resp.raise_for_status()
        except httpx.TimeoutException:
            logger.warning("Gemini TTS timeout")
            raise HTTPException(status_code=504, detail="Gemini TTS timeout")
        except httpx.HTTPStatusError as e:
            logger.error("Gemini TTS HTTP %s: %s", e.response.status_code, e.response.text[:200])
            raise HTTPException(
                status_code=502,
                detail=f"Gemini TTS returned {e.response.status_code}",
            )

    data = resp.json()
    audio_b64 = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("inlineData", {})
        .get("data", "")
    )
    if not audio_b64:
        logger.error("Gemini TTS returned no audio: %s", data)
        raise HTTPException(status_code=502, detail="No audio in Gemini TTS response")

    return SpeechResponse(audio_base64=audio_b64)
