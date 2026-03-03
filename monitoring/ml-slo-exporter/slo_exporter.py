#!/usr/bin/env python3
"""ML SLO Exporter for SHML Platform.

Periodically queries MLflow and Ray APIs to compute ML-specific SLO metrics
and exposes them as Prometheus gauges on port 9091.
"""

import logging
import os
import time
import threading
from datetime import datetime, timezone

import requests
from prometheus_client import Gauge, start_http_server

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow-nginx:80")
RAY_API_URI = os.environ.get("RAY_API_URI", "http://ray-compute-api:8000")
SCRAPE_INTERVAL = int(os.environ.get("SCRAPE_INTERVAL", "60"))
EXPORTER_PORT = int(os.environ.get("EXPORTER_PORT", "9091"))

# Feature Store (Postgres) — for feature freshness metric
POSTGRES_HOST = os.environ.get("POSTGRES_HOST", "postgres")
POSTGRES_PORT = int(os.environ.get("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.environ.get("POSTGRES_FEATURES_DB", "inference")
POSTGRES_USER = os.environ.get("POSTGRES_USER", "inference")
POSTGRES_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "")

# SLO targets
SLO_TARGET_SUCCESS_RATE = float(os.environ.get("SLO_TARGET_SUCCESS_RATE", "0.99"))
# Number of evaluation windows per month (e.g., 720 = 1 per hour for 30 days)
SLO_WINDOWS_PER_MONTH = int(os.environ.get("SLO_WINDOWS_PER_MONTH", "720"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S%z",
)
logger = logging.getLogger("ml-slo-exporter")

# ---------------------------------------------------------------------------
# Prometheus Metrics
# ---------------------------------------------------------------------------

MODEL_FRESHNESS = Gauge(
    "ml_model_freshness_days",
    "Days since the last @champion model was registered",
)

DATASET_FRESHNESS = Gauge(
    "ml_dataset_freshness_days",
    "Days since last dataset update (MLflow artifacts)",
)

EVAL_COMPLETENESS = Gauge(
    "ml_eval_completeness_ratio",
    "Fraction of registered models with evaluation results",
)

TRAINING_SUCCESS_RATE = Gauge(
    "ml_training_success_rate_7d",
    "Training job success rate over the last 7 days",
)

INFERENCE_LATENCY_P99 = Gauge(
    "ml_inference_latency_p99_ms",
    "P99 inference latency in milliseconds",
)

FEATURE_FRESHNESS = Gauge(
    "ml_feature_freshness_minutes",
    "Minutes since last feature materialization (from feature_eval.created_at)",
)

# Per-feature-view metrics (EB-05: Tecton-like per-view SLO tracking)
FEATURE_VIEW_FRESHNESS = Gauge(
    "ml_feature_view_freshness_minutes",
    "Minutes since last materialization per feature view",
    ["feature_view"],
)

FEATURE_VIEW_SLO_MET = Gauge(
    "ml_feature_view_slo_met",
    "Whether the feature view is meeting its freshness SLO (1=yes, 0=no)",
    ["feature_view"],
)

FEATURE_VIEW_SLO_TARGET = Gauge(
    "ml_feature_view_slo_target_minutes",
    "Configured freshness SLO target in minutes per feature view",
    ["feature_view"],
)

ERROR_BUDGET_REMAINING = Gauge(
    "ml_error_budget_remaining_pct",
    "Remaining error budget percentage (target: 99% success, 720 windows/month)",
)

SLO_VIOLATIONS_30D = Gauge(
    "ml_slo_violations_30d",
    "Count of SLO violations in the last 30 days",
)


# ---------------------------------------------------------------------------
# Helper: resilient HTTP GET
# ---------------------------------------------------------------------------


def _get(url: str, params: dict | None = None, timeout: int = 15):
    """Perform a GET request with timeout and error handling.

    Returns the parsed JSON on success, or ``None`` on failure.
    """
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        logger.warning("Connection error reaching %s", url)
    except requests.exceptions.Timeout:
        logger.warning("Timeout reaching %s", url)
    except requests.exceptions.HTTPError as exc:
        logger.warning("HTTP error from %s: %s", url, exc)
    except Exception:
        logger.exception("Unexpected error querying %s", url)
    return None


# ---------------------------------------------------------------------------
# Metric collectors
# ---------------------------------------------------------------------------


def _epoch_ms_to_datetime(epoch_ms: int | str) -> datetime:
    """Convert millisecond epoch (as int or string) to a timezone-aware datetime."""
    return datetime.fromtimestamp(int(epoch_ms) / 1000.0, tz=timezone.utc)


def collect_model_freshness() -> float | None:
    """Return days since the most recently updated @champion model version.

    Queries MLflow ``/api/2.0/mlflow/registered-models/search`` and looks for
    the latest version across all registered models.
    """
    url = f"{MLFLOW_TRACKING_URI}/api/2.0/mlflow/registered-models/search"
    data = _get(url, params={"max_results": "100"})
    if data is None:
        return None

    latest_ts: datetime | None = None
    models = data.get("registered_models", [])
    for model in models:
        # Check latest_versions list for each model
        for version in model.get("latest_versions", []):
            # Prefer champion/production stage models
            stage = (version.get("current_stage") or "").lower()
            aliases = version.get("aliases", [])
            is_champion = stage in ("production", "champion") or "champion" in [
                a.lower() for a in aliases
            ]

            ts_ms = version.get("last_updated_timestamp") or version.get(
                "creation_timestamp"
            )
            if ts_ms is None:
                continue
            version_dt = _epoch_ms_to_datetime(ts_ms)
            if is_champion:
                # Champion version always wins
                if latest_ts is None or version_dt > latest_ts:
                    latest_ts = version_dt
            elif latest_ts is None:
                # Fallback: use any version if no champion found yet
                latest_ts = version_dt

    if latest_ts is None:
        logger.info("No model versions found in MLflow")
        return None

    age_days = (datetime.now(timezone.utc) - latest_ts).total_seconds() / 86400.0
    return round(age_days, 2)


def collect_dataset_freshness() -> float | None:
    """Return days since the last dataset-related artifact was logged.

    Searches recent MLflow runs for any artifacts tagged with 'dataset'.
    Falls back to the most recent run end time as a proxy.
    """
    url = f"{MLFLOW_TRACKING_URI}/api/2.0/mlflow/runs/search"
    payload = {
        "max_results": 20,
        "order_by": ["attributes.end_time DESC"],
        "filter": "tags.mlflow.runName LIKE '%dataset%' OR tags.type = 'data_update'",
    }
    # The search endpoint uses POST
    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        # Fallback: search all recent runs
        data = _get(url)
        if data is None:
            return None

    runs = data.get("runs", [])
    if not runs:
        # Broader search – just get latest run as proxy
        fallback = _get(url, params={"max_results": "5"})
        if fallback:
            runs = fallback.get("runs", [])
        if not runs:
            return None

    latest_ts: datetime | None = None
    for run in runs:
        info = run.get("info", {})
        end_time = info.get("end_time")
        if end_time:
            dt = _epoch_ms_to_datetime(end_time)
            if latest_ts is None or dt > latest_ts:
                latest_ts = dt

    if latest_ts is None:
        return None

    age_days = (datetime.now(timezone.utc) - latest_ts).total_seconds() / 86400.0
    return round(age_days, 2)


def collect_eval_completeness() -> float | None:
    """Return fraction of registered model versions that have evaluation metrics.

    A version is considered "evaluated" if it has at least one metric logged in
    its originating run.
    """
    url = f"{MLFLOW_TRACKING_URI}/api/2.0/mlflow/registered-models/search"
    data = _get(url, params={"max_results": "100"})
    if data is None:
        return None

    total = 0
    evaluated = 0
    models = data.get("registered_models", [])
    for model in models:
        for version in model.get("latest_versions", []):
            total += 1
            run_id = version.get("run_id")
            if not run_id:
                continue
            # Check if the originating run has metrics
            run_url = f"{MLFLOW_TRACKING_URI}/api/2.0/mlflow/runs/get"
            run_data = _get(run_url, params={"run_id": run_id})
            if run_data is None:
                continue
            run_info = run_data.get("run", {})
            metrics = run_info.get("data", {}).get("metrics", [])
            if metrics:
                evaluated += 1

    if total == 0:
        return 1.0  # No models → vacuously complete

    return round(evaluated / total, 4)


def collect_training_success_rate() -> float | None:
    """Return the ratio of FINISHED to total runs over the last 7 days.

    Queries MLflow runs search endpoint.
    """
    seven_days_ago_ms = int((datetime.now(timezone.utc).timestamp() - 7 * 86400) * 1000)
    url = f"{MLFLOW_TRACKING_URI}/api/2.0/mlflow/runs/search"
    payload = {
        "max_results": 1000,
        "filter": f"attributes.start_time > {seven_days_ago_ms}",
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        logger.warning("Failed to query MLflow runs for training success rate")
        return None

    runs = data.get("runs", [])
    if not runs:
        return None

    total = len(runs)
    finished = sum(
        1 for r in runs if r.get("info", {}).get("status", "").upper() == "FINISHED"
    )
    return round(finished / total, 4) if total > 0 else None


def collect_inference_latency() -> float | None:
    """Return P99 inference latency in ms from Ray Compute API metrics.

    Queries Ray /api/v1/metrics or falls back to 0 (placeholder).
    """
    # Try Ray compute API metrics endpoint
    url = f"{RAY_API_URI}/api/v1/metrics"
    data = _get(url)
    if data and isinstance(data, dict):
        latency = data.get("inference_latency_p99_ms")
        if latency is not None:
            return float(latency)

    # Try Prometheus-style metrics from Ray
    url = f"{RAY_API_URI}/metrics"
    try:
        resp = requests.get(url, timeout=10)
        if resp.ok:
            for line in resp.text.splitlines():
                if "inference_latency" in line and not line.startswith("#"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return float(parts[-1])
    except Exception:
        pass

    return None


def collect_feature_freshness() -> float | None:
    """Query feature_eval.created_at to determine feature freshness.

    Returns the number of minutes since the most recent feature
    materialization in the feature_eval table. None if unavailable.
    """
    # Read password from secrets or env
    password = POSTGRES_PASSWORD
    if not password:
        for sp in [
            "/run/secrets/shared_db_password",
            "/app/secrets/shared_db_password.txt",
        ]:
            try:
                with open(sp) as f:
                    password = f.read().strip()
                    break
            except FileNotFoundError:
                continue

    if not password:
        return None

    try:
        import psycopg2

        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=password,
            connect_timeout=5,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(created_at) FROM feature_eval")
            row = cur.fetchone()
        conn.close()

        if row and row[0]:
            last_materialized = row[0]
            now = datetime.now(timezone.utc)
            # Ensure timezone-aware comparison
            if last_materialized.tzinfo is None:
                from datetime import timezone as tz

                last_materialized = last_materialized.replace(tzinfo=tz.utc)
            delta = now - last_materialized
            return round(delta.total_seconds() / 60.0, 1)
    except ImportError:
        logger.warning("psycopg2 not available — feature freshness unavailable")
    except Exception as e:
        logger.warning("Feature freshness query failed: %s", e)

    return None


def collect_error_budget(success_rate: float | None) -> tuple[float | None, int]:
    """Compute remaining error budget % and SLO violation count.

    Error budget model:
      - Target success rate: ``SLO_TARGET_SUCCESS_RATE`` (default 0.99)
      - Allowable failures per month: ``(1 - target) * windows``
      - Actual failure rate derived from ``success_rate``

    Returns (remaining_pct, violations_30d).
    """
    if success_rate is None:
        return None, 0

    allowed_failure_rate = 1.0 - SLO_TARGET_SUCCESS_RATE
    actual_failure_rate = 1.0 - success_rate

    if allowed_failure_rate <= 0:
        remaining_pct = 0.0 if actual_failure_rate > 0 else 100.0
    else:
        consumed = actual_failure_rate / allowed_failure_rate
        remaining_pct = max(0.0, (1.0 - consumed) * 100.0)

    # Estimate violations: each hour in a 30-day window where failure rate > target
    total_allowed_failures = int(SLO_WINDOWS_PER_MONTH * allowed_failure_rate)
    estimated_failures = int(SLO_WINDOWS_PER_MONTH * actual_failure_rate)
    violations = max(0, estimated_failures - total_allowed_failures)

    return round(remaining_pct, 2), violations


def collect_per_view_freshness() -> None:
    """Query the feature registry for per-view freshness and set labeled gauges.

    This enables Grafana panels and alerts to operate at the individual
    feature-view level (e.g., eval_metrics, training_lineage, etc.)
    rather than a single global freshness metric.
    """
    password = POSTGRES_PASSWORD
    if not password:
        for sp in [
            "/run/secrets/shared_db_password",
            "/app/secrets/shared_db_password.txt",
        ]:
            try:
                with open(sp) as f:
                    password = f.read().strip()
                    break
            except FileNotFoundError:
                continue

    if not password:
        return

    try:
        import psycopg2
        import psycopg2.extras

        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            dbname=POSTGRES_DB,
            user=POSTGRES_USER,
            password=password,
            connect_timeout=5,
        )

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Check if feature_views table exists
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'feature_views'
                )
            """
            )
            if not cur.fetchone()["exists"]:
                conn.close()
                return

            cur.execute(
                """
                SELECT
                    fv.name,
                    fv.freshness_slo_minutes AS slo_minutes,
                    (SELECT MAX(completed_at) FROM feature_view_runs
                     WHERE feature_view_name = fv.name AND status = 'succeeded')
                        AS last_materialized_at
                FROM feature_views fv
                WHERE fv.status = 'active'
            """
            )
            rows = cur.fetchall()

        conn.close()

        now = datetime.now(timezone.utc)
        for row in rows:
            view_name = row["name"]
            slo_minutes = row["slo_minutes"]
            last_mat = row["last_materialized_at"]

            FEATURE_VIEW_SLO_TARGET.labels(feature_view=view_name).set(slo_minutes)

            if last_mat:
                if last_mat.tzinfo is None:
                    last_mat = last_mat.replace(tzinfo=timezone.utc)
                freshness = (now - last_mat).total_seconds() / 60.0
                FEATURE_VIEW_FRESHNESS.labels(feature_view=view_name).set(
                    round(freshness, 1)
                )
                FEATURE_VIEW_SLO_MET.labels(feature_view=view_name).set(
                    1.0 if freshness <= slo_minutes else 0.0
                )
            else:
                # No data yet — set freshness to -1 and SLO unmet
                FEATURE_VIEW_FRESHNESS.labels(feature_view=view_name).set(-1)
                FEATURE_VIEW_SLO_MET.labels(feature_view=view_name).set(0)

        logger.info("Per-view freshness: %d views updated", len(rows))

    except ImportError:
        logger.debug("psycopg2 not available — per-view freshness unavailable")
    except Exception as e:
        logger.debug("Per-view freshness collection skipped: %s", e)


# ---------------------------------------------------------------------------
# Main collection loop
# ---------------------------------------------------------------------------

_last_values: dict[str, float] = {}


def _set_gauge(gauge: Gauge, key: str, value: float | None) -> None:
    """Set gauge to *value*, falling back to last known value on ``None``."""
    if value is not None:
        _last_values[key] = value
        gauge.set(value)
    elif key in _last_values:
        gauge.set(_last_values[key])
    # else: leave at default (0)


def collect_all() -> None:
    """Run one full collection cycle."""
    logger.info("Starting metrics collection cycle")
    start = time.monotonic()

    # Model freshness
    model_freshness = collect_model_freshness()
    _set_gauge(MODEL_FRESHNESS, "model_freshness", model_freshness)

    # Dataset freshness
    dataset_freshness = collect_dataset_freshness()
    _set_gauge(DATASET_FRESHNESS, "dataset_freshness", dataset_freshness)

    # Eval completeness
    eval_completeness = collect_eval_completeness()
    _set_gauge(EVAL_COMPLETENESS, "eval_completeness", eval_completeness)

    # Training success rate (7d)
    success_rate = collect_training_success_rate()
    _set_gauge(TRAINING_SUCCESS_RATE, "training_success_rate", success_rate)

    # Inference latency P99
    inference_latency = collect_inference_latency()
    _set_gauge(INFERENCE_LATENCY_P99, "inference_latency", inference_latency)

    # Feature freshness (global — backward compatible)
    feature_freshness = collect_feature_freshness()
    _set_gauge(FEATURE_FRESHNESS, "feature_freshness", feature_freshness)

    # Per-view feature freshness (EB-05: labeled Prometheus gauges)
    collect_per_view_freshness()

    # Error budget
    error_budget, violations = collect_error_budget(success_rate)
    _set_gauge(ERROR_BUDGET_REMAINING, "error_budget", error_budget)
    _set_gauge(SLO_VIOLATIONS_30D, "slo_violations", float(violations))

    elapsed = time.monotonic() - start
    logger.info(
        "Collection cycle complete in %.2fs | freshness=%.1fd success=%.4f budget=%.1f%% violations=%d",
        elapsed,
        model_freshness or -1,
        success_rate or -1,
        error_budget or -1,
        violations,
    )


def run_loop() -> None:
    """Blocking loop that calls ``collect_all`` every ``SCRAPE_INTERVAL`` seconds."""
    while True:
        try:
            collect_all()
        except Exception:
            logger.exception("Unhandled error in collection cycle")
        time.sleep(SCRAPE_INTERVAL)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    logger.info(
        "ML SLO Exporter starting | port=%d interval=%ds mlflow=%s ray=%s",
        EXPORTER_PORT,
        SCRAPE_INTERVAL,
        MLFLOW_TRACKING_URI,
        RAY_API_URI,
    )

    # Start Prometheus HTTP server
    start_http_server(EXPORTER_PORT)
    logger.info("Prometheus metrics server listening on :%d", EXPORTER_PORT)

    # Run collection in a daemon thread so the HTTP server stays responsive
    collector_thread = threading.Thread(target=run_loop, daemon=True)
    collector_thread.start()

    # Block main thread – keeps the process alive
    try:
        collector_thread.join()
    except KeyboardInterrupt:
        logger.info("Shutting down")


if __name__ == "__main__":
    main()
