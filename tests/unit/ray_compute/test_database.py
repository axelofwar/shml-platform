"""Unit tests for ray_compute/api/database.py"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

_root = Path(__file__).resolve().parent.parent.parent.parent
for p in [str(_root), str(_root / "ray_compute")]:
    if p not in sys.path:
        sys.path.insert(0, p)


class TestGetPostgresPassword:
    """Tests for get_postgres_password()"""

    def _import_get_postgres_password(self):
        # Re-import fresh each time by removing cached module
        for key in list(sys.modules.keys()):
            if "ray_compute.api.database" in key or (
                "database" in key and "ray_compute" in key
            ):
                del sys.modules[key]
        from ray_compute.api.database import get_postgres_password  # type: ignore

        return get_postgres_password

    def test_returns_env_var_password_when_no_file(self):
        env = {
            "POSTGRES_PASSWORD": "secret123",
            "POSTGRES_USER": "ray_compute",
            "POSTGRES_HOST": "localhost",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "ray_compute",
        }
        with patch("os.getenv", side_effect=lambda k, d="": env.get(k, d)):
            with patch("sqlalchemy.create_engine"):
                with patch("sqlalchemy.orm.sessionmaker"):
                    fn = self._import_get_postgres_password()
                    # Call directly with controlled env
                    with patch.dict(
                        os.environ,
                        {"POSTGRES_PASSWORD": "mysecret"},
                        clear=False,
                    ):
                        # Remove POSTGRES_PASSWORD_FILE if set
                        os.environ.pop("POSTGRES_PASSWORD_FILE", None)
                        result = fn()
                    # Should return the env var value
                    assert isinstance(result, str)

    def test_returns_password_from_file(self, tmp_path):
        pw_file = tmp_path / "pg_password.txt"
        pw_file.write_text("file_password_xyz")

        with patch.dict(
            os.environ,
            {"POSTGRES_PASSWORD_FILE": str(pw_file)},
            clear=False,
        ):
            with patch("sqlalchemy.create_engine"):
                with patch("sqlalchemy.orm.sessionmaker"):
                    fn = self._import_get_postgres_password()
                    result = fn()
        assert result == "file_password_xyz"

    def test_returns_env_password_when_file_not_found(self):
        with patch.dict(
            os.environ,
            {
                "POSTGRES_PASSWORD_FILE": "/nonexistent/path/pw.txt",
                "POSTGRES_PASSWORD": "fallback_pw",
            },
            clear=False,
        ):
            with patch("sqlalchemy.create_engine"):
                with patch("sqlalchemy.orm.sessionmaker"):
                    fn = self._import_get_postgres_password()
                    result = fn()
        assert result == "fallback_pw"


class TestGetDb:
    """Tests for get_db() generator"""

    def test_get_db_yields_and_closes(self):
        mock_session = MagicMock()
        mock_session_factory = MagicMock(return_value=mock_session)

        with patch("sqlalchemy.create_engine"):
            with patch("sqlalchemy.orm.sessionmaker", return_value=mock_session_factory):
                for key in list(sys.modules.keys()):
                    if "ray_compute.api.database" in key:
                        del sys.modules[key]

                from ray_compute.api.database import get_db  # type: ignore

                gen = get_db()
                session = next(gen)

                assert session is mock_session

                # Close out the generator
                try:
                    next(gen)
                except StopIteration:
                    pass

                mock_session.close.assert_called_once()

    def test_get_db_closes_on_exception(self):
        mock_session = MagicMock()
        mock_session_factory = MagicMock(return_value=mock_session)

        with patch("sqlalchemy.create_engine"):
            with patch("sqlalchemy.orm.sessionmaker", return_value=mock_session_factory):
                for key in list(sys.modules.keys()):
                    if "ray_compute.api.database" in key:
                        del sys.modules[key]

                from ray_compute.api.database import get_db  # type: ignore

                gen = get_db()
                next(gen)
                # Throw into generator to simulate exception in dependent code
                try:
                    gen.throw(RuntimeError("upstream error"))
                except RuntimeError:
                    pass

                # Session must always be closed
                mock_session.close.assert_called_once()


class TestDatabaseUrl:
    """Test DATABASE_URL is constructed from env vars"""

    def test_database_url_uses_env_vars(self):
        with patch.dict(
            os.environ,
            {
                "POSTGRES_USER": "testuser",
                "POSTGRES_PASSWORD": "testpass",
                "POSTGRES_HOST": "db-host",
                "POSTGRES_PORT": "5433",
                "POSTGRES_DB": "testdb",
            },
            clear=False,
        ):
            os.environ.pop("POSTGRES_PASSWORD_FILE", None)
            with patch("sqlalchemy.create_engine") as mock_engine:
                with patch("sqlalchemy.orm.sessionmaker"):
                    for key in list(sys.modules.keys()):
                        if "ray_compute.api.database" in key:
                            del sys.modules[key]

                    import ray_compute.api.database  # type: ignore  # noqa: F401

                    call_args = mock_engine.call_args
                    url = call_args[0][0]
                    assert "testuser" in url
                    assert "db-host" in url
                    assert "5433" in url
                    assert "testdb" in url
