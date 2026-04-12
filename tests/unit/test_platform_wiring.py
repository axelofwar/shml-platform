"""T9: Platform wiring tests — regression guards for infrastructure plumbing.

These tests validate that:
1. All docker compose paths referenced in start_all_safe.sh exist on disk (G1 regression)
2. All required __init__.py files exist for Python packages
3. deploy/compose directory has expected files
4. .env.example does NOT contain hardcoded secrets (pattern check)
5. start_all_safe.sh is executable
6. Taskfile has expected task names
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _read(path: Path) -> str:
    with open(path) as f:
        return f.read()


# ---------------------------------------------------------------------------
# T9.1: start_all_safe.sh compose path regression (G1 guard)
# ---------------------------------------------------------------------------


class TestStartAllSafeComposePaths:
    """Regression: every compose -f <path> in start_all_safe.sh must exist."""

    @pytest.fixture(scope="class")
    def compose_paths(self):
        wrapper = REPO_ROOT / "start_all_safe.sh"
        deploy_script = REPO_ROOT / "scripts" / "deploy" / "start_all_safe.sh"

        if not deploy_script.exists():
            pytest.skip("scripts/deploy/start_all_safe.sh not found")

        content = _read(deploy_script)

        if wrapper.exists():
            wrapper_content = _read(wrapper)
            assert "scripts/deploy/start_all_safe.sh" in wrapper_content

        # Extract all paths passed to `docker compose -f <path>` or `docker-compose -f <path>`
        # Require the path to look like a file path (contains / or .yml)
        pattern = re.compile(
            r"docker(?:-compose|\s+compose)\b[^\n]*?-f\s+([\./][^\s|&;\n\"']+\.yml)"
        )
        paths = pattern.findall(content)
        # Also catch quoted paths that end in .yml
        pattern2 = re.compile(r'-f\s+"([^"]+\.yml)"|-f\s+\'([^\']+\.yml)\'')
        for a, b in pattern2.findall(content):
            paths.append(a or b)
        return [p.strip() for p in paths if p.strip()]

    def test_at_least_one_compose_path_found(self, compose_paths):
        assert len(compose_paths) > 5, "Expected many compose paths in start_all_safe.sh"

    def test_all_compose_paths_exist_on_disk(self, compose_paths):
        missing = []
        for raw_path in compose_paths:
            # Strip shell variable prefixes like ${COMPOSE_DIR}/
            cleaned = re.sub(r"\$\{[^}]+\}/", "", raw_path)
            cleaned = re.sub(r"\$[A-Z_]+/", "", cleaned)
            if cleaned.startswith("$") or not cleaned:
                continue
            full = REPO_ROOT / cleaned
            if not full.exists():
                missing.append(cleaned)
        assert missing == [], f"Missing compose files referenced in start_all_safe.sh:\n" + "\n".join(missing)


# ---------------------------------------------------------------------------
# T9.2: Python package __init__.py presence
# ---------------------------------------------------------------------------


class TestPackageInits:
    """Required __init__.py files must exist."""

    REQUIRED_INITS = [
        "libs/__init__.py",
        "inference/__init__.py",
        "ray_compute/jobs/inference/__init__.py",
        "ray_compute/jobs/features/__init__.py",
        "tests/unit/__init__.py",
        "tests/unit/libs/__init__.py",
        "tests/unit/inference/__init__.py",
        "tests/unit/ray_compute/__init__.py",
    ]

    @pytest.mark.parametrize("rel_path", REQUIRED_INITS)
    def test_init_exists(self, rel_path):
        full = REPO_ROOT / rel_path
        assert full.exists(), f"Missing required __init__.py: {rel_path}"


# ---------------------------------------------------------------------------
# T9.3: deploy/compose directory contains key stacks
# ---------------------------------------------------------------------------


class TestDeployCompose:
    """deploy/compose must contain the primary docker-compose stacks."""

    EXPECTED_COMPOSE_FILES = [
        "deploy/compose/docker-compose.infra.yml",
        "deploy/compose/docker-compose.auth.yml",
        "deploy/compose/docker-compose.core.yml",
    ]

    @pytest.mark.parametrize("rel_path", EXPECTED_COMPOSE_FILES)
    def test_compose_file_exists(self, rel_path):
        full = REPO_ROOT / rel_path
        assert full.exists(), f"Expected compose file missing: {rel_path}"


# ---------------------------------------------------------------------------
# T9.4: .env.example does not contain hardcoded secrets
# ---------------------------------------------------------------------------


class TestEnvExample:
    """Check that .env.example uses placeholder values, not real secrets."""

    SECRET_PATTERNS = [
        r'(?i)password[ \t]*=[ \t]*[A-Za-z0-9+/]{16,}',
        r'(?i)secret[ \t]*=[ \t]*[A-Za-z0-9+/]{16,}',
        r'(?i)api_key[ \t]*=[ \t]*[A-Za-z0-9_\-]{20,}',
        r'sk-[A-Za-z0-9]{20,}',
    ]

    @pytest.fixture(scope="class")
    def env_example_content(self):
        env_file = REPO_ROOT / ".env.example"
        if not env_file.exists():
            pytest.skip(".env.example not found")
        return _read(env_file)

    def test_no_hardcoded_passwords(self, env_example_content):
        for pattern in self.SECRET_PATTERNS:
            matches = re.findall(pattern, env_example_content)
            # Allow ${VAR} substitution patterns
            real = [m for m in matches if not re.search(r'\$\{', m)]
            assert real == [], f"Potential hardcoded secret found in .env.example: {real}"


# ---------------------------------------------------------------------------
# T9.5: start_all_safe.sh is executable
# ---------------------------------------------------------------------------


class TestScriptPermissions:
    """start_all_safe.sh and stop_all.sh must be executable."""

    @pytest.mark.parametrize("script", ["start_all_safe.sh", "stop_all.sh"])
    def test_script_is_executable(self, script):
        path = REPO_ROOT / script
        if not path.exists():
            pytest.skip(f"{script} not found")
        mode = os.stat(path).st_mode
        assert bool(mode & stat.S_IXUSR), f"{script} is not executable"


# ---------------------------------------------------------------------------
# T9.6: Taskfile has expected task names
# ---------------------------------------------------------------------------


class TestTaskfileStructure:
    """Key task names must be present in Taskfile.yml."""

    EXPECTED_TASKS = [
        "status",
        "start",
        "stop",
        "restart",
        "start:watchdog",
        "start:sba",
        "restart:devtools",
        "restart:sba",
        "restart:watchdog",
    ]

    @pytest.fixture(scope="class")
    def taskfile_content(self):
        tf = REPO_ROOT / "Taskfile.yml"
        if not tf.exists():
            pytest.skip("Taskfile.yml not found")
        return _read(tf)

    @pytest.mark.parametrize("task_name", EXPECTED_TASKS)
    def test_task_name_present(self, task_name, taskfile_content):
        assert task_name in taskfile_content, f"Task '{task_name}' missing from Taskfile.yml"


class TestSafeRestartContracts:
    """Safe restart entrypoints must map to validated procedures."""

    EXPECTED_TASK_COMMANDS = {
        '"start:infra"': '"{{.DEPLOY}} start infra"',
        '"start:auth"': '"{{.DEPLOY}} start auth"',
        '"start:mlflow"': '"{{.DEPLOY}} start mlflow"',
        '"start:ray"': '"{{.DEPLOY}} start ray"',
        '"start:inference"': '"{{.DEPLOY}} start inference"',
        '"start:monitoring"': '"{{.DEPLOY}} start monitoring"',
        '"start:devtools"': '"{{.DEPLOY}} start devtools"',
        '"start:agent"': '"{{.DEPLOY}} start agent"',
        '"start:watchdog"': '"{{.DEPLOY}} start watchdog"',
        '"start:sba"': '"{{.DEPLOY}} start sba"',
        '"restart:infra"': '"{{.DEPLOY}} restart infra"',
        '"restart:auth"': '"{{.DEPLOY}} restart auth"',
        '"restart:mlflow"': '"{{.DEPLOY}} restart mlflow"',
        '"restart:ray"': '"{{.DEPLOY}} restart ray"',
        '"restart:inference"': '"{{.DEPLOY}} restart inference"',
        '"restart:monitoring"': '"{{.DEPLOY}} restart monitoring"',
        '"restart:devtools"': '"{{.DEPLOY}} restart devtools"',
        '"restart:sba"': '"{{.DEPLOY}} restart sba"',
        '"restart:watchdog"': '"{{.DEPLOY}} restart watchdog"',
        '"restart:agent"': '"{{.DEPLOY}} restart agent"',
    }

    EXPECTED_SCRIPT_CASES = {
        'infra|infrastructure': ('start_infra', 'down_infra && start_infra'),
        'auth|authentication': ('start_auth', 'down_auth && start_auth'),
        'mlflow': ('start_mlflow', 'down_mlflow && start_mlflow'),
        'ray': ('start_ray', 'down_ray && start_ray'),
        'inference|models|coding': ('start_inference', 'down_inference && start_inference'),
        'monitoring|mon': ('start_monitoring', 'down_monitoring && start_monitoring'),
        'devtools|dev|ide|code-server': ('start_devtools', 'down_devtools && start_devtools'),
        'agent|ace': ('start_agent', 'down_agent && start_agent'),
        'watchdog': ('start_watchdog', 'down_watchdog && start_watchdog'),
        'sba|sba-portal|gemini': ('start_sba_portal', 'down_sba_portal && start_sba_portal'),
    }

    @pytest.fixture(scope="class")
    def taskfile_content(self):
        tf = REPO_ROOT / "Taskfile.yml"
        if not tf.exists():
            pytest.skip("Taskfile.yml not found")
        return _read(tf)

    @pytest.fixture(scope="class")
    def deploy_script_content(self):
        script = REPO_ROOT / "scripts" / "deploy" / "start_all_safe.sh"
        if not script.exists():
            pytest.skip("scripts/deploy/start_all_safe.sh not found")
        return _read(script)

    @pytest.fixture(scope="class")
    def watchdog_content(self):
        script = REPO_ROOT / "scripts" / "self-healing" / "watchdog.sh"
        if not script.exists():
            pytest.skip("scripts/self-healing/watchdog.sh not found")
        return _read(script)

    @pytest.fixture(scope="class")
    def watchdog_compose_content(self):
        compose = REPO_ROOT / "deploy" / "compose" / "docker-compose.watchdog.yml"
        if not compose.exists():
            pytest.skip("deploy/compose/docker-compose.watchdog.yml not found")
        return _read(compose)

    @pytest.mark.parametrize(
        ("task_name", "expected_command"),
        EXPECTED_TASK_COMMANDS.items(),
    )
    def test_task_alias_maps_to_safe_command(self, task_name, expected_command, taskfile_content):
        assert task_name in taskfile_content
        assert expected_command in taskfile_content

    @pytest.mark.parametrize(
        ("case_pattern", "start_handler", "restart_handler"),
        [(key, value[0], value[1]) for key, value in EXPECTED_SCRIPT_CASES.items()],
    )
    def test_service_cases_use_validated_handlers(
        self,
        case_pattern,
        start_handler,
        restart_handler,
        deploy_script_content,
    ):
        assert case_pattern in deploy_script_content
        assert start_handler in deploy_script_content
        assert restart_handler in deploy_script_content

    def test_watchdog_prefers_managed_stack_restart_for_http_failures(self, watchdog_content):
        assert "prefer_managed_stack_restart() {" in watchdog_content
        assert "safe_restart_managed_stack \"$managed_stack\" \"$restart_target\" \"http-probe-${http_code}\"" in watchdog_content
        assert "safe_restart_managed_stack \"devtools\" \"${PLATFORM_PREFIX}-gitlab\" \"gitlab-app-health\"" in watchdog_content

    def test_devtools_start_restores_auth_prerequisite(self, deploy_script_content):
        assert 'log_warn "oauth2-auth middleware not found - starting auth services first"' in deploy_script_content
        assert 'start_auth || {' in deploy_script_content
        assert 'wait_for_middleware "oauth2-auth" 60 || {' in deploy_script_content

    def test_auth_start_restores_infra_prerequisites(self, deploy_script_content):
        assert 'log_warn "Core infrastructure not running - starting infrastructure first"' in deploy_script_content
        assert 'start_infra || {' in deploy_script_content
        assert 'wait_for_middleware "oauth2-auth" 60 || {' in deploy_script_content

    def test_watchdog_prefers_hermes_before_agent_service_fallback(self, watchdog_content):
        assert "collect_incident_evidence() {" in watchdog_content
        assert "dispatch_hermes_resolution() {" in watchdog_content
        assert "sync_watchdog_incident() {" in watchdog_content
        assert 'log "AGENT: Hermes requested escalation to agent-service"' in watchdog_content
        assert '"container_unhealthy"' in watchdog_content
        assert '"Monitored container ${container} is not running or reports unhealthy state. Diagnose the failure, collect evidence, and perform the safest remediation."' in watchdog_content

    def test_watchdog_compose_mounts_repo_and_hermes_home(self, watchdog_compose_content):
        assert "python3" in watchdog_compose_content
        assert "WATCHDOG_HOST_PLATFORM_ROOT" in watchdog_compose_content
        assert "WATCHDOG_HOST_HERMES_HOME" in watchdog_compose_content
        assert "WATCHDOG_HOST_UV_PYTHON_ROOT" in watchdog_compose_content
        assert "WATCHDOG_HERMES_HELPER_IMAGE" in watchdog_compose_content
        assert "HERMES_BIN" in watchdog_compose_content
        assert "- ${WATCHDOG_HOST_PLATFORM_ROOT:-/home/axelofwar/Projects/shml-platform}:${WATCHDOG_HOST_PLATFORM_ROOT:-/home/axelofwar/Projects/shml-platform}" in watchdog_compose_content
        assert "- ${WATCHDOG_HOST_HERMES_HOME:-/home/axelofwar/.hermes}:${WATCHDOG_HOST_HERMES_HOME:-/home/axelofwar/.hermes}" in watchdog_compose_content
        assert "- ${WATCHDOG_HOST_UV_PYTHON_ROOT:-/home/axelofwar/.local/share/uv}:${WATCHDOG_HOST_UV_PYTHON_ROOT:-/home/axelofwar/.local/share/uv}:ro" in watchdog_compose_content

    def test_oauth2_proxy_uses_core_redis_service_name(self):
        auth_compose = REPO_ROOT / "deploy" / "compose" / "docker-compose.auth.yml"
        if not auth_compose.exists():
            pytest.skip("deploy/compose/docker-compose.auth.yml not found")

        content = _read(auth_compose)
        assert "redis://redis:6379" in content
        assert "redis://shml-redis:6379" not in content


class TestWorkspaceTerminalConfig:
    """Workspace terminal settings must avoid fragile terminal revival behavior."""

    @pytest.fixture(scope="class")
    def vscode_settings_content(self):
        settings = REPO_ROOT / ".vscode" / "settings.json"
        if not settings.exists():
            pytest.skip(".vscode/settings.json not found")
        return _read(settings)

    def test_workspace_disables_terminal_persistent_sessions(self, vscode_settings_content):
        assert '"terminal.integrated.enablePersistentSessions": false' in vscode_settings_content

    def test_workspace_uses_explicit_bash_path(self, vscode_settings_content):
        assert '"terminal.integrated.profiles.linux"' in vscode_settings_content
        assert '"path": "/usr/bin/bash"' in vscode_settings_content


class TestComposeWarningGuards:
    """Compose files should avoid known warning regressions during restarts."""

    EXPECTED_GITLAB_RUNNER_TOKENS = [
        "${GITLAB_PLATFORM_RUNNER_REGISTRATION_TOKEN:-}",
        "${GITLAB_ROBOTICS_RUNNER_REGISTRATION_TOKEN:-}",
        "${GITLAB_TRAINING_RUNNER_REGISTRATION_TOKEN:-}",
    ]

    EXPECTED_GITLAB_RUNNER_SERVICES = [
        "gitlab-runner-platform:",
        "gitlab-runner-robotics:",
        "gitlab-runner-training:",
    ]

    EXPECTED_GITLAB_RUNNER_VOLUMES = [
        "gitlab-runner-platform-config:",
        "gitlab-runner-robotics-config:",
        "gitlab-runner-training-config:",
    ]

    @pytest.fixture(scope="class")
    def ray_compose_content(self):
        path = REPO_ROOT / "ray_compute" / "docker-compose.yml"
        if not path.exists():
            pytest.skip("ray_compute/docker-compose.yml not found")
        return _read(path)

    @pytest.fixture(scope="class")
    def infra_compose_content(self):
        path = REPO_ROOT / "deploy" / "compose" / "docker-compose.infra.yml"
        if not path.exists():
            pytest.skip("deploy/compose/docker-compose.infra.yml not found")
        return _read(path)

    @pytest.fixture(scope="class")
    def devtools_compose_content(self):
        path = REPO_ROOT / "deploy" / "compose" / "docker-compose.devtools.yml"
        if not path.exists():
            pytest.skip("deploy/compose/docker-compose.devtools.yml not found")
        return _read(path)

    @pytest.fixture(scope="class")
    def tracing_compose_content(self):
        path = REPO_ROOT / "deploy" / "compose" / "docker-compose.tracing.yml"
        if not path.exists():
            pytest.skip("deploy/compose/docker-compose.tracing.yml not found")
        return _read(path)

    @pytest.fixture(scope="class")
    def logging_compose_content(self):
        path = REPO_ROOT / "deploy" / "compose" / "docker-compose.logging.yml"
        if not path.exists():
            pytest.skip("deploy/compose/docker-compose.logging.yml not found")
        return _read(path)

    @pytest.fixture(scope="class")
    def monitoring_compose_content(self):
        path = REPO_ROOT / "deploy" / "compose" / "docker-compose.monitoring.yml"
        if not path.exists():
            pytest.skip("deploy/compose/docker-compose.monitoring.yml not found")
        return _read(path)

    def test_ray_compose_uses_canonical_fusionauth_cicd_keys(self, ray_compose_content):
        assert "CICD_ADMIN_KEY=${FUSIONAUTH_CICD_SUPER_KEY}" in ray_compose_content
        assert "CICD_DEVELOPER_KEY=${FUSIONAUTH_CICD_DEVELOPER_KEY}" in ray_compose_content
        assert "CICD_ELEVATED_DEVELOPER_KEY=${FUSIONAUTH_CICD_ELEVATED_DEVELOPER_KEY}" in ray_compose_content
        assert "CICD_VIEWER_KEY=${FUSIONAUTH_CICD_VIEWER_KEY}" in ray_compose_content

    def test_ray_shared_volumes_are_external(self, ray_compose_content):
        assert "ray-data:\n    name: ${PLATFORM_PREFIX:-shml}-ray-data\n    external: true" in ray_compose_content
        assert "job-workspaces:\n    name: ${PLATFORM_PREFIX:-shml}-job-workspaces\n    external: true" in ray_compose_content

    @pytest.mark.parametrize(
        "compose_fixture",
        ["infra_compose_content", "devtools_compose_content"],
    )
    def test_gitlab_runner_registration_tokens_are_runtime_expanded(self, request, compose_fixture):
        content = request.getfixturevalue(compose_fixture)
        for token_var in self.EXPECTED_GITLAB_RUNNER_TOKENS:
            assert token_var in content

    @pytest.mark.parametrize(
        "compose_fixture",
        ["infra_compose_content", "devtools_compose_content"],
    )
    def test_gitlab_uses_dedicated_runner_services_and_volumes(self, request, compose_fixture):
        content = request.getfixturevalue(compose_fixture)
        for service_name in self.EXPECTED_GITLAB_RUNNER_SERVICES:
            assert service_name in content
        for volume_name in self.EXPECTED_GITLAB_RUNNER_VOLUMES:
            assert volume_name in content
        assert 'entrypoint: ["/bin/sh", "/scripts/platform/gitlab_runner_entrypoint.sh"]' in content
        assert "- ../../scripts:/scripts:ro" in content

    def test_tracing_compose_drops_obsolete_version_key(self, tracing_compose_content):
        assert not tracing_compose_content.lstrip().startswith("version:")

    def test_observability_compose_drops_obsolete_version_keys(self, logging_compose_content):
        assert not logging_compose_content.lstrip().startswith("version:")

    def test_observability_healthchecks_do_not_require_wget(self, tracing_compose_content, logging_compose_content):
        assert '["CMD", "/otelcol-contrib", "--version"]' in tracing_compose_content
        assert '["CMD", "promtail", "-version"]' in logging_compose_content

    def test_nightly_test_runner_mounts_repo_root(self, monitoring_compose_content, infra_compose_content):
        assert "- ../../:/workspace:ro" in monitoring_compose_content
        assert "- ../../:/workspace:ro" in infra_compose_content

    @pytest.mark.parametrize(
        "compose_fixture",
        ["infra_compose_content", "devtools_compose_content"],
    )
    def test_gitlab_uses_dedicated_postgres_16(self, request, compose_fixture):
        content = request.getfixturevalue(compose_fixture)
        assert "gitlab-postgres:\n    image: postgres:16-alpine" in content
        assert "gitlab_rails['db_host'] = 'gitlab-postgres'" in content
        assert "gitlab-postgres-data:" in content

    def test_infra_gitlab_depends_on_dedicated_postgres_and_redis(self, infra_compose_content):
        assert "depends_on:\n      gitlab-postgres:\n        condition: service_healthy\n      redis:\n        condition: service_healthy" in infra_compose_content

    def test_devtools_gitlab_depends_on_dedicated_postgres_only(self, devtools_compose_content):
        assert "depends_on:\n      gitlab-postgres:\n        condition: service_healthy" in devtools_compose_content
        assert "depends_on:\n      gitlab-postgres:\n        condition: service_healthy\n      redis:\n        condition: service_healthy" not in devtools_compose_content

    @pytest.mark.parametrize(
        "compose_fixture",
        ["infra_compose_content", "devtools_compose_content"],
    )
    def test_gitlab_backups_are_split_from_shared_postgres(self, request, compose_fixture):
        content = request.getfixturevalue(compose_fixture)
        assert "POSTGRES_DB: mlflow_db,ray_compute,inference,fusionauth,chat_api" in content
        assert "POSTGRES_DB: gitlab" in content
        assert "gitlab-postgres-backup:" in content
        assert "image: prodrigestivill/postgres-backup-local:16-alpine" in content

    def test_alertmanager_telegram_healthchecks_use_metrics_endpoint(self, monitoring_compose_content, infra_compose_content):
        assert "http://localhost:9087/metrics >/dev/null || exit 1" in monitoring_compose_content
        assert "http://localhost:9087/metrics >/dev/null || exit 1" in infra_compose_content

    def test_watchdog_suppresses_gitlab_restarts_for_postgres_version_mismatch(self):
        watchdog = _read(REPO_ROOT / "scripts" / "self-healing" / "watchdog.sh")
        assert 'GITLAB_UNHEALTHY_REASON="postgres-version-mismatch"' in watchdog
        assert 'if [[ "${GITLAB_UNHEALTHY_REASON}" == "postgres-version-mismatch" ]]; then' in watchdog
        assert 'restart suppressed' in watchdog

    def test_backup_helpers_route_gitlab_to_dedicated_postgres(self):
        backup_script = _read(REPO_ROOT / "scripts" / "deploy" / "backup.sh")
        assert 'postgres_container_for_db() {' in backup_script
        assert 'echo "${PLATFORM_PREFIX:-shml}-gitlab-postgres"' in backup_script
        assert 'postgres_admin_user_for_db() {' in backup_script
        assert 'echo "gitlab"' in backup_script


# ---------------------------------------------------------------------------
# T9.7: Coverage config exists
# ---------------------------------------------------------------------------


class TestCoverageConfig:
    """.coveragerc must exist and have a [run] source section."""

    def test_coveragerc_exists(self):
        assert (REPO_ROOT / ".coveragerc").exists()

    def test_coveragerc_has_run_section(self):
        content = _read(REPO_ROOT / ".coveragerc")
        assert "[run]" in content

    def test_coveragerc_includes_libs(self):
        content = _read(REPO_ROOT / ".coveragerc")
        assert "libs" in content


# ---------------------------------------------------------------------------
# T9.7: Grafana dashboard provisioning (G4 guard)
# ---------------------------------------------------------------------------


class TestGrafanaDashboards:
    """Grafana dashboard provisioning files must exist and be valid JSON."""

    DASHBOARD_ROOT = REPO_ROOT / "monitoring" / "grafana" / "dashboards"

    def test_mlflow_dashboard_exists(self):
        """G4: mlflow/ dashboard folder must contain at least one dashboard."""
        mlflow_dir = self.DASHBOARD_ROOT / "mlflow"
        jsons = list(mlflow_dir.glob("*.json"))
        assert len(jsons) >= 1, f"Expected ≥1 dashboard in {mlflow_dir}, found none"

    def test_mlflow_dashboard_valid_json(self):
        """Every JSON file in mlflow/ must be valid Grafana dashboard JSON."""
        import json

        mlflow_dir = self.DASHBOARD_ROOT / "mlflow"
        for fpath in mlflow_dir.glob("*.json"):
            with open(fpath) as f:
                d = json.load(f)
            assert "panels" in d, f"{fpath.name} missing 'panels' key"
            assert "uid" in d, f"{fpath.name} missing 'uid' key"
            assert "title" in d, f"{fpath.name} missing 'title' key"

    def test_dashboards_yml_has_mlflow_provider(self):
        """dashboards.yml must define an MLflow provider."""
        dashboards_yml = REPO_ROOT / "monitoring" / "grafana" / "dashboards.yml"
        if not dashboards_yml.exists():
            pytest.skip("dashboards.yml not found")
        content = _read(dashboards_yml)
        assert "mlflow" in content.lower(), "dashboards.yml must have an MLflow provider entry"

    def test_mlflow_datasource_in_grafana_config(self):
        """datasources.yml must reference the mlflow-metrics datasource."""
        datasources_yml = REPO_ROOT / "monitoring" / "grafana" / "datasources.yml"
        if not datasources_yml.exists():
            pytest.skip("datasources.yml not found")
        content = _read(datasources_yml)
        assert "mlflow-metrics" in content, "datasources.yml must define mlflow-metrics datasource"
