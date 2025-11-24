"""
Automatic MLflow Integration for Ray Jobs
This module provides automatic MLflow tracking for all Ray compute jobs with opt-out capability.
"""
import os
import mlflow
from functools import wraps
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class MLflowAutoLogger:
    """
    Automatic MLflow logger for Ray jobs
    
    Features:
    - Automatically initializes MLflow tracking
    - Logs job metadata, parameters, and metrics
    - Supports opt-out via environment variable
    - Handles errors gracefully to not break jobs
    """
    
    def __init__(self):
        self.enabled = os.getenv("DISABLE_MLFLOW_LOGGING", "false").lower() != "true"
        self.tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow-server:5000")
        self.experiment_name = os.getenv("MLFLOW_EXPERIMENT_NAME", "Ray-Jobs")
        self._initialized = False
        
    def initialize(self, experiment_name: Optional[str] = None):
        """Initialize MLflow tracking"""
        if not self.enabled:
            logger.info("MLflow auto-logging is disabled (DISABLE_MLFLOW_LOGGING=true)")
            return
            
        if self._initialized:
            return
            
        try:
            # Set tracking URI
            mlflow.set_tracking_uri(self.tracking_uri)
            
            # Set or create experiment
            exp_name = experiment_name or self.experiment_name
            experiment = mlflow.get_experiment_by_name(exp_name)
            
            if experiment is None:
                experiment_id = mlflow.create_experiment(
                    name=exp_name,
                    tags={
                        "source": "ray-compute",
                        "auto_created": "true"
                    }
                )
                logger.info(f"Created MLflow experiment: {exp_name} (ID: {experiment_id})")
            else:
                experiment_id = experiment.experiment_id
                
            mlflow.set_experiment(exp_name)
            self._initialized = True
            logger.info(f"MLflow tracking initialized: {self.tracking_uri}, experiment: {exp_name}")
            
        except Exception as e:
            logger.error(f"Failed to initialize MLflow tracking: {e}")
            self.enabled = False
    
    def start_run(self, run_name: Optional[str] = None, tags: Optional[Dict[str, str]] = None):
        """Start a new MLflow run"""
        if not self.enabled:
            return None
            
        try:
            self.initialize()
            
            run_tags = {
                "source": "ray-compute",
                "auto_logged": "true"
            }
            if tags:
                run_tags.update(tags)
            
            run = mlflow.start_run(run_name=run_name, tags=run_tags)
            logger.info(f"Started MLflow run: {run.info.run_id}")
            return run
            
        except Exception as e:
            logger.error(f"Failed to start MLflow run: {e}")
            return None
    
    def log_params(self, params: Dict[str, Any]):
        """Log parameters to MLflow"""
        if not self.enabled or not self._initialized:
            return
            
        try:
            mlflow.log_params(params)
            logger.debug(f"Logged {len(params)} parameters to MLflow")
        except Exception as e:
            logger.error(f"Failed to log parameters: {e}")
    
    def log_metrics(self, metrics: Dict[str, float], step: Optional[int] = None):
        """Log metrics to MLflow"""
        if not self.enabled or not self._initialized:
            return
            
        try:
            mlflow.log_metrics(metrics, step=step)
            logger.debug(f"Logged {len(metrics)} metrics to MLflow")
        except Exception as e:
            logger.error(f"Failed to log metrics: {e}")
    
    def log_artifact(self, local_path: str, artifact_path: Optional[str] = None):
        """Log artifact to MLflow"""
        if not self.enabled or not self._initialized:
            return
            
        try:
            mlflow.log_artifact(local_path, artifact_path)
            logger.debug(f"Logged artifact: {local_path}")
        except Exception as e:
            logger.error(f"Failed to log artifact: {e}")
    
    def end_run(self, status: str = "FINISHED"):
        """End the current MLflow run"""
        if not self.enabled or not self._initialized:
            return
            
        try:
            mlflow.end_run(status=status)
            logger.info(f"Ended MLflow run with status: {status}")
        except Exception as e:
            logger.error(f"Failed to end MLflow run: {e}")


# Global instance
_auto_logger = MLflowAutoLogger()


def auto_log_mlflow(experiment_name: Optional[str] = None, 
                   run_name: Optional[str] = None,
                   tags: Optional[Dict[str, str]] = None):
    """
    Decorator to automatically log Ray job execution to MLflow
    
    Usage:
        @auto_log_mlflow(experiment_name="MyExperiment", run_name="job-1")
        def my_ray_job(config):
            # Your job code here
            return results
    
    To disable MLflow logging for a specific job:
        Set environment variable: DISABLE_MLFLOW_LOGGING=true
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Check if MLflow logging is disabled
            if not _auto_logger.enabled:
                logger.info("Executing job without MLflow logging (disabled)")
                return func(*args, **kwargs)
            
            # Start MLflow run
            run = _auto_logger.start_run(run_name=run_name, tags=tags)
            
            try:
                # Log job configuration
                job_config = {
                    "function": func.__name__,
                    "module": func.__module__,
                }
                
                # Extract parameters from kwargs if available
                if 'config' in kwargs:
                    job_config.update(kwargs['config'])
                elif len(args) > 0 and isinstance(args[0], dict):
                    job_config.update(args[0])
                
                _auto_logger.log_params(job_config)
                
                # Execute the job
                result = func(*args, **kwargs)
                
                # Log results if they're dict-like
                if isinstance(result, dict):
                    metrics = {k: v for k, v in result.items() if isinstance(v, (int, float))}
                    if metrics:
                        _auto_logger.log_metrics(metrics)
                
                _auto_logger.end_run(status="FINISHED")
                return result
                
            except Exception as e:
                logger.error(f"Job execution failed: {e}")
                _auto_logger.end_run(status="FAILED")
                raise
        
        return wrapper
    return decorator


def get_auto_logger() -> MLflowAutoLogger:
    """Get the global MLflow auto-logger instance"""
    return _auto_logger


def is_mlflow_enabled() -> bool:
    """Check if MLflow auto-logging is enabled"""
    return _auto_logger.enabled


# Convenience functions
def log_job_start(job_name: str, config: Dict[str, Any]):
    """Log the start of a Ray job"""
    _auto_logger.initialize()
    _auto_logger.start_run(run_name=job_name, tags={"job_name": job_name})
    _auto_logger.log_params(config)


def log_job_metrics(metrics: Dict[str, float], step: Optional[int] = None):
    """Log metrics during job execution"""
    _auto_logger.log_metrics(metrics, step=step)


def log_job_artifact(artifact_path: str, artifact_name: Optional[str] = None):
    """Log an artifact from the job"""
    _auto_logger.log_artifact(artifact_path, artifact_name)


def log_job_end(status: str = "FINISHED"):
    """Log the end of a Ray job"""
    _auto_logger.end_run(status=status)
