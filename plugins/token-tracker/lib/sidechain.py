from __future__ import annotations

import json
from pathlib import Path

from lib.parser import (
    SubagentUsage,
    parse_async_launch,
    parse_sidechain_assistant,
)


def find_sidechain_dir(transcript_path: str) -> Path | None:
    """transcript_path 옆의 sidechain 디렉터리를 반환한다.

    예: ~/.claude/projects/{project}/{session_id}.jsonl
        → ~/.claude/projects/{project}/{session_id}/subagents
    실제 디렉터리가 존재하지 않으면 None.
    """
    if not transcript_path:
        return None
    try:
        path = Path(transcript_path)
    except (TypeError, ValueError):
        return None
    candidate = path.parent / path.stem / "subagents"
    if candidate.is_dir():
        return candidate
    return None


def extract_async_launches(
    entries: list[dict],
) -> dict[str, tuple[str, str]]:
    """메인 jsonl entries에서 async Agent 호출의 (tool_use_id, agent_type) 매핑을 만든다.

    1) assistant 라인의 Agent tool_use 블록에서 id → subagent_type 매핑을 모음.
    2) user 라인의 async_launched toolUseResult 에서 (tool_use_id, agent_id) 추출.
    3) 둘을 합쳐 {agent_id: (tool_use_id, agent_type)} 반환.

    agent_type 정보가 없으면 빈 문자열로 둔다.
    """
    # tool_use_id → agent_type
    type_by_tu_id: dict[str, str] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        if e.get("type") != "assistant":
            continue
        msg = e.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content") or []
        if not isinstance(content, list):
            continue
        for blk in content:
            if not isinstance(blk, dict):
                continue
            if blk.get("type") != "tool_use":
                continue
            if blk.get("name") != "Agent":
                continue
            tu_id = blk.get("id")
            if not isinstance(tu_id, str) or not tu_id:
                continue
            inp = blk.get("input") if isinstance(blk.get("input"), dict) else {}
            sa_type = inp.get("subagent_type") or ""
            type_by_tu_id[tu_id] = str(sa_type)

    # agent_id → (tool_use_id, agent_type)
    out: dict[str, tuple[str, str]] = {}
    for e in entries:
        pair = parse_async_launch(e)
        if pair is None:
            continue
        tool_use_id, agent_id = pair
        agent_type = type_by_tu_id.get(tool_use_id, "")
        out[agent_id] = (tool_use_id, agent_type)
    return out


def collect_sidechain_subagents(
    sidechain_dir: Path,
    launches: dict[str, tuple[str, str]],
) -> list[SubagentUsage]:
    """sidechain_dir 안의 agent-{agent_id}.jsonl 파일들을 파싱해 SubagentUsage 리스트 반환.

    각 파일의 type=="assistant" 라인을 모두 추출하므로 한 agent가 여러 turn을
    돌렸으면 그 수만큼 SubagentUsage가 생성된다. 파일 없거나 읽기 실패 시 silent skip.
    한 줄이 invalid JSON이면 그 줄만 skip하고 진행.
    """
    out: list[SubagentUsage] = []
    if not isinstance(sidechain_dir, Path):
        sidechain_dir = Path(sidechain_dir)
    for agent_id, (tool_use_id, agent_type) in launches.items():
        path = sidechain_dir / f"agent-{agent_id}.jsonl"
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    sub = parse_sidechain_assistant(
                        entry,
                        agent_type=agent_type,
                        agent_id=agent_id,
                        tool_use_id=tool_use_id,
                    )
                    if sub is not None:
                        out.append(sub)
        except OSError:
            continue
    return out
