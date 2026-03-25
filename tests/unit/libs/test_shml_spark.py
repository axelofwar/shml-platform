from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock


_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


class _Builder:
    def __init__(self):
        self.calls = []

    def appName(self, name):
        self.calls.append(("appName", name))
        return self

    def config(self, key, value):
        self.calls.append(("config", key, value))
        return self

    def master(self, value):
        self.calls.append(("master", value))
        return self

    def getOrCreate(self):
        self.calls.append(("getOrCreate",))
        return self


def _install_pyspark_stub(builder: _Builder) -> None:
    pyspark = ModuleType("pyspark")
    pyspark_sql = ModuleType("pyspark.sql")
    pyspark_sql.SparkSession = MagicMock(builder=builder)
    sys.modules["pyspark"] = pyspark
    sys.modules["pyspark.sql"] = pyspark_sql


def test_create_spark_session_local_and_extra_config(monkeypatch):
    builder = _Builder()
    _install_pyspark_stub(builder)
    import libs.shml_spark as spark_mod

    session = spark_mod.create_spark_session(
        "job-1",
        extra_config={"spark.executor.memory": "4g"},
        local_mode=True,
    )

    assert session is builder
    assert ("appName", "job-1") in builder.calls
    assert ("master", "local[*]") in builder.calls
    assert ("config", "spark.executor.memory", "4g") in builder.calls


def test_create_spark_session_cluster_mode(monkeypatch):
    builder = _Builder()
    _install_pyspark_stub(builder)
    import libs.shml_spark as spark_mod

    spark_mod.create_spark_session("job-2", local_mode=False)

    assert not any(call[0] == "master" for call in builder.calls)


def test_branch_merge_and_tag_helpers_issue_expected_sql():
    import libs.shml_spark as spark_mod

    spark = MagicMock()
    spark_mod.create_branch(spark, "staging/test", from_ref="dev")
    spark_mod.merge_branch(spark, "staging/test", into="main")
    spark_mod.tag_release(spark, "v1.0.0", ref="main")

    sql_calls = [call.args[0] for call in spark.sql.call_args_list]
    assert "CREATE BRANCH IF NOT EXISTS `staging/test` IN nessie FROM `dev`" in sql_calls[0]
    assert "MERGE BRANCH `staging/test` INTO `main` IN nessie" in sql_calls[1]
    assert "CREATE TAG IF NOT EXISTS `v1.0.0` IN nessie FROM `main`" in sql_calls[2]
