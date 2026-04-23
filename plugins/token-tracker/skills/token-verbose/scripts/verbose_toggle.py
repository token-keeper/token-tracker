#!/usr/bin/env python3
from __future__ import annotations

import json
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


def _load_config(cfg_file: Path) -> dict:
    if cfg_file.exists():
        try:
            return json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_config(cfg_file: Path, cfg: dict) -> None:
    """Atomic write — write to a sibling tmp file then os.replace.
    Guarantees the reader (on_stop hook) never sees a partial / truncated file.
    """
    payload = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"
    tmp = cfg_file.with_suffix(cfg_file.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, cfg_file)


def _parse_arg(argv: list[str]) -> str | None:
    """Return 'on' / 'off' / '' (status query) / 'unknown'."""
    raw = argv[1] if len(argv) > 1 else ""
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


def main(argv: list[str]) -> int:
    plugin_root = _setup_sys_path()
    cfg_file = plugin_root / "config.json"

    try:
        from lib.i18n_loader import load_strings

        cfg = _load_config(cfg_file)
        lang = cfg.get("language", "en")
        strings = load_strings(lang)

        arg = _parse_arg(argv)

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

        cfg["verbose"] = new_value
        _write_config(cfg_file, cfg)

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
    sys.exit(main(sys.argv))
