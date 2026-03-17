"""Content analyzer to detect images in requests and determine routing."""

import logging
from typing import List, Tuple

from .vision_schemas import MultimodalMessage, ContentPart, ImageContent, TextContent

logger = logging.getLogger(__name__)


class ContentAnalyzer:
    """Analyzes message content to determine if vision model is needed."""

    @staticmethod
    def has_images(messages: List[MultimodalMessage]) -> bool:
        """Check if any message contains images."""
        for msg in messages:
            if isinstance(msg.content, str):
                continue

            # Check content parts
            for part in msg.content:
                if isinstance(part, dict):
                    if part.get("type") == "image_url":
                        return True
                elif hasattr(part, "type"):
                    if part.type == "image_url":
                        return True

        return False

    @staticmethod
    def extract_images_and_text(
        messages: List[MultimodalMessage],
    ) -> Tuple[List[str], str]:
        """
        Extract image URLs and text from messages.

        Returns:
            Tuple of (image_urls, combined_text)
        """
        image_urls = []
        text_parts = []

        for msg in messages:
            # Handle string content
            if isinstance(msg.content, str):
                text_parts.append(f"[{msg.role}]: {msg.content}")
                continue

            # Handle multimodal content
            msg_text = []
            for part in msg.content:
                if isinstance(part, str):
                    msg_text.append(part)
                elif isinstance(part, dict):
                    if part.get("type") == "text":
                        msg_text.append(part.get("text", ""))
                    elif part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url:
                            image_urls.append(url)
                            msg_text.append("[Image attached]")
                elif hasattr(part, "type"):
                    if part.type == "text":
                        msg_text.append(part.text)
                    elif part.type == "image_url":
                        image_urls.append(part.image_url.url)
                        msg_text.append("[Image attached]")

            if msg_text:
                text_parts.append(f"[{msg.role}]: {' '.join(msg_text)}")

        combined_text = "\n".join(text_parts)

        logger.info(
            f"Extracted {len(image_urls)} images and {len(combined_text)} chars of text"
        )
        return image_urls, combined_text

    @staticmethod
    def create_vision_prompt(text: str, image_count: int) -> List[MultimodalMessage]:
        """
        Create a vision-focused prompt for image analysis.

        Args:
            text: The text context from the conversation
            image_count: Number of images to analyze

        Returns:
            Messages formatted for vision model
        """
        system_msg = MultimodalMessage(
            role="system",
            content="You are a vision AI that analyzes images and provides detailed descriptions. "
            "Focus on technical details, objects, text, layouts, and anything relevant to the user's question.",
        )

        # Use the original text as context for what the user wants to know
        user_msg = MultimodalMessage(
            role="user",
            content=f"{text}\n\nPlease analyze the {'image' if image_count == 1 else f'{image_count} images'} "
            f"and provide a detailed description of what you see.",
        )

        return [system_msg, user_msg]

    @staticmethod
    def create_coding_prompt_with_vision(
        original_messages: List[MultimodalMessage], vision_analysis: str
    ) -> List[MultimodalMessage]:
        """
        Create a coding-focused prompt that includes vision analysis results.

        Args:
            original_messages: The original user messages
            vision_analysis: Description from the vision model

        Returns:
            Messages formatted for coding model with vision context
        """
        # Convert original messages to text-only
        text_messages = []
        for msg in original_messages:
            if isinstance(msg.content, str):
                text_messages.append(
                    MultimodalMessage(role=msg.role, content=msg.content)
                )
            else:
                # Extract text parts and replace images with vision analysis
                text_parts = []
                for part in msg.content:
                    if isinstance(part, str):
                        text_parts.append(part)
                    elif isinstance(part, dict):
                        if part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif part.get("type") == "image_url":
                            # Replace image with vision analysis
                            text_parts.append(
                                f"\n[Vision Analysis: {vision_analysis}]\n"
                            )
                    elif hasattr(part, "type"):
                        if part.type == "text":
                            text_parts.append(part.text)
                        elif part.type == "image_url":
                            text_parts.append(
                                f"\n[Vision Analysis: {vision_analysis}]\n"
                            )

                combined = " ".join(text_parts)
                text_messages.append(MultimodalMessage(role=msg.role, content=combined))

        return text_messages
