from __future__ import annotations

from dataclasses import dataclass, field

from lib.parser import TurnUsage
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


def aggregate(turns: list[TurnUsage], elapsed: float) -> Summary:
    unique = _dedupe_by_message_id(turns)
    total_cost = sum(compute_cost(t.model, t) for t in unique)
    # Include cache_creation in the input-side total so displayed "toks" matches
    # what the cost number actually bills for (otherwise a big cache warmup
    # shows tiny toks with a large cost, which looks wrong).
    total_input = sum(
        t.input_tokens + t.cache_creation_tokens + t.cache_read_tokens
        for t in unique
    )
    total_output = sum(t.output_tokens for t in unique)
    cache_read = sum(t.cache_read_tokens for t in unique)
    cache_hit_rate = (cache_read / total_input) if total_input > 0 else 0.0

    return Summary(
        total_cost=total_cost,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        cache_hit_rate=cache_hit_rate,
        total_elapsed=elapsed,
        turns=unique,
    )
