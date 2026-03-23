"""Ray orchestration wrapper — core logic in libs.evaluation.face.wider_face_eval."""
import ray


@ray.remote(num_cpus=2, num_gpus=0.5)
def evaluate_wider_face(config: dict) -> dict:
    """Distributed Ray task: WIDER Face comprehensive evaluation."""
    from libs.evaluation.face.wider_face_eval import WIDERFaceEvaluator
    evaluator = WIDERFaceEvaluator(**config)
    return evaluator.evaluate()


if __name__ == "__main__":
    from libs.evaluation.face.wider_face_eval import main
    main()
