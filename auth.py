from pathlib import Path

import yaml

from config import USERS_FILE


def load_users() -> dict:
    if not USERS_FILE.is_file():
        raise FileNotFoundError(f"Missing {USERS_FILE}")
    with USERS_FILE.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def authenticate(email: str, password: str) -> dict | None:
    users = load_users()
    record = users.get(email.strip().lower())
    if not record:
        return None
    if (record.get("password") or "") != password:
        return None
    role = record.get("role")
    if role not in {"customer", "admin"}:
        return None
    return {"email": email.strip().lower(), "role": role}
