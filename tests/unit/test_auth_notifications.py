"""
Tests for Auth Notification System (Phase 4)
=============================================

Tests webhook hooks configuration, notification script, FusionAuth webhook
config, Homer user management section, and compose env vars — all without
requiring running services.

Usage:
    pytest tests/unit/test_auth_notifications.py -v
"""

import json
import os
import stat
import subprocess

import pytest

_root = os.path.join(os.path.dirname(__file__), "..", "..")


# ===========================================================================
# Webhook Hooks Configuration Tests
# ===========================================================================


class TestWebhookHooks:
    """Verify webhook hooks.json includes FusionAuth registration hook."""

    @pytest.fixture
    def hooks(self):
        path = os.path.join(_root, "scripts", "webhook", "hooks.json")
        if not os.path.exists(path):
            pytest.skip("hooks.json not found")
        with open(path) as f:
            return json.load(f)

    def test_hooks_is_list(self, hooks):
        assert isinstance(hooks, list)

    def test_github_deploy_hook_exists(self, hooks):
        ids = [h["id"] for h in hooks]
        assert "github-deploy" in ids

    def test_fusionauth_registration_hook_exists(self, hooks):
        ids = [h["id"] for h in hooks]
        assert (
            "fusionauth-user-registration" in ids
        ), f"FusionAuth hook not found. Hook IDs: {ids}"

    def test_fusionauth_hook_has_correct_command(self, hooks):
        fa_hook = next(h for h in hooks if h["id"] == "fusionauth-user-registration")
        assert "notify_user_registration" in fa_hook["execute-command"]

    def test_fusionauth_hook_passes_user_fields(self, hooks):
        fa_hook = next(h for h in hooks if h["id"] == "fusionauth-user-registration")
        arg_names = [
            a.get("name", "") for a in fa_hook.get("pass-arguments-to-command", [])
        ]
        assert any("email" in n for n in arg_names), "Hook should pass user email"
        assert any("id" in n for n in arg_names), "Hook should pass user id"

    def test_fusionauth_hook_uses_webhook_secret(self, hooks):
        fa_hook = next(h for h in hooks if h["id"] == "fusionauth-user-registration")
        trigger = fa_hook.get("trigger-rule", {})
        match = trigger.get("match", {})
        assert "FUSIONAUTH_WEBHOOK_SECRET" in json.dumps(
            match
        ), "Hook should authenticate via FUSIONAUTH_WEBHOOK_SECRET"

    def test_health_hook_exists(self, hooks):
        ids = [h["id"] for h in hooks]
        assert "health" in ids

    def test_hooks_json_valid(self):
        """hooks.json should be valid JSON."""
        path = os.path.join(_root, "scripts", "webhook", "hooks.json")
        with open(path) as f:
            data = json.load(f)
        assert len(data) >= 3, "Expected at least 3 hooks (github, fusionauth, health)"


# ===========================================================================
# Notification Script Tests
# ===========================================================================


class TestNotificationScript:
    """Test the user registration notification script."""

    @pytest.fixture
    def script_path(self):
        path = os.path.join(_root, "scripts", "webhook", "notify_user_registration.sh")
        if not os.path.exists(path):
            pytest.skip("Notification script not found")
        return path

    def test_script_exists(self, script_path):
        assert os.path.exists(script_path)

    def test_script_is_executable(self, script_path):
        mode = os.stat(script_path).st_mode
        assert mode & stat.S_IXUSR, "Script should be executable by owner"

    def test_script_has_shebang(self, script_path):
        with open(script_path) as f:
            first_line = f.readline()
        assert first_line.startswith("#!/bin/bash"), "Script should have bash shebang"

    def test_script_uses_set_euo(self, script_path):
        with open(script_path) as f:
            content = f.read()
        assert (
            "set -euo pipefail" in content or "set -e" in content
        ), "Script should use strict mode"

    def test_script_sends_telegram(self, script_path):
        with open(script_path) as f:
            content = f.read()
        assert "send_telegram" in content
        assert "TELEGRAM_BOT_TOKEN" in content
        assert "TELEGRAM_CHAT_ID" in content
        assert "api.telegram.org" in content

    def test_script_logs_registration(self, script_path):
        with open(script_path) as f:
            content = f.read()
        assert "user_registrations.log" in content or "log" in content.lower()

    def test_script_includes_user_info_in_message(self, script_path):
        with open(script_path) as f:
            content = f.read()
        assert "USER_EMAIL" in content
        assert "USER_ID" in content

    def test_script_mentions_role_upgrade(self, script_path):
        """Script should tell admin how to upgrade user role."""
        with open(script_path) as f:
            content = f.read()
        assert "viewer" in content.lower(), "Should mention default viewer role"
        assert (
            "user-management" in content or "set-role" in content
        ), "Should include role upgrade instructions"

    def test_script_dry_run(self, script_path):
        """Script should run successfully with no Telegram credentials (no-op send)."""
        result = subprocess.run(
            [
                "bash",
                script_path,
                "test@example.com",
                "testuser",
                "fake-uuid-1234",
                "50a4dc27-test",
                "user.create",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            env={
                **os.environ,
                "TELEGRAM_BOT_TOKEN": "",
                "TELEGRAM_CHAT_ID": "",
            },
        )
        # Should exit 0 even without Telegram credentials (graceful degradation)
        assert result.returncode == 0, f"Script failed: {result.stderr}"


# ===========================================================================
# FusionAuth Webhook Configuration Tests
# ===========================================================================


class TestFusionAuthWebhookConfig:
    """Verify FusionAuth webhook JSON configuration."""

    @pytest.fixture
    def webhook_config(self):
        path = os.path.join(
            _root, "fusionauth", "webhooks", "user-registration-webhook.json"
        )
        if not os.path.exists(path):
            pytest.skip("FusionAuth webhook config not found")
        with open(path) as f:
            return json.load(f)

    def test_webhook_config_exists(self, webhook_config):
        assert "webhook" in webhook_config

    def test_webhook_listens_to_user_create(self, webhook_config):
        events = webhook_config["webhook"]["eventsEnabled"]
        assert events.get("user.create") is True

    def test_webhook_listens_to_registration_create(self, webhook_config):
        events = webhook_config["webhook"]["eventsEnabled"]
        assert events.get("user.registration.create") is True

    def test_webhook_does_not_listen_to_login(self, webhook_config):
        events = webhook_config["webhook"]["eventsEnabled"]
        assert events.get("user.loginSuccess") is False

    def test_webhook_url_points_to_deployer(self, webhook_config):
        url = webhook_config["webhook"]["url"]
        assert "webhook-deployer" in url
        assert "fusionauth-user-registration" in url

    def test_webhook_has_secret_header(self, webhook_config):
        headers = webhook_config["webhook"]["headers"]
        assert "X-FusionAuth-Webhook-Secret" in headers

    def test_webhook_has_timeout_config(self, webhook_config):
        wh = webhook_config["webhook"]
        assert wh["connectTimeout"] > 0
        assert wh["readTimeout"] > 0


# ===========================================================================
# Docker Compose Env Var Tests
# ===========================================================================


class TestComposeEnvVars:
    """Verify deploy/compose/docker-compose.infra.yml has required env vars for notifications."""

    @pytest.fixture
    def compose_content(self):
        path = os.path.join(_root, "deploy/compose/docker-compose.infra.yml")
        if not os.path.exists(path):
            pytest.skip("deploy/compose/docker-compose.infra.yml not found")
        with open(path) as f:
            return f.read()

    def test_webhook_deployer_has_fusionauth_secret(self, compose_content):
        assert "FUSIONAUTH_WEBHOOK_SECRET" in compose_content

    def test_webhook_deployer_has_telegram_vars(self, compose_content):
        assert "TELEGRAM_BOT_TOKEN" in compose_content
        assert "TELEGRAM_CHAT_ID" in compose_content

    def test_env_example_has_fusionauth_webhook_secret(self):
        path = os.path.join(_root, ".env.example")
        if not os.path.exists(path):
            pytest.skip(".env.example not found")
        with open(path) as f:
            content = f.read()
        assert "FUSIONAUTH_WEBHOOK_SECRET" in content


# ===========================================================================
# Homer User Management Section Tests
# ===========================================================================


class TestHomerUserManagement:
    """Verify Homer dashboard has user management section."""

    @pytest.fixture
    def homer_content(self):
        path = os.path.join(_root, "monitoring", "homer", "config.yml")
        if not os.path.exists(path):
            pytest.skip("Homer config not found")
        with open(path) as f:
            return f.read()

    def test_homer_has_user_management_section(self, homer_content):
        assert "User Management" in homer_content

    def test_homer_has_user_admin_link(self, homer_content):
        assert "User Admin" in homer_content
        assert "/auth/admin/user/" in homer_content

    def test_homer_has_role_assignments_link(self, homer_content):
        assert "Role Assignments" in homer_content

    def test_homer_has_webhook_notifications_link(self, homer_content):
        assert "Webhook Notifications" in homer_content
        assert "Telegram" in homer_content

    def test_homer_has_user_management_cli(self, homer_content):
        assert "user-management" in homer_content

    def test_homer_has_feature_platform_slo_dashboard(self, homer_content):
        assert "Feature Platform SLOs" in homer_content
        assert "feature-platform-slos" in homer_content
