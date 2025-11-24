"""
GPU-enabled Ray job for testing GPU allocation and monitoring.
"""
import ray
import time
import os
import numpy as np

@ray.remote(num_gpus=0.5)  # Request 0.5 GPU (GPU sharing)
def gpu_task(task_id, matrix_size=5000):
    """Perform matrix multiplication on GPU if available."""
    try:
        import cupy as cp
        
        # Create random matrices
        a = cp.random.rand(matrix_size, matrix_size, dtype=cp.float32)
        b = cp.random.rand(matrix_size, matrix_size, dtype=cp.float32)
        
        start = time.time()
        c = cp.dot(a, b)
        cp.cuda.Stream.null.synchronize()  # Wait for GPU to finish
        elapsed = time.time() - start
        
        return {
            "task_id": task_id,
            "success": True,
            "device": "GPU (cupy)",
            "matrix_size": matrix_size,
            "computation_time": elapsed,
            "gpu_available": True
        }
    except ImportError:
        # Fallback to CPU with NumPy
        a = np.random.rand(matrix_size, matrix_size).astype(np.float32)
        b = np.random.rand(matrix_size, matrix_size).astype(np.float32)
        
        start = time.time()
        c = np.dot(a, b)
        elapsed = time.time() - start
        
        return {
            "task_id": task_id,
            "success": True,
            "device": "CPU (numpy)",
            "matrix_size": matrix_size,
            "computation_time": elapsed,
            "gpu_available": False
        }

def main():
    # Initialize Ray
    ray.init(address="auto")
    
    print("=" * 60)
    print("Ray GPU Job Test")
    print("=" * 60)
    
    # Cluster info
    resources = ray.cluster_resources()
    print(f"Available CPUs: {resources.get('CPU', 0)}")
    print(f"Available GPUs: {resources.get('GPU', 0)}")
    print(f"Available memory: {resources.get('memory', 0) / 1e9:.2f} GB")
    print()
    
    # Submit GPU tasks
    print("Submitting GPU tasks...")
    num_tasks = 4
    matrix_size = 3000
    
    start_time = time.time()
    futures = [gpu_task.remote(i, matrix_size) for i in range(num_tasks)]
    results = ray.get(futures)
    total_time = time.time() - start_time
    
    print("\nTask Results:")
    print("-" * 60)
    for result in results:
        print(f"Task {result['task_id']}: {result['device']} - {result['computation_time']:.3f}s")
    
    print(f"\nTotal execution time: {total_time:.2f}s")
    print(f"Average task time: {sum(r['computation_time'] for r in results) / len(results):.3f}s")
    
    # MLflow logging
    try:
        import mlflow
        
        mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow-server:5000")
        mlflow.set_tracking_uri(mlflow_uri)
        mlflow.set_experiment("ray-compute-jobs")
        
        with mlflow.start_run(run_name="gpu_matrix_multiplication"):
            mlflow.log_param("num_tasks", num_tasks)
            mlflow.log_param("matrix_size", matrix_size)
            mlflow.log_param("device", results[0]['device'])
            mlflow.log_param("gpu_available", results[0]['gpu_available'])
            mlflow.log_metric("total_time", total_time)
            mlflow.log_metric("avg_task_time", sum(r['computation_time'] for r in results) / len(results))
            mlflow.set_tag("compute_type", "gpu" if results[0]['gpu_available'] else "cpu")
            
        print("\n✓ Results logged to MLflow")
    except Exception as e:
        print(f"\n⚠ MLflow logging failed: {e}")
    
    print("\n" + "=" * 60)
    print("GPU job completed!")
    print("=" * 60)
    
    ray.shutdown()

if __name__ == "__main__":
    main()
