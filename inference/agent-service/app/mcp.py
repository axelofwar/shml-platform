"""
MCP (Model Context Protocol) Server Implementation for SHML Platform.

Exposes platform capabilities as MCP tools for OpenCode integration:
- training_status: Get Ray job status and metrics
- gpu_status: Check GPU VRAM usage and processes
- mlflow_query: Query MLflow experiments and runs
- vision_analyze: Analyze images with Qwen3-VL (RTX 2070)

⚠️ TRAINING SAFETY:
- Code generation tools are DISABLED while RTX 3090 is busy with training
- Vision tools use RTX 2070, always safe to call
- Status/query tools are read-only, always safe

MCP Protocol Reference: https://opencode.ai/docs/mcp-servers
"""

import asyncio
import os
import subprocess
import json
import base64
import httpx
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================================
# MCP Protocol Models
# ============================================================================


class MCPToolParameter(BaseModel):
    """MCP tool parameter definition"""

    name: str
    type: str  # "string", "number", "boolean", "object", "array"
    description: str
    required: bool = True
    default: Optional[Any] = None


class MCPTool(BaseModel):
    """MCP tool definition"""

    name: str
    description: str
    parameters: List[MCPToolParameter] = Field(default_factory=list)
    gpu_required: Optional[str] = None  # None, "cuda:0", "cuda:1"
    safe_during_training: bool = True  # Can be called while RTX 3090 is training


class MCPToolResult(BaseModel):
    """Result from MCP tool execution"""

    success: bool
    result: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0


class MCPServerInfo(BaseModel):
    """MCP server information"""

    name: str = "shml-platform"
    version: str = "1.0.0"
    description: str = "SHML Platform MCP Server - Vision, Training, GPU tools"
    tools_count: int = 0
    training_active: bool = False
    gpu_status: Dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# Training Status Detector
# ============================================================================


class TrainingStatusChecker:
    """Check if training is active on RTX 3090 Ti (GPU 0)"""

    # GPU INDEX MAPPING (verified via nvidia-smi):
    #   cuda:0 = RTX 3090 Ti (24GB) - Training GPU
    #   cuda:1 = RTX 2070 (8GB) - Vision/Inference GPU
    TRAINING_GPU_INDEX = 0  # RTX 3090 Ti
    VISION_GPU_INDEX = 1  # RTX 2070

    @staticmethod
    async def is_training_active() -> tuple[bool, Dict[str, Any]]:
        """
        Check if training is running on RTX 3090 Ti (cuda:0)

        Returns:
            (is_active: bool, info: dict)
        """
        try:
            # Check nvidia-smi for GPU 0 (RTX 3090 Ti) processes
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-compute-apps=pid,name,used_memory",
                    "--format=csv,noheader,nounits",
                    "-i",
                    "0",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                return False, {"error": "nvidia-smi failed"}

            output = result.stdout.strip()
            if not output:
                return False, {"gpu_0_processes": [], "training_active": False}

            processes = []
            training_keywords = ["python", "ray", "yolo", "train", "ultralytics"]
            training_active = False

            for line in output.split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    proc = {
                        "pid": parts[0],
                        "name": parts[1],
                        "memory_mb": int(parts[2]) if parts[2].isdigit() else 0,
                    }
                    processes.append(proc)

                    # Check if this looks like training
                    for kw in training_keywords:
                        if kw in parts[1].lower():
                            training_active = True
                            break

            # Also check for high VRAM usage (>20GB = likely training)
            total_vram = sum(p["memory_mb"] for p in processes)
            if total_vram > 20000:  # >20GB VRAM used
                training_active = True

            return training_active, {
                "gpu_0_processes": processes,  # RTX 3090 Ti
                "training_active": training_active,
                "total_vram_used_mb": total_vram,
            }

        except Exception as e:
            logger.error(f"Failed to check training status: {e}")
            return False, {"error": str(e)}


# ============================================================================
# MCP Tool Implementations
# ============================================================================


class MCPToolExecutor:
    """Execute MCP tools with safety checks"""

    def __init__(self):
        self.gateway_url = "http://inference-gateway:8000"
        self.qwen3_vl_url = "http://qwen3-vl-api:8000"
        self.mlflow_url = os.environ.get(
            "MLFLOW_TRACKING_URI", "http://mlflow-nginx:80"
        )
        self.ray_api_url = "http://ray-compute-api:8000"

    async def execute(self, tool_name: str, args: Dict[str, Any]) -> MCPToolResult:
        """Execute a tool by name with arguments"""
        start_time = datetime.now()

        try:
            # Route to appropriate handler
            handlers = {
                "training_status": self._training_status,
                "gpu_status": self._gpu_status,
                "mlflow_query": self._mlflow_query,
                "vision_analyze": self._vision_analyze,
                "vision_then_code": self._vision_then_code,
            }

            handler = handlers.get(tool_name)
            if not handler:
                return MCPToolResult(
                    success=False,
                    error=f"Unknown tool: {tool_name}",
                    execution_time_ms=0,
                )

            result = await handler(args)

            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            return MCPToolResult(
                success=True, result=result, execution_time_ms=execution_time
            )

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds() * 1000
            logger.exception(f"Tool execution failed: {tool_name}")
            return MCPToolResult(
                success=False, error=str(e), execution_time_ms=execution_time
            )

    async def _training_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get training job status from Ray and MLflow

        Args:
            job_id: Optional specific job ID (default: latest)
        """
        job_id = args.get("job_id", "latest")

        status = {
            "timestamp": datetime.now().isoformat(),
            "job_id": job_id,
            "ray_status": None,
            "mlflow_metrics": None,
            "gpu_info": None,
        }

        # Check GPU training status
        training_active, gpu_info = await TrainingStatusChecker.is_training_active()
        status["gpu_info"] = gpu_info
        status["training_active"] = training_active

        # Try to get Ray job status
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                if job_id == "latest":
                    # Get latest job
                    resp = await client.get(f"{self.ray_api_url}/api/v1/jobs")
                    if resp.status_code == 200:
                        jobs = resp.json()
                        if jobs.get("jobs"):
                            latest = sorted(
                                jobs["jobs"],
                                key=lambda x: x.get("created_at", ""),
                                reverse=True,
                            )[0]
                            status["ray_status"] = latest
                            job_id = latest.get("job_id")
                else:
                    resp = await client.get(f"{self.ray_api_url}/api/v1/jobs/{job_id}")
                    if resp.status_code == 200:
                        status["ray_status"] = resp.json()
        except Exception as e:
            status["ray_error"] = str(e)

        # Try to get MLflow metrics (check results.csv for training progress)
        try:
            # Check for local training logs
            import os

            log_dir = "/home/axelofwar/Projects/shml-platform/logs"
            results_file = None

            # Find latest training run results
            for root, dirs, files in os.walk(log_dir):
                for f in files:
                    if f == "results.csv":
                        results_file = os.path.join(root, f)

            if results_file and os.path.exists(results_file):
                import csv

                with open(results_file, "r") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)
                    if rows:
                        latest = rows[-1]
                        status["mlflow_metrics"] = {
                            "epoch": latest.get("epoch", "?"),
                            "mAP50": latest.get("metrics/mAP50(B)", "?"),
                            "recall": latest.get("metrics/recall(B)", "?"),
                            "box_loss": latest.get("train/box_loss", "?"),
                            "cls_loss": latest.get("train/cls_loss", "?"),
                        }
        except Exception as e:
            status["mlflow_error"] = str(e)

        return status

    async def _gpu_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get GPU status from nvidia-smi

        Args:
            gpu_id: Optional specific GPU (default: all)
        """
        gpu_id = args.get("gpu_id")

        try:
            cmd = [
                "nvidia-smi",
                "--query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ]
            if gpu_id is not None:
                cmd.extend(["-i", str(gpu_id)])

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

            if result.returncode != 0:
                return {"error": "nvidia-smi failed", "stderr": result.stderr}

            gpus = []
            for line in result.stdout.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 6:
                    gpus.append(
                        {
                            "index": int(parts[0]),
                            "name": parts[1],
                            "memory_used_mb": int(parts[2]),
                            "memory_total_mb": int(parts[3]),
                            "utilization_percent": int(parts[4]),
                            "temperature_c": int(parts[5]),
                            "memory_percent": round(
                                int(parts[2]) / int(parts[3]) * 100, 1
                            ),
                        }
                    )

            # Get processes
            proc_cmd = [
                "nvidia-smi",
                "--query-compute-apps=gpu_uuid,pid,name,used_memory",
                "--format=csv,noheader,nounits",
            ]
            proc_result = subprocess.run(
                proc_cmd, capture_output=True, text=True, timeout=5
            )

            processes = []
            if proc_result.returncode == 0:
                for line in proc_result.stdout.strip().split("\n"):
                    if line:
                        parts = [p.strip() for p in line.split(",")]
                        if len(parts) >= 4:
                            processes.append(
                                {
                                    "gpu_uuid": parts[0],
                                    "pid": parts[1],
                                    "name": parts[2],
                                    "memory_mb": (
                                        int(parts[3]) if parts[3].isdigit() else 0
                                    ),
                                }
                            )

            # Check training status
            training_active, _ = await TrainingStatusChecker.is_training_active()

            return {
                "timestamp": datetime.now().isoformat(),
                "gpus": gpus,
                "processes": processes,
                "training_active": training_active,
                "gpu_assignment": {
                    "cuda:0": "RTX 3090 Ti (Training GPU)",
                    "cuda:1": "RTX 2070 (Vision/Inference GPU)",
                },
                "safe_for_inference": {
                    "cuda:0": not training_active,  # RTX 3090 Ti only if not training
                    "cuda:1": True,  # RTX 2070 always available for vision
                },
            }

        except Exception as e:
            logger.exception("GPU status check failed")
            return {"error": str(e)}

    async def _mlflow_query(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Query MLflow experiments and runs

        Args:
            experiment_name: Optional experiment name filter
            run_id: Optional specific run ID
            metric: Optional metric to retrieve
        """
        experiment_name = args.get("experiment_name")
        run_id = args.get("run_id")
        metric = args.get("metric")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # List experiments
                resp = await client.get(
                    f"{self.mlflow_url}/api/2.0/mlflow/experiments/list"
                )

                if resp.status_code != 200:
                    # Try fallback URL (direct container)
                    resp = await client.get(
                        "http://172.30.0.19:5000/api/2.0/mlflow/experiments/list"
                    )

                if resp.status_code == 200:
                    experiments = resp.json().get("experiments", [])

                    # Filter if requested
                    if experiment_name:
                        experiments = [
                            e
                            for e in experiments
                            if experiment_name.lower() in e.get("name", "").lower()
                        ]

                    return {
                        "timestamp": datetime.now().isoformat(),
                        "experiments": experiments[:10],  # Limit results
                        "total_count": len(experiments),
                    }
                else:
                    return {
                        "error": f"MLflow API returned {resp.status_code}",
                        "hint": "MLflow may be using OAuth. Check TROUBLESHOOTING.md",
                    }

        except Exception as e:
            logger.exception("MLflow query failed")
            return {"error": str(e)}

    async def _vision_analyze(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze image with Qwen3-VL (RTX 2070 - always safe)

        Args:
            image: Base64-encoded image OR URL
            prompt: Analysis prompt (default: "Describe this image in detail")
        """
        image = args.get("image")
        prompt = args.get("prompt", "Describe this image in detail")

        if not image:
            return {"error": "image parameter required (base64 or URL)"}

        try:
            # Determine if URL or base64
            if image.startswith("http://") or image.startswith("https://"):
                image_content = {"type": "image_url", "image_url": {"url": image}}
            else:
                # Assume base64
                if not image.startswith("data:"):
                    image = f"data:image/png;base64,{image}"
                image_content = {"type": "image_url", "image_url": {"url": image}}

            # Call Qwen3-VL
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{self.qwen3_vl_url}/v1/chat/completions",
                    json={
                        "model": "qwen3-vl",
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    image_content,
                                    {"type": "text", "text": prompt},
                                ],
                            }
                        ],
                        "max_tokens": 2048,
                    },
                )

                if resp.status_code == 200:
                    result = resp.json()
                    return {
                        "timestamp": datetime.now().isoformat(),
                        "model": "qwen3-vl-8b",
                        "gpu": "cuda:0 (RTX 2070)",
                        "analysis": result.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", ""),
                        "usage": result.get("usage", {}),
                    }
                else:
                    return {
                        "error": f"Qwen3-VL returned {resp.status_code}",
                        "detail": resp.text[:500],
                    }

        except Exception as e:
            logger.exception("Vision analysis failed")
            return {"error": str(e)}

    async def _vision_then_code(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze image then generate code (REQUIRES RTX 3090 - blocked during training)

        Args:
            image: Base64-encoded image OR URL
            task: Code generation task based on image
        """
        # Safety check - is training active?
        training_active, gpu_info = await TrainingStatusChecker.is_training_active()

        if training_active:
            return {
                "error": "BLOCKED: RTX 3090 is busy with training",
                "training_info": gpu_info,
                "hint": "Use vision_analyze (RTX 2070) or wait for training to complete",
                "safe_during_training": False,
            }

        # If we get here, training is not active - proceed with full pipeline
        image = args.get("image")
        task = args.get("task", "Generate code based on this image")

        # First, analyze with vision
        vision_result = await self._vision_analyze(
            {"image": image, "prompt": f"Analyze this image for: {task}"}
        )

        if "error" in vision_result:
            return vision_result

        # TODO: Route to coding model when available post-training
        return {
            "timestamp": datetime.now().isoformat(),
            "vision_analysis": vision_result.get("analysis"),
            "code_generation": "NOT IMPLEMENTED - Waiting for Nemotron-3 setup (Phase P7)",
            "hint": "After Phase 5 training, coding model will be available on RTX 3090",
        }


# ============================================================================
# MCP Server / Router
# ============================================================================


class MCPServer:
    """MCP Server for SHML Platform"""

    def __init__(self):
        self.executor = MCPToolExecutor()
        self.tools = self._define_tools()

    def _define_tools(self) -> List[MCPTool]:
        """Define available MCP tools"""
        return [
            MCPTool(
                name="training_status",
                description="Get Ray training job status, MLflow metrics, GPU usage. Always safe to call.",
                parameters=[
                    MCPToolParameter(
                        name="job_id",
                        type="string",
                        description="Job ID or 'latest' for most recent job",
                        required=False,
                        default="latest",
                    )
                ],
                gpu_required=None,
                safe_during_training=True,
            ),
            MCPTool(
                name="gpu_status",
                description="Get GPU VRAM usage, processes, temperature. Always safe to call.",
                parameters=[
                    MCPToolParameter(
                        name="gpu_id",
                        type="number",
                        description="GPU index (0=RTX 2070, 1=RTX 3090) or omit for all",
                        required=False,
                    )
                ],
                gpu_required=None,
                safe_during_training=True,
            ),
            MCPTool(
                name="mlflow_query",
                description="Query MLflow experiments and runs. Always safe to call.",
                parameters=[
                    MCPToolParameter(
                        name="experiment_name",
                        type="string",
                        description="Filter by experiment name (partial match)",
                        required=False,
                    ),
                    MCPToolParameter(
                        name="run_id",
                        type="string",
                        description="Specific run ID to retrieve",
                        required=False,
                    ),
                    MCPToolParameter(
                        name="metric",
                        type="string",
                        description="Specific metric to retrieve",
                        required=False,
                    ),
                ],
                gpu_required=None,
                safe_during_training=True,
            ),
            MCPTool(
                name="vision_analyze",
                description="Analyze image with Qwen3-VL. Uses RTX 2070, always safe during training.",
                parameters=[
                    MCPToolParameter(
                        name="image",
                        type="string",
                        description="Base64-encoded image or URL",
                        required=True,
                    ),
                    MCPToolParameter(
                        name="prompt",
                        type="string",
                        description="Analysis prompt",
                        required=False,
                        default="Describe this image in detail",
                    ),
                ],
                gpu_required="cuda:1",  # RTX 2070 - Vision GPU
                safe_during_training=True,
            ),
            MCPTool(
                name="vision_then_code",
                description="Analyze image then generate code. ⚠️ BLOCKED during training (needs RTX 3090 Ti).",
                parameters=[
                    MCPToolParameter(
                        name="image",
                        type="string",
                        description="Base64-encoded image or URL",
                        required=True,
                    ),
                    MCPToolParameter(
                        name="task",
                        type="string",
                        description="Code generation task based on image",
                        required=True,
                    ),
                ],
                gpu_required="cuda:0",  # RTX 3090 Ti - Training GPU (blocked during training)
                safe_during_training=False,
            ),
        ]

    async def get_server_info(self) -> MCPServerInfo:
        """Get server information and status"""
        training_active, gpu_info = await TrainingStatusChecker.is_training_active()

        return MCPServerInfo(
            name="shml-platform",
            version="1.0.0",
            description="SHML Platform MCP Server - Vision, Training, GPU tools",
            tools_count=len(self.tools),
            training_active=training_active,
            gpu_status=gpu_info,
        )

    def get_tools(self) -> List[Dict[str, Any]]:
        """Get list of available tools in MCP format"""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        p.name: {
                            "type": p.type,
                            "description": p.description,
                            **({"default": p.default} if p.default is not None else {}),
                        }
                        for p in tool.parameters
                    },
                    "required": [p.name for p in tool.parameters if p.required],
                },
                "metadata": {
                    "gpu_required": tool.gpu_required,
                    "safe_during_training": tool.safe_during_training,
                },
            }
            for tool in self.tools
        ]

    async def call_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> MCPToolResult:
        """Execute a tool by name"""
        # Validate tool exists
        tool = next((t for t in self.tools if t.name == tool_name), None)
        if not tool:
            return MCPToolResult(
                success=False,
                error=f"Unknown tool: {tool_name}. Available: {[t.name for t in self.tools]}",
            )

        # Check if safe during training
        if not tool.safe_during_training:
            training_active, _ = await TrainingStatusChecker.is_training_active()
            if training_active:
                return MCPToolResult(
                    success=False,
                    error=f"Tool '{tool_name}' requires GPU cuda:1 which is busy with training. "
                    f"Use safe alternatives or wait for training to complete.",
                )

        # Execute
        return await self.executor.execute(tool_name, arguments)


# Global MCP server instance
mcp_server = MCPServer()
