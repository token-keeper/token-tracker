from __future__ import annotations

from dataclasses import dataclass, field

from lib.parser import SubagentUsage, TurnUsage
from lib.pricing import compute_cost


@dataclass
class Summary:
    total_cost: float
    total_input_tokens: int
    total_output_tokens: int
    cache_hit_rate: float
    total_elapsed: float
    turns: list[TurnUsage] = field(default_factory=list)


def _dedupe_by_message_id(turns: list[TurnUsage]) -> list[TurnUsage]:
    """Claude Code splits a single API response into multiple JSONL lines
    (one per content block: thinking, text, tool_use, etc.) but copies the
    same `usage` field into each. Count each unique message_id once.
    Turns without a message_id (old fixtures, malformed entries) are kept
    as-is since we cannot identify duplicates."""
    seen: set[str] = set()
    out: list[TurnUsage] = []
    for t in turns:
        if t.message_id:
            if t.message_id in seen:
                continue
            seen.add(t.message_id)
        out.append(t)
    return out


def _attach_subagents(
    turns: list[TurnUsage], subagents: list[SubagentUsage]
) -> None:
    """Match each SubagentUsage to its parent turn via tool_use_id.

    Builds an index `tool_use_id -> turn` from each turn's
    `agent_tool_use_ids`, then appends matching subagents into the turn's
    `subagents` list. Unmatched subagents are dropped silently (KISS) — they
    do not contribute to Summary totals.
    """
    index: dict[str, TurnUsage] = {}
    for t in turns:
        for tu_id in t.agent_tool_use_ids:
            if tu_id:
                index[tu_id] = t
    for sub in subagents:
        parent = index.get(sub.tool_use_id)
        if parent is not None:
            parent.subagents.append(sub)


def aggregate(
    turns: list[TurnUsage],
    elapsed: float,
    subagents: list[SubagentUsage] | None = None,
) -> Summary:
    unique = _dedupe_by_message_id(turns)
    for i, t in enumerate(unique):
        t.index = i

    if subagents:
        _attach_subagents(unique, subagents)

    # Per-turn main cost.
    total_cost = sum(compute_cost(t.model, t) for t in unique)
    # Subagent cost: bill against parent's model rates (D6) — sub.model may be
    # empty (foreground tool_result case) and even when present we currently
    # treat the parent model as the source of truth for billing.
    for t in unique:
        for sub in t.subagents:
            total_cost += compute_cost(t.model, sub)

    # Include cache_creation in the input-side total so displayed "toks" matches
    # what the cost number actually bills for (otherwise a big cache warmup
    # shows tiny toks with a large cost, which looks wrong).
    total_input = sum(
        t.input_tokens + t.cache_creation_tokens + t.cache_read_tokens
        for t in unique
    )
    total_output = sum(t.output_tokens for t in unique)
    cache_read = sum(t.cache_read_tokens for t in unique)

    # Add subagent contributions.
    for t in unique:
        for sub in t.subagents:
            total_input += (
                sub.input_tokens + sub.cache_creation_tokens + sub.cache_read_tokens
            )
            total_output += sub.output_tokens
            cache_read += sub.cache_read_tokens

    cache_hit_rate = (cache_read / total_input) if total_input > 0 else 0.0

    return Summary(
        total_cost=total_cost,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        cache_hit_rate=cache_hit_rate,
        total_elapsed=elapsed,
        turns=unique,
    )
