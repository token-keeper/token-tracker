from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from lib import paths


def _state_path(session_id: str) -> Path:
    return paths.state_dir() / f"{session_id}.json"


def save_state(session_id: str, data: dict) -> None:
    target = _state_path(session_id)
    fd, tmp = tempfile.mkstemp(
        prefix=".tmp-", suffix=".json", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, target)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_state(session_id: str) -> dict | None:
    target = _state_path(session_id)
    if not target.exists():
        return None
    try:
        with target.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
