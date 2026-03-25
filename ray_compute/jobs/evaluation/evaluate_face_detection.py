"""
ray_compute/jobs/evaluation/evaluate_face_detection.py
Ray orchestration wrapper — core logic lives in libs.evaluation.face.
"""
import ray


@ray.remote(num_cpus=2, num_gpus=0.5)
def evaluate_face_detection(config: dict) -> dict:
    """Distributed Ray task: evaluate face detection on WIDER Face val set."""
    from libs.evaluation.face.evaluate_face_detection import (
        EvaluationConfig,
        FaceDetectionEvaluator,
    )
    eval_config = EvaluationConfig(**config)
    evaluator = FaceDetectionEvaluator(eval_config)
    return evaluator.evaluate()


if __name__ == "__main__":
    from libs.evaluation.face.evaluate_face_detection import main
    main()
