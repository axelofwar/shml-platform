"""QLoRA fine-tuning entry point for Qwen3-VL.

Pipeline:
  1. Yield RTX 3090 Ti from z-image-api (free VRAM)
  2. Load base model in NF4 4-bit (BitsAndBytes)
  3. Apply PEFT LoRA adapter
  4. SFTTrainer train loop with MLflow logging
  5. Save adapter to output_dir/adapter/

Usage:
    python -m finetune.train --config finetune/config.py
    # or import and call train(cfg) programmatically from Ray job
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _yield_gpu(cfg) -> None:
    """Ask z-image-api to unload from VRAM before training."""
    try:
        import httpx
        resp = httpx.post(cfg.yield_endpoint, timeout=cfg.yield_timeout_sec)
        if resp.status_code == 200:
            logger.info("GPU yielded by z-image-api")
        else:
            logger.warning("Yield request returned %d — continuing anyway", resp.status_code)
    except Exception as exc:
        logger.warning("Could not yield GPU (non-fatal): %s", exc)


def train(cfg) -> str:
    """Run QLoRA fine-tuning.  Returns path to saved adapter."""
    from config import QLoRAConfig  # local import for Ray job portability
    assert isinstance(cfg, QLoRAConfig), f"Expected QLoRAConfig, got {type(cfg)}"

    import torch
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        TrainingArguments,
    )
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from trl import SFTTrainer, DataCollatorForCompletionOnlyLM
    from datasets import Dataset as HFDataset

    # --- 1. Yield GPU ---
    _yield_gpu(cfg)

    # --- 2. MLflow ---
    import mlflow

    try:
        mlflow.set_tracking_uri(cfg.mlflow_tracking_uri)
    except Exception:
        mlflow.set_tracking_uri(f"file:///tmp/mlruns")
    mlflow.set_experiment(cfg.mlflow_experiment)

    with mlflow.start_run(run_name="qlora-train") as run:
        mlflow.log_params({
            "base_model": cfg.base_model,
            "r": cfg.r,
            "lora_alpha": cfg.lora_alpha,
            "lora_dropout": cfg.lora_dropout,
            "target_modules": ",".join(cfg.target_modules),
            "learning_rate": cfg.learning_rate,
            "num_train_epochs": cfg.num_train_epochs,
            "per_device_train_batch_size": cfg.per_device_train_batch_size,
            "gradient_accumulation_steps": cfg.gradient_accumulation_steps,
            "max_seq_length": cfg.max_seq_length,
            "dataset_path": cfg.dataset_path,
        })

        # --- 3. Quantization config (NF4) ---
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )

        # --- 4. Load base model ---
        logger.info("Loading base model: %s", cfg.base_model)
        model = AutoModelForCausalLM.from_pretrained(
            cfg.base_model,
            quantization_config=bnb_config,
            device_map={"": cfg.gpu_id},
            trust_remote_code=True,
            cache_dir=cfg.model_cache_dir,
        )
        model = prepare_model_for_kbit_training(model)

        tokenizer = AutoTokenizer.from_pretrained(
            cfg.base_model,
            trust_remote_code=True,
            cache_dir=cfg.model_cache_dir,
        )
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        # --- 5. LoRA adapter ---
        lora_cfg = LoraConfig(
            r=cfg.r,
            lora_alpha=cfg.lora_alpha,
            lora_dropout=cfg.lora_dropout,
            target_modules=cfg.target_modules,
            bias=cfg.bias,
            task_type=cfg.task_type,
        )
        model = get_peft_model(model, lora_cfg)
        model.print_trainable_parameters()

        # --- 6. Dataset ---
        from dataset import load_jsonl_dataset  # type: ignore[import]

        raw_samples = load_jsonl_dataset(cfg.dataset_path, fmt=cfg.dataset_format)

        def _apply_chat_template(messages: list[dict]) -> str:
            return tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=False
            )

        texts = [_apply_chat_template(msgs) for msgs in raw_samples]
        hf_ds = HFDataset.from_dict({"text": texts})

        # --- 7. Training args ---
        training_args = TrainingArguments(
            output_dir=cfg.output_dir,
            num_train_epochs=cfg.num_train_epochs,
            per_device_train_batch_size=cfg.per_device_train_batch_size,
            gradient_accumulation_steps=cfg.gradient_accumulation_steps,
            learning_rate=cfg.learning_rate,
            lr_scheduler_type=cfg.lr_scheduler_type,
            warmup_ratio=cfg.warmup_ratio,
            weight_decay=cfg.weight_decay,
            max_grad_norm=cfg.max_grad_norm,
            fp16=cfg.fp16,
            bf16=cfg.bf16,
            optim=cfg.optim,
            logging_steps=cfg.logging_steps,
            save_steps=cfg.save_steps,
            save_total_limit=cfg.save_total_limit,
            dataloader_num_workers=cfg.dataloader_num_workers,
            report_to=[],  # MLflow managed manually
        )

        # --- 8. SFTTrainer ---
        trainer = SFTTrainer(
            model=model,
            args=training_args,
            train_dataset=hf_ds,
            tokenizer=tokenizer,
            max_seq_length=cfg.max_seq_length,
            dataset_text_field="text",
            packing=False,
        )

        logger.info("Starting SFT training — %d steps total", len(trainer.get_train_dataloader()))
        train_result = trainer.train()

        # --- 9. Log metrics ---
        for key, val in train_result.metrics.items():
            try:
                mlflow.log_metric(key, float(val))
            except (TypeError, ValueError):
                pass

        # --- 10. Save adapter ---
        adapter_path = cfg.adapter_path()
        Path(adapter_path).mkdir(parents=True, exist_ok=True)
        model.save_pretrained(adapter_path)
        tokenizer.save_pretrained(adapter_path)
        mlflow.log_artifact(adapter_path, artifact_path="adapter")
        logger.info("Adapter saved to %s", adapter_path)

        return adapter_path


if __name__ == "__main__":
    import argparse
    import importlib.util

    parser = argparse.ArgumentParser(description="QLoRA fine-tuning for Qwen3-VL")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "config.py"),
        help="Path to QLoRAConfig definition (module with cfg = QLoRAConfig(...))",
    )
    args = parser.parse_args()

    # Load config module
    spec = importlib.util.spec_from_file_location("qlora_config_module", args.config)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    cfg_obj = getattr(mod, "cfg", None)
    if cfg_obj is None:
        # Instantiate with defaults
        from config import QLoRAConfig
        cfg_obj = QLoRAConfig()

    train(cfg_obj)
