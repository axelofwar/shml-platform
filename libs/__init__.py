"""
SHML Platform Libraries

Sub-modules (import directly from the relevant module):
  from libs.shml_spark import create_spark_session      # PySpark + Nessie/Iceberg
  from libs.shml_features import FeatureClient          # FiftyOne + pgvector
  from libs.feature_store.registry import FeatureRegistry
  from libs.evaluation.face.evaluate_face_detection import FaceDetectionEvaluator
  from libs.annotation.yfcc100m.yfcc100m_downloader import YFCC100MDownloader

Do NOT add eager imports here — sub-modules carry heavy runtime dependencies
(pyspark, torch, fiftyone) that must not be pulled in transitively.
"""
