"""
Tests for FiftyOne Embeddings & Similarity Search
===================================================

Tests the FiftyOne proxy entrypoint, compose configuration, path prefix
handling, feature store similarity search, and eval pipeline structure.

Usage:
    pytest tests/unit/test_fiftyone_embeddings.py -v
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

_root = os.path.join(os.path.dirname(__file__), "..", "..")


# ===========================================================================
# FiftyOne Compose Configuration Tests
# ===========================================================================


class TestFiftyOneCompose:
    """Verify FiftyOne docker-compose settings."""

    @pytest.fixture
    def compose_content(self):
        path = os.path.join(_root, "deploy/compose/docker-compose.infra.yml")
        if not os.path.exists(path):
            pytest.skip("deploy/compose/docker-compose.infra.yml not found")
        with open(path) as f:
            return f.read()

    def test_fiftyone_server_path_prefix_set(self, compose_content):
        """FIFTYONE_SERVER_PATH_PREFIX must be set for reverse proxy."""
        assert "FIFTYONE_SERVER_PATH_PREFIX: /fiftyone" in compose_content

    def test_fiftyone_path_prefix_set(self, compose_content):
        """FIFTYONE_PATH_PREFIX must be set for entrypoint patching."""
        assert "FIFTYONE_PATH_PREFIX: /fiftyone" in compose_content

    def test_fiftyone_uses_entrypoint(self, compose_content):
        """FiftyOne should use the entrypoint.py for dynamic index.html patching."""
        assert "entrypoint.py" in compose_content

    def test_fiftyone_no_hardcoded_python_path(self, compose_content):
        """Should NOT hardcode python3.11 path for index.html mount."""
        # The old approach mounted to a specific python version path
        assert (
            "python3.11/site-packages" not in compose_content
        ), "Should not hardcode Python version in index.html mount path"

    def test_fiftyone_entrypoint_mounted(self, compose_content):
        """Entrypoint directory should be mounted."""
        assert "fiftyone-entrypoint" in compose_content

    def test_fiftyone_mongodb_uri_set(self, compose_content):
        assert "mongodb://fiftyone-mongodb:27017" in compose_content

    def test_fiftyone_requires_developer_role(self, compose_content):
        assert "role-auth-developer" in compose_content

    def test_fiftyone_strip_prefix(self, compose_content):
        assert "fiftyone-strip" in compose_content


# ===========================================================================
# FiftyOne Entrypoint Tests
# ===========================================================================


class TestFiftyOneEntrypoint:
    """Test the FiftyOne proxy entrypoint script."""

    @pytest.fixture
    def entrypoint_path(self):
        path = os.path.join(_root, "config", "fiftyone", "entrypoint.py")
        if not os.path.exists(path):
            pytest.skip("FiftyOne entrypoint not found")
        return path

    def test_entrypoint_exists(self, entrypoint_path):
        assert os.path.exists(entrypoint_path)

    def test_entrypoint_reads_path_prefix_env(self, entrypoint_path):
        with open(entrypoint_path) as f:
            content = f.read()
        assert "FIFTYONE_PATH_PREFIX" in content

    def test_entrypoint_injects_script_tag(self, entrypoint_path):
        with open(entrypoint_path) as f:
            content = f.read()
        assert "FIFTYONE_SERVER_PATH_PREFIX" in content

    def test_entrypoint_finds_dynamic_path(self, entrypoint_path):
        """Entrypoint should search for index.html dynamically, not hardcode."""
        with open(entrypoint_path) as f:
            content = f.read()
        assert "glob" in content or "find_index_html" in content

    def test_entrypoint_idempotent_patch(self, entrypoint_path):
        """Entrypoint should check if already patched to avoid double injection."""
        with open(entrypoint_path) as f:
            content = f.read()
        assert (
            "already patched" in content.lower()
            or "FIFTYONE_SERVER_PATH_PREFIX" in content
        )

    def test_entrypoint_has_fallback(self, entrypoint_path):
        """Entrypoint should continue even if patching fails."""
        with open(entrypoint_path) as f:
            content = f.read()
        assert "WARNING" in content or "except" in content


# ===========================================================================
# FiftyOne Index HTML Tests
# ===========================================================================


class TestFiftyOneIndexHtml:
    """Test the custom FiftyOne index.html."""

    @pytest.fixture
    def index_path(self):
        path = os.path.join(_root, "config", "fiftyone", "index.html")
        if not os.path.exists(path):
            pytest.skip("FiftyOne index.html not found")
        return path

    def test_index_exists(self, index_path):
        assert os.path.exists(index_path)

    def test_index_has_path_prefix_script(self, index_path):
        with open(index_path) as f:
            content = f.read()
        assert "FIFTYONE_SERVER_PATH_PREFIX" in content
        assert '"/fiftyone"' in content

    def test_index_script_before_modules(self, index_path):
        """Path prefix must be set BEFORE module scripts load."""
        with open(index_path) as f:
            content = f.read()
        prefix_pos = content.find("FIFTYONE_SERVER_PATH_PREFIX")
        module_pos = content.find('type="module"')
        assert (
            prefix_pos < module_pos
        ), "Path prefix script must appear before module scripts"


# ===========================================================================
# Feature Store Similarity Search Tests
# ===========================================================================


class TestSimilaritySearch:
    """Test pgvector similarity search in shml_features.py."""

    @pytest.fixture
    def features_content(self):
        path = os.path.join(_root, "libs", "shml_features.py")
        if not os.path.exists(path):
            pytest.skip("shml_features.py not found")
        with open(path) as f:
            return f.read()

    def test_uses_hnsw_index(self, features_content):
        """Should use HNSW index (works with any row count, unlike IVFFlat)."""
        assert (
            "hnsw" in features_content.lower()
        ), "Should use HNSW index for similarity search"

    def test_no_ivfflat_index_in_create_statements(self, features_content):
        """CREATE INDEX statements should NOT use IVFFlat (fails with small datasets)."""
        # Only check actual CREATE INDEX statements, not comments/docstrings
        create_idx_lines = [
            line
            for line in features_content.split("\n")
            if "CREATE INDEX" in line.upper() and "ivfflat" in line.lower()
        ]
        assert (
            len(create_idx_lines) == 0
        ), f"Found IVFFlat in CREATE INDEX statements (use HNSW instead): {create_idx_lines}"

    def test_cosine_distance_operator(self, features_content):
        """Should use pgvector cosine distance operator."""
        assert "<=>" in features_content, "Should use <=> cosine distance"
        assert "vector_cosine_ops" in features_content

    def test_null_embedding_filter(self, features_content):
        """Similarity search should filter out NULL embeddings."""
        assert "embedding IS NOT NULL" in features_content

    def test_empty_embedding_guard(self, features_content):
        """Should guard against empty embedding input."""
        assert (
            "not embedding" in features_content
            or "len(embedding) == 0" in features_content
        )

    def test_count_check_before_search(self, features_content):
        """Should check if embeddings exist before searching."""
        assert "COUNT" in features_content

    def test_find_similar_examples_exists(self, features_content):
        assert "def find_similar_examples" in features_content


# ===========================================================================
# FiftyOne Eval Pipeline Tests
# ===========================================================================


class TestFiftyOneEvalPipeline:
    """Test the FiftyOne evaluation pipeline structure.

    The core logic lives in libs/evaluation/face/fiftyone_eval_pipeline.py;
    ray_compute/jobs/evaluation/fiftyone_eval_pipeline.py is a thin Ray wrapper
    that delegates to it. Tests check the libs module for domain logic.
    """

    @pytest.fixture
    def pipeline_content(self):
        """Load the libs-level fiftyone evaluation pipeline source."""
        path = os.path.join(
            _root, "libs", "evaluation", "face", "fiftyone_eval_pipeline.py"
        )
        if not os.path.exists(path):
            pytest.skip("libs/evaluation/face/fiftyone_eval_pipeline.py not found")
        with open(path) as f:
            return f.read()

    @pytest.fixture
    def ray_wrapper_content(self):
        """Load the Ray orchestration wrapper source."""
        path = os.path.join(
            _root, "ray_compute", "jobs", "evaluation", "fiftyone_eval_pipeline.py"
        )
        if not os.path.exists(path):
            pytest.skip("ray_compute fiftyone_eval_pipeline.py not found")
        with open(path) as f:
            return f.read()

    def test_pipeline_computes_embeddings(self, pipeline_content):
        assert "compute_embeddings" in pipeline_content

    def test_pipeline_computes_similarity(self, pipeline_content):
        assert "compute_similarity" in pipeline_content

    def test_pipeline_computes_uniqueness(self, pipeline_content):
        assert "compute_uniqueness" in pipeline_content

    def test_pipeline_computes_hardness(self, pipeline_content):
        assert "compute_hardness" in pipeline_content

    def test_pipeline_exports_hard_examples(self, pipeline_content):
        assert "export_hard_examples" in pipeline_content
        assert "feature_hard_examples" in pipeline_content

    def test_pipeline_uses_clip_model(self, pipeline_content):
        assert "clip-vit-base32-torch" in pipeline_content

    def test_pipeline_has_skip_brain_flag(self, pipeline_content):
        assert "--skip-brain" in pipeline_content

    def test_pipeline_handles_missing_fiftyone(self, pipeline_content):
        """Pipeline should gracefully handle missing FiftyOne."""
        assert "FIFTYONE_AVAILABLE" in pipeline_content
        assert "ImportError" in pipeline_content

    def test_ray_wrapper_delegates_to_libs(self, ray_wrapper_content):
        """Ray wrapper should delegate to libs.evaluation.face module."""
        assert "libs.evaluation.face" in ray_wrapper_content
        assert "fiftyone_eval_pipeline" in ray_wrapper_content

    def test_ray_wrapper_uses_ray_remote(self, ray_wrapper_content):
        """Ray wrapper must use @ray.remote decorator."""
        assert "@ray.remote" in ray_wrapper_content


# ===========================================================================
# SDK FiftyOne Client Tests
# ===========================================================================


class TestSDKFiftyOneClient:
    """Test the SDK FiftyOne integration client."""

    @pytest.fixture
    def client_content(self):
        path = os.path.join(_root, "sdk", "shml", "integrations", "fiftyone.py")
        if not os.path.exists(path):
            pytest.skip("SDK FiftyOne client not found")
        with open(path) as f:
            return f.read()

    def test_client_has_compute_embeddings(self, client_content):
        assert "def compute_embeddings" in client_content

    def test_client_has_compute_similarity(self, client_content):
        assert "def compute_similarity" in client_content

    def test_client_has_compute_uniqueness(self, client_content):
        assert "def compute_uniqueness" in client_content

    def test_client_handles_missing_brain(self, client_content):
        """Client should raise FiftyOneError if brain not installed."""
        assert "fiftyone.brain not available" in client_content

    def test_client_sets_database_uri(self, client_content):
        """Client should set FIFTYONE_DATABASE_URI before import."""
        assert "FIFTYONE_DATABASE_URI" in client_content

    def test_client_has_healthy_check(self, client_content):
        assert "def healthy" in client_content
