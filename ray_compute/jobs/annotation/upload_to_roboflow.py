import os
import glob
import random
import logging
from pathlib import Path
from roboflow import Roboflow
from tqdm import tqdm

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Platform root - avoid hardcoded paths
PLATFORM_ROOT = os.environ.get("PLATFORM_ROOT", str(Path(__file__).resolve().parents[3]))


def upload_images(
    api_key: str,
    project_id: str,
    image_dir: str,
    num_images: int = 1000,
    batch_name: str = "yfcc100m_batch_1",
):
    """
    Upload images to Roboflow for SAM3 Rapid annotation.
    """
    rf = Roboflow(api_key=api_key)
    try:
        # Note: This assumes the workspace is the default one associated with the key
        # If you have multiple workspaces, you might need to specify it.
        project = rf.workspace().project(project_id)
        logger.info(f"Connected to project: {project.name}")
    except Exception as e:
        logger.error(f"Could not access project {project_id}: {e}")
        logger.info("Please ensure the project exists in Roboflow before uploading.")
        return

    # Find images
    extensions = ["*.jpg", "*.jpeg", "*.png"]
    image_files = []
    for ext in extensions:
        image_files.extend(
            glob.glob(os.path.join(image_dir, "**", ext), recursive=True)
        )

    logger.info(f"Found {len(image_files)} images in {image_dir}")

    if not image_files:
        logger.warning("No images found!")
        return

    # Select random subset
    selected_files = random.sample(image_files, min(len(image_files), num_images))

    logger.info(f"Uploading {len(selected_files)} images to project '{project_id}'...")

    success_count = 0
    for img_path in tqdm(selected_files):
        try:
            # Upload image
            # batch_name helps group them in Roboflow
            # split="train" assigns them to the training set (unannotated)
            project.upload(img_path, batch_name=batch_name, split="train")
            success_count += 1
        except Exception as e:
            logger.error(f"Failed to upload {img_path}: {e}")

    logger.info(f"Successfully uploaded {success_count}/{len(selected_files)} images.")


if __name__ == "__main__":
    API_KEY = os.getenv("AXELOFWAR_ROBOFLOW_API_KEY") or os.getenv("ROBOFLOW_API_KEY")
    PROJECT_ID = os.getenv("ROBOFLOW_PROJECT_ID", "face-detection-sam3")
    IMAGE_DIR = os.getenv(
        "YFCC_IMAGE_DIR",
        f"{PLATFORM_ROOT}/ray_compute/data/datasets/yfcc100m",
    )

    if not API_KEY:
        logger.error("API Key not found. Set AXELOFWAR_ROBOFLOW_API_KEY.")
        exit(1)

    upload_images(API_KEY, PROJECT_ID, IMAGE_DIR)
