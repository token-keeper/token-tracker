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

        # Claude Code sometimes fires Stop before the assistant line has been
        # flushed to the JSONL. Poll up to 500ms when the initial read yields
        # no assistant turns — total ≤500ms added to Stop latency worst-case.
        entries = _read_tail(transcript_path, offset)
        turns = [t for t in (parse_line(e) for e in entries) if t is not None]
        retries = 0
        while has_state and not turns and retries < 5:
            time.sleep(0.1)
            entries = _read_tail(transcript_path, offset)
            turns = [t for t in (parse_line(e) for e in entries) if t is not None]
            retries += 1

        if not has_state and not turns:
            return 0

        elapsed = max(0.0, time.time() - started_at)
        summary = aggregate(turns, elapsed=elapsed)

        # Persist the just-computed Summary so /token-detail can read it.
        # Only save when we actually produced turns (flush polling finished).
        if summary.turns:
            try:
                from lib.summary_store import save_last_summary
                save_last_summary(session_id, summary)
            except Exception:
                _log_error(f"[on_stop] save_last_summary: {traceback.format_exc()}")

        cfg = _load_config(plugin_root)
        lang = cfg.get("language", "en")
        msg = format_summary(summary, lang)

        # verbose: env가 whitelist 값이면 env가 config을 override. whitelist 외 값
        # (빈 문자열, "invalid" 등)은 env 무시하고 config 사용 — 오타로 설정이 덮여
        # 꺼지는 회귀 방지.
        env_v = os.environ.get("TOKEN_TRACKER_VERBOSE")
        env_norm = env_v.strip().lower() if env_v is not None else None
        if env_norm in ("1", "true", "yes", "on"):
            verbose = True
        elif env_norm in ("0", "false", "no", "off"):
            verbose = False
        else:
            verbose = bool(cfg.get("verbose", False))
        if verbose and summary.turns:
            from lib.detail_formatter import format_detail
            msg = msg + "\n" + format_detail(summary, lang)

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
