---
description: "Use when writing Python, TypeScript, or bash code. Covers async/await patterns, type annotations, logging, error handling, import ordering, naming conventions, and complexity budget."
applyTo: "**/*.py,**/*.ts,**/*.tsx,**/*.sh"
---

# 📝 Code Style Guide

## Python

### Type Annotations (required for all new code)

```python
from __future__ import annotations
from typing import Optional, Union, List, Dict, Any
from pathlib import Path

# Functions — annotate params and return type
def process_job(job_id: str, config: dict[str, Any]) -> JobResult:
    ...

# Classes — use dataclasses or Pydantic
from dataclasses import dataclass, field

@dataclass
class JobConfig:
    job_id: str
    resources: dict[str, int] = field(default_factory=dict)
    timeout_seconds: int = 300
```

### Async/Await

```python
# Use async for all I/O (HTTP, DB, file, subprocess)
import asyncio
import httpx

async def fetch_job_status(job_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}/jobs/{job_id}")
        response.raise_for_status()
        return response.json()

# Never block the event loop:
# ❌ time.sleep(1)
# ✅ await asyncio.sleep(1)
# ❌ requests.get(url)
# ✅ await client.get(url)
```

### Logging

```python
import logging

logger = logging.getLogger(__name__)  # Always use __name__

# Log levels: DEBUG (dev detail), INFO (normal ops), WARNING (degraded), ERROR (failure), CRITICAL (system failure)
logger.info("Job %s started, config=%s", job_id, config)
logger.warning("GPU memory low: %d MB remaining", remaining_mb)
logger.error("Job %s failed: %s", job_id, exc, exc_info=True)

# Never log secrets:
# ❌ logger.info("Auth token: %s", token)
# ✅ logger.info("Auth token present: %s", bool(token))
```

### Error Handling

```python
# Specific exceptions — never bare except
try:
    result = await service.call(payload)
except httpx.TimeoutException as e:
    logger.warning("Service timeout for job %s: %s", job_id, e)
    raise HTTPException(status_code=504, detail="Upstream timeout")
except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e))
# except Exception as e:  ← Only at top-level handlers

# Use context managers for resources
async with db.transaction():
    await db.execute(query, params)
```

### Import Conventions

```python
# Order: stdlib → third-party → local (separated by blank lines)
import os
import sys
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.models import JobConfig
from app.db import get_session
```

### Naming

```python
# snake_case for functions, variables, modules
def get_job_status(job_id: str) -> str: ...
ray_head_url = "http://ray-head:8265"

# PascalCase for classes
class JobSubmissionRequest(BaseModel): ...

# UPPERCASE for constants
MAX_RETRIES = 3
DEFAULT_TIMEOUT_SECONDS = 30

# Prefix private with _
_internal_cache: dict = {}
```

## Shell Scripts

```bash
#!/usr/bin/env bash
set -euo pipefail  # Always: exit on error, undefined var error, pipe failure

# Use [[ ]] not [ ]
if [[ -n "${VAR:-}" ]]; then

# Quote all variables
echo "Processing: ${JOB_ID}"
cp "${source_file}" "${dest_dir}/"

# Use $() not backticks
current_dir=$(pwd)

# Prefer -exec over xargs for file ops
find . -name "*.log" -exec rm {} +
```

## TypeScript / React (chat-ui-v2)

```typescript
// Explicit types — no implicit any
interface JobStatus {
  jobId: string;
  status: 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';
  createdAt: string;
  metrics?: Record<string, number>;
}

// Async/await for all promises
async function fetchJob(jobId: string): Promise<JobStatus> {
  const response = await fetch(`/api/v1/jobs/${jobId}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

// React: functional components + hooks
const JobCard: React.FC<{ job: JobStatus }> = ({ job }) => {
  const [expanded, setExpanded] = useState(false);
  return <div>...</div>;
};
```

## Complexity Budget

- Functions: ≤30 lines, single responsibility
- Files: ≤300 lines (split larger files)
- Nesting: ≤3 levels deep (extract early returns, helper functions)
- No "clever" one-liners that obscure intent

## What NOT to add without request

- Don't add docstrings to code you didn't change
- Don't add type annotations to existing untyped functions unless fixing a bug there
- Don't add error handling for impossible scenarios
- Don't create utility helpers for one-time use
- Don't refactor surrounding code when fixing a targeted bug
