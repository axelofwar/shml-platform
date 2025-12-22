"""
Cluster Management API Endpoints
Proxy endpoints to Ray native dashboard API for cluster monitoring
"""

import os
import asyncio
import httpx
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .auth import get_current_user
from .models import User

# Initialize router
router = APIRouter(prefix="/cluster", tags=["cluster"])

# Ray dashboard address
RAY_DASHBOARD_URL = os.getenv("RAY_DASHBOARD_ADDRESS", "http://ray-head:8265")

# HTTP client for proxying to Ray dashboard
http_client = httpx.AsyncClient(timeout=10.0)


class NodeInfo(BaseModel):
    """Node information"""

    node_id: str
    ip: str
    hostname: str
    is_head: bool
    state: str
    cpu_usage: float
    cpu_total: float
    memory_used: float
    memory_total: float
    gpu_usage: List[Dict[str, Any]]
    disk_usage: float
    disk_total: float


class ClusterStatus(BaseModel):
    """Cluster status response"""

    status: str
    ray_version: str
    total_nodes: int
    active_nodes: int
    total_cpus: float
    used_cpus: float
    total_gpus: float
    used_gpus: float
    total_memory_gb: float
    used_memory_gb: float
    object_store_memory_gb: float
    object_store_used_gb: float


class GPUInfo(BaseModel):
    """GPU information"""

    index: int
    name: str
    memory_total_mb: float
    memory_used_mb: float
    memory_free_mb: float
    utilization_percent: float
    temperature_c: Optional[float] = None


@router.get("/status", response_model=ClusterStatus)
async def get_cluster_status(
    current_user: User = Depends(get_current_user),
):
    """
    Get cluster status summary from Ray dashboard
    Returns CPU, GPU, memory usage across all nodes
    """
    try:
        response = await http_client.get(f"{RAY_DASHBOARD_URL}/api/cluster_status")
        response.raise_for_status()
        data = response.json()

        # Parse cluster status from Ray API response
        cluster_data = data.get("data", {})
        load_metrics = cluster_data.get("loadMetricsReport", {})
        usage = load_metrics.get("usage", {})

        # Extract resource usage
        cpu_usage = usage.get("CPU", [0, 0])
        gpu_usage = usage.get("GPU", [0, 0])
        memory_usage = usage.get("memory", [0, 0])
        object_store = usage.get("objectStoreMemory", [0, 0])

        # Get version info
        version_response = await http_client.get(f"{RAY_DASHBOARD_URL}/api/version")
        version_data = (
            version_response.json() if version_response.status_code == 200 else {}
        )

        # Count active nodes
        autoscaler = cluster_data.get("autoscalerReport", {})
        active_nodes = autoscaler.get("activeNodes", {})
        total_nodes = sum(active_nodes.values()) if active_nodes else 1

        return ClusterStatus(
            status="healthy" if data.get("result") else "degraded",
            ray_version=version_data.get("ray_version", "unknown"),
            total_nodes=total_nodes,
            active_nodes=total_nodes,
            total_cpus=cpu_usage[1] if len(cpu_usage) > 1 else 0,
            used_cpus=cpu_usage[0] if len(cpu_usage) > 0 else 0,
            total_gpus=gpu_usage[1] if len(gpu_usage) > 1 else 0,
            used_gpus=gpu_usage[0] if len(gpu_usage) > 0 else 0,
            total_memory_gb=memory_usage[1] / (1024**3) if len(memory_usage) > 1 else 0,
            used_memory_gb=memory_usage[0] / (1024**3) if len(memory_usage) > 0 else 0,
            object_store_memory_gb=(
                object_store[1] / (1024**3) if len(object_store) > 1 else 0
            ),
            object_store_used_gb=(
                object_store[0] / (1024**3) if len(object_store) > 0 else 0
            ),
        )

    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=503, detail=f"Failed to connect to Ray dashboard: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error getting cluster status: {str(e)}"
        )


@router.get("/nodes")
async def get_cluster_nodes(
    current_user: User = Depends(get_current_user),
):
    """
    Get list of all nodes in the cluster
    """
    try:
        response = await http_client.get(f"{RAY_DASHBOARD_URL}/nodes?view=summary")
        response.raise_for_status()
        data = response.json()

        nodes = []
        for node in data.get("data", {}).get("summary", []):
            nodes.append(
                {
                    "node_id": node.get("raylet", {}).get("nodeId", ""),
                    "ip": node.get("ip", ""),
                    "hostname": node.get("hostname", ""),
                    "is_head": node.get("raylet", {}).get("isHeadNode", False),
                    "state": node.get("raylet", {}).get("state", "UNKNOWN"),
                    "cpu": node.get("cpu", 0),
                    "mem": node.get("mem", [0, 0, 0]),  # [used, available, percent]
                    "gpus": node.get("gpus", []),
                    "disk": node.get("disk", {}),
                }
            )

        return {"nodes": nodes, "total": len(nodes)}

    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=503, detail=f"Failed to connect to Ray dashboard: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting nodes: {str(e)}")


@router.get("/gpus")
async def get_gpu_info(
    current_user: User = Depends(get_current_user),
):
    """
    Get GPU information from all nodes
    Returns detailed GPU stats including memory and utilization
    """
    try:
        response = await http_client.get(f"{RAY_DASHBOARD_URL}/nodes?view=summary")
        response.raise_for_status()
        data = response.json()

        gpus = []
        for node in data.get("data", {}).get("summary", []):
            node_gpus = node.get("gpus", [])
            for i, gpu in enumerate(node_gpus):
                gpus.append(
                    {
                        "node_id": node.get("raylet", {}).get("nodeId", ""),
                        "node_ip": node.get("ip", ""),
                        "index": gpu.get("index", i),
                        "name": gpu.get("name", "Unknown GPU"),
                        "memory_total_mb": gpu.get("memoryTotal", 0),
                        "memory_used_mb": gpu.get("memoryUsed", 0),
                        "memory_free_mb": gpu.get("memoryTotal", 0)
                        - gpu.get("memoryUsed", 0),
                        "utilization_percent": gpu.get("utilizationGpu", 0),
                        "temperature_c": gpu.get("temperatureGpu"),
                    }
                )

        return {"gpus": gpus, "total": len(gpus)}

    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=503, detail=f"Failed to connect to Ray dashboard: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting GPU info: {str(e)}")


@router.get("/actors")
async def get_actors(
    current_user: User = Depends(get_current_user),
):
    """
    Get list of Ray actors in the cluster
    """
    try:
        response = await http_client.get(
            f"{RAY_DASHBOARD_URL}/logical/actors?view=summary"
        )
        response.raise_for_status()
        data = response.json()

        actors = data.get("data", {}).get("actors", {})
        actor_list = []

        for actor_id, actor_info in actors.items():
            actor_list.append(
                {
                    "actor_id": actor_id,
                    "class_name": actor_info.get("actorClass", "Unknown"),
                    "state": actor_info.get("state", "UNKNOWN"),
                    "pid": actor_info.get("pid"),
                    "node_id": actor_info.get("address", {}).get("rayletId"),
                    "num_restarts": actor_info.get("numRestarts", 0),
                }
            )

        return {"actors": actor_list, "total": len(actor_list)}

    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=503, detail=f"Failed to connect to Ray dashboard: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting actors: {str(e)}")


@router.get("/resource-usage")
async def get_resource_usage(
    current_user: User = Depends(get_current_user),
):
    """
    Get real-time resource usage summary
    Useful for quick dashboard stats
    """
    try:
        response = await http_client.get(f"{RAY_DASHBOARD_URL}/api/cluster_status")
        response.raise_for_status()
        data = response.json()

        cluster_data = data.get("data", {})
        load_metrics = cluster_data.get("loadMetricsReport", {})
        usage = load_metrics.get("usage", {})

        # Parse all resource types
        resources = {}
        for key, values in usage.items():
            if isinstance(values, list) and len(values) >= 2:
                resources[key] = {
                    "used": values[0],
                    "total": values[1],
                    "percent": (values[0] / values[1] * 100) if values[1] > 0 else 0,
                }

        return {
            "resources": resources,
            "timestamp": cluster_data.get("clusterStatus", {}).get("time"),
        }

    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=503, detail=f"Failed to connect to Ray dashboard: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error getting resource usage: {str(e)}"
        )
