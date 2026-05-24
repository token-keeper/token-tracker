#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path


def _setup_sys_path() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        root = Path(env)
    else:
        # scripts/history.py -> scripts -> token-history -> skills -> plugin root
        root = Path(__file__).resolve().parent.parent.parent.parent
    sys.path.insert(0, str(root))
    return root


def _log_error(msg: str) -> None:
    try:
        from lib.paths import log_dir
        (log_dir() / "error.log").open("a", encoding="utf-8").write(msg + "\n")
    except Exception:
        print(msg, file=sys.stderr)


def main(argv: list[str]) -> int:
    plugin_root = _setup_sys_path()
    session_id = argv[1] if len(argv) > 1 else ""

    try:
        from lib.config import get_language, load_config
        from lib.history_store import load_session_history
        from lib.i18n_loader import load_strings
        from lib.http_server import ensure_server_running

        lang = get_language(load_config(plugin_root))
        strings = load_strings(lang)

        if not session_id:
            print(strings["no_data_message"])
            return 0

        # 데이터 존재 확인 (없으면 안 띄움)
        current = load_session_history(session_id)
        if not current:
            print(strings["no_data_message"])
            return 0

        # daemon 시작 (idempotent)
        ensure_server_running()

        url = f"http://127.0.0.1:8765/{session_id}"
        try:
            subprocess.run(["open", url], check=False)
        except FileNotFoundError:
            pass

        print(strings["opened_url"].format(url=url))
        return 0
    except Exception:
        tb = traceback.format_exc()
        _log_error(f"[history.py] {tb}")
        print(tb, file=sys.stderr)
        try:
            from lib.i18n_loader import load_strings
            print(load_strings("en")["no_data_message"])
        except Exception:
            print("token-history: unexpected error")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
