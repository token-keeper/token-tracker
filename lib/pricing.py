from __future__ import annotations

from lib.parser import TurnUsage


# Prices in USD per 1,000,000 tokens.
# Sources: Anthropic pricing page (retrieved 2026-04-22).
# Keys must match the "model" field observed in Claude Code JSONL transcripts.
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-7": {
        "input": 15.0,
        "output": 75.0,
        "cache_creation": 18.75,
        "cache_read": 1.5,
    },
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_creation": 3.75,
        "cache_read": 0.3,
    },
    "claude-haiku-4-5": {
        "input": 1.0,
        "output": 5.0,
        "cache_creation": 1.25,
        "cache_read": 0.1,
    },
}


def compute_cost(model: str, usage: TurnUsage) -> float:
    rates = PRICING.get(model)
    if rates is None:
        return 0.0
    per_mtok = 1_000_000.0
    return (
        usage.input_tokens * rates["input"] / per_mtok
        + usage.output_tokens * rates["output"] / per_mtok
        + usage.cache_creation_tokens * rates["cache_creation"] / per_mtok
        + usage.cache_read_tokens * rates["cache_read"] / per_mtok
    )


def is_known_model(model: str) -> bool:
    return model in PRICING
