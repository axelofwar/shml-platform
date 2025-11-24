"""
Prometheus Metrics Exporter for MLflow
Exports system and MLflow-specific metrics
"""

import os
import time
import psutil
import logging
from pathlib import Path
from typing import Dict

from prometheus_client import start_http_server, Gauge, Counter, Histogram
from mlflow.tracking import MlflowClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# System metrics
CPU_USAGE = Gauge('mlflow_system_cpu_percent', 'CPU usage percentage')
MEMORY_USAGE = Gauge('mlflow_system_memory_percent', 'Memory usage percentage')
DISK_USAGE = Gauge('mlflow_system_disk_percent', 'Disk usage percentage')
DISK_FREE_GB = Gauge('mlflow_system_disk_free_gb', 'Free disk space in GB')

# MLflow metrics
TOTAL_EXPERIMENTS = Gauge('mlflow_experiments_total', 'Total number of experiments')
TOTAL_RUNS = Gauge('mlflow_runs_total', 'Total number of runs')
ACTIVE_RUNS = Gauge('mlflow_runs_active', 'Number of active runs')
TOTAL_MODELS = Gauge('mlflow_models_total', 'Total registered models')
TOTAL_ARTIFACTS_GB = Gauge('mlflow_artifacts_size_gb', 'Total artifact storage in GB')

# Operation counters
RUN_CREATED = Counter('mlflow_run_created_total', 'Total runs created')
MODEL_REGISTERED = Counter('mlflow_model_registered_total', 'Total models registered')
ARTIFACT_UPLOADED = Counter('mlflow_artifact_uploaded_total', 'Total artifacts uploaded')
ARTIFACT_COMPRESSED = Counter('mlflow_artifact_compressed_total', 'Total artifacts compressed')

# Performance metrics
RUN_DURATION = Histogram('mlflow_run_duration_seconds', 'Run duration in seconds')
ARTIFACT_UPLOAD_SIZE = Histogram('mlflow_artifact_upload_size_mb', 'Artifact upload size in MB',
                                  buckets=[1, 10, 50, 100, 500, 1000, 5000, 10000])


class MetricsCollector:
    """Collect and export MLflow metrics to Prometheus"""
    
    def __init__(self, port: int = 8000):
        self.port = port
        self.client = MlflowClient()
        self.artifact_root = Path(os.getenv('MLFLOW_ARTIFACT_ROOT', '/mlflow/artifacts'))
    
    def collect_system_metrics(self):
        """Collect system-level metrics"""
        try:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=1)
            CPU_USAGE.set(cpu_percent)
            
            # Memory
            memory = psutil.virtual_memory()
            MEMORY_USAGE.set(memory.percent)
            
            # Disk
            disk = psutil.disk_usage('/')
            DISK_USAGE.set(disk.percent)
            DISK_FREE_GB.set(disk.free / (1024**3))
            
        except Exception as e:
            logger.error(f"Error collecting system metrics: {e}")
    
    def collect_mlflow_metrics(self):
        """Collect MLflow-specific metrics"""
        try:
            # Experiments
            experiments = self.client.search_experiments()
            TOTAL_EXPERIMENTS.set(len(experiments))
            
            # Runs
            all_runs = []
            active_runs = []
            for exp in experiments:
                runs = self.client.search_runs(
                    experiment_ids=[exp.experiment_id],
                    max_results=10000
                )
                all_runs.extend(runs)
                active_runs.extend([r for r in runs if r.info.status == 'RUNNING'])
            
            TOTAL_RUNS.set(len(all_runs))
            ACTIVE_RUNS.set(len(active_runs))
            
            # Registered models
            models = self.client.search_registered_models()
            TOTAL_MODELS.set(len(models))
            
            # Artifact storage
            if self.artifact_root.exists():
                total_size = sum(
                    f.stat().st_size for f in self.artifact_root.rglob('*') if f.is_file()
                )
                TOTAL_ARTIFACTS_GB.set(total_size / (1024**3))
            
        except Exception as e:
            logger.error(f"Error collecting MLflow metrics: {e}")
    
    def start(self):
        """Start metrics collection server"""
        logger.info(f"Starting Prometheus metrics exporter on port {self.port}")
        start_http_server(self.port)
        
        logger.info("Metrics collection started")
        while True:
            try:
                self.collect_system_metrics()
                self.collect_mlflow_metrics()
                time.sleep(15)  # Collect every 15 seconds
            except KeyboardInterrupt:
                logger.info("Shutting down metrics collector")
                break
            except Exception as e:
                logger.error(f"Error in metrics collection loop: {e}")
                time.sleep(60)


if __name__ == '__main__':
    collector = MetricsCollector(port=8000)
    collector.start()
