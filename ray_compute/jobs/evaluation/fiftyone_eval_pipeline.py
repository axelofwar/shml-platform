"""Ray orchestration wrapper — core logic in libs.evaluation.face.fiftyone_eval_pipeline."""
import ray


@ray.remote(num_cpus=4, num_gpus=0)
def run_fiftyone_evaluation(config: dict) -> dict:
    """Distributed Ray task: FiftyOne-based evaluation pipeline."""
    from libs.evaluation.face import fiftyone_eval_pipeline as _eval
    return _eval.run_evaluation(**config)


if __name__ == "__main__":
    from libs.evaluation.face.fiftyone_eval_pipeline import main
    main()
