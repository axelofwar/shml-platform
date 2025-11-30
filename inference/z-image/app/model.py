"""Z-Image model management with dynamic loading/unloading."""
import gc
import io
import base64
import time
import threading
import logging
from typing import Optional
from datetime import datetime

import torch
from PIL import Image

from .config import (
    MODEL_ID, DEVICE, DTYPE, NUM_INFERENCE_STEPS,
    HF_HOME, OUTPUT_DIR, UNLOAD_TIMEOUT_SECONDS, YIELD_TO_TRAINING
)

logger = logging.getLogger(__name__)


class ZImageModel:
    """Manages Z-Image model lifecycle with training-aware resource management."""
    
    def __init__(self):
        self.pipe = None
        self.loaded = False
        self.loading = False
        self.last_used: Optional[datetime] = None
        self.images_generated = 0
        self.total_generation_time = 0.0
        self.start_time = time.time()
        self.yielded_to_training = False
        self._lock = threading.Lock()
        self._unload_timer: Optional[threading.Timer] = None
    
    def load(self) -> bool:
        """Load Z-Image pipeline on RTX 3090."""
        if self.loaded or self.loading:
            return self.loaded
        
        with self._lock:
            if self.loaded:
                return True
            
            self.loading = True
            logger.info(f"Loading {MODEL_ID} on {DEVICE}")
            
            try:
                from diffusers import ZImagePipeline
                
                # Determine dtype
                dtype = torch.bfloat16 if DTYPE == "bfloat16" else torch.float16
                
                self.pipe = ZImagePipeline.from_pretrained(
                    MODEL_ID,
                    torch_dtype=dtype,
                    cache_dir=str(HF_HOME),
                    local_files_only=True,  # Privacy: offline only
                )
                self.pipe.to(DEVICE)
                
                # Optional optimizations
                try:
                    self.pipe.transformer.set_attention_backend("flash")
                except Exception:
                    logger.info("Flash attention not available, using default")
                
                self.loaded = True
                self.yielded_to_training = False
                self.last_used = datetime.now()
                logger.info(f"Model loaded successfully. VRAM: {self.get_vram_usage():.2f}GB")
                return True
                
            except Exception as e:
                logger.error(f"Failed to load model: {e}")
                self.loading = False
                raise
            finally:
                self.loading = False
    
    def unload(self, reason: str = "manual") -> bool:
        """Unload model to free GPU memory for training."""
        with self._lock:
            if not self.loaded:
                return True
            
            logger.info(f"Unloading model (reason: {reason})")
            
            try:
                del self.pipe
                self.pipe = None
                self.loaded = False
                
                if reason == "training":
                    self.yielded_to_training = True
                
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
    
    def generate(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        width: int = 1024,
        height: int = 1024,
        num_inference_steps: int = NUM_INFERENCE_STEPS,
        guidance_scale: float = 0.0,
        seed: Optional[int] = None,
    ) -> tuple[Image.Image, int, float]:
        """Generate image. Returns (image, seed, generation_time)."""
        if not self.loaded:
            self.load()
        
        self._reset_unload_timer()
        start_time = time.time()
        
        try:
            # Set seed for reproducibility
            if seed is None:
                seed = torch.randint(0, 2**32 - 1, (1,)).item()
            
            generator = torch.Generator(DEVICE).manual_seed(seed)
            
            # Generate image
            result = self.pipe(
                prompt=prompt,
                negative_prompt=negative_prompt,
                height=height,
                width=width,
                num_inference_steps=num_inference_steps + 1,  # Turbo quirk
                guidance_scale=guidance_scale,
                generator=generator,
            )
            
            image = result.images[0]
            generation_time = time.time() - start_time
            
            # Update stats
            self.images_generated += 1
            self.total_generation_time += generation_time
            self.last_used = datetime.now()
            
            logger.info(f"Generated {width}x{height} image in {generation_time:.2f}s")
            
            return image, seed, generation_time
            
        except Exception as e:
            logger.error(f"Generation failed: {e}")
            raise
    
    def image_to_base64(self, image: Image.Image) -> str:
        """Convert PIL Image to base64 string."""
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode()
    
    def _reset_unload_timer(self):
        """Reset the auto-unload timer."""
        if self._unload_timer:
            self._unload_timer.cancel()
        
        if UNLOAD_TIMEOUT_SECONDS > 0 and YIELD_TO_TRAINING:
            self._unload_timer = threading.Timer(
                UNLOAD_TIMEOUT_SECONDS,
                self._auto_unload
            )
            self._unload_timer.daemon = True
            self._unload_timer.start()
    
    def _auto_unload(self):
        """Auto-unload after timeout to free RTX 3090 for training."""
        logger.info(f"Auto-unloading after {UNLOAD_TIMEOUT_SECONDS}s idle (freeing RTX 3090)")
        self.unload(reason="idle")
    
    def yield_to_training(self) -> bool:
        """Called when training starts - unload to free RTX 3090."""
        if not YIELD_TO_TRAINING:
            return False
        
        logger.info("Yielding GPU to training job")
        return self.unload(reason="training")
    
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
    
    def get_average_generation_time(self) -> float:
        """Get average generation time in seconds."""
        if self.images_generated == 0:
            return 0.0
        return self.total_generation_time / self.images_generated
    
    def get_uptime(self) -> float:
        """Get uptime in seconds."""
        return time.time() - self.start_time


# Global model instance
model_instance = ZImageModel()
