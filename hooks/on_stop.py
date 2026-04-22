#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path


def _setup_sys_path() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        root = Path(env)
    else:
        root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    return root


def _load_config(plugin_root: Path) -> dict:
    cfg_file = plugin_root / "config.json"
    if cfg_file.exists():
        try:
            return json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"language": "en", "verbose": False}


def _emit(system_message: str) -> None:
    json.dump(
        {"systemMessage": system_message, "continue": True}, sys.stdout
    )
    sys.stdout.flush()


def _log_error(msg: str) -> None:
    try:
        from lib.paths import log_dir
        log_file = log_dir() / "error.log"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _read_tail(transcript_path: str, offset: int) -> list[dict]:
    entries: list[dict] = []
    try:
        file_size = os.path.getsize(transcript_path)
        start = offset if 0 <= offset <= file_size else 0
        with open(transcript_path, "rb") as f:
            f.seek(start)
            data = f.read()
    except OSError:
        return []

    for raw in data.splitlines():
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def main() -> int:
    plugin_root = _setup_sys_path()
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
        session_id = hook_input.get("session_id")
        transcript_path = hook_input.get("transcript_path")
        if not session_id or not transcript_path:
            return 0

        from lib.state import load_state
        from lib.parser import parse_line
        from lib.aggregator import aggregate
        from lib.formatter import format_summary

        state = load_state(session_id)
        has_state = state is not None
        state = state or {}
        offset = int(state.get("offset", 0))
        started_at = float(state.get("started_at", time.time()))

        entries = _read_tail(transcript_path, offset)
        turns = [t for t in (parse_line(e) for e in entries) if t is not None]

        if not has_state and not turns:
            return 0

        elapsed = max(0.0, time.time() - started_at)
        summary = aggregate(turns, elapsed=elapsed)

        cfg = _load_config(plugin_root)
        lang = cfg.get("language", "en")
        msg = format_summary(summary, lang)
        _emit(msg)
    except Exception:
        _log_error(f"[on_stop] {traceback.format_exc()}")
        try:
            _emit("[token-tracker] error — see ~/.claude/plugins/token-tracker/log/error.log")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
