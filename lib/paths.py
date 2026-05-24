from __future__ import annotations

import os
from pathlib import Path


def plugin_root() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def _base_data_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / "plugins" / "token-tracker"


def state_dir() -> Path:
    d = _base_data_dir() / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir() -> Path:
    d = _base_data_dir() / "log"
    d.mkdir(parents=True, exist_ok=True)
    return d
