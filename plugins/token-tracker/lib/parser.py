from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TurnUsage:
    model: str
    input_tokens: int
    output_tokens: int
    # 제거: cache_creation_tokens
    # 신규 — default와 fallback의 1h 값(0)은 동일. 5m 값은 의미 다름:
    #   default=값 없음, fallback=legacy 합산값을 5m로 매핑한 양수일 수 있음.
    cache_creation_5m_tokens: int = 0
    cache_creation_1h_tokens: int = 0
    cache_read_tokens: int = 0
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
    tool_use_id: str
    input_tokens: int
    output_tokens: int
    # 제거: cache_creation_tokens
    cache_creation_5m_tokens: int = 0
    cache_creation_1h_tokens: int = 0
    cache_read_tokens: int = 0
    total_duration_ms: int = 0
    # Model used by this subagent run. Sources (in priority order):
    #   1. async sub: sidechain jsonl `assistant.message.model` (most accurate)
    #   2. foreground sub: main jsonl Agent `tool_use.input.model` (only when
    #      caller dispatched with `model:` explicitly)
    #   3. unknown: empty string → aggregator falls back to parent turn model
    model: str = ""


def _iso_to_epoch(iso: str) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def parse_agent_tool_uses(entry: dict) -> list[tuple[str, str, str]]:
    """assistant 엔트리에서 (tool_use_id, subagent_type, model) 트리플을 모두 반환.

    assistant 라인이 아니거나 Agent tool_use 블록이 없으면 빈 리스트.
    `subagent_type`은 `input.subagent_type`에서, `model`은 `input.model`에서.
    둘 다 없으면 빈 문자열. `model`은 caller가 dispatch 시 명시한 경우만
    채워지며, async sub은 sidechain의 `message.model`이 더 정확하므로
    여기서 채운 값은 fallback용이다.
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

    triples: list[tuple[str, str, str]] = []
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
        model = inp.get("model") or ""
        triples.append((tu_id, str(sa_type), str(model)))
    return triples


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

    # cache_creation tier 분리 추출 (spec §4)
    cc = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    cache_5m = int(cc.get("ephemeral_5m_input_tokens", 0))
    cache_1h = int(cc.get("ephemeral_1h_input_tokens", 0))
    if not cc:
        # fallback: 옛 entry는 합산값을 5m로 간주 (방향: underbill).
        # 진단 결과 이 path는 실전 dead code이지만 옛 fixture 호환 위해 유지.
        cache_5m = int(usage.get("cache_creation_input_tokens", 0))
        cache_1h = 0

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
    agent_tool_use_ids = [tu_id for tu_id, _, _ in parse_agent_tool_uses(entry)]

    timestamp_iso = entry.get("timestamp", "")

    return TurnUsage(
        model=msg.get("model", ""),
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cache_creation_5m_tokens=cache_5m,
        cache_creation_1h_tokens=cache_1h,
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
    usage = tur.get("usage") if isinstance(tur.get("usage"), dict) else {}

    return SubagentUsage(
        agent_type=str(agent_type),
        tool_use_id=tool_use_id,
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cache_creation_tokens=int(usage.get("cache_creation_input_tokens", 0)),
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
        total_duration_ms=int(tur.get("totalDurationMs", 0) or 0),
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
        tool_use_id=tool_use_id,
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cache_creation_tokens=int(usage.get("cache_creation_input_tokens", 0)),
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
        total_duration_ms=0,
        model=str(msg.get("model", "")),
    )
