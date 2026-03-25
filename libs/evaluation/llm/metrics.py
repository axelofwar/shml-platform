"""LLM text-quality metrics: ROUGE, BERTScore, BLEU.

Usage:
    from libs.evaluation.llm.metrics import compute_metrics

    results = compute_metrics(
        predictions=["The cat sat on the mat."],
        references=["The cat is sitting on the mat."],
    )
    # {"rouge1": 0.83, "rouge2": 0.57, "rougeL": 0.83,
    #  "bertscore_f1": 0.94, "bleu": 0.42}
"""

from __future__ import annotations

import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


def compute_metrics(
    predictions: List[str],
    references: List[str],
    lang: str = "en",
    bertscore_model: str = "microsoft/deberta-xlarge-mnli",
    run_bertscore: bool = True,
) -> Dict[str, float]:
    """Compute ROUGE, BERTScore and BLEU for a batch of prediction/reference pairs.

    Args:
        predictions: Model-generated strings.
        references: Ground-truth reference strings.
        lang: Language code for BERTScore (default: 'en').
        bertscore_model: HuggingFace model for BERTScore.
        run_bertscore: Set False to skip BERTScore (slow on CPU).

    Returns:
        Dict with rouge1/rouge2/rougeL, bertscore_precision/recall/f1, bleu.
    """
    import evaluate

    results: Dict[str, float] = {}

    # --- ROUGE ---
    rouge = evaluate.load("rouge")
    rouge_out = rouge.compute(predictions=predictions, references=references)
    results["rouge1"] = round(rouge_out["rouge1"], 4)
    results["rouge2"] = round(rouge_out["rouge2"], 4)
    results["rougeL"] = round(rouge_out["rougeL"], 4)
    logger.debug("ROUGE computed: %s", {k: results[k] for k in ("rouge1", "rouge2", "rougeL")})

    # --- BLEU ---
    bleu = evaluate.load("bleu")
    bleu_out = bleu.compute(
        predictions=predictions,
        references=[[r] for r in references],
    )
    results["bleu"] = round(bleu_out["bleu"], 4)

    # --- BERTScore ---
    if run_bertscore:
        bertscore = evaluate.load("bertscore")
        bs_out = bertscore.compute(
            predictions=predictions,
            references=references,
            lang=lang,
            model_type=bertscore_model,
        )
        results["bertscore_precision"] = round(sum(bs_out["precision"]) / len(bs_out["precision"]), 4)
        results["bertscore_recall"] = round(sum(bs_out["recall"]) / len(bs_out["recall"]), 4)
        results["bertscore_f1"] = round(sum(bs_out["f1"]) / len(bs_out["f1"]), 4)
        logger.debug("BERTScore F1: %.4f", results["bertscore_f1"])

    return results


def log_metrics_to_mlflow(
    metrics: Dict[str, float],
    prefix: str = "eval",
    run_id: Optional[str] = None,
) -> None:
    """Log computed metrics to active (or specified) MLflow run.

    Args:
        metrics: Output of compute_metrics().
        prefix: Metric name prefix (e.g. 'eval' → 'eval/rouge1').
        run_id: Existing MLflow run ID to log into (None = active run).
    """
    import mlflow

    prefixed = {f"{prefix}/{k}": v for k, v in metrics.items()}
    if run_id:
        with mlflow.start_run(run_id=run_id):
            mlflow.log_metrics(prefixed)
    else:
        mlflow.log_metrics(prefixed)
    logger.info("Logged %d metrics to MLflow (prefix=%s)", len(prefixed), prefix)
