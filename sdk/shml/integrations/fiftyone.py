"""
FiftyOne Integration Client
=============================

Dataset visualization and evaluation management via FiftyOne + MongoDB.
Auto-configures FIFTYONE_DATABASE_URI before importing fiftyone.
"""

from __future__ import annotations

import os
from typing import Any

from shml.config import PlatformConfig
from shml.exceptions import FiftyOneError


class FiftyOneClient:
    """FiftyOne dataset and visualization client."""

    def __init__(self, config: PlatformConfig | None = None):
        self._config = config or PlatformConfig.from_env()
        self._fo = None
        self._available = False
        self._init()

    def _init(self) -> None:
        """Set FIFTYONE_DATABASE_URI and lazily import fiftyone."""
        # Must set env var BEFORE first import of fiftyone
        mongo_uri = self._config.fiftyone_mongodb_uri
        if mongo_uri:
            os.environ.setdefault("FIFTYONE_DATABASE_URI", mongo_uri)

        try:
            import fiftyone as fo

            self._fo = fo
            self._available = True
        except ImportError:
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def _require(self) -> Any:
        """Return the fiftyone module or raise."""
        if not self._available or self._fo is None:
            raise FiftyOneError(
                "FiftyOne is not installed. Install with: pip install fiftyone"
            )
        return self._fo

    def healthy(self) -> bool:
        """Check if FiftyOne can connect to MongoDB."""
        if not self._available:
            return False
        try:
            fo = self._require()
            fo.list_datasets()
            return True
        except Exception:
            return False

    def list_datasets(self) -> list[str]:
        """List all available datasets."""
        fo = self._require()
        try:
            return list(fo.list_datasets())
        except Exception as e:
            raise FiftyOneError(f"Failed to list datasets: {e}")

    def create_dataset(
        self,
        name: str,
        overwrite: bool = False,
        persistent: bool = True,
    ) -> Any:
        """Create or load a FiftyOne dataset.

        Args:
            name: Dataset name.
            overwrite: If True, delete any existing dataset with this name.
            persistent: If True, persist the dataset in MongoDB.

        Returns:
            fiftyone.Dataset instance.
        """
        fo = self._require()
        try:
            if overwrite and name in fo.list_datasets():
                fo.delete_dataset(name)

            if name in fo.list_datasets():
                return fo.load_dataset(name)

            dataset = fo.Dataset(name, persistent=persistent)
            return dataset
        except Exception as e:
            raise FiftyOneError(f"Failed to create dataset '{name}': {e}")

    def load_dataset(self, name: str) -> Any:
        """Load an existing dataset by name."""
        fo = self._require()
        try:
            if name not in fo.list_datasets():
                raise FiftyOneError(f"Dataset '{name}' not found")
            return fo.load_dataset(name)
        except FiftyOneError:
            raise
        except Exception as e:
            raise FiftyOneError(f"Failed to load dataset '{name}': {e}")

    def delete_dataset(self, name: str) -> bool:
        """Delete a dataset. Returns True if deleted."""
        fo = self._require()
        try:
            if name in fo.list_datasets():
                fo.delete_dataset(name)
                return True
            return False
        except Exception as e:
            raise FiftyOneError(f"Failed to delete dataset '{name}': {e}")

    def add_samples_from_predictions(
        self,
        dataset_name: str,
        image_paths: list[str],
        predictions: list[dict[str, Any]] | None = None,
        ground_truth: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
    ) -> int:
        """Add detection samples (images + predictions) to a dataset.

        Args:
            dataset_name: Target dataset name (created if it doesn't exist).
            image_paths: List of image file paths.
            predictions: List of detection dicts (one per image)
                         with keys: boxes, labels, scores.
            ground_truth: Optional ground-truth dicts.
            tags: Optional tags to apply to all samples.

        Returns:
            Number of samples added.
        """
        fo = self._require()
        dataset = self.create_dataset(dataset_name)

        samples = []
        for i, img_path in enumerate(image_paths):
            sample = fo.Sample(filepath=img_path)

            if tags:
                sample.tags = tags

            if predictions and i < len(predictions):
                pred = predictions[i]
                detections = self._build_detections(fo, pred)
                sample["predictions"] = fo.Detections(detections=detections)

            if ground_truth and i < len(ground_truth):
                gt = ground_truth[i]
                gt_dets = self._build_detections(fo, gt)
                sample["ground_truth"] = fo.Detections(detections=gt_dets)

            samples.append(sample)

        dataset.add_samples(samples)
        return len(samples)

    @staticmethod
    def _build_detections(fo: Any, pred_dict: dict[str, Any]) -> list:
        """Convert a prediction dict to a list of fo.Detection objects."""
        detections = []
        boxes = pred_dict.get("boxes", [])
        labels = pred_dict.get("labels", [])
        scores = pred_dict.get("scores", [])

        for j, box in enumerate(boxes):
            label = labels[j] if j < len(labels) else "unknown"
            confidence = scores[j] if j < len(scores) else None

            det = fo.Detection(
                label=str(label),
                bounding_box=box,  # [x, y, w, h] normalized
                confidence=confidence,
            )
            detections.append(det)

        return detections

    def evaluate_detections(
        self,
        dataset_name: str,
        pred_field: str = "predictions",
        gt_field: str = "ground_truth",
        eval_key: str = "eval",
    ) -> dict[str, Any]:
        """Run FiftyOne evaluation on detections.

        Returns a dict with mAP, precision, recall metrics.
        """
        fo = self._require()
        try:
            dataset = self.load_dataset(dataset_name)
            results = dataset.evaluate_detections(
                pred_field,
                gt_field=gt_field,
                eval_key=eval_key,
            )
            return {
                "mAP": getattr(results, "mAP", None),
                "eval_key": eval_key,
                "dataset": dataset_name,
            }
        except FiftyOneError:
            raise
        except Exception as e:
            raise FiftyOneError(f"Evaluation failed: {e}")

    # ── Brain Methods (Phase 9+) ─────────────────────────────────────────

    def compute_embeddings(
        self,
        dataset_name: str,
        model_name: str = "clip-vit-base32-torch",
        embeddings_field: str = "embeddings",
        batch_size: int = 32,
    ) -> bool:
        """Compute CLIP embeddings for all samples in a dataset.

        Uses FiftyOne Brain to generate embeddings that power
        similarity search, uniqueness scoring, and visualization.

        Args:
            dataset_name: Target dataset name.
            model_name: Embedding model (clip, resnet, etc).
            embeddings_field: Field name to store embeddings.
            batch_size: Inference batch size.

        Returns:
            True if successful.
        """
        fo = self._require()
        try:
            import fiftyone.brain as fob

            dataset = self.load_dataset(dataset_name)
            fob.compute_embeddings(
                dataset,
                model=model_name,
                embeddings_field=embeddings_field,
                batch_size=batch_size,
            )
            dataset.save()
            return True
        except ImportError:
            raise FiftyOneError("fiftyone.brain not available")
        except Exception as e:
            raise FiftyOneError(f"Embedding computation failed: {e}")

    def compute_similarity(
        self,
        dataset_name: str,
        embeddings_field: str = "embeddings",
        brain_key: str = "similarity",
    ) -> bool:
        """Build a similarity index for nearest-neighbor queries.

        Once computed, use dataset.sort_by_similarity(query) to find
        similar/dissimilar samples for active learning curation.

        Returns:
            True if successful.
        """
        fo = self._require()
        try:
            import fiftyone.brain as fob

            dataset = self.load_dataset(dataset_name)
            fob.compute_similarity(
                dataset,
                embeddings=embeddings_field,
                brain_key=brain_key,
            )
            dataset.save()
            return True
        except ImportError:
            raise FiftyOneError("fiftyone.brain not available")
        except Exception as e:
            raise FiftyOneError(f"Similarity computation failed: {e}")

    def compute_uniqueness(
        self,
        dataset_name: str,
        embeddings_field: str = "embeddings",
        uniqueness_field: str = "uniqueness",
    ) -> bool:
        """Score each sample by uniqueness (how different it is from others).

        High-uniqueness samples are rare edge cases; low-uniqueness
        duplicates can be pruned. Used for dataset curation.

        Returns:
            True if successful.
        """
        fo = self._require()
        try:
            import fiftyone.brain as fob

            dataset = self.load_dataset(dataset_name)
            fob.compute_uniqueness(
                dataset,
                embeddings=embeddings_field,
                uniqueness_field=uniqueness_field,
            )
            dataset.save()
            return True
        except ImportError:
            raise FiftyOneError("fiftyone.brain not available")
        except Exception as e:
            raise FiftyOneError(f"Uniqueness computation failed: {e}")

    def compute_mistakenness(
        self,
        dataset_name: str,
        pred_field: str = "predictions",
        label_field: str = "ground_truth",
        mistakenness_field: str = "mistakenness",
    ) -> bool:
        """Score each sample by likelihood of annotation error.

        High-mistakenness samples likely have incorrect labels and
        should be reviewed. Critical for noisy merged datasets.

        Returns:
            True if successful.
        """
        fo = self._require()
        try:
            import fiftyone.brain as fob

            dataset = self.load_dataset(dataset_name)
            fob.compute_mistakenness(
                dataset,
                pred_field,
                label_field=label_field,
                mistakenness_field=mistakenness_field,
            )
            dataset.save()
            return True
        except ImportError:
            raise FiftyOneError("fiftyone.brain not available")
        except Exception as e:
            raise FiftyOneError(f"Mistakenness computation failed: {e}")

    def compute_hardness(
        self,
        dataset_name: str,
        pred_field: str = "predictions",
        hardness_field: str = "hardness",
    ) -> bool:
        """Score each sample by prediction difficulty (hardness).

        High-hardness samples are difficult for the model and
        should be prioritized in active learning loops.

        Returns:
            True if successful.
        """
        fo = self._require()
        try:
            import fiftyone.brain as fob

            dataset = self.load_dataset(dataset_name)
            fob.compute_hardness(
                dataset,
                pred_field,
                hardness_field=hardness_field,
            )
            dataset.save()
            return True
        except ImportError:
            raise FiftyOneError("fiftyone.brain not available")
        except Exception as e:
            raise FiftyOneError(f"Hardness computation failed: {e}")

    def compute_visualization(
        self,
        dataset_name: str,
        embeddings_field: str = "embeddings",
        brain_key: str = "vis",
        method: str = "umap",
        num_dims: int = 2,
    ) -> bool:
        """Compute 2D/3D visualization coordinates (UMAP/t-SNE).

        Creates interactive scatter plots for exploring embedding
        space and finding clusters of similar/anomalous samples.

        Returns:
            True if successful.
        """
        fo = self._require()
        try:
            import fiftyone.brain as fob

            dataset = self.load_dataset(dataset_name)
            fob.compute_visualization(
                dataset,
                embeddings=embeddings_field,
                brain_key=brain_key,
                method=method,
                num_dims=num_dims,
            )
            dataset.save()
            return True
        except ImportError:
            raise FiftyOneError("fiftyone.brain not available")
        except Exception as e:
            raise FiftyOneError(f"Visualization computation failed: {e}")

    def get_hard_samples(
        self,
        dataset_name: str,
        hardness_field: str = "hardness",
        threshold: float = 0.8,
        limit: int = 500,
    ) -> Any:
        """Get the hardest samples from a dataset.

        Returns a FiftyOne DatasetView of the most difficult samples,
        sorted by hardness score descending.
        """
        fo = self._require()
        try:
            dataset = self.load_dataset(dataset_name)
            view = (
                dataset.match(fo.ViewExpression(f"${hardness_field}") > threshold)
                .sort_by(hardness_field, reverse=True)
                .limit(limit)
            )
            return view
        except Exception as e:
            raise FiftyOneError(f"Failed to get hard samples: {e}")

    def create_evaluation_view(
        self,
        dataset_name: str,
        eval_key: str = "eval",
        filter_type: str = "fn",
    ) -> Any:
        """Create a filtered view of evaluation results.

        Args:
            filter_type: "fn" (false negatives), "fp" (false positives),
                         "tp" (true positives).

        Returns:
            Filtered FiftyOne DatasetView.
        """
        fo = self._require()
        try:
            dataset = self.load_dataset(dataset_name)
            if filter_type == "fn":
                return dataset.filter_labels(
                    "ground_truth",
                    fo.ViewExpression(f"${eval_key}") == "fn",
                )
            elif filter_type == "fp":
                return dataset.filter_labels(
                    "predictions",
                    fo.ViewExpression(f"${eval_key}") == "fp",
                )
            elif filter_type == "tp":
                return dataset.filter_labels(
                    "predictions",
                    fo.ViewExpression(f"${eval_key}") == "tp",
                )
            return dataset
        except Exception as e:
            raise FiftyOneError(f"Failed to create evaluation view: {e}")

    def load_coco_dataset(
        self,
        name: str,
        data_path: str,
        labels_path: str,
        persistent: bool = True,
        overwrite: bool = False,
    ) -> Any:
        """Load a COCO-format dataset into FiftyOne.

        Args:
            name: Dataset name.
            data_path: Path to images directory.
            labels_path: Path to COCO JSON annotations.
            persistent: Persist in MongoDB.
            overwrite: Overwrite existing dataset.

        Returns:
            fiftyone.Dataset instance.
        """
        fo = self._require()
        try:
            if overwrite and name in fo.list_datasets():
                fo.delete_dataset(name)

            if name in fo.list_datasets():
                return fo.load_dataset(name)

            dataset = fo.Dataset.from_dir(
                dataset_type=fo.types.COCODetectionDataset,
                data_path=data_path,
                labels_path=labels_path,
                name=name,
            )
            dataset.persistent = persistent
            dataset.save()
            return dataset
        except Exception as e:
            raise FiftyOneError(f"Failed to load COCO dataset: {e}")
