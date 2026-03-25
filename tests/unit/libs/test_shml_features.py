"""Tests for libs/shml_features.py (FeatureClient).

All psycopg2 and requests calls are mocked — no live DB required.
"""
from __future__ import annotations

import os
import sys
import json
from unittest.mock import MagicMock, patch, call

import pytest

# Mock psycopg2 before importing shml_features
_mock_psycopg2 = MagicMock()
_mock_psycopg2.extras = MagicMock()
_mock_psycopg2.extras.RealDictCursor = MagicMock()
sys.modules["psycopg2"] = _mock_psycopg2
sys.modules["psycopg2.extras"] = _mock_psycopg2.extras

_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
if _root not in sys.path:
    sys.path.insert(0, _root)

from libs.shml_features import FeatureClient  # noqa: E402


# ===========================================================================
# Helpers
# ===========================================================================

def _make_conn_mock(rows=None, count_row=None):
    """Build a psycopg2 connection mock with cursor returning given rows."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.closed = 0  # Not closed

    # Context manager returns mock_cursor
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    if rows is not None:
        mock_cursor.fetchall.return_value = [dict(r) for r in rows]
    if count_row is not None:
        mock_cursor.fetchone.return_value = count_row
    return mock_conn, mock_cursor


# ===========================================================================
# TestFeatureClientConstructor
# ===========================================================================


class TestFeatureClientConstructor:
    def test_default_config_uses_env_vars(self):
        client = FeatureClient()
        assert client._pg_config["host"] == os.environ.get("POSTGRES_HOST", "postgres")
        assert client._pg_config["port"] == int(os.environ.get("POSTGRES_PORT", "5432"))

    def test_custom_config(self):
        client = FeatureClient(
            postgres_host="myhost",
            postgres_port=5433,
            postgres_db="testdb",
            postgres_user="testuser",
            postgres_password="secret",
        )
        assert client._pg_config["host"] == "myhost"
        assert client._pg_config["port"] == 5433
        assert client._pg_config["dbname"] == "testdb"
        assert client._pg_config["user"] == "testuser"
        assert client._pg_config["password"] == "secret"

    def test_conn_is_none_initially(self):
        client = FeatureClient()
        assert client._conn is None

    def test_get_conn_creates_connection(self):
        client = FeatureClient()
        mock_conn = MagicMock()
        mock_conn.closed = 0
        _mock_psycopg2.connect.return_value = mock_conn

        conn = client._get_conn()
        assert conn is mock_conn
        _mock_psycopg2.connect.assert_called_once()

    def test_get_conn_reuses_open_connection(self):
        client = FeatureClient()
        mock_conn = MagicMock()
        mock_conn.closed = 0
        _mock_psycopg2.connect.return_value = mock_conn

        client._get_conn()
        _mock_psycopg2.connect.reset_mock()
        client._get_conn()
        # Should NOT call connect again
        _mock_psycopg2.connect.assert_not_called()

    def test_get_conn_reconnects_when_closed(self):
        client = FeatureClient()
        # First connection is "closed"
        mock_conn_closed = MagicMock()
        mock_conn_closed.closed = 1
        client._conn = mock_conn_closed

        mock_conn_new = MagicMock()
        mock_conn_new.closed = 0
        _mock_psycopg2.connect.return_value = mock_conn_new

        conn = client._get_conn()
        assert conn is mock_conn_new


# ===========================================================================
# TestInitSchema
# ===========================================================================


class TestInitSchema:
    def test_init_schema_executes_creates(self):
        client = FeatureClient()
        mock_conn, mock_cursor = _make_conn_mock()
        client._conn = mock_conn

        client.init_schema()

        # Should have executed multiple CREATE TABLE / CREATE EXTENSION statements
        assert mock_cursor.execute.call_count >= 5
        mock_conn.commit.assert_called_once()

    def test_init_schema_creates_vector_extension(self):
        client = FeatureClient()
        mock_conn, mock_cursor = _make_conn_mock()
        client._conn = mock_conn

        client.init_schema()

        # Check that CREATE EXTENSION IF NOT EXISTS vector was called
        calls_sql = [str(c.args[0]).lower() for c in mock_cursor.execute.call_args_list]
        assert any("vector" in sql for sql in calls_sql)

    def test_init_schema_creates_feature_eval(self):
        client = FeatureClient()
        mock_conn, mock_cursor = _make_conn_mock()
        client._conn = mock_conn

        client.init_schema()

        calls_sql = [str(c.args[0]).lower() for c in mock_cursor.execute.call_args_list]
        assert any("feature_eval" in sql for sql in calls_sql)


# ===========================================================================
# TestGetEvalFeatures
# ===========================================================================


class TestGetEvalFeatures:
    def test_get_eval_features_latest(self):
        client = FeatureClient()
        rows = [{"model_version": "v1", "map50": 0.8}]
        mock_conn, mock_cursor = _make_conn_mock(rows=rows)
        client._conn = mock_conn
        mock_cursor.fetchall.return_value = rows  # Context mgr cursor

        result = client.get_eval_features()
        assert isinstance(result, list)

    def test_get_eval_features_with_version(self):
        client = FeatureClient()
        rows = [{"model_version": "v2", "map50": 0.85}]
        mock_conn, mock_cursor = _make_conn_mock(rows=rows)
        client._conn = mock_conn
        mock_cursor.fetchall.return_value = rows

        result = client.get_eval_features(model_version="v2", limit=5)
        # Should have queried — verify execute was called at least once
        assert mock_cursor.execute.called

    def test_get_eval_features_returns_list_of_dicts(self):
        client = FeatureClient()
        rows = [{"k": "v"}]
        mock_conn, mock_cursor = _make_conn_mock(rows=rows)
        client._conn = mock_conn
        mock_cursor.fetchall.return_value = rows

        result = client.get_eval_features()
        assert result == rows


# ===========================================================================
# TestFindSimilarExamples
# ===========================================================================


class TestFindSimilarExamples:
    def test_empty_embedding_returns_empty(self):
        client = FeatureClient()
        result = client.find_similar_examples([])
        assert result == []

    def test_none_embedding_returns_empty(self):
        client = FeatureClient()
        result = client.find_similar_examples(None)  # type: ignore
        assert result == []

    def test_no_embeddings_in_db_returns_empty(self):
        client = FeatureClient()
        mock_conn, mock_cursor = _make_conn_mock()
        client._conn = mock_conn
        mock_cursor.fetchone.return_value = {"count": 0}
        mock_cursor.fetchall.return_value = []

        result = client.find_similar_examples([0.1] * 512)
        assert result == []

    def test_finds_similar_without_cluster_filter(self):
        client = FeatureClient()
        mock_conn, mock_cursor = _make_conn_mock()
        client._conn = mock_conn
        mock_cursor.fetchone.return_value = {"count": 10}
        mock_cursor.fetchall.return_value = [{"image_id": "img1", "distance": 0.05}]

        result = client.find_similar_examples([0.5] * 512, k=5)
        assert isinstance(result, list)

    def test_finds_similar_with_cluster_filter(self):
        client = FeatureClient()
        mock_conn, mock_cursor = _make_conn_mock()
        client._conn = mock_conn
        mock_cursor.fetchone.return_value = {"count": 5}
        mock_cursor.fetchall.return_value = [{"image_id": "img2", "distance": 0.1}]

        result = client.find_similar_examples([0.5] * 512, k=3, cluster_id=7)
        assert isinstance(result, list)
        # Should have queried with cluster filter
        calls_sql = [str(c.args[0]) for c in mock_cursor.execute.call_args_list]
        assert any("cluster_id" in sql or "failure_cluster_id" in sql for sql in calls_sql)


# ===========================================================================
# TestMaterializeEvalFeatures
# ===========================================================================


class TestMaterializeEvalFeatures:
    def _mock_run_response(self, run_id="abc123"):
        return {
            "run": {
                "info": {"run_id": run_id},
                "data": {
                    "metrics": [
                        {"key": "final_mAP50", "value": 0.85},
                        {"key": "final_mAP50_95", "value": 0.60},
                    ],
                    "params": [
                        {"key": "dataset", "value": "yfcc100m"},
                        {"key": "epochs", "value": "100"},
                    ],
                    "tags": [
                        {"key": "model_version", "value": "v2.0"},
                        {"key": "phase", "value": "p3"},
                    ],
                },
            }
        }

    def test_materialize_success(self):
        client = FeatureClient()
        mock_conn, mock_cursor = _make_conn_mock()
        client._conn = mock_conn

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = self._mock_run_response()

        with patch("requests.get", return_value=mock_resp):
            result = client.materialize_eval_features("abc123")

        assert result is True
        mock_conn.commit.assert_called_once()

    def test_materialize_failure_on_http_error(self):
        client = FeatureClient()
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.text = "Not Found"

        with patch("requests.get", return_value=mock_resp):
            result = client.materialize_eval_features("badrun")

        assert result is False

    def test_materialize_handles_missing_metrics(self):
        client = FeatureClient()
        mock_conn, mock_cursor = _make_conn_mock()
        client._conn = mock_conn

        run_data = {
            "run": {
                "info": {},
                "data": {
                    "metrics": [],
                    "params": [],
                    "tags": [],
                },
            }
        }
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = run_data

        with patch("requests.get", return_value=mock_resp):
            result = client.materialize_eval_features("abc123")

        assert result is True


# ===========================================================================
# TestMaterializeTrainingLineage
# ===========================================================================


class TestMaterializeTrainingLineage:
    def test_lineage_success(self):
        client = FeatureClient()
        mock_conn, mock_cursor = _make_conn_mock()
        client._conn = mock_conn

        run_data = {
            "run": {
                "info": {"run_id": "run1"},
                "data": {
                    "params": [
                        {"key": "lr", "value": "0.001"},
                        {"key": "dataset_version", "value": "v3"},
                    ],
                    "tags": [
                        {"key": "mlflow.experimentName", "value": "exp1"},
                        {"key": "phase", "value": "p1"},
                    ],
                },
            }
        }
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = run_data

        with patch("requests.get", return_value=mock_resp):
            result = client.materialize_training_lineage("run1")

        assert result is True
        mock_conn.commit.assert_called_once()

    def test_lineage_failure_on_http_error(self):
        client = FeatureClient()
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.text = "Server Error"

        with patch("requests.get", return_value=mock_resp):
            result = client.materialize_training_lineage("runX")

        assert result is False


# ===========================================================================
# TestLoadFiftyOneDataset
# ===========================================================================


class TestLoadFiftyOneDataset:
    def test_load_fiftyone_dataset_yolo(self):
        mock_fo = MagicMock()
        mock_dataset = MagicMock()
        mock_fo.dataset_exists.return_value = False
        mock_fo.Dataset.from_dir.return_value = mock_dataset

        with patch.dict(sys.modules, {"fiftyone": mock_fo}):
            result = FeatureClient.load_fiftyone_dataset(
                name="test-ds", dataset_dir="/data/images", dataset_type="yolo"
            )
            assert result is not None

    def test_load_fiftyone_dataset_existing(self):
        mock_fo = MagicMock()
        mock_dataset = MagicMock()
        mock_fo.load_dataset.return_value = mock_dataset

        with patch.dict(sys.modules, {"fiftyone": mock_fo}):
            result = FeatureClient.load_fiftyone_dataset(
                name="existing-ds", dataset_dir="/data/images"
            )
            assert result == mock_dataset


# ===========================================================================
# Module-level constants
# ===========================================================================


class TestModuleConstants:
    def test_postgres_host_default(self):
        from libs.shml_features import POSTGRES_HOST
        assert isinstance(POSTGRES_HOST, str)

    def test_postgres_port_is_int(self):
        from libs.shml_features import POSTGRES_PORT
        assert isinstance(POSTGRES_PORT, int)
        assert POSTGRES_PORT > 0

    def test_mlflow_tracking_uri_is_string(self):
        from libs.shml_features import MLFLOW_TRACKING_URI
        assert isinstance(MLFLOW_TRACKING_URI, str)
