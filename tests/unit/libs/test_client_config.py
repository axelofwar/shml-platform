from __future__ import annotations

from configparser import ConfigParser

from libs.client.shml import config as config_module


class TestLoadCredentialsFile:
    def test_returns_empty_when_credentials_file_is_missing(self, monkeypatch, tmp_path):
        credentials_file = tmp_path / "credentials"
        monkeypatch.setattr(config_module, "CREDENTIALS_FILE", credentials_file)

        assert config_module.load_credentials_file() == {}

    def test_returns_empty_when_profile_does_not_exist(self, monkeypatch, tmp_path):
        credentials_file = tmp_path / "credentials"
        credentials_file.write_text("[default]\napi_key = shml_default\n", encoding="utf-8")
        monkeypatch.setattr(config_module, "CREDENTIALS_FILE", credentials_file)

        assert config_module.load_credentials_file("dev") == {}

    def test_loads_selected_profile_values(self, monkeypatch, tmp_path):
        credentials_file = tmp_path / "credentials"
        credentials_file.write_text(
            "[default]\napi_key = shml_default\n"
            "[dev]\napi_key = shml_dev\nbase_url = http://dev.local\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(config_module, "CREDENTIALS_FILE", credentials_file)

        assert config_module.load_credentials_file("dev") == {
            "api_key": "shml_dev",
            "base_url": "http://dev.local",
        }


class TestSaveCredentials:
    def test_creates_credentials_file_and_sets_secure_permissions(self, monkeypatch, tmp_path):
        credentials_file = tmp_path / ".shml" / "credentials"
        monkeypatch.setattr(config_module, "CREDENTIALS_FILE", credentials_file)

        config_module.save_credentials(
            api_key="shml_key",
            base_url="http://localhost:9000",
            oauth_token="oauth-token",
            profile="dev",
        )

        parser = ConfigParser()
        parser.read(credentials_file)

        assert credentials_file.exists()
        assert oct(credentials_file.stat().st_mode & 0o777) == "0o600"
        assert dict(parser["dev"]) == {
            "api_key": "shml_key",
            "base_url": "http://localhost:9000",
            "oauth_token": "oauth-token",
        }

    def test_preserves_existing_profiles_when_updating_one_profile(self, monkeypatch, tmp_path):
        credentials_file = tmp_path / ".shml" / "credentials"
        credentials_file.parent.mkdir(parents=True)
        credentials_file.write_text(
            "[default]\napi_key = shml_default\n"
            "[dev]\napi_key = shml_old\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(config_module, "CREDENTIALS_FILE", credentials_file)

        config_module.save_credentials(base_url="http://dev.local", profile="dev")

        parser = ConfigParser()
        parser.read(credentials_file)

        assert parser["default"]["api_key"] == "shml_default"
        assert parser["dev"]["api_key"] == "shml_old"
        assert parser["dev"]["base_url"] == "http://dev.local"


class TestGetConfig:
    def test_prefers_constructor_arguments_over_env_and_credentials(self, monkeypatch):
        monkeypatch.setattr(
            config_module,
            "load_credentials_file",
            lambda profile: {
                "base_url": "http://file.local",
                "api_key": "file-key",
                "oauth_token": "file-token",
            },
        )
        monkeypatch.setenv("SHML_BASE_URL", "http://env.local")
        monkeypatch.setenv("SHML_API_KEY", "env-key")
        monkeypatch.setenv("SHML_OAUTH_TOKEN", "env-token")

        config = config_module.get_config(
            base_url="http://arg.local",
            api_key="arg-key",
            oauth_token="arg-token",
            profile="dev",
        )

        assert config == config_module.Config(
            base_url="http://arg.local",
            api_key="arg-key",
            oauth_token="arg-token",
            profile="dev",
        )

    def test_prefers_environment_over_credentials_file(self, monkeypatch):
        monkeypatch.setattr(
            config_module,
            "load_credentials_file",
            lambda profile: {
                "base_url": "http://file.local",
                "api_key": "file-key",
                "oauth_token": "file-token",
            },
        )
        monkeypatch.setenv("SHML_BASE_URL", "http://env.local")
        monkeypatch.setenv("SHML_API_KEY", "env-key")
        monkeypatch.delenv("SHML_OAUTH_TOKEN", raising=False)

        config = config_module.get_config(profile="env")

        assert config.base_url == "http://env.local"
        assert config.api_key == "env-key"
        assert config.oauth_token == "file-token"
        assert config.profile == "env"

    def test_falls_back_to_default_base_url_when_no_other_source_exists(self, monkeypatch):
        monkeypatch.setattr(config_module, "load_credentials_file", lambda profile: {})
        monkeypatch.delenv("SHML_BASE_URL", raising=False)
        monkeypatch.delenv("SHML_API_KEY", raising=False)
        monkeypatch.delenv("SHML_OAUTH_TOKEN", raising=False)
        monkeypatch.setattr(config_module, "DEFAULT_BASE_URL", "http://default.local")

        config = config_module.get_config()

        assert config == config_module.Config(
            base_url="http://default.local",
            api_key=None,
            oauth_token=None,
            profile="default",
        )
