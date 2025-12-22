#!/usr/bin/env python3
"""GPU monitoring script - executes nvidia-smi and returns structured data."""

import subprocess
import json
import sys


def get_gpu_status() -> dict:
    """Get GPU status using nvidia-smi."""
    result = {"gpus": [], "total_gpus": 0, "healthy": False, "error": None}

    try:
        # Try nvidia-smi directly
        output = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if output.returncode != 0:
            # Try via docker container
            output = subprocess.run(
                [
                    "docker",
                    "exec",
                    "nemotron-coding",
                    "nvidia-smi",
                    "--query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )

        if output.returncode == 0:
            for line in output.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 7:
                    result["gpus"].append(
                        {
                            "index": int(parts[0]),
                            "name": parts[1],
                            "memory_total_mib": int(parts[2]),
                            "memory_used_mib": int(parts[3]),
                            "memory_free_mib": int(parts[4]),
                            "utilization_percent": int(parts[5]),
                            "temperature_c": int(parts[6]),
                        }
                    )

            result["total_gpus"] = len(result["gpus"])
            result["healthy"] = result["total_gpus"] > 0
        else:
            result["error"] = output.stderr or "nvidia-smi failed"

    except FileNotFoundError:
        result["error"] = "nvidia-smi not found. Install NVIDIA drivers."
    except subprocess.TimeoutExpired:
        result["error"] = "nvidia-smi timed out"
    except Exception as e:
        result["error"] = str(e)

    return result


def get_gpu_processes() -> dict:
    """Get processes using GPUs."""
    result = {"processes": [], "error": None}

    try:
        output = subprocess.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,name,used_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if output.returncode == 0:
            for line in output.stdout.strip().split("\n"):
                if not line or "[Not Found]" in line:
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    result["processes"].append(
                        {"pid": parts[0], "name": parts[1], "memory_mib": parts[2]}
                    )
    except Exception as e:
        result["error"] = str(e)

    return result


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "status"

    if action == "status":
        print(json.dumps(get_gpu_status(), indent=2))
    elif action == "processes":
        print(json.dumps(get_gpu_processes(), indent=2))
    else:
        print(json.dumps({"error": f"Unknown action: {action}"}))
