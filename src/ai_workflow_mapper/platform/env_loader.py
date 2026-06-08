"""Load project .env into os.environ for local development."""

from __future__ import annotations

import os
from pathlib import Path


def find_project_root() -> Path:
    """Walk up from this file until pyproject.toml is found."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def _read_env_text(path: Path) -> str:
    """Read .env text, tolerating UTF-8 and UTF-16 (Windows Notepad default)."""
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    return raw.decode("utf-8")


def _load_env_manual(env_path: Path) -> bool:
    for line in _read_env_text(env_path).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    return True


def load_project_env() -> bool:
    """Load repo-root `.env` if present. Returns True when a file was loaded."""
    env_path = find_project_root() / ".env"
    if not env_path.is_file():
        return False

    try:
        from dotenv import dotenv_values

        values = dotenv_values(env_path, encoding="utf-8")
        if not any(values):
            values = dotenv_values(env_path, encoding="utf-16")
        for key, value in values.items():
            if key and value is not None and key not in os.environ:
                os.environ[key] = value
        return True
    except ImportError:
        return _load_env_manual(env_path)
    except UnicodeDecodeError:
        return _load_env_manual(env_path)
