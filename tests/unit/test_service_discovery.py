from __future__ import annotations

import subprocess
from types import SimpleNamespace

from scripts.platform import service_discovery


def test_container_ip_returns_first_address_from_multi_network_inspect(monkeypatch):
    service_discovery.container_ip.cache_clear()

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="172.18.0.9\n172.30.0.16\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert service_discovery.container_ip("shml-gitlab", "gitlab") == "172.18.0.9"


def test_container_ip_tries_next_name_when_first_lookup_fails(monkeypatch):
    service_discovery.container_ip.cache_clear()
    results = iter(
        [
            SimpleNamespace(returncode=1, stdout=""),
            SimpleNamespace(returncode=0, stdout="172.30.0.40\n"),
        ]
    )

    def fake_run(*args, **kwargs):
        return next(results)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert service_discovery.container_ip("missing-gitlab", "shml-gitlab") == "172.30.0.40"
