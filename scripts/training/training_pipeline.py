#!/usr/bin/env python3
"""Training Pipeline Automation — SHML Platform.

Declarative training pipeline runner that:
1. Reads pipeline definitions from YAML configs
2. Manages training lifecycles (submit → monitor → checkpoint → next stage)
3. Sends Telegram notifications for stage transitions, failures, completions
4. Integrates with MLflow for experiment tracking
5. Supports curriculum learning (multi-stage progressive training)

Usage:
    python training_pipeline.py --config pipelines/face_detection.yml
    python training_pipeline.py --config pipelines/face_detection.yml --dry-run
    python training_pipeline.py --status  # Show all active pipelines
    python training_pipeline.py --resume <pipeline-id>

Designed to run as a long-lived service in Docker or as a Ray job.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_script_dir = os.path.dirname(os.path.abspath(__file__))
for p in [
    os.path.join(_script_dir, "..", "libs"),
    os.path.join(_script_dir, "..", "..", "libs"),
]:
    p = os.path.abspath(p)
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("training-pipeline")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
RAY_HEAD = os.getenv("RAY_HEAD_ADDRESS", "ray-head:8265")
MLFLOW_URL = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow-server:5000")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT_ID", "")
PIPELINE_STATE_DIR = os.getenv("PIPELINE_STATE_DIR", "/var/lib/training-pipelines")
POLL_INTERVAL = int(os.getenv("PIPELINE_POLL_INTERVAL", "60"))


# ---------------------------------------------------------------------------
# Telegram helper
# ---------------------------------------------------------------------------
def send_telegram(msg: str) -> None:
    """Send a Telegram notification (best-effort)."""
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT and requests):
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        logger.warning("Telegram send failed")


# ---------------------------------------------------------------------------
# Pipeline definition (loaded from YAML)
# ---------------------------------------------------------------------------
class PipelineStage:
    """Single training stage within a pipeline."""

    def __init__(self, cfg: dict[str, Any]):
        self.name: str = cfg["name"]
        self.entrypoint: str = cfg["entrypoint"]
        self.epochs: int = cfg.get("epochs", 30)
        self.batch_size: int = cfg.get("batch_size", 4)
        self.grad_accum: int = cfg.get("grad_accum", 1)
        self.learning_rate: float = cfg.get("learning_rate", 1e-4)
        self.resume_from: str | None = cfg.get("resume_from")
        self.gpu: int = cfg.get("gpu", 0)
        self.extra_args: dict[str, Any] = cfg.get("extra_args", {})
        self.success_metric: str = cfg.get("success_metric", "mAP@50")
        self.success_threshold: float = cfg.get("success_threshold", 0.0)
        self.timeout_hours: int = cfg.get("timeout_hours", 24)
        self.runtime_env: dict[str, Any] = cfg.get("runtime_env", {})

    def build_entrypoint(self, checkpoint_path: str | None = None) -> str:
        """Build the full entrypoint command string."""
        cmd = self.entrypoint
        cmd += f" --epochs {self.epochs}"
        cmd += f" --batch-size {self.batch_size}"
        if self.grad_accum > 1:
            cmd += f" --grad-accum {self.grad_accum}"
        if self.learning_rate != 1e-4:
            cmd += f" --lr {self.learning_rate}"

        # Resume from previous stage checkpoint or explicit path
        resume = checkpoint_path or self.resume_from
        if resume:
            cmd += f" --resume {resume}"

        for k, v in self.extra_args.items():
            if isinstance(v, bool):
                if v:
                    cmd += f" --{k}"
            else:
                cmd += f" --{k} {v}"

        return cmd


class Pipeline:
    """Multi-stage training pipeline loaded from YAML."""

    def __init__(self, config_path: str):
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        self.name: str = cfg["pipeline"]["name"]
        self.description: str = cfg["pipeline"].get("description", "")
        self.experiment: str = cfg["pipeline"].get("mlflow_experiment", self.name)
        self.notify_on: list[str] = cfg["pipeline"].get(
            "notify_on", ["start", "stage_complete", "failure", "complete"]
        )
        self.stages: list[PipelineStage] = [
            PipelineStage(s) for s in cfg["pipeline"]["stages"]
        ]
        self.config_path = config_path

    def __repr__(self) -> str:
        return f"Pipeline({self.name}, {len(self.stages)} stages)"


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------
class PipelineRunner:
    """Runs a pipeline by submitting stages sequentially to Ray."""

    def __init__(self, pipeline: Pipeline, dry_run: bool = False):
        self.pipeline = pipeline
        self.dry_run = dry_run
        self.state_dir = Path(PIPELINE_STATE_DIR) / pipeline.name
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def run(self, start_stage: int = 0) -> bool:
        """Execute pipeline stages sequentially."""
        logger.info(
            "Starting pipeline %s (%d stages, starting at %d)",
            self.pipeline.name,
            len(self.pipeline.stages),
            start_stage,
        )

        if "start" in self.pipeline.notify_on:
            send_telegram(
                f"🚀 *Training Pipeline Started*: `{self.pipeline.name}`\n"
                f"Stages: {len(self.pipeline.stages)}, starting at #{start_stage}"
            )

        checkpoint_path: str | None = None

        for i, stage in enumerate(self.pipeline.stages):
            if i < start_stage:
                continue

            logger.info(
                "=== Stage %d/%d: %s ===",
                i + 1,
                len(self.pipeline.stages),
                stage.name,
            )

            self._save_state(
                {"current_stage": i, "status": "running", "started_at": _now()}
            )

            success, checkpoint_path = self._run_stage(stage, i, checkpoint_path)

            if not success:
                logger.error("Stage %s failed — pipeline halted", stage.name)
                self._save_state(
                    {"current_stage": i, "status": "failed", "failed_at": _now()}
                )
                if "failure" in self.pipeline.notify_on:
                    send_telegram(
                        f"❌ *Pipeline Failed*: `{self.pipeline.name}`\n"
                        f"Stage: {stage.name} ({i + 1}/{len(self.pipeline.stages)})"
                    )
                return False

            if "stage_complete" in self.pipeline.notify_on:
                send_telegram(
                    f"✅ *Stage Complete*: `{self.pipeline.name}`\n"
                    f"Finished: {stage.name} ({i + 1}/{len(self.pipeline.stages)})\n"
                    f"Checkpoint: `{checkpoint_path or 'none'}`"
                )

        self._save_state(
            {
                "current_stage": len(self.pipeline.stages),
                "status": "completed",
                "completed_at": _now(),
            }
        )

        if "complete" in self.pipeline.notify_on:
            send_telegram(
                f"🎉 *Pipeline Complete*: `{self.pipeline.name}`\n"
                f"All {len(self.pipeline.stages)} stages finished successfully"
            )

        return True

    def _run_stage(
        self, stage: PipelineStage, stage_idx: int, checkpoint: str | None
    ) -> tuple[bool, str | None]:
        """Submit a stage to Ray and monitor until completion."""
        entrypoint = stage.build_entrypoint(checkpoint)
        submission_id = f"{self.pipeline.name}-stage{stage_idx}-{int(time.time())}"

        logger.info("Entrypoint: %s", entrypoint)
        logger.info("Submission ID: %s", submission_id)

        if self.dry_run:
            logger.info("[DRY RUN] Would submit: %s", entrypoint)
            return True, checkpoint

        if not requests:
            logger.error("requests library not available — cannot submit to Ray")
            return False, None

        # Submit to Ray
        payload = {
            "entrypoint": entrypoint,
            "submission_id": submission_id,
            "runtime_env": stage.runtime_env
            or {"working_dir": "/opt/ray/job_workspaces"},
            "metadata": {
                "pipeline": self.pipeline.name,
                "stage": stage.name,
                "stage_index": str(stage_idx),
            },
        }

        try:
            resp = requests.post(
                f"http://{RAY_HEAD}/api/jobs/",
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.error("Failed to submit job: %s", e)
            return False, None

        logger.info("Job submitted: %s", submission_id)

        # Monitor job
        return self._monitor_job(submission_id, stage)

    def _monitor_job(
        self, submission_id: str, stage: PipelineStage
    ) -> tuple[bool, str | None]:
        """Poll Ray job status until completion or timeout."""
        timeout_s = stage.timeout_hours * 3600
        start = time.time()

        while time.time() - start < timeout_s:
            try:
                resp = requests.get(
                    f"http://{RAY_HEAD}/api/jobs/{submission_id}",
                    timeout=10,
                )
                data = resp.json()
                status = data.get("status", "UNKNOWN")
            except Exception as e:
                logger.warning("Failed to poll job status: %s", e)
                time.sleep(POLL_INTERVAL)
                continue

            if status == "SUCCEEDED":
                logger.info("Job %s succeeded", submission_id)
                # Try to extract checkpoint path from job logs
                checkpoint = self._extract_checkpoint(submission_id)
                return True, checkpoint

            if status in ("FAILED", "STOPPED"):
                logger.error("Job %s ended with status: %s", submission_id, status)
                return False, None

            elapsed = time.time() - start
            logger.info(
                "Job %s: %s (%.0f min elapsed / %.0f max)",
                submission_id,
                status,
                elapsed / 60,
                timeout_s / 60,
            )
            time.sleep(POLL_INTERVAL)

        logger.error(
            "Job %s timed out after %d hours", submission_id, stage.timeout_hours
        )
        return False, None

    def _extract_checkpoint(self, submission_id: str) -> str | None:
        """Try to extract checkpoint path from job logs."""
        try:
            resp = requests.get(
                f"http://{RAY_HEAD}/api/jobs/{submission_id}/logs",
                timeout=10,
            )
            logs = resp.text
            # Look for common checkpoint patterns
            for line in reversed(logs.split("\n")):
                if "checkpoint" in line.lower() and "/" in line:
                    # Extract path-like token
                    for token in line.split():
                        if "/" in token and "checkpoint" in token.lower():
                            return token.strip("'\"")
        except Exception:
            pass
        return None

    def _save_state(self, state: dict[str, Any]) -> None:
        """Persist pipeline state for resume capability."""
        state_file = self.state_dir / "state.json"
        state["pipeline"] = self.pipeline.name
        state["updated_at"] = _now()
        state_file.write_text(json.dumps(state, indent=2))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def show_status() -> None:
    """Show status of all pipelines."""
    state_root = Path(PIPELINE_STATE_DIR)
    if not state_root.exists():
        print("No pipeline state found")
        return

    for pipeline_dir in sorted(state_root.iterdir()):
        state_file = pipeline_dir / "state.json"
        if state_file.exists():
            state = json.loads(state_file.read_text())
            status = state.get("status", "unknown")
            stage = state.get("current_stage", "?")
            updated = state.get("updated_at", "?")
            icon = {"running": "🔄", "completed": "✅", "failed": "❌"}.get(
                status, "❓"
            )
            print(f"{icon} {pipeline_dir.name}: {status} (stage {stage}) — {updated}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Training Pipeline Automation")
    parser.add_argument("--config", help="Path to pipeline YAML config")
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate without submitting"
    )
    parser.add_argument(
        "--status", action="store_true", help="Show all pipeline status"
    )
    parser.add_argument("--resume", type=str, help="Resume a pipeline by name")
    parser.add_argument("--start-stage", type=int, default=0, help="Start from stage N")

    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.resume:
        state_file = Path(PIPELINE_STATE_DIR) / args.resume / "state.json"
        if not state_file.exists():
            logger.error("No state found for pipeline: %s", args.resume)
            sys.exit(1)
        state = json.loads(state_file.read_text())
        config_candidates = [
            f"pipelines/{args.resume}.yml",
            f"pipelines/{args.resume}.yaml",
        ]
        for c in config_candidates:
            if os.path.exists(c):
                pipeline = Pipeline(c)
                runner = PipelineRunner(pipeline, dry_run=args.dry_run)
                stage = state.get("current_stage", 0)
                success = runner.run(start_stage=stage)
                sys.exit(0 if success else 1)
        logger.error("Could not find config for pipeline: %s", args.resume)
        sys.exit(1)

    if not args.config:
        parser.print_help()
        sys.exit(1)

    pipeline = Pipeline(args.config)
    runner = PipelineRunner(pipeline, dry_run=args.dry_run)
    success = runner.run(start_stage=args.start_stage)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
