#!/usr/bin/env python3
"""Unified model benchmark — compares GGUF (llama.cpp), vLLM AWQ, and vLLM+TriAttention.

Usage:
    # Benchmark running GGUF endpoint:
    python3 inference/benchmark_models.py --backend gguf --endpoint http://172.30.0.31:8000

    # Benchmark vLLM AWQ (must be running):
    python3 inference/benchmark_models.py --backend vllm-awq --endpoint http://localhost:8000

    # Run all backends and compare:
    python3 inference/benchmark_models.py --all
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

PROMPTS = {
    "short": {
        "messages": [{"role": "user", "content": "What is 2+2? Be brief."}],
        "max_tokens": 50,
        "description": "Trivial arithmetic",
    },
    "medium": {
        "messages": [
            {
                "role": "user",
                "content": "Explain the difference between TCP and UDP. Include 3 key distinctions.",
            }
        ],
        "max_tokens": 300,
        "description": "Short explanation",
    },
    "code": {
        "messages": [
            {
                "role": "user",
                "content": "Write a Python function that implements binary search on a sorted list. Include type hints.",
            }
        ],
        "max_tokens": 512,
        "description": "Code generation",
    },
    "reasoning": {
        "messages": [
            {
                "role": "user",
                "content": (
                    "A farmer has 17 sheep. All but 9 die. How many sheep does the farmer have left? "
                    "Think through this step by step."
                ),
            }
        ],
        "max_tokens": 256,
        "description": "Reasoning puzzle",
    },
    "long_context": {
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful coding assistant.",
            },
            {
                "role": "user",
                "content": (
                    "Implement a FastAPI application with the following features:\n"
                    "1. User registration with email validation\n"
                    "2. JWT authentication with refresh tokens\n"
                    "3. Rate limiting middleware\n"
                    "4. Health check endpoint\n"
                    "5. Pydantic request/response models\n"
                    "Include proper error handling and type annotations."
                ),
            },
        ],
        "max_tokens": 1024,
        "description": "Complex code generation",
    },
}


@dataclass
class BenchmarkResult:
    backend: str
    prompt_name: str
    description: str
    elapsed_seconds: float
    total_tokens: int
    reasoning_chars: int
    content_chars: int
    tokens_per_second: float
    first_token_ms: Optional[float] = None
    error: Optional[str] = None


@dataclass
class BackendConfig:
    name: str
    endpoint: str
    model: str = ""


def benchmark_streaming(
    config: BackendConfig, prompt_name: str, prompt: dict
) -> BenchmarkResult:
    """Benchmark a single prompt via streaming SSE."""
    url = f"{config.endpoint}/v1/chat/completions"
    payload = {
        "model": config.model or "default",
        "messages": prompt["messages"],
        "max_tokens": prompt["max_tokens"],
        "temperature": 0.6,
        "stream": True,
    }

    reasoning_chars = 0
    content_chars = 0
    total_tokens = 0
    first_token_time = None

    try:
        start = time.perf_counter()
        with httpx.Client(timeout=120.0) as client:
            with client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})

                    if first_token_time is None and (
                        delta.get("content") or delta.get("reasoning_content")
                    ):
                        first_token_time = time.perf_counter()

                    if delta.get("reasoning_content"):
                        reasoning_chars += len(delta["reasoning_content"])
                    if delta.get("content"):
                        content_chars += len(delta["content"])

                    usage = chunk.get("usage")
                    if usage and usage.get("completion_tokens"):
                        total_tokens = usage["completion_tokens"]

        elapsed = time.perf_counter() - start

        # Estimate tokens from chars if usage not reported
        if total_tokens == 0:
            total_tokens = max(1, (reasoning_chars + content_chars) // 4)

        tps = total_tokens / elapsed if elapsed > 0 else 0
        ttft = (
            (first_token_time - start) * 1000
            if first_token_time
            else None
        )

        return BenchmarkResult(
            backend=config.name,
            prompt_name=prompt_name,
            description=prompt["description"],
            elapsed_seconds=round(elapsed, 2),
            total_tokens=total_tokens,
            reasoning_chars=reasoning_chars,
            content_chars=content_chars,
            tokens_per_second=round(tps, 1),
            first_token_ms=round(ttft, 0) if ttft else None,
        )
    except Exception as e:
        return BenchmarkResult(
            backend=config.name,
            prompt_name=prompt_name,
            description=prompt["description"],
            elapsed_seconds=0,
            total_tokens=0,
            reasoning_chars=0,
            content_chars=0,
            tokens_per_second=0,
            error=str(e),
        )


def check_health(endpoint: str) -> bool:
    """Check if endpoint is reachable."""
    try:
        resp = httpx.get(f"{endpoint}/health", timeout=5.0)
        return resp.status_code == 200
    except Exception:
        return False


def get_gpu_info() -> str:
    """Get GPU VRAM usage."""
    try:
        import subprocess

        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return "unavailable"


def run_benchmark(
    config: BackendConfig,
    prompts: Optional[list[str]] = None,
    warmup: bool = True,
) -> list[BenchmarkResult]:
    """Run full benchmark suite on a backend."""
    results = []
    prompt_keys = prompts or list(PROMPTS.keys())

    if warmup:
        logger.info(f"  Warmup request to {config.name}...")
        benchmark_streaming(config, "warmup", PROMPTS["short"])

    for name in prompt_keys:
        if name not in PROMPTS:
            logger.warning(f"  Unknown prompt: {name}")
            continue
        logger.info(f"  [{config.name}] Running: {name}...")
        result = benchmark_streaming(config, name, PROMPTS[name])
        if result.error:
            logger.error(f"  [{config.name}] {name}: ERROR — {result.error}")
        else:
            logger.info(
                f"  [{config.name}] {name}: {result.elapsed_seconds}s, "
                f"{result.total_tokens} tok, {result.tokens_per_second} tok/s, "
                f"TTFT={result.first_token_ms}ms"
            )
        results.append(result)

    return results


def print_comparison_table(all_results: dict[str, list[BenchmarkResult]]) -> str:
    """Print a comparison table across backends."""
    lines = []
    lines.append("\n" + "=" * 90)
    lines.append("BENCHMARK COMPARISON")
    lines.append("=" * 90)

    # Header
    backends = list(all_results.keys())
    header = f"{'Prompt':<15} | "
    header += " | ".join(f"{b:>20}" for b in backends)
    lines.append(header)
    lines.append("-" * len(header))

    # Metrics per prompt
    prompt_names = list(PROMPTS.keys())
    for metric_name, metric_key in [
        ("tok/s", "tokens_per_second"),
        ("TTFT (ms)", "first_token_ms"),
        ("time (s)", "elapsed_seconds"),
    ]:
        lines.append(f"\n--- {metric_name} ---")
        for pname in prompt_names:
            row = f"{pname:<15} | "
            for backend in backends:
                matching = [r for r in all_results[backend] if r.prompt_name == pname]
                if matching and not matching[0].error:
                    val = getattr(matching[0], metric_key)
                    row += f"{val if val is not None else 'N/A':>20} | "
                else:
                    row += f"{'ERROR':>20} | "
            lines.append(row)

    lines.append("\n" + "=" * 90)
    lines.append(f"GPU: {get_gpu_info()}")
    lines.append("=" * 90)

    output = "\n".join(lines)
    print(output)
    return output


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    parser = argparse.ArgumentParser(description="Model benchmark comparison")
    parser.add_argument(
        "--backend",
        choices=["gguf", "vllm-awq", "vllm-triattn"],
        help="Backend to benchmark",
    )
    parser.add_argument("--endpoint", help="Endpoint URL (e.g. http://172.30.0.31:8000)")
    parser.add_argument("--model", default="", help="Model name for API calls")
    parser.add_argument(
        "--prompts",
        nargs="+",
        help="Specific prompts to run (default: all)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all available backends",
    )
    parser.add_argument(
        "--output",
        help="Save results to JSON file",
    )
    parser.add_argument(
        "--no-warmup",
        action="store_true",
        help="Skip warmup request",
    )
    args = parser.parse_args()

    all_results: dict[str, list[BenchmarkResult]] = {}

    # Default backends when --all
    default_backends = [
        BackendConfig("GGUF (llama.cpp)", "http://172.30.0.31:8000"),
    ]

    if args.all:
        for config in default_backends:
            if check_health(config.endpoint):
                logger.info(f"Benchmarking {config.name} at {config.endpoint}")
                results = run_benchmark(
                    config, args.prompts, warmup=not args.no_warmup
                )
                all_results[config.name] = results
            else:
                logger.warning(f"Skipping {config.name} — endpoint unreachable")
    elif args.backend and args.endpoint:
        config = BackendConfig(args.backend, args.endpoint, args.model)
        if not check_health(config.endpoint):
            logger.error(f"Endpoint {args.endpoint} unreachable")
            sys.exit(1)
        results = run_benchmark(config, args.prompts, warmup=not args.no_warmup)
        all_results[config.name] = results
    else:
        parser.print_help()
        sys.exit(1)

    # Print comparison
    table = print_comparison_table(all_results)

    # Save results
    if args.output:
        serializable = {
            backend: [
                {
                    "backend": r.backend,
                    "prompt": r.prompt_name,
                    "description": r.description,
                    "elapsed_s": r.elapsed_seconds,
                    "tokens": r.total_tokens,
                    "reasoning_chars": r.reasoning_chars,
                    "content_chars": r.content_chars,
                    "tok_per_s": r.tokens_per_second,
                    "ttft_ms": r.first_token_ms,
                    "error": r.error,
                }
                for r in results_list
            ]
            for backend, results_list in all_results.items()
        }
        with open(args.output, "w") as f:
            json.dump(serializable, f, indent=2)
        logger.info(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
