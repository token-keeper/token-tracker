#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _setup_sys_path() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        root = Path(env)
    else:
        # scripts/verbose_toggle.py -> scripts -> token-verbose -> skills -> plugin root
        root = Path(__file__).resolve().parent.parent.parent.parent
    sys.path.insert(0, str(root))
    return root


def _parse_arg(raw: str) -> str:
    """Return 'on' / 'off' / '' (status query) / 'unknown'."""
    val = raw.strip().lower()
    if val == "":
        return ""
    if val in ("on", "1", "true", "yes"):
        return "on"
    if val in ("off", "0", "false", "no"):
        return "off"
    return "unknown"


def _log_error(msg: str) -> None:
    try:
        from lib.paths import log_dir
        (log_dir() / "error.log").open("a", encoding="utf-8").write(msg + "\n")
    except Exception:
        print(msg, file=sys.stderr)


def main() -> int:
    plugin_root = _setup_sys_path()

    try:
        from lib.config import load_config, update_config, get_language
        from lib.i18n_loader import load_strings

        cfg = load_config(plugin_root)
        lang = get_language(cfg)
        strings = load_strings(lang)

        arg = _parse_arg(os.environ.get("TOKEN_TRACKER_VERBOSE_ARG", ""))

        if arg == "unknown":
            print(strings["verbose_usage"])
            return 0

        current = bool(cfg.get("verbose", False))
        on_label = strings["verbose_on"]
        off_label = strings["verbose_off"]
        current_label = on_label if current else off_label

        if arg == "":
            print(strings["verbose_status"].format(state=current_label))
            return 0

        new_value = (arg == "on")
        if new_value == current:
            print(strings["verbose_no_change"].format(state=current_label))
            return 0

        update_config(plugin_root, {"verbose": new_value})

        new_label = on_label if new_value else off_label
        print(strings["verbose_changed"].format(
            from_state=current_label, to_state=new_label
        ))
        return 0
    except Exception:
        tb = traceback.format_exc()
        _log_error(f"[verbose_toggle.py] {tb}")
        print(tb, file=sys.stderr)
        try:
            from lib.i18n_loader import load_strings
            print(load_strings("en")["verbose_error"])
        except Exception:
            print("verbose toggle: unexpected error")
        return 0


if __name__ == "__main__":
    sys.exit(main())
