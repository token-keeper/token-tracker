import math

from lib import pricing
from lib.parser import SubagentUsage, TurnUsage


def test_known_model_cost_opus():
    u = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    cost = pricing.compute_cost("claude-opus-4-7", u)
    assert math.isclose(cost, 15.0, rel_tol=1e-6)


def test_cache_read_is_cheaper_than_input():
    u_cache = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=1_000_000,
    )
    u_input = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    assert pricing.compute_cost("claude-opus-4-7", u_cache) < pricing.compute_cost(
        "claude-opus-4-7", u_input
    )


def test_unknown_model_returns_zero():
    u = TurnUsage(
        model="claude-ghost-1",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    assert pricing.compute_cost("claude-ghost-1", u) == 0.0


def test_sonnet_known():
    u = TurnUsage(
        model="claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    assert pricing.compute_cost("claude-sonnet-4-6", u) == 3.0


def test_haiku_known():
    u = TurnUsage(
        model="claude-haiku-4-5",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    assert pricing.compute_cost("claude-haiku-4-5", u) > 0.0


def test_prefix_match_opus_with_context_suffix():
    """Claude Code emits ids like 'claude-opus-4-7[1m]' — should fall back to prefix match."""
    u = TurnUsage(
        model="claude-opus-4-7[1m]",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    assert math.isclose(pricing.compute_cost("claude-opus-4-7[1m]", u), 15.0, rel_tol=1e-6)


def test_prefix_match_sonnet_with_date_suffix():
    """Date-suffixed ids like 'claude-sonnet-4-6-20260101' should also resolve."""
    u = TurnUsage(
        model="claude-sonnet-4-6-20260101",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    assert pricing.compute_cost("claude-sonnet-4-6-20260101", u) == 3.0


def test_prefix_match_picks_longest_key():
    """If multiple keys prefix-match, pick the longest (most specific)."""
    from lib import pricing as p

    p.PRICING["claude-opus-4-7-turbo"] = {
        "input": 99.0,
        "output": 99.0,
        "cache_creation": 99.0,
        "cache_read": 99.0,
    }
    try:
        u = TurnUsage(
            model="claude-opus-4-7-turbo-2026",
            input_tokens=1_000_000,
            output_tokens=0,
            cache_creation_tokens=0,
            cache_read_tokens=0,
        )
        # Both "claude-opus-4-7" and "claude-opus-4-7-turbo" match; longer wins.
        assert math.isclose(p.compute_cost("claude-opus-4-7-turbo-2026", u), 99.0, rel_tol=1e-6)
    finally:
        del p.PRICING["claude-opus-4-7-turbo"]


def test_is_known_model_accepts_prefix():
    assert pricing.is_known_model("claude-opus-4-7[1m]") is True
    assert pricing.is_known_model("claude-unknown-x") is False


def test_compute_cost_accepts_subagent_usage():
    """compute_cost는 duck-typing으로 SubagentUsage도 처리해야 한다 (D6 부모 모델 단가 추정 경로).

    aggregator는 부모 turn 모델로 SubagentUsage를 합산해 비용을 산정한다 — TurnUsage와
    같은 4개 토큰 필드를 갖는 객체는 모두 동일한 결과를 내야 한다 (회귀 가드).
    """
    sub = SubagentUsage(
        agent_type="general-purpose",
        tool_use_id="toolu_xyz",
        input_tokens=1_000_000,
        output_tokens=500_000,
        cache_creation_tokens=0,
        cache_read_tokens=2_000_000,
    )
    turn = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=1_000_000,
        output_tokens=500_000,
        cache_creation_tokens=0,
        cache_read_tokens=2_000_000,
    )
    sub_cost = pricing.compute_cost("claude-opus-4-7", sub)
    turn_cost = pricing.compute_cost("claude-opus-4-7", turn)
    assert math.isclose(sub_cost, turn_cost, rel_tol=1e-9)
    # Sanity: 1M input * $15 + 0.5M output * $75 + 2M cache_read * $1.5 = 15 + 37.5 + 3 = 55.5
    assert math.isclose(sub_cost, 55.5, rel_tol=1e-9)
