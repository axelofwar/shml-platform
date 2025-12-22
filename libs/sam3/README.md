# SAM3 Integration

This directory is reserved for local SAM3 integration if we decide to move away from the Roboflow API or need a local fallback.

## Current Strategy
We are currently using **Roboflow Rapid** for SAM3 inference to leverage:
- **Exemplar Prompts**: Box one -> Find all.
- **Zero-setup**: No local GPU memory management hell.
- **Auto-scaling**: Roboflow handles the infrastructure.

## Local Setup (Future)
If we need to run locally:
1. Clone the SAM3 repo (when available/if open source).
2. Install dependencies.
3. Use `ray_compute/jobs/annotation/sam3_roboflow_pipeline.py` as a reference for the interface.
