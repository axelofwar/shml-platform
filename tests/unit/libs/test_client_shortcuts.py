from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from libs.client.shml import shortcuts


class TestRaySubmit:
    def test_submits_with_direct_client_and_closes_it(self, monkeypatch):
        client = MagicMock()
        client.submit.return_value = {"job_id": "job-1"}
        monkeypatch.setattr(shortcuts, "Client", MagicMock(return_value=client))

        result = shortcuts.ray_submit(
            "print('hi')",
            key="shml-key",
            gpu=0.5,
            name="demo",
            timeout=4,
            queue="gpu",
        )

        assert result == {"job_id": "job-1"}
        shortcuts.Client.assert_called_once_with(api_key="shml-key")
        client.submit.assert_called_once_with(
            code="print('hi')",
            gpu=0.5,
            name="demo",
            timeout_hours=4,
            queue="gpu",
        )
        client.close.assert_called_once_with()

    def test_closes_original_and_impersonated_clients(self, monkeypatch):
        base_client = MagicMock()
        impersonated_client = MagicMock()
        impersonated_client.submit.return_value = {"job_id": "job-2"}
        base_client.impersonate.return_value = impersonated_client
        monkeypatch.setattr(shortcuts, "Client", MagicMock(return_value=base_client))

        result = shortcuts.ray_submit("print('hi')", impersonate="developer")

        assert result == {"job_id": "job-2"}
        base_client.impersonate.assert_called_once_with("developer")
        impersonated_client.close.assert_called_once_with()
        base_client.close.assert_called_once_with()


class TestShortcutContextManagers:
    def test_ray_status_uses_context_manager(self, monkeypatch):
        client = MagicMock()
        client.status.return_value = {"status": "running"}
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        monkeypatch.setattr(shortcuts, "Client", MagicMock(return_value=client))

        result = shortcuts.ray_status("job-123", key="shml-key")

        assert result == {"status": "running"}
        shortcuts.Client.assert_called_once_with(api_key="shml-key")
        client.status.assert_called_once_with("job-123")
        client.__exit__.assert_called_once()

    def test_ray_logs_uses_context_manager(self, monkeypatch):
        client = MagicMock()
        client.logs.return_value = "hello logs"
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        monkeypatch.setattr(shortcuts, "Client", MagicMock(return_value=client))

        result = shortcuts.ray_logs("job-123")

        assert result == "hello logs"
        client.logs.assert_called_once_with("job-123")

    def test_ray_cancel_uses_context_manager_and_passes_reason(self, monkeypatch):
        client = MagicMock()
        client.cancel.return_value = {"status": "cancelled"}
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        monkeypatch.setattr(shortcuts, "Client", MagicMock(return_value=client))

        result = shortcuts.ray_cancel("job-123", reason="user request")

        assert result == {"status": "cancelled"}
        client.cancel.assert_called_once_with("job-123", reason="user request")


def test_shml_package_raises_attribute_error_for_unknown_attribute():
    import libs.client.shml as shml

    with pytest.raises(AttributeError):
        getattr(shml, "missing_attribute")
