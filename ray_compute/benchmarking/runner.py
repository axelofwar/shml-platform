"""Ray orchestration wrapper — core logic in libs.evaluation.benchmarking.runner."""
import ray


@ray.remote(num_cpus=4, num_gpus=0)
def run_benchmark(config: dict) -> dict:
    """Distributed Ray task: run model performance benchmark."""
    from libs.evaluation.benchmarking.runner import run
    return run(**config)


if __name__ == "__main__":
    from libs.evaluation.benchmarking.runner import main
    main()
