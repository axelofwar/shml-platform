from __future__ import annotations

import importlib.util
from argparse import Namespace
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_module(module_name: str, relative_path: str):
    path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_dispatch_watchdog_hermes_extracts_json_from_ansi_output():
    module = _load_module("dispatch_watchdog_hermes", "scripts/self-healing/dispatch_watchdog_hermes.py")
    payload = module.extract_payload(
        "\x1b[32m{"
        '"diagnosis":"GitLab unhealthy",'
        '"root_cause":"postgres mismatch",'
        '"severity":"critical",'
        '"restart_order":["shml-gitlab"],'
        '"gpu_yield_needed":false,'
        '"requires_agent_service":false,'
        '"vault_summary":"Recovered GitLab",'
        '"operator_notes":"Watch postgres version"}'
        "\x1b[0m"
    )

    assert payload["diagnosis"] == "GitLab unhealthy"
    assert payload["restart_order"] == ["shml-gitlab"]


def test_sync_watchdog_incident_to_obsidian_upserts_managed_entry():
    module = _load_module("sync_watchdog_incident", "scripts/self-healing/sync_watchdog_incident_to_obsidian.py")
    args = Namespace(
        incident_id="20260408T120000Z-gitlab-outage",
        issue_type="gitlab_outage",
        severity="critical",
        summary="GitLab was unreachable until the dedicated postgres dependency was restored.",
        root_cause="Dedicated GitLab PostgreSQL service was unavailable.",
        containers="shml-gitlab gitlab-postgres",
        restart_order="gitlab-postgres shml-gitlab",
        evidence_dir="/var/lib/watchdog/incidents/20260408T120000Z-gitlab-outage",
        transcript_path="/var/lib/watchdog/incidents/20260408T120000Z-gitlab-outage/hermes-transcript.txt",
        gitlab_issue="321",
    )

    initial = "# Plan\n\nExisting content.\n"
    updated = module.upsert_entry(initial, args)

    assert module.START_MARKER in updated
    assert "### Incident 20260408T120000Z-gitlab-outage — gitlab_outage" in updated
    assert "Dedicated GitLab PostgreSQL service was unavailable." in updated
    assert "`gitlab-postgres, shml-gitlab`" in updated or "`shml-gitlab, gitlab-postgres`" in updated
