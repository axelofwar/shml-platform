"""
Progress reporting for SHML Training Library.

Implements AG-UI protocol for real-time streaming to UIs,
plus console logging and notification support.
"""

import json
import time
import threading
import requests
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from queue import Queue
import sys


class AGUIEventType(Enum):
    """AG-UI Protocol event types."""

    # Run lifecycle
    RUN_STARTED = "RUN_STARTED"
    RUN_FINISHED = "RUN_FINISHED"
    RUN_ERROR = "RUN_ERROR"

    # Text messages
    TEXT_MESSAGE_START = "TEXT_MESSAGE_START"
    TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
    TEXT_MESSAGE_END = "TEXT_MESSAGE_END"

    # Tool calls (for multi-step operations)
    TOOL_CALL_START = "TOOL_CALL_START"
    TOOL_CALL_ARGS = "TOOL_CALL_ARGS"
    TOOL_CALL_END = "TOOL_CALL_END"

    # State updates
    STATE_SNAPSHOT = "STATE_SNAPSHOT"
    STATE_DELTA = "STATE_DELTA"

    # Custom training events
    EPOCH_START = "EPOCH_START"
    EPOCH_END = "EPOCH_END"
    STEP_UPDATE = "STEP_UPDATE"
    CHECKPOINT_SAVED = "CHECKPOINT_SAVED"
    METRIC_UPDATE = "METRIC_UPDATE"


@dataclass
class AGUIEvent:
    """AG-UI Protocol event."""

    type: AGUIEventType
    timestamp: str
    run_id: str
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "timestamp": self.timestamp,
            "runId": self.run_id,
            **self.data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    def to_sse(self) -> str:
        """Format as Server-Sent Event."""
        return f"data: {self.to_json()}\n\n"


class AGUIEventEmitter:
    """
    Emits AG-UI protocol events for real-time UI updates.

    Supports:
    - SSE (Server-Sent Events) streaming to HTTP endpoint
    - WebSocket streaming
    - Local event queue for polling

    Usage:
        emitter = AGUIEventEmitter(run_id="train-123")
        emitter.start()

        emitter.emit_run_started(config={'epochs': 100})
        emitter.emit_state_delta({'epoch': 1, 'loss': 0.5})
        emitter.emit_run_finished(metrics={'final_loss': 0.1})
    """

    def __init__(
        self,
        run_id: str,
        endpoint: Optional[str] = None,
        buffer_size: int = 1000,
    ):
        """
        Args:
            run_id: Unique identifier for this training run
            endpoint: HTTP endpoint for SSE streaming (optional)
            buffer_size: Size of local event buffer
        """
        self.run_id = run_id
        self.endpoint = endpoint
        self.buffer_size = buffer_size

        self._event_queue: Queue = Queue(maxsize=buffer_size)
        self._started = False
        self._sender_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._callbacks: List[Callable[[AGUIEvent], None]] = []

    def start(self) -> None:
        """Start the event emitter."""
        if self._started:
            return

        self._started = True
        self._stop_event.clear()

        # Start sender thread if endpoint configured
        if self.endpoint:
            self._sender_thread = threading.Thread(
                target=self._sender_loop,
                daemon=True,
            )
            self._sender_thread.start()

    def stop(self) -> None:
        """Stop the event emitter."""
        self._stop_event.set()
        if self._sender_thread:
            self._sender_thread.join(timeout=5)
        self._started = False

    def add_callback(self, callback: Callable[[AGUIEvent], None]) -> None:
        """Add callback to be called on each event."""
        self._callbacks.append(callback)

    def _emit(self, event_type: AGUIEventType, data: Dict[str, Any]) -> None:
        """Internal event emission."""
        event = AGUIEvent(
            type=event_type,
            timestamp=datetime.now().isoformat(),
            run_id=self.run_id,
            data=data,
        )

        # Add to queue
        try:
            self._event_queue.put_nowait(event)
        except:
            # Queue full, drop oldest
            try:
                self._event_queue.get_nowait()
                self._event_queue.put_nowait(event)
            except:
                pass

        # Call callbacks
        for callback in self._callbacks:
            try:
                callback(event)
            except Exception:
                pass

    def _sender_loop(self) -> None:
        """Background thread for sending events to endpoint."""
        session = requests.Session()

        while not self._stop_event.is_set():
            try:
                event = self._event_queue.get(timeout=1)

                if self.endpoint:
                    try:
                        session.post(
                            self.endpoint,
                            json=event.to_dict(),
                            timeout=5,
                        )
                    except Exception:
                        pass

            except:
                continue

    # =========================================================================
    # Run Lifecycle Events
    # =========================================================================

    def emit_run_started(
        self,
        config: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit RUN_STARTED event."""
        self._emit(
            AGUIEventType.RUN_STARTED,
            {
                "config": config or {},
                "metadata": metadata or {},
            },
        )

    def emit_run_finished(
        self,
        metrics: Optional[Dict[str, float]] = None,
        status: str = "completed",
    ) -> None:
        """Emit RUN_FINISHED event."""
        self._emit(
            AGUIEventType.RUN_FINISHED,
            {
                "status": status,
                "metrics": metrics or {},
            },
        )

    def emit_run_error(
        self,
        error: str,
        traceback: Optional[str] = None,
    ) -> None:
        """Emit RUN_ERROR event."""
        self._emit(
            AGUIEventType.RUN_ERROR,
            {
                "error": error,
                "traceback": traceback,
            },
        )

    # =========================================================================
    # Training State Events
    # =========================================================================

    def emit_state_delta(self, delta: Dict[str, Any]) -> None:
        """Emit STATE_DELTA event with incremental state update."""
        self._emit(AGUIEventType.STATE_DELTA, {"delta": delta})

    def emit_state_snapshot(self, state: Dict[str, Any]) -> None:
        """Emit STATE_SNAPSHOT event with full state."""
        self._emit(AGUIEventType.STATE_SNAPSHOT, {"snapshot": state})

    def emit_epoch_start(self, epoch: int, total_epochs: int) -> None:
        """Emit EPOCH_START event."""
        self._emit(
            AGUIEventType.EPOCH_START,
            {
                "epoch": epoch,
                "total_epochs": total_epochs,
                "progress": epoch / total_epochs,
            },
        )

    def emit_epoch_end(
        self,
        epoch: int,
        metrics: Dict[str, float],
        duration_seconds: float,
    ) -> None:
        """Emit EPOCH_END event."""
        self._emit(
            AGUIEventType.EPOCH_END,
            {
                "epoch": epoch,
                "metrics": metrics,
                "duration_seconds": duration_seconds,
            },
        )

    def emit_step_update(
        self,
        step: int,
        total_steps: int,
        loss: float,
        learning_rate: float,
        throughput: Optional[float] = None,
        gpu_memory_gb: Optional[float] = None,
    ) -> None:
        """Emit STEP_UPDATE event."""
        self._emit(
            AGUIEventType.STEP_UPDATE,
            {
                "step": step,
                "total_steps": total_steps,
                "progress": step / total_steps if total_steps > 0 else 0,
                "loss": loss,
                "learning_rate": learning_rate,
                "throughput": throughput,
                "gpu_memory_gb": gpu_memory_gb,
            },
        )

    def emit_checkpoint_saved(
        self,
        path: str,
        epoch: int,
        is_best: bool = False,
    ) -> None:
        """Emit CHECKPOINT_SAVED event."""
        self._emit(
            AGUIEventType.CHECKPOINT_SAVED,
            {
                "path": path,
                "epoch": epoch,
                "is_best": is_best,
            },
        )

    def emit_metric_update(self, metrics: Dict[str, float]) -> None:
        """Emit METRIC_UPDATE event."""
        self._emit(AGUIEventType.METRIC_UPDATE, {"metrics": metrics})

    # =========================================================================
    # Event Retrieval
    # =========================================================================

    def get_pending_events(self) -> List[AGUIEvent]:
        """Get all pending events from queue."""
        events = []
        while not self._event_queue.empty():
            try:
                events.append(self._event_queue.get_nowait())
            except:
                break
        return events


class ProgressReporter:
    """
    High-level progress reporter for training.

    Combines:
    - AG-UI event emission
    - Console logging
    - Notification support (ntfy.sh)

    Usage:
        reporter = ProgressReporter(
            run_id="train-123",
            total_epochs=100,
            agui_endpoint="http://localhost:8080/events",
            ntfy_topic="shml-training",
        )

        reporter.start_run(config={'model': 'bert-base'})

        for epoch in range(100):
            reporter.start_epoch(epoch)
            for step, loss in training_loop():
                reporter.log_step(step, loss=loss)
            reporter.end_epoch(epoch, metrics={'loss': 0.5})

        reporter.end_run(metrics={'final_loss': 0.1})
    """

    def __init__(
        self,
        run_id: str,
        total_epochs: int = 0,
        total_steps: int = 0,
        agui_endpoint: Optional[str] = None,
        ntfy_topic: Optional[str] = None,
        log_to_console: bool = True,
        console_log_interval: int = 10,
    ):
        """
        Args:
            run_id: Unique run identifier
            total_epochs: Total number of epochs
            total_steps: Total number of steps (optional)
            agui_endpoint: HTTP endpoint for AG-UI events
            ntfy_topic: ntfy.sh topic for notifications
            log_to_console: Whether to log to console
            console_log_interval: Steps between console logs
        """
        self.run_id = run_id
        self.total_epochs = total_epochs
        self.total_steps = total_steps
        self.ntfy_topic = ntfy_topic
        self.log_to_console = log_to_console
        self.console_log_interval = console_log_interval

        # AG-UI emitter
        self.emitter = AGUIEventEmitter(run_id, agui_endpoint)

        # State tracking
        self._current_epoch = 0
        self._current_step = 0
        self._epoch_start_time: Optional[float] = None
        self._run_start_time: Optional[float] = None
        self._last_console_log_step = -1

    def start_run(self, config: Optional[Dict[str, Any]] = None) -> None:
        """Start training run."""
        self._run_start_time = time.time()
        self.emitter.start()
        self.emitter.emit_run_started(config)

        if self.log_to_console:
            print("\n" + "=" * 60)
            print(f"Training Run: {self.run_id}")
            print("=" * 60)
            if config:
                for key, value in config.items():
                    print(f"  {key}: {value}")
            print("=" * 60 + "\n")

    def end_run(
        self,
        metrics: Optional[Dict[str, float]] = None,
        status: str = "completed",
    ) -> None:
        """End training run."""
        self.emitter.emit_run_finished(metrics, status)
        self.emitter.stop()

        duration = time.time() - self._run_start_time if self._run_start_time else 0

        if self.log_to_console:
            print("\n" + "=" * 60)
            print(f"Training Complete: {self.run_id}")
            print(f"Duration: {duration / 3600:.2f} hours")
            if metrics:
                print("Final Metrics:")
                for key, value in metrics.items():
                    print(f"  {key}: {value:.4f}")
            print("=" * 60 + "\n")

        # Send notification
        if self.ntfy_topic:
            self._send_notification(
                title=f"Training Complete: {self.run_id}",
                message=f"Duration: {duration/3600:.2f}h\n"
                + "\n".join(f"{k}: {v:.4f}" for k, v in (metrics or {}).items()),
                priority=4,
            )

    def start_epoch(self, epoch: int) -> None:
        """Start an epoch."""
        self._current_epoch = epoch
        self._epoch_start_time = time.time()
        self.emitter.emit_epoch_start(epoch, self.total_epochs)

        if self.log_to_console:
            progress = epoch / self.total_epochs if self.total_epochs > 0 else 0
            print(f"\n📌 Epoch {epoch}/{self.total_epochs} ({progress*100:.1f}%)")

    def end_epoch(self, epoch: int, metrics: Dict[str, float]) -> None:
        """End an epoch."""
        duration = time.time() - self._epoch_start_time if self._epoch_start_time else 0
        self.emitter.emit_epoch_end(epoch, metrics, duration)

        if self.log_to_console:
            metrics_str = ", ".join(f"{k}: {v:.4f}" for k, v in metrics.items())
            print(f"   ✅ Epoch {epoch} complete ({duration:.1f}s) - {metrics_str}")

    def log_step(
        self,
        step: int,
        loss: float,
        learning_rate: Optional[float] = None,
        throughput: Optional[float] = None,
        gpu_memory_gb: Optional[float] = None,
        **extra_metrics,
    ) -> None:
        """Log a training step."""
        self._current_step = step

        self.emitter.emit_step_update(
            step=step,
            total_steps=self.total_steps,
            loss=loss,
            learning_rate=learning_rate or 0,
            throughput=throughput,
            gpu_memory_gb=gpu_memory_gb,
        )

        # Console logging at interval
        if self.log_to_console:
            if step - self._last_console_log_step >= self.console_log_interval:
                self._log_step_console(
                    step, loss, learning_rate, throughput, gpu_memory_gb
                )
                self._last_console_log_step = step

    def _log_step_console(
        self,
        step: int,
        loss: float,
        learning_rate: Optional[float],
        throughput: Optional[float],
        gpu_memory_gb: Optional[float],
    ) -> None:
        """Log step to console."""
        parts = [f"step {step}"]

        if self.total_steps > 0:
            progress = step / self.total_steps * 100
            parts.append(f"{progress:.1f}%")

        parts.append(f"loss: {loss:.4f}")

        if learning_rate:
            parts.append(f"lr: {learning_rate:.2e}")

        if throughput:
            parts.append(f"{throughput:.1f} samples/s")

        if gpu_memory_gb:
            parts.append(f"GPU: {gpu_memory_gb:.1f}GB")

        print(f"   {' | '.join(parts)}")

    def log_checkpoint(self, path: str, epoch: int, is_best: bool = False) -> None:
        """Log checkpoint save."""
        self.emitter.emit_checkpoint_saved(path, epoch, is_best)

        if self.log_to_console:
            best_str = " (best)" if is_best else ""
            print(f"   💾 Checkpoint saved: {path}{best_str}")

    def log_metrics(self, metrics: Dict[str, float]) -> None:
        """Log arbitrary metrics."""
        self.emitter.emit_metric_update(metrics)

    def log_error(self, error: str, traceback: Optional[str] = None) -> None:
        """Log an error."""
        self.emitter.emit_run_error(error, traceback)

        if self.log_to_console:
            print(f"\n❌ Error: {error}")
            if traceback:
                print(traceback)

        # Send notification
        if self.ntfy_topic:
            self._send_notification(
                title=f"Training Error: {self.run_id}",
                message=error,
                priority=5,
                tags=["warning"],
            )

    def _send_notification(
        self,
        title: str,
        message: str,
        priority: int = 3,
        tags: Optional[List[str]] = None,
    ) -> None:
        """Send notification via ntfy.sh."""
        if not self.ntfy_topic:
            return

        try:
            requests.post(
                f"https://ntfy.sh/{self.ntfy_topic}",
                data=message,
                headers={
                    "Title": title,
                    "Priority": str(priority),
                    "Tags": ",".join(tags or []),
                },
                timeout=5,
            )
        except Exception:
            pass


# Convenience function for quick progress bar
def print_progress_bar(
    current: int,
    total: int,
    prefix: str = "",
    suffix: str = "",
    length: int = 40,
    fill: str = "█",
) -> None:
    """Print a progress bar to console."""
    percent = current / total if total > 0 else 0
    filled = int(length * percent)
    bar = fill * filled + "-" * (length - filled)
    print(f"\r{prefix} |{bar}| {percent*100:.1f}% {suffix}", end="")
    if current >= total:
        print()
