"""RAGAS evaluation for RAG agents — faithfulness, answer relevancy, context recall.

Wraps the RAGAS library and logs results to MLflow under the 'agent-eval' experiment.

Usage:
    from libs.evaluation.agents.ragas_eval import run_ragas_eval

    scores = run_ragas_eval(
        questions=["What is the capital of France?"],
        answers=["Paris is the capital of France."],
        contexts=[["France is a country in Western Europe. Paris is its capital."]],
        ground_truths=["Paris"],
        mlflow_run_id="abc123",
    )
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

RAGAS_METRICS_DEFAULT = ["faithfulness", "answer_relevancy", "context_recall", "context_precision"]


def run_ragas_eval(
    questions: List[str],
    answers: List[str],
    contexts: List[List[str]],
    ground_truths: List[str],
    metrics: Optional[List[str]] = None,
    mlflow_experiment: str = "agent-eval",
    mlflow_run_id: Optional[str] = None,
    mlflow_run_name: str = "ragas-eval",
) -> Dict[str, float]:
    """Run RAGAS evaluation suite on a batch of QA samples.

    Args:
        questions: User questions.
        answers: Model-generated answers.
        contexts: Retrieved context passages per question (list of lists).
        ground_truths: Reference answers.
        metrics: RAGAS metric names (default: faithfulness, answer_relevancy,
                 context_recall, context_precision).
        mlflow_experiment: MLflow experiment name for logging.
        mlflow_run_id: Log into existing run (None = create new run).
        mlflow_run_name: Name for new MLflow run.

    Returns:
        Dict mapping metric name → mean score over the batch.
    """
    try:
        from ragas import evaluate as ragas_evaluate
        from ragas.metrics import (
            faithfulness,
            answer_relevancy,
            context_recall,
            context_precision,
        )
        from datasets import Dataset
    except ImportError as exc:
        raise ImportError(
            "Install ragas and datasets: pip install ragas datasets"
        ) from exc

    metrics = metrics or RAGAS_METRICS_DEFAULT

    _metric_objects = {
        "faithfulness": faithfulness,
        "answer_relevancy": answer_relevancy,
        "context_recall": context_recall,
        "context_precision": context_precision,
    }
    selected = [_metric_objects[m] for m in metrics if m in _metric_objects]
    unknown = [m for m in metrics if m not in _metric_objects]
    if unknown:
        logger.warning("Unknown RAGAS metrics (skipped): %s", unknown)

    dataset = Dataset.from_dict({
        "question": questions,
        "answer": answers,
        "contexts": contexts,
        "ground_truth": ground_truths,
    })

    logger.info("Running RAGAS on %d samples with metrics: %s", len(questions), metrics)
    result = ragas_evaluate(dataset, metrics=selected)

    scores: Dict[str, float] = {}
    for metric_name in result.scores.column_names if hasattr(result.scores, "column_names") else []:
        col = result.scores[metric_name]
        scores[metric_name] = round(sum(col) / len(col), 4) if col else 0.0

    # Fallback: some RAGAS versions return a dict directly
    if not scores and hasattr(result, "__getitem__"):
        for m in metrics:
            if m in result:
                scores[m] = round(float(result[m]), 4)

    logger.info("RAGAS scores: %s", scores)

    # Log to MLflow
    import mlflow
    mlflow.set_experiment(mlflow_experiment)
    if mlflow_run_id:
        with mlflow.start_run(run_id=mlflow_run_id):
            mlflow.log_metrics({f"ragas/{k}": v for k, v in scores.items()})
    else:
        with mlflow.start_run(run_name=mlflow_run_name):
            mlflow.log_params({
                "n_samples": len(questions),
                "metrics": ",".join(metrics),
            })
            mlflow.log_metrics({f"ragas/{k}": v for k, v in scores.items()})

    return scores
