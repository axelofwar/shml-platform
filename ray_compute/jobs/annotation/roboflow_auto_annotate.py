"""Ray orchestration wrapper — core logic in libs.annotation.sam3_roboflow."""
import ray


@ray.remote(num_cpus=4, num_gpus=1)
def run_roboflow_auto_annotate(config: dict) -> dict:
    """Distributed Ray task: Roboflow auto-annotation."""
    from libs.annotation.sam3_roboflow.roboflow_auto_annotate import run
    return run(**config)


if __name__ == "__main__":
    from libs.annotation.sam3_roboflow.roboflow_auto_annotate import main
    main()
