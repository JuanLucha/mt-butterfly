from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
import os


def _get_app_support_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "mt-butterfly"


def _get_env_files() -> list[Path | str]:
    app_support = _get_app_support_dir()
    app_support.mkdir(parents=True, exist_ok=True)
    return [app_support / ".env", ".env"]


class Settings(BaseSettings):
    auth_token: str = "dev-token"
    workspaces_dir: str = "/tmp/mt-butterfly-workspaces"
    gmail_user: str = ""
    gmail_app_password: str = ""
    database_url: str = ""
    opencode_path: str = "opencode"

    model_config = SettingsConfigDict(env_file=_get_env_files(), env_file_encoding="utf-8")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.database_url:
            app_support = _get_app_support_dir()
            self.database_url = f"sqlite+aiosqlite:///{app_support / 'mt-butterfly.db'}"


settings = Settings()
