from __future__ import annotations

import sys

from lib.parser import TurnUsage


# Prices in USD per 1,000,000 tokens.
# Source: https://platform.claude.com/docs/en/about-claude/pricing
# Fetched: 2026-05-03
# 회귀 fix: Opus 4.7은 4.5부터 단가가 1/3로 인하됐는데 우리는 옛 단가($15)를 박아둠.
#
# 가정:
# - prompt cache write는 5m / 1h 두 tier만 존재 (Anthropic 2년간 두 tier 유지).
#   30m/4h 등 새 tier 추가 시 PRICING 키 + parser + summary_store v4 bump 필요.
# - cache_read는 모든 tier 단가 동일 (5m/1h 모두 동일 cache_read 단가).
#   향후 분리되면 spec/회귀 재검토.
# - 단가 변경 시 tests/test_pricing.py의 절대값 회귀 가드 테스트
#   (test_pricing_opus_4_7_all_rates_absolute, test_pricing_sonnet_4_6_1h_..., test_pricing_haiku_4_5_1h_...)
#   도 같이 갱신. 안 갱신하면 정당한 단가 변경이 회귀로 오인됨.
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-7": {
        "input": 5.0,
        "output": 25.0,
        "cache_creation_5m": 6.25,
        "cache_creation_1h": 10.0,
        "cache_read": 0.50,
    },
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_creation_5m": 3.75,
        "cache_creation_1h": 6.0,
        "cache_read": 0.30,
    },
    "claude-haiku-4-5": {
        "input": 1.0,
        "output": 5.0,
        "cache_creation_5m": 1.25,
        "cache_creation_1h": 2.0,
        "cache_read": 0.10,
    },
}


_warned_unknown_models: set[str] = set()


def _resolve_rates(model: str) -> dict[str, float] | None:
    """Look up pricing for a model id.

    Claude Code often emits suffixed model ids like "claude-opus-4-7[1m]" or
    "claude-opus-4-7-20260101". Exact match first; fall back to longest-prefix
    match against known keys to handle these variants.
    """
    if model in PRICING:
        return PRICING[model]
    best: tuple[int, str] | None = None
    for key in PRICING:
        if model.startswith(key) and (best is None or len(key) > best[0]):
            best = (len(key), key)
    return PRICING[best[1]] if best else None


def compute_cost(model: str, usage: TurnUsage) -> float:
    """Compute USD cost for a usage record.

    Accepts any object exposing the token-count fields (`input_tokens`,
    `output_tokens`, `cache_creation_5m_tokens`, `cache_creation_1h_tokens`,
    `cache_read_tokens`) — both TurnUsage and SubagentUsage satisfy this
    duck-typed contract.
    """
    rates = _resolve_rates(model)
    if rates is None:
        # Silent $0 안전장치 — 미등록 모델 alias 발견 시 stderr 1회 경고
        if model not in _warned_unknown_models:
            _warned_unknown_models.add(model)
            sys.stderr.write(f"[token-tracker] unknown pricing model: {model}\n")
        return 0.0
    per_mtok = 1_000_000.0
    return (
        usage.input_tokens * rates["input"] / per_mtok
        + usage.output_tokens * rates["output"] / per_mtok
        + usage.cache_creation_5m_tokens * rates["cache_creation_5m"] / per_mtok
        + usage.cache_creation_1h_tokens * rates["cache_creation_1h"] / per_mtok
        + usage.cache_read_tokens * rates["cache_read"] / per_mtok
    )


def is_known_model(model: str) -> bool:
    return _resolve_rates(model) is not None


def effective_billing_model(sub_model: str, parent_model: str) -> str:
    """Pick the model id to bill a subagent's usage at.

    Returns ``sub_model`` when it's a known pricing key (exact or prefix match);
    otherwise falls back to ``parent_model``. This guards against unknown short
    aliases like ``"sonnet"`` from ``Agent(model="sonnet")`` dispatch — without
    this fallback, ``compute_cost("sonnet", sub)`` would silently return $0.
    """
    if sub_model and is_known_model(sub_model):
        return sub_model
    return parent_model
