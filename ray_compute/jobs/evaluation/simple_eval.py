"""Ray orchestration wrapper — core logic in libs.evaluation.llm.simple_eval."""
import ray


@ray.remote(num_cpus=2, num_gpus=0)
def run_simple_eval(config: dict) -> dict:
    """Distributed Ray task: lightweight single-model evaluation."""
    from libs.evaluation.llm import simple_eval as _eval
    return _eval.run(**config)


if __name__ == "__main__":
    from libs.evaluation.llm.simple_eval import main
    main()
