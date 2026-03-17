"""Orchestrator for vision + coding model pipeline."""

import logging
import httpx
from typing import List, Optional, Tuple
from fastapi import HTTPException

from .vision_schemas import (
    MultimodalMessage,
    ImageAnalysis,
    OrchestrationRequest,
    OrchestrationResponse,
)
from .content_analyzer import ContentAnalyzer
from .config import QWEN3_VL_URL, CODING_MODEL_URL

logger = logging.getLogger(__name__)


class ModelOrchestrator:
    """Orchestrates requests between vision and coding models."""

    def __init__(self):
        self.analyzer = ContentAnalyzer()
        self.http_client = None

    async def initialize(self):
        """Initialize HTTP client."""
        if not self.http_client:
            self.http_client = httpx.AsyncClient(timeout=300.0)  # 5min timeout

    async def close(self):
        """Close HTTP client."""
        if self.http_client:
            await self.http_client.close()

    async def process_request(
        self, request: OrchestrationRequest
    ) -> OrchestrationResponse:
        """
        Process a request through the orchestration pipeline.

        Flow:
        1. Check if request contains images
        2. If yes: vision model first, then coding model with vision results
        3. If no: coding model directly

        Args:
            request: The orchestration request with messages

        Returns:
            Orchestrated response with vision analysis (if applicable)
        """
        await self.initialize()

        has_images = self.analyzer.has_images(request.messages)

        if has_images:
            logger.info("Images detected - using vision-then-coding pipeline")
            return await self._vision_then_coding(request)
        else:
            logger.info("No images - using coding-only pipeline")
            return await self._coding_only(request)

    async def _vision_then_coding(
        self, request: OrchestrationRequest
    ) -> OrchestrationResponse:
        """Process request through vision model first, then coding model."""

        # Step 1: Extract images and text
        image_urls, context_text = self.analyzer.extract_images_and_text(
            request.messages
        )

        # Step 2: Analyze images with vision model
        vision_analysis = await self._call_vision_model(request.messages, image_urls)

        # Step 3: Create coding prompt with vision analysis
        coding_messages = self.analyzer.create_coding_prompt_with_vision(
            request.messages, vision_analysis.description
        )

        # Step 4: Call coding model
        coding_response, tokens = await self._call_coding_model(
            coding_messages, request.temperature, request.max_tokens, request.top_p
        )

        return OrchestrationResponse(
            text=coding_response,
            vision_analysis=vision_analysis,
            coding_model_used="qwen2.5-coder-32b",
            vision_model_used=vision_analysis.model,
            total_tokens=tokens,
            orchestration_path="vision-then-coding",
        )

    async def _coding_only(
        self, request: OrchestrationRequest
    ) -> OrchestrationResponse:
        """Process request through coding model only."""

        # Convert multimodal messages to simple text messages
        text_messages = []
        for msg in request.messages:
            content = (
                msg.content
                if isinstance(msg.content, str)
                else " ".join(
                    (
                        part
                        if isinstance(part, str)
                        else (
                            part.get("text", "")
                            if isinstance(part, dict)
                            else part.text
                        )
                    )
                    for part in msg.content
                )
            )
            text_messages.append(MultimodalMessage(role=msg.role, content=content))

        coding_response, tokens = await self._call_coding_model(
            text_messages, request.temperature, request.max_tokens, request.top_p
        )

        return OrchestrationResponse(
            text=coding_response,
            vision_analysis=None,
            coding_model_used="qwen2.5-coder-32b",
            vision_model_used=None,
            total_tokens=tokens,
            orchestration_path="coding-only",
        )

    async def _call_vision_model(
        self, messages: List[MultimodalMessage], image_urls: List[str]
    ) -> ImageAnalysis:
        """Call the vision model (Qwen3-VL) to analyze images."""

        try:
            # Format messages for vision model
            vision_request = {
                "model": "qwen3-vl-8b",
                "messages": [msg.model_dump() for msg in messages],
                "temperature": 0.7,
                "max_tokens": 2048,
            }

            response = await self.http_client.post(
                f"{QWEN3_VL_URL}/v1/chat/completions", json=vision_request
            )
            response.raise_for_status()

            result = response.json()
            vision_text = result["choices"][0]["message"]["content"]

            logger.info(f"Vision model response: {vision_text[:200]}...")

            return ImageAnalysis(
                description=vision_text,
                detected_objects=[],  # Could parse from response
                text_extracted=None,
                confidence=1.0,
                model="qwen3-vl-8b",
            )

        except Exception as e:
            logger.error(f"Vision model call failed: {e}")
            raise HTTPException(status_code=500, detail=f"Vision model error: {str(e)}")

    async def _call_coding_model(
        self,
        messages: List[MultimodalMessage],
        temperature: float,
        max_tokens: int,
        top_p: float,
    ) -> Tuple[str, int]:
        """
        Call the coding model (Qwen2.5-Coder).

        Returns:
            Tuple of (response_text, total_tokens)
        """

        try:
            # Format messages for coding model
            coding_request = {
                "model": "qwen2.5-coder-32b",
                "messages": [
                    {
                        "role": msg.role,
                        "content": (
                            msg.content
                            if isinstance(msg.content, str)
                            else " ".join(
                                (
                                    part
                                    if isinstance(part, str)
                                    else (
                                        part.get("text", "")
                                        if isinstance(part, dict)
                                        else part.text
                                    )
                                )
                                for part in msg.content
                            )
                        ),
                    }
                    for msg in messages
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p,
            }

            response = await self.http_client.post(
                f"{CODING_MODEL_URL}/v1/chat/completions", json=coding_request
            )
            response.raise_for_status()

            result = response.json()
            coding_text = result["choices"][0]["message"]["content"]
            total_tokens = result["usage"]["total_tokens"]

            logger.info(f"Coding model generated {total_tokens} tokens")

            return coding_text, total_tokens

        except Exception as e:
            logger.error(f"Coding model call failed: {e}")
            raise HTTPException(status_code=500, detail=f"Coding model error: {str(e)}")


# Global orchestrator instance
orchestrator = ModelOrchestrator()
