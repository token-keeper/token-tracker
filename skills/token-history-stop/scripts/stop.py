#!/usr/bin/env python3
"""token-history HTTP daemon stop 진입점."""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _setup_sys_path() -> None:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        root = Path(env)
    else:
        # scripts/stop.py -> scripts -> token-history-stop -> skills -> plugin root
        root = Path(__file__).resolve().parent.parent.parent.parent
    sys.path.insert(0, str(root))


def main(argv: list[str]) -> int:
    _setup_sys_path()
    try:
        from lib.http_server import stop
        n = stop()
        if n > 0:
            print(f"token-history server stopped ({n} process)")
        else:
            print("no server running")
        return 0
    except Exception:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
