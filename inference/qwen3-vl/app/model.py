"""Qwen3-VL model management with dynamic loading/unloading."""

import gc
import time
import threading
import logging
import base64
import io
from typing import Optional, List, Union
from datetime import datetime

import torch
from PIL import Image
import httpx

from .config import (
    MODEL_ID,
    QUANTIZATION,
    DEVICE,
    MAX_NEW_TOKENS,
    HF_HOME,
    UNLOAD_TIMEOUT_SECONDS,
    YIELD_TO_TRAINING,
)
from .schemas import Message, ContentPart, TextContent, ImageContent

logger = logging.getLogger(__name__)


class Qwen3VLModel:
    """Manages Qwen3-VL model lifecycle with resource-aware loading."""

    def __init__(self):
        self.model = None
        self.processor = None
        self.loaded = False
        self.loading = False
        self.last_used: Optional[datetime] = None
        self.requests_served = 0
        self.total_latency_ms = 0.0
        self.start_time = time.time()
        self._lock = threading.Lock()
        self._unload_timer: Optional[threading.Timer] = None

    def load(self) -> bool:
        """Load model with INT4 quantization for RTX 2070."""
        if self.loaded or self.loading:
            return self.loaded

        with self._lock:
            if self.loaded:
                return True

            self.loading = True
            logger.info(
                f"Loading {MODEL_ID} with {QUANTIZATION} quantization on {DEVICE}"
            )

            try:
                from transformers import Qwen2VLForConditionalGeneration, AutoProcessor

                # Quantization config for INT4
                quantization_config = None
                if QUANTIZATION == "int4":
                    from transformers import BitsAndBytesConfig

                    quantization_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.float16,
                        bnb_4bit_use_double_quant=True,
                        bnb_4bit_quant_type="nf4",
                    )
                elif QUANTIZATION == "int8":
                    from transformers import BitsAndBytesConfig

                    quantization_config = BitsAndBytesConfig(load_in_8bit=True)

                # Load model
                self.model = Qwen2VLForConditionalGeneration.from_pretrained(
                    MODEL_ID,
                    quantization_config=quantization_config,
                    device_map=DEVICE if quantization_config else "auto",
                    torch_dtype=torch.float16,
                    cache_dir=str(HF_HOME),
                    local_files_only=True,  # Privacy: offline only
                )

                self.processor = AutoProcessor.from_pretrained(
                    MODEL_ID,
                    cache_dir=str(HF_HOME),
                    local_files_only=True,
                )

                self.loaded = True
                self.last_used = datetime.now()
                logger.info(
                    f"Model loaded successfully. VRAM: {self.get_vram_usage():.2f}GB"
                )
                return True

            except Exception as e:
                logger.error(f"Failed to load model: {e}")
                self.loading = False
                raise
            finally:
                self.loading = False

    def unload(self) -> bool:
        """Unload model to free GPU memory."""
        with self._lock:
            if not self.loaded:
                return True

            logger.info("Unloading model to free GPU memory")

            try:
                del self.model
                del self.processor
                self.model = None
                self.processor = None
                self.loaded = False

                # Force garbage collection
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()

                logger.info("Model unloaded successfully")
                return True

            except Exception as e:
                logger.error(f"Failed to unload model: {e}")
                return False

    def generate(self, messages: List[Message], **kwargs) -> tuple[str, int, int]:
        """Generate completion from messages. Returns (text, prompt_tokens, completion_tokens)."""
        if not self.loaded:
            self.load()

        self._reset_unload_timer()
        start_time = time.time()

        try:
            # Extract text and images from messages
            formatted_text, images = self._format_messages(messages)

            # Tokenize with images if present
            if images:
                inputs = self.processor(
                    text=formatted_text,
                    images=images,
                    return_tensors="pt",
                    padding=True,
                ).to(self.model.device)
            else:
                inputs = self.processor(
                    text=formatted_text,
                    return_tensors="pt",
                    padding=True,
                ).to(self.model.device)

            prompt_tokens = inputs.input_ids.shape[1]

            # Generate
            max_tokens = min(kwargs.get("max_tokens", MAX_NEW_TOKENS), MAX_NEW_TOKENS)

            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=max_tokens,
                    temperature=kwargs.get("temperature", 0.7),
                    top_p=kwargs.get("top_p", 0.9),
                    do_sample=True,
                    pad_token_id=self.processor.tokenizer.pad_token_id,
                )

            # Decode
            generated_ids = outputs[0][prompt_tokens:]
            completion_tokens = len(generated_ids)
            response_text = self.processor.decode(
                generated_ids, skip_special_tokens=True
            )

            # Update stats
            latency_ms = (time.time() - start_time) * 1000
            self.requests_served += 1
            self.total_latency_ms += latency_ms
            self.last_used = datetime.now()

            logger.info(f"Generated {completion_tokens} tokens in {latency_ms:.0f}ms")

            return response_text, prompt_tokens, completion_tokens

        except Exception as e:
            logger.error(f"Generation failed: {e}")
            raise

    def _format_messages(
        self, messages: List[Message]
    ) -> tuple[str, Optional[List[Image.Image]]]:
        """Format messages for Qwen chat template. Returns (formatted_text, images)."""
        formatted = ""
        images = []

        for msg in messages:
            # Handle content - can be string or list of parts
            text_content = ""

            if isinstance(msg.content, str):
                text_content = msg.content
            else:
                # Process content parts
                for part in msg.content:
                    if isinstance(part, str):
                        text_content += part
                    elif isinstance(part, dict):
                        # Handle dict format from API
                        if part.get("type") == "text":
                            text_content += part.get("text", "")
                        elif part.get("type") == "image_url":
                            image_url = part.get("image_url", {}).get("url", "")
                            if image_url:
                                try:
                                    img = self._load_image(image_url)
                                    images.append(img)
                                except Exception as e:
                                    logger.error(f"Failed to load image: {e}")
                    else:
                        # Handle Pydantic models
                        if hasattr(part, "type"):
                            if part.type == "text":
                                text_content += part.text
                            elif part.type == "image_url":
                                try:
                                    img = self._load_image(part.image_url.url)
                                    images.append(img)
                                except Exception as e:
                                    logger.error(f"Failed to load image: {e}")

            # Format with chat template
            if msg.role == "system":
                formatted += f"<|im_start|>system\n{text_content}<|im_end|>\n"
            elif msg.role == "user":
                formatted += f"<|im_start|>user\n{text_content}<|im_end|>\n"
            elif msg.role == "assistant":
                formatted += f"<|im_start|>assistant\n{text_content}<|im_end|>\n"

        formatted += "<|im_start|>assistant\n"
        return formatted, images if images else None

    def _load_image(self, image_url: str) -> Image.Image:
        """Load image from data URI or HTTP(S) URL."""
        if image_url.startswith("data:image"):
            # Base64 data URI
            base64_data = image_url.split(",")[1]
            image_data = base64.b64decode(base64_data)
            return Image.open(io.BytesIO(image_data))
        elif image_url.startswith("http"):
            # HTTP(S) URL
            response = httpx.get(image_url, timeout=10.0)
            response.raise_for_status()
            return Image.open(io.BytesIO(response.content))
        else:
            raise ValueError(f"Unsupported image URL format: {image_url}")

    def _reset_unload_timer(self):
        """Reset the auto-unload timer."""
        if self._unload_timer:
            self._unload_timer.cancel()

        if UNLOAD_TIMEOUT_SECONDS > 0:
            self._unload_timer = threading.Timer(
                UNLOAD_TIMEOUT_SECONDS, self._auto_unload
            )
            self._unload_timer.daemon = True
            self._unload_timer.start()

    def _auto_unload(self):
        """Auto-unload after timeout (only if not primary GPU)."""
        # Don't auto-unload from RTX 2070 - it's always available
        if "cuda:0" in DEVICE:
            logger.info("Skipping auto-unload on primary GPU (RTX 2070)")
            return

        logger.info(f"Auto-unloading after {UNLOAD_TIMEOUT_SECONDS}s idle")
        self.unload()

    def get_vram_usage(self) -> float:
        """Get current VRAM usage in GB."""
        if not torch.cuda.is_available():
            return 0.0

        device_idx = int(DEVICE.split(":")[-1]) if ":" in DEVICE else 0
        return torch.cuda.memory_allocated(device_idx) / (1024**3)

    def get_vram_total(self) -> float:
        """Get total VRAM in GB."""
        if not torch.cuda.is_available():
            return 0.0

        device_idx = int(DEVICE.split(":")[-1]) if ":" in DEVICE else 0
        return torch.cuda.get_device_properties(device_idx).total_memory / (1024**3)

    def get_average_latency(self) -> float:
        """Get average latency in ms."""
        if self.requests_served == 0:
            return 0.0
        return self.total_latency_ms / self.requests_served

    def get_uptime(self) -> float:
        """Get uptime in seconds."""
        return time.time() - self.start_time


# Global model instance
model_instance = Qwen3VLModel()
