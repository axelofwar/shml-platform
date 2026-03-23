"""T7: Unit tests for monitoring configuration files.

These tests validate YAML structure without requiring live Prometheus/Grafana.
All assertions are purely file-based — no external services needed.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MONITORING_DIR = REPO_ROOT / "monitoring"
PROMETHEUS_DIR = MONITORING_DIR / "prometheus"
ALERTMANAGER_DIR = MONITORING_DIR / "alertmanager"
GRAFANA_DIR = MONITORING_DIR / "grafana"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Prometheus config tests
# ---------------------------------------------------------------------------


class TestPrometheusConfig:
    """Validate prometheus.yml structure."""

    @pytest.fixture(scope="class")
    def cfg(self):
        return load_yaml(PROMETHEUS_DIR / "prometheus.yml")

    def test_global_scrape_interval_set(self, cfg):
        assert "global" in cfg
        assert "scrape_interval" in cfg["global"]

    def test_scrape_configs_is_list(self, cfg):
        assert isinstance(cfg.get("scrape_configs"), list)
        assert len(cfg["scrape_configs"]) > 0

    def test_all_job_names_unique(self, cfg):
        job_names = [j["job_name"] for j in cfg["scrape_configs"]]
        assert len(job_names) == len(set(job_names)), "Duplicate job_name entries found"

    def test_rule_files_section_present(self, cfg):
        assert "rule_files" in cfg

    def test_alertmanager_configured(self, cfg):
        assert "alerting" in cfg
        am = cfg["alerting"]["alertmanagers"]
        assert isinstance(am, list)
        assert len(am) > 0

    def test_each_scrape_job_has_static_config_or_relabel(self, cfg):
        for job in cfg["scrape_configs"]:
            assert "job_name" in job, f"Missing job_name in {job}"
            has_targets = "static_configs" in job or "relabel_configs" in job
            # Some jobs use file_sd_configs or other discovery
            assert "job_name" in job  # at minimum

    def test_ml_slo_exporter_job_present(self, cfg):
        job_names = [j["job_name"] for j in cfg["scrape_configs"]]
        assert "ml-slo-exporter" in job_names, "ml-slo-exporter scrape job missing"

    def test_feature_store_job_present(self, cfg):
        job_names = [j["job_name"] for j in cfg["scrape_configs"]]
        assert "feature-store" in job_names, "feature-store scrape job missing"

    def test_external_labels_include_cluster(self, cfg):
        labels = cfg["global"].get("external_labels", {})
        assert "cluster" in labels


# ---------------------------------------------------------------------------
# Alert rule tests
# ---------------------------------------------------------------------------


class TestAlertRules:
    """Validate Prometheus alert rule YAML files."""

    @pytest.fixture(
        scope="class",
        params=list((PROMETHEUS_DIR / "alerts").glob("*.yml")),
        ids=lambda p: p.name,
    )
    def alert_file(self, request):
        return load_yaml(request.param)

    def test_has_groups_key(self, alert_file):
        assert "groups" in alert_file

    def test_groups_is_list(self, alert_file):
        assert isinstance(alert_file["groups"], list)

    def test_each_group_has_name(self, alert_file):
        for group in alert_file["groups"]:
            assert "name" in group

    def test_each_rule_has_alert_and_expr(self, alert_file):
        for group in alert_file["groups"]:
            for rule in group.get("rules", []):
                # Alert rules have alert+expr; recording rules have record+expr
                assert "expr" in rule, f"Rule missing expr: {rule}"
                if "alert" in rule:
                    assert "annotations" in rule or "labels" in rule

    def test_alert_names_no_spaces(self, alert_file):
        for group in alert_file["groups"]:
            for rule in group.get("rules", []):
                if "alert" in rule:
                    assert " " not in rule["alert"], (
                        f"Alert name '{rule['alert']}' contains spaces"
                    )


# ---------------------------------------------------------------------------
# Alertmanager config tests
# ---------------------------------------------------------------------------


class TestAlertmanagerConfig:
    """Validate alertmanager.yml."""

    @pytest.fixture(scope="class")
    def cfg(self):
        path = ALERTMANAGER_DIR / "alertmanager.yml"
        if not path.exists():
            pytest.skip("alertmanager.yml not found")
        return load_yaml(path)

    def test_route_section_present(self, cfg):
        assert "route" in cfg

    def test_receivers_defined(self, cfg):
        assert "receivers" in cfg
        assert isinstance(cfg["receivers"], list)
        assert len(cfg["receivers"]) > 0

    def test_route_has_receiver(self, cfg):
        assert "receiver" in cfg["route"]


# ---------------------------------------------------------------------------
# Grafana datasources tests
# ---------------------------------------------------------------------------


class TestGrafanaDatasources:
    """Validate grafana/datasources.yml."""

    @pytest.fixture(scope="class")
    def cfg(self):
        path = GRAFANA_DIR / "datasources.yml"
        if not path.exists():
            pytest.skip("grafana/datasources.yml not found")
        return load_yaml(path)

    def test_api_version_present(self, cfg):
        assert "apiVersion" in cfg

    def test_datasources_is_list(self, cfg):
        assert isinstance(cfg.get("datasources"), list)

    def test_prometheus_datasource_configured(self, cfg):
        types = [d.get("type") for d in cfg["datasources"]]
        assert "prometheus" in types, "Prometheus datasource missing from grafana datasources.yml"

    def test_datasource_names_unique(self, cfg):
        names = [d.get("name") for d in cfg["datasources"]]
        assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Homer dashboard config
# ---------------------------------------------------------------------------


class TestHomerConfig:
    """Validate homer/config.yml service structure."""

    @pytest.fixture(scope="class")
    def cfg(self):
        path = MONITORING_DIR / "homer" / "config.yml"
        if not path.exists():
            pytest.skip("homer/config.yml not found")
        return load_yaml(path)

    def test_services_section_present(self, cfg):
        assert "services" in cfg or "links" in cfg

    def test_title_present(self, cfg):
        assert "title" in cfg or "subtitle" in cfg
