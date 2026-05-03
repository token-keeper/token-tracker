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
        # scripts/detail.py -> scripts -> token-detail -> skills -> plugin root
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
        from lib.i18n_loader import load_strings
        from lib.summary_store import load_last_summary
        from lib.detail_formatter import format_detail

        from lib.config import load_config, get_language
        lang = get_language(load_config(plugin_root))
        strings = load_strings(lang)

        if not session_id:
            print(strings["err_no_state"])
            return 0

        summary = load_last_summary(session_id)

        if summary is None:
            # Distinguish "no file" from "file but unreadable/unsupported"
            from lib import paths
            candidate = paths.state_dir() / session_id / "last_summary.json"
            if not candidate.exists():
                print(strings["err_no_state"])
                return 0
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if data.get("schema_version") not in (3,):
                    print(strings["err_unsupported_schema"])
                    return 0
            except Exception:
                pass
            print(strings["err_parse"])
            return 0

        if not summary.turns:
            print(strings["err_empty_turns"])
            return 0

        print(format_detail(summary, lang))
        return 0
    except Exception:
        tb = traceback.format_exc()
        _log_error(f"[detail.py] {tb}")
        print(tb, file=sys.stderr)
        try:
            from lib.i18n_loader import load_strings
            print(load_strings("en")["err_parse"])
        except Exception:
            print("detail skill: unexpected error")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
