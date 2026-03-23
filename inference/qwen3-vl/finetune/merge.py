"""Merge a trained LoRA adapter into the base model and log to MLflow.

Usage:
    python -m finetune.merge \
        --adapter /data/checkpoints/qwen3-vl-qlora/adapter \
        --output  /data/models/qwen3-vl-merged \
        [--mlflow-run-id <run_id>]
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def merge(
    adapter_path: str,
    output_dir: str,
    base_model: str | None = None,
    mlflow_tracking_uri: str = "http://mlflow-nginx:80",
    mlflow_experiment: str = "qwen3-vl-qlora",
    mlflow_run_id: str | None = None,
) -> str:
    """Merge LoRA adapter weights into base model and log via MLflow.

    Args:
        adapter_path: Directory containing the PEFT adapter (adapter_config.json, etc.)
        output_dir:   Where to write the merged full-precision model.
        base_model:   Override base model path/id (reads from adapter config if None).
        mlflow_tracking_uri: MLflow server URI.
        mlflow_experiment: Experiment name for logging.
        mlflow_run_id: Resume an existing MLflow run instead of creating a new one.

    Returns:
        Path to the merged model directory.
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel
    import mlflow
    import mlflow.transformers

    # Resolve base model from adapter config when not supplied
    if base_model is None:
        import json
        adapter_config_path = Path(adapter_path) / "adapter_config.json"
        if adapter_config_path.exists():
            with open(adapter_config_path) as fh:
                adapter_config = json.load(fh)
            base_model = adapter_config.get("base_model_name_or_path")
        if not base_model:
            raise ValueError(
                "base_model must be provided or inferable from adapter_config.json"
            )

    logger.info("Merging adapter from %s into %s", adapter_path, base_model)

    # Load base in fp16 for merge (avoids OOM on 24 GB)
    base = AutoModelForCausalLM.from_pretrained(
        base_model,
        torch_dtype=torch.float16,
        device_map="cpu",
        trust_remote_code=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        adapter_path, trust_remote_code=True
    )

    # Merge and unload LoRA weights
    model = PeftModel.from_pretrained(base, adapter_path)
    merged = model.merge_and_unload()
    logger.info("Merge complete — saving to %s", output_dir)

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(output_dir, safe_serialization=True)
    tokenizer.save_pretrained(output_dir)

    # Log to MLflow
    try:
        mlflow.set_tracking_uri(mlflow_tracking_uri)
    except Exception:
        mlflow.set_tracking_uri("file:///tmp/mlruns")
    mlflow.set_experiment(mlflow_experiment)

    run_ctx = (
        mlflow.start_run(run_id=mlflow_run_id)
        if mlflow_run_id
        else mlflow.start_run(run_name="qlora-merge")
    )
    with run_ctx:
        mlflow.log_param("adapter_path", adapter_path)
        mlflow.log_param("base_model", base_model)
        mlflow.log_param("output_dir", output_dir)
        mlflow.transformers.log_model(
            transformers_model={
                "model": merged,
                "tokenizer": tokenizer,
            },
            artifact_path="merged_model",
            task="text-generation",
        )
        logger.info("Merged model logged to MLflow")

    return output_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge QLoRA adapter into base model")
    parser.add_argument(
        "--adapter",
        required=True,
        help="Path to the trained LoRA adapter directory",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Destination directory for the merged model",
    )
    parser.add_argument(
        "--base-model",
        default=None,
        help="Base model path or HF repo ID (inferred from adapter config if omitted)",
    )
    parser.add_argument(
        "--mlflow-uri",
        default="http://mlflow-nginx:80",
        help="MLflow tracking URI",
    )
    parser.add_argument(
        "--mlflow-experiment",
        default="qwen3-vl-qlora",
        help="MLflow experiment name",
    )
    parser.add_argument(
        "--mlflow-run-id",
        default=None,
        help="Resume an existing MLflow run (optional)",
    )
    args = parser.parse_args()

    merge(
        adapter_path=args.adapter,
        output_dir=args.output,
        base_model=args.base_model,
        mlflow_tracking_uri=args.mlflow_uri,
        mlflow_experiment=args.mlflow_experiment,
        mlflow_run_id=args.mlflow_run_id,
    )
