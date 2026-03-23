"""QLoRA fine-tuning configuration for Qwen3-VL."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# NF4 quantization config (BitsAndBytes)
NF4_QUANT_CONFIG = {
    "load_in_4bit": True,
    "bnb_4bit_quant_type": "nf4",
    "bnb_4bit_use_double_quant": True,
    "bnb_4bit_compute_dtype": "bfloat16",
}


@dataclass
class QLoRAConfig:
    """Configuration for QLoRA fine-tuning of Qwen3-VL."""

    # --- Model ---
    base_model: str = "Qwen/Qwen2-VL-7B-Instruct"
    model_cache_dir: str = "/data/models/qwen3-vl"

    # --- LoRA adapter ---
    r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    target_modules: list[str] = field(default_factory=lambda: [
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ])
    bias: str = "none"
    task_type: str = "CAUSAL_LM"

    # --- Dataset ---
    dataset_path: str = "/data/datasets/qwen3-vl/train.jsonl"
    dataset_format: str = "sharegpt"  # "sharegpt" or "alpaca"
    max_seq_length: int = 2048
    streaming: bool = False

    # --- Training ---
    output_dir: str = "/data/checkpoints/qwen3-vl-qlora"
    num_train_epochs: int = 3
    per_device_train_batch_size: int = 1
    gradient_accumulation_steps: int = 8
    learning_rate: float = 2e-4
    lr_scheduler_type: str = "cosine"
    warmup_ratio: float = 0.03
    weight_decay: float = 0.01
    max_grad_norm: float = 1.0
    fp16: bool = False
    bf16: bool = True
    optim: str = "paged_adamw_32bit"
    dataloader_num_workers: int = 2

    # --- Logging & Checkpointing ---
    logging_steps: int = 10
    save_steps: int = 100
    save_total_limit: int = 3
    mlflow_experiment: str = "qwen3-vl-qlora"
    mlflow_tracking_uri: str = "http://mlflow-nginx:80"

    # --- GPU ---
    gpu_id: int = 0  # RTX 3090 Ti (cuda:0)
    yield_endpoint: str = "http://z-image-api:8000/yield-to-training"
    yield_timeout_sec: int = 30

    # --- Merge ---
    merged_output_dir: Optional[str] = None  # Set to save merged model

    def adapter_path(self) -> str:
        """Directory where the trained LoRA adapter is saved."""
        return f"{self.output_dir}/adapter"
