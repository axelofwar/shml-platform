"""Ray orchestration wrapper — core logic in libs.annotation.yfcc100m."""
import ray


@ray.remote(num_cpus=4, num_gpus=0)
def extract_yfcc100m_sqlite(config: dict) -> dict:
    """Distributed Ray task: YFCC100M SQLite extraction."""
    from libs.annotation.yfcc100m.yfcc100m_sqlite_extract import extract
    return extract(**config)


if __name__ == "__main__":
    from libs.annotation.yfcc100m.yfcc100m_sqlite_extract import main
    main()
