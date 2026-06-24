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


def _is_cn_wake_stop(entries: list[dict]) -> bool:
    """이 Stop 이 cache-necromancer auto-wake turn 에서 fire 됐는지 판정.

    cache-necromancer 의 wake 는 Stop hook 의 stderr ping 으로 Claude 를
    재기동하며(UserPromptSubmit 미경유), Claude Code 는 이 wake 를 transcript 에
    `type:user, isMeta:true`, content 에 `[cn:keepalive ...]` 를 포함한
    "Stop hook feedback" 엔트리로 기록한다. offset 윈도우의 가장 최근 user
    엔트리가 이 wake ping 이면, 이 Stop 은 실제 사용자 입력이 아니라 wake turn
    에서 fire 된 것 → emit 억제(직전 turn 토큰 재표시 방지).

    - isMeta 게이트 필수: 진짜 프롬프트에 우연히 같은 문자열이 들어가도 억제 X.
    - 마커는 `[cn:keepalive` 접두사로 한정 (`[cn:warn]` 등 다른 cn stderr 제외).
    """
    for e in reversed(entries):
        if e.get("type") != "user":
            continue
        if not e.get("isMeta"):
            return False  # 최근 user 엔트리가 진짜 프롬프트 → 정상 표시
        msg = e.get("message") or {}
        content = msg.get("content")
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        return "[cn:keepalive" in text
    return False


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
            collect_sub_tool_names,
            count_active_async_agents_from_file,
            extract_async_launches_from_file,
            find_sidechain_dir,
        )

        state = load_state(session_id)
        has_state = state is not None
        state = state or {}
        offset = int(state.get("offset", 0))
        started_at = float(state.get("started_at", time.time()))

        # offset 갱신 정책 (v0.6.4): on_stop은 offset을 절대 갱신하지 않는다.
        # offset의 유일한 갱신점은 on_user_prompt.py — 한 사용자 입력에 대한
        # last_summary가 메인의 모든 응답 turn + 모든 sub 결과를 누적해야 하기
        # 때문이다 (한 입력 = 한 누적 출력). 매 Stop은 user_prompt 시점부터의
        # entries를 반복 read하지만 dedupe(_dedupe_by_message_id)로 turn/sub
        # 중복은 발생하지 않는다. save_state 호출을 추가하지 말 것.

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

        # cache-necromancer auto-wake 로 발생한 Stop 은 사용자가 만든 turn 이
        # 아니라 시스템 잡음이다. early return 으로 aggregate/history/emit 모두
        # 건너뛰어 직전 실제 turn 의 토큰이 재표시되는 것을 막는다 (last_summary·
        # history 오염도 방지 — 의도된 동작).
        if _is_cn_wake_stop(entries):
            return 0

        # Async subagents: extracted from sidechain jsonl files when available.
        # `extract_async_launches_from_file` reads the full main jsonl (offset
        # ignored) so dispatches recorded in an earlier turn are still seen
        # when the current Stop fires from a later turn's `_read_tail`.
        async_subs = []
        sidechain_dir = find_sidechain_dir(transcript_path)
        if sidechain_dir is not None:
            launches = extract_async_launches_from_file(transcript_path)
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

        # Upgrade each sub's tools_used from coarse toolStats buckets to the
        # real tool names (incl MCP) recorded in its sidechain transcript.
        # Every sub (fg + async) writes `{session}/subagents/agent-{id}.jsonl`.
        # Missing/unreadable file → keep the bucket fallback.
        #
        # Async agents emit one SubagentUsage row per assistant line, all
        # sharing an agent_id; collect_sub_tool_names returns the agent-wide
        # tool list, so attribute it to the FIRST row only — otherwise every
        # row would repeat the same tools. (Foreground subs are 1 row/agent,
        # so this is a no-op for them.)
        if sidechain_dir is not None:
            enriched_agents: set[str] = set()
            for s in fg_subs + async_subs:
                if not s.agent_id or s.agent_id in enriched_agents:
                    continue
                enriched_agents.add(s.agent_id)
                real_tools = collect_sub_tool_names(sidechain_dir, s.agent_id)
                if real_tools:
                    s.tools_used = real_tools

        elapsed = max(0.0, time.time() - started_at)
        summary = aggregate(turns, elapsed=elapsed, subagents=fg_subs + async_subs)

        # Persist the just-computed Summary for downstream readers (verbose mode,
        # future inspection tools). Only save when we actually produced turns
        # (flush polling finished).
        if summary.turns:
            try:
                from lib.summary_store import save_last_summary
                save_last_summary(session_id, summary)
            except Exception:
                _log_error(f"[on_stop] save_last_summary: {traceback.format_exc()}")

            # /token-history (v0.8.0): persist history.jsonl entry. Same gate
            # as last_summary (only when turns exist). Failure here must NOT
            # break the existing emit / async early-return flow.
            try:
                # state is normalized to {} above (line 87) so dict-access is safe.
                pid = state.get("prompt_id")
                if pid:
                    from lib.history_store import append_or_update_history
                    from lib.parser import parse_transcript_for_history
                    transcript_entries_for_hist = parse_transcript_for_history(entries)

                    # Compute models_used + has_subagent_other_model
                    models_seen: list[str] = []
                    has_other = False
                    for t in summary.turns:
                        if t.model and t.model not in models_seen:
                            models_seen.append(t.model)
                        for s in t.subagents:
                            sm = getattr(s, "model", "")
                            if sm and sm != t.model:
                                has_other = True

                    from dataclasses import asdict
                    append_or_update_history(
                        session_id=session_id,
                        prompt_id=pid,
                        user_prompt_text=state.get("prompt_text", ""),
                        started_at=started_at,
                        ended_at=time.time(),
                        summary_dict=asdict(summary),
                        models_used=models_seen,
                        has_subagent_other_model=has_other,
                        transcript_entries=transcript_entries_for_hist,
                    )
            except Exception:
                _log_error(f"[on_stop] history_store: {traceback.format_exc()}")

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
        # 위에서 저장됐으므로 누적치는 보존된다. 모두 끝난 시점의 Stop에서 1번만 emit.
        # verbose는 "한 줄 요약 vs 상세 표"의 출력 형식 차이일 뿐 "언제 emit할지"에는
        # 영향 주지 않는다.
        # file-based로 jsonl 전체를 읽어 이전 turn의 dispatch도 본다 (윈도우 회귀 fix).
        if count_active_async_agents_from_file(transcript_path) > 0:
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
