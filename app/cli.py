import argparse
import secrets
import sys
from pathlib import Path

import uvicorn


def _get_app_support_dir() -> Path:
    return Path.home() / "Library" / "Application Support" / "mt-butterfly"


def _get_env_path() -> Path:
    return _get_app_support_dir() / ".env"


def _clean_setup() -> None:
    env_path = _get_env_path()
    if env_path.exists():
        env_path.unlink()
        print(f"Removed: {env_path}")
    else:
        print("No config file found")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="mt-butterfly server")
    parser.add_argument("--token", "-t", help="AUTH_TOKEN (required if no config exists)")
    parser.add_argument("--workspaces-dir", "-w", help="WORKSPACES_DIR")
    parser.add_argument("--gmail-user", help="GMAIL_USER for email notifications")
    parser.add_argument("--gmail-password", help="GMAIL_APP_PASSWORD")
    parser.add_argument("--config", action="store_true", help="Force wizard to run")
    parser.add_argument("--clean-setup", action="store_true", help="Remove config and exit")
    return parser.parse_args()


def _env_has_valid_token() -> bool:
    env_path = _get_env_path()
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


def _run_wizard(args: argparse.Namespace) -> bool:
    force = args.config
    has_cli_token = bool(args.token)
    
    if not force and _env_has_valid_token():
        return False
    
    if not force and has_cli_token:
        _write_env_from_args(args)
        return False
    
    app_support = _get_app_support_dir()
    app_support.mkdir(parents=True, exist_ok=True)
    env_path = _get_env_path()
    
    print("=" * 50)
    print("mt-butterfly Setup Wizard")
    print("=" * 50)
    print()
    
    suggested_token = secrets.token_urlsafe(16)
    print(f"Generated AUTH_TOKEN: {suggested_token}")
    print("(You can use this or enter your own)")
    print()
    
    auth_token = args.token or input("AUTH_TOKEN [default: generated]: ").strip()
    if not auth_token:
        auth_token = suggested_token
    
    print()
    default_workspaces = str(Path.home() / "mt-butterfly")
    workspaces_dir = args.workspaces_dir or input(f"WORKSPACES_DIR [default: {default_workspaces}]: ").strip()
    if not workspaces_dir:
        workspaces_dir = default_workspaces
    
    print()
    print("Optional - Gmail configuration for email notifications:")
    gmail_user = args.gmail_user or input("GMAIL_USER [skip]: ").strip()
    gmail_app_password = ""
    if gmail_user:
        gmail_app_password = args.gmail_password or input("GMAIL_APP_PASSWORD: ").strip()
    
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


def _write_env_from_args(args: argparse.Namespace) -> None:
    app_support = _get_app_support_dir()
    app_support.mkdir(parents=True, exist_ok=True)
    env_path = _get_env_path()
    
    auth_token = args.token
    workspaces_dir = args.workspaces_dir or str(Path.home() / "mt-butterfly")
    gmail_user = args.gmail_user
    gmail_app_password = args.gmail_password
    
    env_content = f"""AUTH_TOKEN={auth_token}
WORKSPACES_DIR={workspaces_dir}
"""
    if gmail_user:
        env_content += f"GMAIL_USER={gmail_user}\n"
    if gmail_app_password:
        env_content += f"GMAIL_APP_PASSWORD={gmail_app_password}\n"
    
    env_path.write_text(env_content)
    Path(workspaces_dir).mkdir(parents=True, exist_ok=True)
    
    print(f"Configuration written to: {env_path}")
    print(f"Access URL: http://localhost:8000/?t={auth_token}")
    print()


def main():
    args = _parse_args()
    
    if args.clean_setup:
        _clean_setup()
        return
    
    _run_wizard(args)
    
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )


if __name__ == "__main__":
    main()
