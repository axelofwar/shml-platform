# Multi-Model Orchestration Plan
## Vision-Language + Coding Model Integration

**Version:** 1.0 | **Created:** 2025-12-07 | **Status:** Planning  
**Author:** AI Assistant | **Reviewer:** @axelofwar

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Current State Analysis](#current-state-analysis)
3. [Problem Statement](#problem-statement)
4. [Proposed Architecture](#proposed-architecture)
5. [GPU Resource Allocation](#gpu-resource-allocation)
6. [Implementation Plan](#implementation-plan)
7. [Known Issues & Constraints](#known-issues--constraints)
8. [Testing Strategy](#testing-strategy)
9. [Rollback Plan](#rollback-plan)
10. [References](#references)

---

## Executive Summary

### Goal
Create a smart multi-model orchestration system that automatically routes requests to the appropriate model:
- **Vision-Language Model (Qwen2-VL-2B)**: Processes screenshots and images, extracts context
- **Coding Model (Qwen2.5-Coder-7B/32B)**: Handles code generation with enriched context from VL

### Key Decisions
- **Option A Selected**: Qwen2-VL-2B (~2GB) + Qwen2.5-Coder-7B (~4.5GB) on RTX 2070
- **Handoff Protocol**: VL extracts structured context → injected as system message → Coding model generates
- **GPU Priority**: Training always takes precedence on RTX 3090 Ti

### Expected Outcomes
- Screenshots automatically processed and context extracted
- Seamless model switching invisible to user
- Always-available inference on RTX 2070 (fallback)
- Full quality inference on RTX 3090 Ti when not training

---

## Current State Analysis

### Existing Infrastructure

| Component | Location | Status |
|-----------|----------|--------|
| Inference Gateway | `inference/gateway/` | ✅ Working |
| Request Router | `inference/coding-model/app/request_router.py` | ✅ Working |
| Training Coordinator | `inference/coding-model/app/training_coordinator.py` | ✅ Working |
| Training Detector | `inference/coding-model/app/training_detector.py` | ✅ Working |
| Model Router (chat-api) | `inference/chat-api/app/model_router.py` | ✅ Working |
| Qwen3-VL Service | `inference/qwen3-vl/` | ⚠️ **Not processing images** |
| Coding Model Service | `inference/coding-model/` | ✅ Working |

### Current Model Configuration

```
RTX 3090 Ti (24GB) - GPU 0:
├── Primary: Qwen2.5-Coder-32B-AWQ (~18-20GB)
└── Training jobs (mutually exclusive with primary)

RTX 2070 (8GB, ~6.8GB usable) - GPU 1:
├── Fallback: Qwen2.5-Coder-3B-AWQ (~4GB) ← CURRENTLY
└── Qwen3-VL-8B (NOT actually being used for vision)
```

### Critical Discovery: Vision Model Not Processing Images

**File:** `inference/qwen3-vl/app/model.py` lines 130-140

```python
# CURRENT CODE - Only processes TEXT, not images!
inputs = self.processor(
    text=formatted,
    return_tensors="pt",
    padding=True,
).to(self.model.device)
```

The Qwen3-VL model is loaded but **never receives image input**. The API only accepts text messages.

**See:** [Known Issues - Vision Model](#known-issue-1-vision-model-not-processing-images)

---

## Problem Statement

### User Need
> "I want to paste a screenshot into the chat, have the system understand what's in it (error messages, UI state, code snippets), and then get intelligent coding assistance based on that visual context."

### Current Gaps

| Gap | Impact | Severity |
|-----|--------|----------|
| VL model not processing images | Screenshots ignored | 🔴 Critical |
| No image detection in requests | Can't auto-route to VL | 🔴 Critical |
| No handoff protocol | VL→Coding context lost | 🔴 Critical |
| Wrong model size on 2070 | 3B too weak, 8B doesn't fit with VL | 🟡 Medium |
| No structured VL output | Coding model gets raw text | 🟡 Medium |

### Design Requirements

1. **Auto-detect images** in incoming messages (base64, URLs, file uploads)
2. **Route to VL first** when images present
3. **Extract structured context** (code, errors, UI elements)
4. **Hand off to coding model** with enriched context
5. **Always available** on RTX 2070 (even during training)
6. **Transparent to user** (single API, automatic orchestration)

---

## Proposed Architecture

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         USER REQUEST                                         │
│                              │                                               │
│                              ▼                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    INFERENCE GATEWAY                                   │  │
│  │                                                                        │  │
│  │   ┌─────────────┐     ┌─────────────┐     ┌─────────────────────┐    │  │
│  │   │   Content   │     │   Route     │     │   Orchestrate       │    │  │
│  │   │   Analyzer  │ ──▶ │   Decision  │ ──▶ │   Execution         │    │  │
│  │   └─────────────┘     └─────────────┘     └─────────────────────┘    │  │
│  │         │                    │                      │                 │  │
│  │         ▼                    ▼                      ▼                 │  │
│  │   Has images?          Text only?            VL → Coding?            │  │
│  │   Base64/URL?          Simple/Complex?       Direct Coding?          │  │
│  │                                                                        │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                              │                                               │
│              ┌───────────────┼───────────────┐                              │
│              ▼               ▼               ▼                              │
│  ┌─────────────────┐  ┌───────────┐  ┌─────────────────┐                   │
│  │   VISION PATH   │  │  DIRECT   │  │  COMPLEX PATH   │                   │
│  │                 │  │  CODING   │  │                 │                   │
│  │  Qwen2-VL-2B   │  │           │  │ Qwen2.5-32B    │                   │
│  │       │         │  │ Qwen2.5  │  │ (if available)  │                   │
│  │       ▼         │  │ -7B/3B   │  │       or        │                   │
│  │ ImageAnalysis   │  │          │  │ Queue + Wait    │                   │
│  │       │         │  │          │  │                 │                   │
│  │       ▼         │  │          │  │                 │                   │
│  │  Coding Model   │  │          │  │                 │                   │
│  └─────────────────┘  └───────────┘  └─────────────────┘                   │
│                              │                                               │
│                              ▼                                               │
│                         RESPONSE                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Vision-Language Handoff Protocol

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        VL → CODING HANDOFF                                    │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  1. USER MESSAGE with screenshot                                              │
│     {                                                                         │
│       "role": "user",                                                         │
│       "content": [                                                            │
│         {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}│
│         {"type": "text", "text": "Fix this error"}                            │
│       ]                                                                       │
│     }                                                                         │
│                                                                               │
│  2. VL MODEL processes image → outputs ImageAnalysis                          │
│     {                                                                         │
│       "description": "VS Code editor showing Python file with red underline", │
│       "code_visible": "def calculate(x):\n    return x.upper()",              │
│       "errors_visible": ["AttributeError: 'int' object has no 'upper'"],      │
│       "ui_context": "Python file open, Problems panel shows 1 error",         │
│       "file_info": {"language": "python", "filename": "calculator.py"},       │
│       "suggested_action": "Fix type error - upper() called on int"            │
│     }                                                                         │
│                                                                               │
│  3. GATEWAY injects as system context                                         │
│     {                                                                         │
│       "role": "system",                                                       │
│       "content": "[Visual Context]\nThe user shared a screenshot showing:\n..."│
│     }                                                                         │
│                                                                               │
│  4. CODING MODEL receives text-only request with rich context                 │
│     - Original user message (text part only)                                  │
│     - Injected visual context as system message                               │
│     - Generates code fix                                                      │
│                                                                               │
└──────────────────────────────────────────────────────────────────────────────┘
```

### New Schemas

**File to create:** `inference/gateway/app/vision_schemas.py`

```python
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum

class ImageContentType(Enum):
    SCREENSHOT = "screenshot"
    CODE_SNIPPET = "code_snippet"
    DIAGRAM = "diagram"
    ERROR_MESSAGE = "error_message"
    UI_MOCKUP = "ui_mockup"
    UNKNOWN = "unknown"

class FileInfo(BaseModel):
    """Information about files visible in screenshot."""
    filename: Optional[str] = None
    language: Optional[str] = None
    path: Optional[str] = None

class UIElement(BaseModel):
    """Detected UI element."""
    element_type: str  # button, input, panel, tab, etc.
    label: Optional[str] = None
    state: Optional[str] = None  # active, disabled, error, etc.

class ImageAnalysis(BaseModel):
    """Structured output from vision model analysis."""

    # Core analysis
    content_type: ImageContentType
    description: str = Field(..., description="What the image shows")

    # Code-specific
    code_visible: Optional[str] = Field(None, description="Any code visible in image")
    code_language: Optional[str] = Field(None, description="Programming language if detected")

    # Error detection
    errors_visible: List[str] = Field(default_factory=list, description="Error messages")
    warnings_visible: List[str] = Field(default_factory=list, description="Warning messages")

    # UI context
    ui_context: Optional[str] = Field(None, description="UI state description")
    ui_elements: List[UIElement] = Field(default_factory=list)

    # File info
    file_info: Optional[FileInfo] = None

    # Actionable summary
    suggested_action: str = Field(..., description="What the user likely wants")

    # Confidence
    confidence: float = Field(default=0.8, ge=0, le=1)

    def to_system_prompt(self) -> str:
        """Convert analysis to system prompt for coding model."""
        parts = ["[Visual Context from Screenshot]"]
        parts.append(f"Content Type: {self.content_type.value}")
        parts.append(f"Description: {self.description}")

        if self.code_visible:
            parts.append(f"\nCode Visible ({self.code_language or 'unknown'}):")
            parts.append(f"```{self.code_language or ''}\n{self.code_visible}\n```")

        if self.errors_visible:
            parts.append(f"\nErrors Detected:")
            for err in self.errors_visible:
                parts.append(f"  - {err}")

        if self.ui_context:
            parts.append(f"\nUI State: {self.ui_context}")

        if self.file_info and self.file_info.filename:
            parts.append(f"\nFile: {self.file_info.filename}")

        parts.append(f"\nLikely User Intent: {self.suggested_action}")

        return "\n".join(parts)
```

---

## GPU Resource Allocation

### Target Configuration (Option A)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        GPU ALLOCATION - OPTION A                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  RTX 3090 Ti (24GB VRAM) - GPU 0                                            │
│  ════════════════════════════════                                           │
│  │                                                                          │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  │  TRAINING MODE (Priority 1)                                     │    │
│  │  │  • Face detection training: ~18-21GB                            │    │
│  │  │  • Z-Image for data augmentation (on-demand): ~6GB              │    │
│  │  │  • All inference models UNLOADED                                │    │
│  │  └─────────────────────────────────────────────────────────────────┘    │
│  │                                                                          │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  │  INFERENCE MODE (When training idle)                            │    │
│  │  │  • Qwen2.5-Coder-32B-AWQ: ~18-20GB (primary coding)             │    │
│  │  │  • Z-Image: ~6GB (on-demand, time-shared)                       │    │
│  │  │  • Yields immediately when training signal detected             │    │
│  │  └─────────────────────────────────────────────────────────────────┘    │
│  │                                                                          │
│                                                                              │
│  RTX 2070 (8GB VRAM, ~6.8GB usable due to display) - GPU 1                  │
│  ════════════════════════════════════════════════════════                   │
│  │                                                                          │
│  │  ┌─────────────────────────────────────────────────────────────────┐    │
│  │  │  ALWAYS AVAILABLE (no yielding)                                 │    │
│  │  │  • Qwen2-VL-2B (vision): ~2GB                                   │    │
│  │  │  • Qwen2.5-Coder-7B-AWQ (fallback coding): ~4.5GB               │    │
│  │  │  • Total: ~6.5GB (fits in 6.8GB available)                      │    │
│  │  └─────────────────────────────────────────────────────────────────┘    │
│  │                                                                          │
│  │  ⚠️  Display overhead: ~1.2GB (3 monitors connected)                    │
│  │  📄 See: docs/internal/GPU_MEMORY_ANALYSIS.md                           │
│  │                                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Memory Budget Detail

| GPU | Component | VRAM | Notes |
|-----|-----------|------|-------|
| **GPU 0** | Total | 24,564 MiB | RTX 3090 Ti |
| | Display | ~0 | Disabled |
| | Training peak | ~21,000 MiB | During validation |
| | Qwen-32B-AWQ | ~18,500 MiB | When not training |
| | Z-Image | ~6,500 MiB | On-demand |
| **GPU 1** | Total | 8,192 MiB | RTX 2070 |
| | Display | ~1,200 MiB | 3 monitors |
| | Available | ~6,800 MiB | After display |
| | Qwen2-VL-2B | ~2,000 MiB | Vision model |
| | Qwen2.5-Coder-7B-AWQ | ~4,500 MiB | Fallback coding |
| | **Headroom** | ~300 MiB | Safety margin |

### Model Quality Comparison

| Model | Parameters | Quality* | Context | VRAM (4-bit) |
|-------|------------|----------|---------|--------------|
| Qwen2.5-Coder-32B-AWQ | 32B | ~90% | 4K | ~18GB |
| Qwen2.5-Coder-7B-AWQ | 7B | ~82% | 8K | ~4.5GB |
| Qwen2.5-Coder-3B-AWQ | 3B | ~75% | 8K | ~2GB |
| Qwen2-VL-7B | 7B | Good vision | 32K | ~4.5GB |
| Qwen2-VL-2B | 2B | Adequate vision | 32K | ~2GB |

*Quality relative to Claude Sonnet for coding tasks (subjective estimate)

---

## Implementation Plan

### Phase 1: Vision Model Fix (Priority: Critical)

**Goal:** Make Qwen-VL actually process images

**Files to modify:**
- `inference/qwen3-vl/app/schemas.py` - Add multimodal message support
- `inference/qwen3-vl/app/model.py` - Implement image processing
- `inference/qwen3-vl/app/main.py` - Update API to accept images

**Changes:**

1. **Update schemas.py** to support OpenAI-style multimodal messages:
```python
class ContentPart(BaseModel):
    type: Literal["text", "image_url"]
    text: Optional[str] = None
    image_url: Optional[dict] = None  # {"url": "data:image/..."}

class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: Union[str, List[ContentPart]]  # Support both formats
```

2. **Update model.py** to process images:
```python
def generate(self, messages: List[Message], **kwargs):
    # Extract images from messages
    images = self._extract_images(messages)
    text = self._extract_text(messages)

    # Process with vision
    if images:
        inputs = self.processor(
            text=text,
            images=images,  # <-- ADD IMAGE INPUT
            return_tensors="pt",
            padding=True,
        ).to(self.model.device)
    else:
        inputs = self.processor(
            text=text,
            return_tensors="pt",
            padding=True,
        ).to(self.model.device)
```

**Estimated effort:** 2-4 hours

### Phase 2: Model Swap (Priority: High)

**Goal:** Replace Qwen3-VL-8B with Qwen2-VL-2B, upgrade fallback to 7B

**Files to modify:**
- `inference/docker-compose.inference.yml` - GPU assignments
- `inference/qwen3-vl/app/config.py` - Model ID
- `inference/coding-model/docker-compose.yml` - Fallback model
- `inference/scripts/download_models.sh` - Add new models

**Changes:**

1. **Download new models:**
```bash
# Qwen2-VL-2B for vision
huggingface-cli download Qwen/Qwen2-VL-2B-Instruct

# Qwen2.5-Coder-7B for fallback (already have AWQ version testing script)
huggingface-cli download Qwen/Qwen2.5-Coder-7B-Instruct-AWQ
```

2. **Update docker-compose.inference.yml:**
```yaml
qwen-vl-api:  # Renamed from qwen3-vl-api
  environment:
    - MODEL_ID=Qwen/Qwen2-VL-2B-Instruct
    - QUANTIZATION=int4
    - DEVICE=cuda:1  # RTX 2070
  deploy:
    resources:
      reservations:
        devices:
          - device_ids: ["1"]  # GPU 1
```

3. **Update coding-model fallback:**
```yaml
coding-model-fallback:
  environment:
    - MODEL_ID=Qwen/Qwen2.5-Coder-7B-Instruct-AWQ  # Upgrade from 3B
    - MAX_MODEL_LEN=4096  # Reduced context for memory
```

**Estimated effort:** 2-3 hours

### Phase 3: Gateway Orchestration (Priority: High)

**Goal:** Implement auto-routing and VL→Coding handoff

**Files to create:**
- `inference/gateway/app/vision_schemas.py` - ImageAnalysis schema
- `inference/gateway/app/content_analyzer.py` - Image detection
- `inference/gateway/app/orchestrator.py` - Multi-model orchestration

**Files to modify:**
- `inference/gateway/app/main.py` - Add orchestration endpoints
- `inference/gateway/app/config.py` - Add VL service URL

**New Components:**

1. **Content Analyzer:**
```python
class ContentAnalyzer:
    """Analyzes incoming messages for content type."""

    def detect_images(self, messages: List[dict]) -> List[ImageInfo]:
        """Detect images in messages (base64, URLs, file refs)."""
        images = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                for part in content:
                    if part.get("type") == "image_url":
                        images.append(ImageInfo(
                            source="inline",
                            url=part["image_url"]["url"]
                        ))
            elif isinstance(content, str):
                # Check for base64 inline
                if "data:image" in content:
                    images.append(ImageInfo(source="inline_base64"))
                # Check for image tags/markers
                if "[screenshot]" in content.lower():
                    images.append(ImageInfo(source="marker"))
        return images

    def analyze_complexity(self, messages: List[dict]) -> float:
        """Score request complexity (0-1)."""
        # Use existing RequestRouter logic
        pass
```

2. **Orchestrator:**
```python
class MultiModelOrchestrator:
    """Orchestrates requests across VL and Coding models."""

    async def process_request(self, request: ChatRequest) -> ChatResponse:
        # Step 1: Analyze content
        images = self.analyzer.detect_images(request.messages)

        if images:
            # Step 2: Process through VL
            vl_response = await self.vl_client.analyze_images(
                messages=request.messages,
                images=images
            )

            # Step 3: Parse structured analysis
            analysis = ImageAnalysis.parse_obj(vl_response)

            # Step 4: Inject as system context
            enriched_messages = self._inject_visual_context(
                request.messages,
                analysis
            )

            # Step 5: Route to coding model
            return await self.coding_client.complete(enriched_messages)

        else:
            # Direct to coding model
            return await self.coding_client.complete(request.messages)
```

**Estimated effort:** 4-6 hours

### Phase 4: Integration Testing (Priority: High)

**Goal:** Verify end-to-end flow works correctly

**Test Cases:**

1. **Text-only request** → Routes directly to coding model
2. **Request with screenshot** → VL → Coding handoff
3. **Training active** → Falls back to 7B (no 32B access)
4. **Training active + screenshot** → VL → 7B fallback
5. **Complex request during training** → Queued for 32B with wait time

**Files to create:**
- `inference/tests/test_orchestrator.py`
- `inference/tests/test_vl_handoff.py`

**Estimated effort:** 2-3 hours

### Phase 5: UI Integration (Priority: Medium)

**Goal:** Enable screenshot paste in chat-ui

**Files to modify:**
- `chat-ui/src/components/ChatInput.tsx` - Add paste handler
- `chat-ui/src/services/api.ts` - Support multimodal messages

**Changes:**

1. **Add paste handler:**
```typescript
const handlePaste = async (e: ClipboardEvent) => {
  const items = e.clipboardData?.items;
  for (const item of items || []) {
    if (item.type.startsWith('image/')) {
      const blob = item.getAsFile();
      const base64 = await blobToBase64(blob);
      // Add to message as image content
      setMessageContent([
        ...messageContent,
        { type: 'image_url', image_url: { url: base64 } }
      ]);
    }
  }
};
```

**Estimated effort:** 2-3 hours

---

## Known Issues & Constraints

### Known Issue 1: Vision Model Not Processing Images

**Location:** `inference/qwen3-vl/app/model.py` lines 130-140

**Problem:** The Qwen3-VL model is loaded but only receives text input. The `processor()` call does not include the `images` parameter.

**Impact:** Screenshots are ignored; VL model acts as text-only model

**Fix:** Phase 1 of implementation plan

**Reference:** This document, [Current State Analysis](#current-state-analysis)

---

### Known Issue 2: "7B Too Large" Claim is Incorrect

**Location:** `inference/coding-model/docker-compose.yml` line 120

**Original Comment:**
```yaml
# Qwen2.5-Coder-3B AWQ - fits in 8GB VRAM (7B is too large)
```

**Reality:**
- Qwen2.5-Coder-7B-AWQ: ~4.5GB VRAM
- Display overhead: ~1.2GB
- Available: ~6.8GB
- **7B DOES fit** with ~2GB headroom

**Evidence:** `docs/internal/GPU_MEMORY_ANALYSIS.md` shows 7B at ~4.5GB

**Fix:** Phase 2 upgrades fallback from 3B → 7B

---

### Known Issue 3: Display Overhead on GPU 1

**Location:** `docs/internal/GPU_MEMORY_ANALYSIS.md`

**Problem:** RTX 2070 has 3 monitors connected, consuming ~1.2GB VRAM

**Available VRAM:** 8GB - 1.2GB = ~6.8GB

**Mitigation:** Plan accounts for this; Option A fits in 6.8GB

**Alternative:** Go headless to reclaim 1.2GB (not recommended during development)

---

### Known Issue 4: MPS/GPU Sharing Failed

**Location:** `docs/internal/archived_approaches/README.md`

**Problem:** Attempted to use NVIDIA MPS for concurrent GPU sharing between training and inference

**Why it failed:**
- Memory math: 32B model (20GB) + training (12GB) > 24GB VRAM
- MPS blocks Docker containers at 100% thread allocation
- OOM risk during training validation peaks

**Current solution:** Mutually exclusive access (yield-based)

**Reference:** `docs/internal/archived_approaches/DYNAMIC_MPS_DESIGN.md`

---

### Known Issue 5: Qwen3-VL vs Qwen2-VL Naming Confusion

**Problem:** Codebase references "Qwen3-VL" but model is actually "Qwen2-VL"

**Files affected:**
- `inference/qwen3-vl/` directory name
- `inference/docker-compose.inference.yml` service name

**Plan:** Keep directory name for compatibility, but use correct model ID internally

---

### Constraint 1: Training Takes Priority

**Requirement:** Training jobs on RTX 3090 Ti always take precedence

**Implementation:**
- `YIELD_ON_TRAINING=true` environment variable
- Training detector monitors Ray jobs + file signals
- Health check fails during training → Traefik routes to fallback

**Reference:** `inference/coding-model/app/training_detector.py`

---

### Constraint 2: Network Must Be shml-platform

**Requirement:** All inference services use `shml-platform` network (external)

**Previous issue:** Some compose files referenced `ml-platform` network

**Fix applied:** 2025-12-07 - All compose files now use `shml-platform`

**Verification:**
```bash
grep -E "networks:|external:" inference/docker-compose.inference.yml
```

---

### Constraint 3: Redis Hostname is shml-redis

**Requirement:** Redis container is named `shml-redis`, not `shml-platform-redis`

**Previous issue:** Some configs used wrong hostname

**Fix applied:** 2025-12-07

**Reference:** `inference/docker-compose.inference.yml` REDIS_HOST variable

---

## Testing Strategy

### Unit Tests

| Test | File | Coverage |
|------|------|----------|
| Image detection | `test_content_analyzer.py` | Base64, URLs, markers |
| ImageAnalysis schema | `test_vision_schemas.py` | Serialization, to_system_prompt() |
| Handoff protocol | `test_orchestrator.py` | VL→Coding flow |

### Integration Tests

| Test | Scenario | Expected |
|------|----------|----------|
| Text only | "Write a function" | Direct to coding model |
| Screenshot | [image] + "Fix this" | VL → Coding |
| Training active | Any request | Falls back to 7B |
| Complex + training | "Refactor entire codebase" | Queue for 32B |

### Manual Tests

```bash
# Test 1: VL processes image
curl -X POST http://localhost/api/llm/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{
      "role": "user",
      "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBOR..."}},
        {"type": "text", "text": "What do you see?"}
      ]
    }]
  }'

# Test 2: VL → Coding handoff
curl -X POST http://localhost/api/coding/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{
      "role": "user",
      "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBOR..."}},
        {"type": "text", "text": "Fix the error shown in this screenshot"}
      ]
    }]
  }'
```

---

## Rollback Plan

### If Phase 1 (VL Fix) Fails
- Revert changes to qwen3-vl service
- VL model continues as text-only (current state)
- No impact on coding model

### If Phase 2 (Model Swap) Fails
- Revert to Qwen2.5-Coder-3B fallback
- Keep Qwen3-VL-8B (but won't fit with coding on 2070)
- May need to time-share models

### If Phase 3 (Orchestration) Fails
- Disable orchestrator
- Direct routing to individual services
- Manual model selection in UI

### Docker Rollback Commands

```bash
# Revert to previous compose
cd /home/axelofwar/Projects/shml-platform
git checkout HEAD~1 -- inference/docker-compose.inference.yml

# Restart services
./start_all_safe.sh restart inference
```

---

## References

### Internal Documentation

| Document | Path | Relevance |
|----------|------|-----------|
| GPU Memory Analysis | `docs/internal/GPU_MEMORY_ANALYSIS.md` | VRAM budgets, model sizes |
| Archived Approaches | `docs/internal/archived_approaches/README.md` | Why MPS failed |
| Architecture | `docs/internal/ARCHITECTURE.md` | Overall system design |
| Troubleshooting | `docs/internal/TROUBLESHOOTING.md` | Common issues |

### Code References

| Component | Path | Purpose |
|-----------|------|---------|
| Request Router | `inference/coding-model/app/request_router.py` | Complexity analysis |
| Training Detector | `inference/coding-model/app/training_detector.py` | Multi-source detection |
| Training Coordinator | `inference/coding-model/app/training_coordinator.py` | Checkpoint/pause logic |
| Model Router | `inference/chat-api/app/model_router.py` | Basic routing |
| Gateway | `inference/gateway/app/main.py` | API gateway |
| Qwen3-VL Model | `inference/qwen3-vl/app/model.py` | Vision model (needs fix) |

### External References

| Resource | URL | Notes |
|----------|-----|-------|
| Anthropic SDK | https://github.com/anthropics/anthropic-sdk-python | Tool runner pattern |
| Qwen2-VL | https://huggingface.co/Qwen/Qwen2-VL-2B-Instruct | Vision model docs |
| Qwen2.5-Coder | https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-AWQ | Coding model docs |

### Test Scripts

| Script | Path | Purpose |
|--------|------|---------|
| Fallback Model Test | `inference/coding-model/test_fallback_model.sh` | Safe model testing |
| Download Models | `inference/scripts/download_models.sh` | Model downloads |

---

## Appendix A: Claude SDK Principles Applied

Based on analysis of Anthropic SDK patterns:

### Implemented

| Principle | Implementation |
|-----------|----------------|
| Tool Runner Loop | Orchestrator iterates VL→Coding |
| Streaming | Both models support streaming |
| Token Counting | RequestRouter estimates tokens |
| Retry Logic | httpx client with retries |

### To Implement

| Principle | Priority | Notes |
|-----------|----------|-------|
| Structured Tool Output | High | ImageAnalysis schema |
| Request IDs | Medium | Trace across handoff |
| Batch Processing | Low | Multiple screenshots |

---

## Appendix B: Quick Start for New Chat

If starting this task in a new chat without context:

```markdown
## Context
I'm implementing multi-model orchestration for the shml-platform inference stack.
See: docs/internal/MULTI_MODEL_ORCHESTRATION_PLAN.md

## Current State
- Qwen3-VL exists but doesn't process images (bug)
- Fallback is 3B (should be 7B)
- No auto-routing between VL and coding models

## Goal
- Fix VL to process images
- Swap to Qwen2-VL-2B + Qwen2.5-Coder-7B on RTX 2070
- Implement gateway orchestration for auto VL→Coding handoff

## Start With
Phase 1: Fix vision model in inference/qwen3-vl/app/model.py
```

---

**Document Status:** Ready for Implementation  
**Next Action:** Begin Phase 1 - Vision Model Fix
