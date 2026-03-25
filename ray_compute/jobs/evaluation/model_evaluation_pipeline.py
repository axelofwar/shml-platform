"""Ray orchestration wrapper — core logic in libs.evaluation.llm.model_evaluation_pipeline."""
import ray


@ray.remote(num_cpus=4, num_gpus=0)
def run_model_evaluation_pipeline(config: dict) -> dict:
    """Distributed Ray task: multi-model evaluation pipeline."""
    from libs.evaluation.llm import model_evaluation_pipeline as _eval
    return _eval.run(**config)


if __name__ == "__main__":
    from libs.evaluation.llm.model_evaluation_pipeline import main
    main()
