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
        from lib.parser import (
            parse_agent_tool_uses,
            parse_line,
            parse_tool_result_for_agent,
        )
        from lib.aggregator import aggregate
        from lib.formatter import format_summary
        from lib.sidechain import (
            collect_sidechain_subagents,
            count_active_async_agents,
            extract_async_launches,
            find_sidechain_dir,
        )

        state = load_state(session_id)
        has_state = state is not None
        state = state or {}
        offset = int(state.get("offset", 0))
        started_at = float(state.get("started_at", time.time()))

        # Claude Code sometimes fires Stop before the assistant line — or its
        # subagent tool_result line — has been flushed to the JSONL. Poll up to
        # 500ms (5×100ms) until BOTH conditions are satisfied:
        #   1. at least one assistant turn is readable, AND
        #   2. every Agent tool_use_id from those turns has a matching fg sub
        #      tool_result line (status=="completed").
        # Async (sidechain) subagents are handled separately and may legitimately
        # be missing from the main jsonl — they are not part of this gate.
        def _read_state() -> tuple[list, list, list]:
            ents = _read_tail(transcript_path, offset)
            tns = [t for t in (parse_line(e) for e in ents) if t is not None]
            fgs = [
                s for s in (parse_tool_result_for_agent(e) for e in ents) if s is not None
            ]
            return ents, tns, fgs

        def _missing_fg_match(tns, fgs) -> bool:
            expected = {tu for t in tns for tu in t.agent_tool_use_ids}
            if not expected:
                return False
            matched = {s.tool_use_id for s in fgs}
            return bool(expected - matched)

        entries, turns, fg_subs = _read_state()
        retries = 0
        while (
            has_state
            and retries < 5
            and (not turns or _missing_fg_match(turns, fg_subs))
        ):
            time.sleep(0.1)
            entries, turns, fg_subs = _read_state()
            retries += 1

        if not has_state and not turns:
            return 0

        # Async subagents: extracted from sidechain jsonl files when available.
        async_subs = []
        sidechain_dir = find_sidechain_dir(transcript_path)
        if sidechain_dir is not None:
            launches = extract_async_launches(entries)
            if launches:
                async_subs = collect_sidechain_subagents(sidechain_dir, launches)

        # Foreground subs only have model info on the dispatching tool_use line.
        # Walk every assistant entry once, build {tool_use_id: model}, and fill
        # any fg_sub whose model is still empty.
        tu_to_model: dict[str, str] = {}
        for e in entries:
            for tu_id, _t, model in parse_agent_tool_uses(e):
                if model and tu_id not in tu_to_model:
                    tu_to_model[tu_id] = model
        for s in fg_subs:
            if not s.model and s.tool_use_id in tu_to_model:
                s.model = tu_to_model[s.tool_use_id]

        elapsed = max(0.0, time.time() - started_at)
        summary = aggregate(turns, elapsed=elapsed, subagents=fg_subs + async_subs)

        # Persist the just-computed Summary so /token-detail can read it.
        # Only save when we actually produced turns (flush polling finished).
        if summary.turns:
            try:
                from lib.summary_store import save_last_summary
                save_last_summary(session_id, summary)
            except Exception:
                _log_error(f"[on_stop] save_last_summary: {traceback.format_exc()}")

        from lib.config import load_config, get_language, is_verbose

        cfg = load_config(plugin_root)
        lang = get_language(cfg)
        verbose = is_verbose(cfg, os.environ.get("TOKEN_TRACKER_VERBOSE"))
        msg = format_summary(summary, lang)

        if verbose and summary.turns:
            from lib.detail_formatter import format_detail
            msg = msg + "\n" + format_detail(summary, lang)

        # Async background dispatch UX (옵션 D): 활성 background agent가 1개라도
        # 있으면 매 Stop마다 끼어드는 출력을 silent 처리. last_summary는 이미
        # 위에서 저장됐으므로 사용자가 /token-detail로 누적치 확인 가능. 모두
        # 끝난 시점의 Stop에서 1번만 emit. verbose는 "한 줄 요약 vs 상세 표"의
        # 출력 형식 차이일 뿐 "언제 emit할지"에는 영향 주지 않는다.
        if count_active_async_agents(entries) > 0:
            return 0

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
