from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
import os
from platformdirs import user_data_dir


def _get_app_support_dir() -> Path:
    return Path(user_data_dir("mt-butterfly", appauthor=False))


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
    task_timeout_minutes: int = 30
    task_max_concurrent: int = 2
    task_run_retention_days: int = 30

    model_config = SettingsConfigDict(env_file=_get_env_files(), env_file_encoding="utf-8")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.database_url:
            app_support = _get_app_support_dir()
            self.database_url = f"sqlite+aiosqlite:///{app_support / 'mt-butterfly.db'}"


settings = Settings()
