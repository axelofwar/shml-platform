"""Ray orchestration wrapper — core logic in libs.evaluation.face.pr_curve_sweep."""
import ray


@ray.remote(num_cpus=4, num_gpus=0.5)
def run_pr_curve_sweep(config: dict) -> dict:
    """Distributed Ray task: confidence/IoU threshold sweep for PR curve."""
    from libs.evaluation.face.pr_curve_sweep import conf_sweep, iou_sweep
    if config.get("sweep_type") == "iou":
        return iou_sweep(**{k: v for k, v in config.items() if k != "sweep_type"})
    return conf_sweep(**{k: v for k, v in config.items() if k != "sweep_type"})


if __name__ == "__main__":
    from libs.evaluation.face.pr_curve_sweep import main
    main()
