"""Single owner of token-tracker config.json.

All reads and read-modify-write updates go through this module so we don't
clobber fields across concurrent writers (hook + toggle skills).
"""
from __future__ import annotations

import json
import os
from pathlib import Path


DEFAULTS: dict = {"language": "en", "verbose": False}

_ENV_TRUE = {"1", "true", "yes", "on"}
_ENV_FALSE = {"0", "false", "no", "off"}


def _config_path(plugin_root: Path) -> Path:
    return plugin_root / "config.json"


def load_config(plugin_root: Path) -> dict:
    path = _config_path(plugin_root)
    if not path.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)
    if not isinstance(data, dict):
        return dict(DEFAULTS)
    return data


def update_config(plugin_root: Path, patch: dict) -> dict:
    """Read current config, merge `patch`, write atomically. Returns merged dict.

    Raises OSError on write failure (callers handle UX).
    """
    merged = load_config(plugin_root)
    merged.update(patch)
    path = _config_path(plugin_root)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    try:
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    return merged


def get_language(cfg: dict) -> str:
    return cfg.get("language", DEFAULTS["language"])


def is_verbose(cfg: dict, env_value: str | None) -> bool:
    if env_value is not None:
        norm = env_value.strip().lower()
        if norm in _ENV_TRUE:
            return True
        if norm in _ENV_FALSE:
            return False
    return bool(cfg.get("verbose", DEFAULTS["verbose"]))
