"""Ray orchestration wrapper — core logic in libs.annotation.yfcc100m."""
import ray


@ray.remote(num_cpus=4, num_gpus=0)
def run_yfcc100m_sqlite_pipeline(config: dict) -> dict:
    """Distributed Ray task: YFCC100M SQLite annotation pipeline."""
    from libs.annotation.yfcc100m.yfcc100m_sqlite_pipeline import run_pipeline
    return run_pipeline(**config)


if __name__ == "__main__":
    from libs.annotation.yfcc100m.yfcc100m_sqlite_pipeline import main
    main()
