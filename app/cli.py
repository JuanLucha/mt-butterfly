import secrets
import sys
from pathlib import Path
from typing import Optional

import uvicorn


def _get_app_support_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "mt-butterfly"


def _env_file_exists() -> bool:
    app_support = _get_app_support_dir()
    env_path = app_support / ".env"
    if not env_path.exists():
        return False
    
    content = env_path.read_text()
    for line in content.splitlines():
        if line.strip() and not line.startswith("#"):
            key = line.split("=", 1)[0].strip()
            if key == "AUTH_TOKEN":
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value and value != "dev-token":
                    return True
    return False


def _run_wizard(force: bool = False) -> bool:
    if not force and _env_file_exists():
        return False
    
    app_support = _get_app_support_dir()
    app_support.mkdir(parents=True, exist_ok=True)
    env_path = app_support / ".env"
    
    print("=" * 50)
    print("mt-butterfly Setup Wizard")
    print("=" * 50)
    print()
    
    suggested_token = secrets.token_urlsafe(16)
    print(f"Generated AUTH_TOKEN: {suggested_token}")
    print("(You can use this or enter your own)")
    print()
    
    auth_token = input("AUTH_TOKEN [default: generated]: ").strip()
    if not auth_token:
        auth_token = suggested_token
    
    print()
    default_workspaces = str(Path.home() / "mt-butterfly")
    workspaces_dir = input(f"WORKSPACES_DIR [default: {default_workspaces}]: ").strip()
    if not workspaces_dir:
        workspaces_dir = default_workspaces
    
    print()
    print("Optional - Gmail configuration for email notifications:")
    gmail_user = input("GMAIL_USER [skip]: ").strip()
    gmail_app_password = ""
    if gmail_user:
        gmail_app_password = input("GMAIL_APP_PASSWORD: ").strip()
    
    env_content = f"""AUTH_TOKEN={auth_token}
WORKSPACES_DIR={workspaces_dir}
"""
    if gmail_user:
        env_content += f"GMAIL_USER={gmail_user}\n"
    if gmail_app_password:
        env_content += f"GMAIL_APP_PASSWORD={gmail_app_password}\n"
    
    env_path.write_text(env_content)
    Path(workspaces_dir).mkdir(parents=True, exist_ok=True)
    
    print()
    print("=" * 50)
    print(f"Configuration saved to: {env_path}")
    print("=" * 50)
    print()
    print(f"Access URL: http://localhost:8000/?t={auth_token}")
    print()
    print("Starting server...")
    print()
    
    return True


def main():
    force_config = "--config" in sys.argv
    _run_wizard(force=force_config)
    
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
