"""Ray orchestration wrapper — core logic in libs.annotation.sam3_roboflow."""
import ray


@ray.remote(num_cpus=4, num_gpus=1)
def run_sam3_roboflow_pipeline(config: dict) -> dict:
    """Distributed Ray task: SAM3 + Roboflow auto-annotation pipeline."""
    from libs.annotation.sam3_roboflow.sam3_roboflow_pipeline import run_pipeline
    return run_pipeline(**config)


if __name__ == "__main__":
    from libs.annotation.sam3_roboflow.sam3_roboflow_pipeline import main
    main()
