"""Ray orchestration wrapper — core logic in libs.annotation.sam3_roboflow."""
import ray


@ray.remote(num_cpus=2, num_gpus=0)
def upload_to_roboflow(config: dict) -> dict:
    """Distributed Ray task: upload annotated data to Roboflow."""
    from libs.annotation.sam3_roboflow.upload_to_roboflow import upload
    return upload(**config)


if __name__ == "__main__":
    from libs.annotation.sam3_roboflow.upload_to_roboflow import main
    main()
