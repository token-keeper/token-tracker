from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TurnUsage:
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    tools_used: list[dict] = field(default_factory=list)  # [{"name": str, "count": int}]
    timestamp_iso: str = ""
    message_id: str = ""
    index: int = 0  # set by aggregator
    started_at: float | None = None  # derived from timestamp_iso (epoch seconds)
    ended_at: float | None = None  # reserved; currently always None from JSONL
    # Agent tool_use ids issued by this turn — used by aggregator to match
    # SubagentUsage records back to their parent turn.
    agent_tool_use_ids: list[str] = field(default_factory=list)
    # Filled by aggregator: subagent runs whose tool_use_id matched this turn.
    subagents: list["SubagentUsage"] = field(default_factory=list)


@dataclass
class SubagentUsage:
    agent_type: str
    agent_id: str
    tool_use_id: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    model: str = ""
    total_duration_ms: int = 0
    started_at: float | None = None


def _iso_to_epoch(iso: str) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def parse_agent_tool_uses(entry: dict) -> list[tuple[str, str]]:
    """assistant 엔트리에서 (tool_use_id, subagent_type) 쌍을 모두 반환.

    assistant 라인이 아니거나 Agent tool_use 블록이 없으면 빈 리스트.
    `subagent_type`은 `input.subagent_type`에서, 없으면 빈 문자열로 둔다.
    이 헬퍼는 `parse_line`의 `agent_tool_use_ids` 수집과 sidechain 모듈의
    async 매핑이 같은 jsonl 구조 해석을 공유하도록 만든다.
    """
    if not isinstance(entry, dict):
        return []
    if entry.get("type") != "assistant":
        return []
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content") or []
    if not isinstance(content, list):
        return []

    pairs: list[tuple[str, str]] = []
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
        pairs.append((tu_id, str(sa_type)))
    return pairs


def parse_line(entry: dict) -> TurnUsage | None:
    if not isinstance(entry, dict):
        return None
    if entry.get("type") != "assistant":
        return None
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return None
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return None

    content = msg.get("content") or []
    raw_names = [
        blk.get("name", "")
        for blk in content
        if isinstance(blk, dict) and blk.get("type") == "tool_use"
    ]
    counter = Counter(name for name in raw_names if name)
    tools_used = [
        {"name": name, "count": count}
        for name, count in counter.items()
    ]
    agent_tool_use_ids = [tu_id for tu_id, _ in parse_agent_tool_uses(entry)]

    timestamp_iso = entry.get("timestamp", "")

    return TurnUsage(
        model=msg.get("model", ""),
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cache_creation_tokens=int(usage.get("cache_creation_input_tokens", 0)),
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
        tools_used=tools_used,
        timestamp_iso=timestamp_iso,
        message_id=str(msg.get("id", "")),
        started_at=_iso_to_epoch(timestamp_iso),
        agent_tool_use_ids=agent_tool_use_ids,
    )


def _extract_tool_use_id(entry: dict) -> str:
    """user 라인 message.content 에서 tool_result 블록의 tool_use_id 를 가져온다."""
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content") or []
    if not isinstance(content, list):
        return ""
    for blk in content:
        if isinstance(blk, dict) and blk.get("type") == "tool_result":
            tu_id = blk.get("tool_use_id")
            if isinstance(tu_id, str) and tu_id:
                return tu_id
    return ""


def parse_tool_result_for_agent(entry: dict) -> SubagentUsage | None:
    """foreground (sync) Agent tool 의 completed 결과를 SubagentUsage 로 변환.

    메인 jsonl 의 type=="user" 라인 중 toolUseResult 에 agentType + status=="completed"
    가 있는 라인만 처리한다. async_launched 등은 None.
    """
    if not isinstance(entry, dict):
        return None
    if entry.get("type") != "user":
        return None
    tur = entry.get("toolUseResult")
    if not isinstance(tur, dict):
        return None
    agent_type = tur.get("agentType")
    if not agent_type:
        return None
    if tur.get("status") != "completed":
        return None

    tool_use_id = _extract_tool_use_id(entry)
    agent_id = tur.get("agentId") or ""
    usage = tur.get("usage") if isinstance(tur.get("usage"), dict) else {}

    return SubagentUsage(
        agent_type=str(agent_type),
        agent_id=str(agent_id),
        tool_use_id=tool_use_id,
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cache_creation_tokens=int(usage.get("cache_creation_input_tokens", 0)),
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
        model="",
        total_duration_ms=int(tur.get("totalDurationMs", 0) or 0),
        started_at=_iso_to_epoch(entry.get("timestamp", "")),
    )


def parse_async_launch(entry: dict) -> tuple[str, str] | None:
    """async Agent tool 호출의 launch 라인에서 (tool_use_id, agent_id) 추출.

    메인 jsonl 의 type=="user" 라인 중 toolUseResult.status=="async_launched" 인 경우만.
    sidechain jsonl 매칭에 사용된다.
    """
    if not isinstance(entry, dict):
        return None
    if entry.get("type") != "user":
        return None
    tur = entry.get("toolUseResult")
    if not isinstance(tur, dict):
        return None
    if tur.get("status") != "async_launched":
        return None

    tool_use_id = _extract_tool_use_id(entry)
    agent_id = tur.get("agentId") or ""
    if not tool_use_id or not agent_id:
        return None
    return (tool_use_id, str(agent_id))


def parse_sidechain_assistant(
    entry: dict,
    agent_type: str,
    agent_id: str,
    tool_use_id: str,
) -> SubagentUsage | None:
    """sidechain jsonl 한 라인에서 SubagentUsage 추출.

    호출자가 해당 파일이 sidechain jsonl 임을 보장해야 한다 (isSidechain 검증 X).
    type=="assistant" 이고 message.usage 가 dict 일 때만 처리한다.
    """
    if not isinstance(entry, dict):
        return None
    if entry.get("type") != "assistant":
        return None
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return None
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return None

    return SubagentUsage(
        agent_type=agent_type,
        agent_id=agent_id,
        tool_use_id=tool_use_id,
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cache_creation_tokens=int(usage.get("cache_creation_input_tokens", 0)),
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
        model=str(msg.get("model", "")),
        total_duration_ms=0,
        started_at=_iso_to_epoch(entry.get("timestamp", "")),
    )
