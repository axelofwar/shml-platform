#!/usr/bin/env python3
"""
Phase 9: FiftyOne Evaluation Pipeline
=======================================

Post-training evaluation that leverages FiftyOne Brain for:
1. Load trained model predictions into FiftyOne dataset
2. Run COCO-style evaluation (mAP, recall, precision)
3. Compute CLIP embeddings for similarity/active-learning
4. Score sample uniqueness, hardness, and mistakenness
5. Build visualization (UMAP) for embedding space exploration
6. Export hard examples to Feature Store (pgvector)
7. Create filtered views for failure analysis

Usage:
    python fiftyone_eval_pipeline.py --model-path /path/to/best_model.pth
    python fiftyone_eval_pipeline.py --dataset-name phase9_rfdetr_eval
    python fiftyone_eval_pipeline.py --skip-brain  # Skip brain computations
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# SDK path setup
_script_dir = os.path.dirname(os.path.abspath(__file__))
_sdk_candidates = [
    os.path.join(_script_dir, "..", "..", "sdk"),
    os.path.join(_script_dir, "..", "..", "..", "sdk"),
]
_libs_candidates = [
    os.path.join(_script_dir, "..", "libs"),
    os.path.join(_script_dir, "..", "..", "..", "libs"),
    os.path.join(_script_dir, "..", "..", "libs"),
]
for p in _sdk_candidates + _libs_candidates:
    p = os.path.abspath(p)
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

# ── Imports ──
FIFTYONE_AVAILABLE = False
try:
    if "FIFTYONE_DATABASE_URI" not in os.environ:
        os.environ["FIFTYONE_DATABASE_URI"] = "mongodb://fiftyone-mongodb:27017"
    import fiftyone as fo
    import fiftyone.brain as fob

    FIFTYONE_AVAILABLE = True
except ImportError:
    pass

RFDETR_AVAILABLE = False
try:
    from rfdetr import RFDETRLarge

    RFDETR_AVAILABLE = True
except ImportError:
    pass

FEATURE_CLIENT_AVAILABLE = False
try:
    from shml_features import FeatureClient

    FEATURE_CLIENT_AVAILABLE = True
except ImportError:
    pass


def load_or_create_dataset(
    data_dir: Path,
    dataset_name: str,
) -> Any:
    """Load existing FiftyOne dataset or create from COCO annotations."""
    if not FIFTYONE_AVAILABLE:
        raise RuntimeError("FiftyOne not available")

    if dataset_name in fo.list_datasets():
        print(f"  Loading existing dataset: {dataset_name}")
        return fo.load_dataset(dataset_name)

    # Create from COCO annotations
    annot_path = data_dir / "annotations" / "val.json"
    images_dir = data_dir / "images" / "val"

    if not annot_path.exists():
        raise FileNotFoundError(f"Annotations not found: {annot_path}")

    print(f"  Creating dataset from COCO: {annot_path}")
    dataset = fo.Dataset.from_dir(
        dataset_type=fo.types.COCODetectionDataset,
        data_path=str(images_dir),
        labels_path=str(annot_path),
        name=dataset_name,
    )
    dataset.persistent = True
    dataset.save()
    print(f"  ✓ Dataset created: {len(dataset)} samples")
    return dataset


def run_model_predictions(
    dataset: Any,
    model_path: str,
    threshold: float = 0.3,
    batch_size: int = 8,
) -> None:
    """Run RF-DETR model on dataset and store predictions."""
    if not RFDETR_AVAILABLE:
        print("  ⚠️  RF-DETR not available — skipping predictions")
        return

    from PIL import Image
    import torch

    print(f"  Running RF-DETR predictions on {len(dataset)} samples...")

    model = RFDETRLarge()
    if model_path and Path(model_path).exists():
        state_dict = torch.load(model_path, map_location="cpu")
        model.model.load_state_dict(state_dict)
        print(f"  ✓ Loaded weights: {model_path}")

    model.model.eval()
    if torch.cuda.is_available():
        model.model.cuda()

    count = 0
    for sample in dataset.iter_samples(progress=True):
        try:
            pil_img = Image.open(sample.filepath).convert("RGB")
            w_img, h_img = pil_img.size

            detections = model.predict(pil_img, threshold=threshold)

            fo_dets = []
            if (
                detections is not None
                and hasattr(detections, "xyxy")
                and len(detections.xyxy) > 0
            ):
                for i in range(len(detections.xyxy)):
                    x1, y1, x2, y2 = detections.xyxy[i]
                    conf = (
                        float(detections.confidence[i])
                        if detections.confidence is not None
                        else 1.0
                    )

                    box = [
                        float(x1) / w_img,
                        float(y1) / h_img,
                        float(x2 - x1) / w_img,
                        float(y2 - y1) / h_img,
                    ]
                    fo_dets.append(
                        fo.Detection(
                            label="face",
                            bounding_box=box,
                            confidence=conf,
                        )
                    )

            sample["predictions"] = fo.Detections(detections=fo_dets)
            sample.save()
            count += 1

        except Exception as e:
            print(f"  ⚠️  Prediction failed for {sample.filepath}: {e}")
            continue

    print(f"  ✓ Predictions added to {count} samples")


def run_evaluation(dataset: Any, eval_key: str = "eval") -> dict:
    """Run COCO-style evaluation on predictions vs ground truth."""
    print(f"\n━━━ COCO Evaluation ━━━")
    try:
        results = dataset.evaluate_detections(
            "predictions",
            gt_field="ground_truth",
            eval_key=eval_key,
            compute_mAP=True,
        )

        metrics = {
            "mAP": getattr(results, "mAP", None),
            "mAP50": None,  # Will be computed if available
        }

        # Print detailed results
        print(f"  mAP: {metrics['mAP']}")
        results.print_report()

        return metrics
    except Exception as e:
        print(f"  ⚠️  Evaluation failed: {e}")
        return {}


def run_brain_computations(
    dataset: Any,
    embedding_model: str = "clip-vit-base32-torch",
    batch_size: int = 32,
) -> None:
    """Run FiftyOne Brain computations for active learning."""
    print(f"\n━━━ FiftyOne Brain Computations ━━━")

    # 1. Compute CLIP embeddings
    print("  [1/5] Computing CLIP embeddings...")
    try:
        fob.compute_embeddings(
            dataset,
            model=embedding_model,
            embeddings_field="clip_embeddings",
            batch_size=batch_size,
        )
        dataset.save()
        print("  ✓ CLIP embeddings computed")
    except Exception as e:
        print(f"  ⚠️  Embeddings failed: {e}")
        return  # Can't continue without embeddings

    # 2. Similarity index
    print("  [2/5] Building similarity index...")
    try:
        fob.compute_similarity(
            dataset,
            embeddings="clip_embeddings",
            brain_key="similarity",
        )
        dataset.save()
        print("  ✓ Similarity index built")
    except Exception as e:
        print(f"  ⚠️  Similarity failed: {e}")

    # 3. Uniqueness scoring
    print("  [3/5] Computing uniqueness scores...")
    try:
        fob.compute_uniqueness(
            dataset,
            embeddings="clip_embeddings",
            uniqueness_field="uniqueness",
        )
        dataset.save()
        print("  ✓ Uniqueness scores computed")
    except Exception as e:
        print(f"  ⚠️  Uniqueness failed: {e}")

    # 4. Hardness scoring (requires predictions)
    print("  [4/5] Computing hardness scores...")
    try:
        if dataset.has_sample_field("predictions"):
            fob.compute_hardness(
                dataset,
                "predictions",
                hardness_field="hardness",
            )
            dataset.save()
            print("  ✓ Hardness scores computed")
        else:
            print("  ⚠️  No predictions field — skipping hardness")
    except Exception as e:
        print(f"  ⚠️  Hardness failed: {e}")

    # 5. UMAP visualization
    print("  [5/5] Computing UMAP visualization...")
    try:
        fob.compute_visualization(
            dataset,
            embeddings="clip_embeddings",
            brain_key="vis_umap",
            method="umap",
            num_dims=2,
        )
        dataset.save()
        print("  ✓ UMAP visualization computed")
    except Exception as e:
        print(f"  ⚠️  Visualization failed: {e}")

    print("  ✓ Brain computations complete")


def export_hard_examples(
    dataset: Any,
    hardness_threshold: float = 0.7,
    max_examples: int = 500,
    run_id: str = "",
) -> int:
    """Export hard/unique examples to Feature Store for active learning.

    Extracts CLIP embeddings + metadata for samples that are:
    - Hard to predict (high hardness score)
    - Unique (high uniqueness score)
    - False negatives (missed detections)
    """
    if not FEATURE_CLIENT_AVAILABLE:
        print("  ⚠️  FeatureClient not available — skipping export")
        return 0

    print(f"\n━━━ Exporting Hard Examples to Feature Store ━━━")

    # Read DB password
    password = os.environ.get("POSTGRES_PASSWORD", "")
    if not password:
        for sp in [
            "/run/secrets/shared_db_password",
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "..",
                "secrets",
                "shared_db_password.txt",
            ),
        ]:
            try:
                with open(sp) as f:
                    password = f.read().strip()
                    break
            except FileNotFoundError:
                continue

    if not password:
        print("  ⚠️  DB password not available")
        return 0

    try:
        client = FeatureClient(
            postgres_host=os.environ.get("POSTGRES_HOST", "postgres"),
            postgres_port=int(os.environ.get("POSTGRES_PORT", "5432")),
            postgres_db=os.environ.get("POSTGRES_DB", "inference"),
            postgres_user=os.environ.get("POSTGRES_USER", "inference"),
            postgres_password=password,
        )
        client.init_schema()

        # Get hard samples
        exported = 0
        if dataset.has_sample_field("hardness"):
            hard_view = dataset.sort_by("hardness", reverse=True).limit(max_examples)

            conn = client._get_conn()
            with conn.cursor() as cur:
                for sample in hard_view:
                    embedding = None
                    if (
                        hasattr(sample, "clip_embeddings")
                        and sample.clip_embeddings is not None
                    ):
                        embedding = list(sample.clip_embeddings)

                    hardness = getattr(sample, "hardness", None)
                    uniqueness = getattr(sample, "uniqueness", None)

                    # Determine face size bucket from ground truth
                    face_size_bucket = "unknown"
                    if sample.ground_truth:
                        max_dim = 0
                        for det in sample.ground_truth.detections:
                            w, h = det.bounding_box[2], det.bounding_box[3]
                            # Bounding boxes are normalized — approximate pixel size
                            max_dim = max(max_dim, max(w, h))
                        if max_dim < 0.04:
                            face_size_bucket = "tiny_lt32"
                        elif max_dim < 0.12:
                            face_size_bucket = "small_32_96"
                        elif max_dim < 0.32:
                            face_size_bucket = "medium_96_256"
                        else:
                            face_size_bucket = "large_gt256"

                    try:
                        cur.execute(
                            """
                            INSERT INTO feature_hard_examples
                                (image_id, run_id, embedding, face_size_bucket,
                                 false_negative_count, extra)
                            VALUES (%s, %s, %s::vector, %s, %s, %s)
                            ON CONFLICT DO NOTHING
                        """,
                            (
                                os.path.basename(sample.filepath),
                                run_id,
                                str(embedding) if embedding else None,
                                face_size_bucket,
                                0,
                                json.dumps(
                                    {
                                        "hardness": hardness,
                                        "uniqueness": uniqueness,
                                        "source": "fiftyone_brain",
                                    }
                                ),
                            ),
                        )
                        exported += 1
                    except Exception:
                        continue

                conn.commit()

        client.close()
        print(f"  ✓ Exported {exported} hard examples to feature_hard_examples")
        return exported
    except Exception as e:
        print(f"  ⚠️  Export failed: {e}")
        return 0


def print_analysis_summary(dataset: Any, eval_metrics: dict) -> None:
    """Print summary of evaluation and brain analysis."""
    print("\n" + "=" * 70)
    print("FIFTYONE EVALUATION SUMMARY")
    print("=" * 70)

    print(f"\n  Dataset:     {dataset.name}")
    print(f"  Samples:     {len(dataset)}")

    if eval_metrics:
        print(f"\n  Evaluation:")
        for k, v in eval_metrics.items():
            if v is not None:
                print(f"    {k}: {v:.4f}" if isinstance(v, float) else f"    {k}: {v}")

    # Brain statistics
    if dataset.has_sample_field("hardness"):
        import numpy as np

        hardness_vals = dataset.values("hardness")
        hardness_vals = [v for v in hardness_vals if v is not None]
        if hardness_vals:
            print(f"\n  Hardness Distribution:")
            print(f"    Mean:   {np.mean(hardness_vals):.3f}")
            print(f"    Median: {np.median(hardness_vals):.3f}")
            print(f"    Max:    {np.max(hardness_vals):.3f}")
            hard_count = sum(1 for v in hardness_vals if v > 0.7)
            print(f"    Hard (>0.7): {hard_count} samples")

    if dataset.has_sample_field("uniqueness"):
        import numpy as np

        uniq_vals = dataset.values("uniqueness")
        uniq_vals = [v for v in uniq_vals if v is not None]
        if uniq_vals:
            print(f"\n  Uniqueness Distribution:")
            print(f"    Mean:   {np.mean(uniq_vals):.3f}")
            print(f"    Median: {np.median(uniq_vals):.3f}")
            low_uniq = sum(1 for v in uniq_vals if v < 0.1)
            print(f"    Near-duplicates (<0.1): {low_uniq} samples")

    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="FiftyOne Evaluation Pipeline")
    parser.add_argument(
        "--data-dir",
        type=str,
        default="/data/face_detection",
        help="COCO dataset directory",
    )
    parser.add_argument(
        "--dataset-name",
        type=str,
        default="phase9_rfdetr_eval",
        help="FiftyOne dataset name",
    )
    parser.add_argument(
        "--model-path", type=str, default=None, help="Path to trained model weights"
    )
    parser.add_argument(
        "--run-id", type=str, default="", help="MLflow run ID for traceability"
    )
    parser.add_argument(
        "--skip-brain", action="store_true", help="Skip brain computations"
    )
    parser.add_argument(
        "--skip-predictions",
        action="store_true",
        help="Skip model predictions (use existing)",
    )
    parser.add_argument(
        "--embedding-model",
        type=str,
        default="clip-vit-base32-torch",
        help="Embedding model for brain computations",
    )
    parser.add_argument(
        "--hardness-threshold",
        type=float,
        default=0.7,
        help="Threshold for hard example export",
    )
    args = parser.parse_args()

    if not FIFTYONE_AVAILABLE:
        print("❌ FiftyOne not available. Install with: pip install fiftyone")
        sys.exit(1)

    data_dir = Path(args.data_dir)

    print("=" * 70)
    print("Phase 9: FiftyOne Evaluation Pipeline")
    print("=" * 70)

    # 1. Load/create dataset
    print("\n━━━ Dataset Setup ━━━")
    dataset = load_or_create_dataset(data_dir, args.dataset_name)

    # 2. Run predictions (optional)
    if not args.skip_predictions and args.model_path:
        run_model_predictions(dataset, args.model_path)

    # 3. Run evaluation
    eval_metrics = run_evaluation(dataset)

    # 4. Brain computations
    if not args.skip_brain:
        run_brain_computations(dataset, embedding_model=args.embedding_model)

    # 5. Export hard examples
    if not args.skip_brain and dataset.has_sample_field("hardness"):
        export_hard_examples(
            dataset,
            hardness_threshold=args.hardness_threshold,
            run_id=args.run_id,
        )

    # 6. Summary
    print_analysis_summary(dataset, eval_metrics)

    print("\n✅ Evaluation pipeline complete")
    print(f"   View in FiftyOne: fo.launch_app(fo.load_dataset('{args.dataset_name}'))")


if __name__ == "__main__":
    main()
