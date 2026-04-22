from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TurnUsage:
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    tools_used: list[str] = field(default_factory=list)
    timestamp_iso: str = ""
    message_id: str = ""


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
    tools = [
        blk.get("name", "")
        for blk in content
        if isinstance(blk, dict) and blk.get("type") == "tool_use"
    ]

    return TurnUsage(
        model=msg.get("model", ""),
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cache_creation_tokens=int(usage.get("cache_creation_input_tokens", 0)),
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
        tools_used=tools,
        timestamp_iso=entry.get("timestamp", ""),
        message_id=str(msg.get("id", "")),
    )
