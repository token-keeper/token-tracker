from __future__ import annotations

import json
import re
from pathlib import Path

from lib.parser import (
    SubagentUsage,
    parse_agent_tool_uses,
    parse_async_launch,
    parse_sidechain_assistant,
)


# agent_id is interpolated into a filename (`agent-{agent_id}.jsonl`) and
# comes from the main jsonl, which is external input. Restrict to a safe
# alphabet so attackers can't inject `../` segments or absolute paths to read
# arbitrary files via the path traversal.
_SAFE_AGENT_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _is_safe_agent_id(agent_id: str) -> bool:
    return bool(isinstance(agent_id, str) and _SAFE_AGENT_ID.fullmatch(agent_id))


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
) -> dict[str, tuple[str, str, str]]:
    """메인 jsonl entries에서 async Agent 호출의 (tool_use_id, agent_type, model) 매핑.

    1) `parse_agent_tool_uses`로 모든 assistant 라인의 (id, subagent_type, model) 룩업.
    2) user 라인의 async_launched toolUseResult에서 (tool_use_id, agent_id) 추출.
    3) 둘을 합쳐 {agent_id: (tool_use_id, agent_type, model)} 반환.

    `model`은 caller가 dispatch 시 명시한 값(input.model). sidechain assistant의
    `message.model`이 더 정확하므로 이 값은 fallback 용도다.
    agent_type 정보가 없으면 빈 문자열.
    """
    # tool_use_id → (agent_type, model)
    info_by_tu_id: dict[str, tuple[str, str]] = {}
    for e in entries:
        for tu_id, sa_type, model in parse_agent_tool_uses(e):
            info_by_tu_id[tu_id] = (sa_type, model)

    # agent_id → (tool_use_id, agent_type, model)
    out: dict[str, tuple[str, str, str]] = {}
    for e in entries:
        pair = parse_async_launch(e)
        if pair is None:
            continue
        tool_use_id, agent_id = pair
        agent_type, model = info_by_tu_id.get(tool_use_id, ("", ""))
        out[agent_id] = (tool_use_id, agent_type, model)
    return out


def collect_sidechain_subagents(
    sidechain_dir: Path,
    launches: dict[str, tuple[str, str, str]],
) -> list[SubagentUsage]:
    """sidechain_dir 안의 agent-{agent_id}.jsonl 파일들을 파싱해 SubagentUsage 리스트 반환.

    각 파일의 type=="assistant" 라인을 모두 추출하므로 한 agent가 여러 turn을
    돌렸으면 그 수만큼 SubagentUsage가 생성된다. 파일 없거나 읽기 실패 시 silent skip.
    한 줄이 invalid JSON이면 그 줄만 skip하고 진행.

    `launches`의 model은 fallback용. sidechain assistant 라인이 자체 model을
    노출하면 그 값이 우선이고, 없을 때만 launches의 model로 채운다.
    """
    out: list[SubagentUsage] = []
    if not isinstance(sidechain_dir, Path):
        sidechain_dir = Path(sidechain_dir)
    sidechain_resolved = sidechain_dir.resolve()
    for agent_id, (tool_use_id, agent_type, fallback_model) in launches.items():
        # Path traversal guard: only allow safe filename characters.
        if not _is_safe_agent_id(agent_id):
            continue
        path = sidechain_dir / f"agent-{agent_id}.jsonl"
        if not path.is_file():
            continue
        # Symlink guard: refuse to follow links — they could point outside
        # sidechain_dir (e.g., to another user's files).
        if path.is_symlink():
            continue
        # Defense in depth: even with the regex + symlink check, ensure the
        # resolved path stays inside sidechain_dir.
        try:
            if not path.resolve().is_relative_to(sidechain_resolved):
                continue
        except (OSError, ValueError):
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
                        tool_use_id=tool_use_id,
                    )
                    if sub is not None:
                        # sidechain message.model wins; fall back to launch
                        # input.model only when sidechain didn't expose one.
                        if not sub.model and fallback_model:
                            sub.model = fallback_model
                        out.append(sub)
        except OSError:
            continue
    return out
