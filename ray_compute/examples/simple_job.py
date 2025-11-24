"""
Simple Ray job example for testing job submission.
This demonstrates basic Ray functionality and MLflow logging.
"""
import ray
import time
import os

@ray.remote
def compute_pi(num_samples):
    """Monte Carlo estimation of Pi."""
    import random
    inside = 0
    for _ in range(num_samples):
        x, y = random.random(), random.random()
        if x*x + y*y <= 1:
            inside += 1
    return inside

def main():
    # Initialize Ray
    ray.init(address="auto")
    
    print("=" * 60)
    print("Ray Cluster Information")
    print("=" * 60)
    print(f"Ray cluster resources: {ray.cluster_resources()}")
    print(f"Available nodes: {len(ray.nodes())}")
    print()
    
    # Run parallel computation
    print("Computing Pi using Monte Carlo method...")
    num_samples = 10_000_000
    num_tasks = 10
    samples_per_task = num_samples // num_tasks
    
    start_time = time.time()
    
    # Submit tasks in parallel
    futures = [compute_pi.remote(samples_per_task) for _ in range(num_tasks)]
    
    # Gather results
    results = ray.get(futures)
    total_inside = sum(results)
    
    pi_estimate = (4.0 * total_inside) / num_samples
    elapsed_time = time.time() - start_time
    
    print(f"Pi estimate: {pi_estimate:.6f}")
    print(f"Error: {abs(pi_estimate - 3.141592653589793):.6f}")
    print(f"Computation time: {elapsed_time:.2f} seconds")
    print(f"Tasks completed: {num_tasks}")
    print()
    
    # Try MLflow logging if available
    try:
        import mlflow
        
        # Set tracking URI from environment or use default
        mlflow_uri = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow-server:5000")
        mlflow.set_tracking_uri(mlflow_uri)
        
        # Create experiment if it doesn't exist
        experiment_name = "ray-compute-jobs"
        try:
            experiment_id = mlflow.create_experiment(experiment_name)
        except:
            experiment_id = mlflow.get_experiment_by_name(experiment_name).experiment_id
        
        mlflow.set_experiment(experiment_name)
        
        # Log the run
        with mlflow.start_run(run_name="simple_pi_calculation"):
            mlflow.log_param("num_samples", num_samples)
            mlflow.log_param("num_tasks", num_tasks)
            mlflow.log_metric("pi_estimate", pi_estimate)
            mlflow.log_metric("computation_time", elapsed_time)
            mlflow.log_metric("error", abs(pi_estimate - 3.141592653589793))
            mlflow.set_tag("job_type", "monte_carlo")
            mlflow.set_tag("compute_type", "cpu")
            
        print("✓ Results logged to MLflow")
        print(f"  Experiment: {experiment_name}")
        print(f"  Tracking URI: {mlflow_uri}")
        
    except Exception as e:
        print(f"⚠ MLflow logging skipped: {e}")
    
    print()
    print("=" * 60)
    print("Job completed successfully!")
    print("=" * 60)
    
    ray.shutdown()

if __name__ == "__main__":
    main()
