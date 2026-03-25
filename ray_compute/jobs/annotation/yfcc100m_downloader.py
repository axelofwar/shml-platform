"""Ray orchestration wrapper — core logic in libs.annotation.yfcc100m."""
import ray


@ray.remote(num_cpus=4, num_gpus=0)
def download_yfcc100m(config: dict) -> dict:
    """Distributed Ray task: YFCC100M dataset download."""
    from libs.annotation.yfcc100m.yfcc100m_downloader import download
    return download(**config)


if __name__ == "__main__":
    from libs.annotation.yfcc100m.yfcc100m_downloader import main
    main()
