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


def aggregate(turns: list[TurnUsage], elapsed: float) -> Summary:
    total_cost = sum(compute_cost(t.model, t) for t in turns)
    total_input = sum(t.input_tokens + t.cache_read_tokens for t in turns)
    total_output = sum(t.output_tokens for t in turns)
    cache_read = sum(t.cache_read_tokens for t in turns)
    cache_hit_rate = (cache_read / total_input) if total_input > 0 else 0.0

    return Summary(
        total_cost=total_cost,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        cache_hit_rate=cache_hit_rate,
        total_elapsed=elapsed,
        turns=list(turns),
    )
