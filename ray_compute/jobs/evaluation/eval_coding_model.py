"""Ray orchestration wrapper — core logic in libs.evaluation.coding.eval_coding_model."""
import ray


@ray.remote(num_cpus=4, num_gpus=0)
def evaluate_coding_model(config: dict) -> dict:
    """Distributed Ray task: evaluate coding model on benchmarks."""
    from libs.evaluation.coding import eval_coding_model as _eval
    return _eval.run_evaluation(**config)


if __name__ == "__main__":
    from libs.evaluation.coding.eval_coding_model import main
    main()
