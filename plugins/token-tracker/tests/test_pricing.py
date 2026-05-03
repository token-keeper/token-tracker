import math

from lib import pricing
from lib.parser import SubagentUsage, TurnUsage


def test_known_model_cost_opus():
    u = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_tokens=0,
    )
    cost = pricing.compute_cost("claude-opus-4-7", u)
    # Opus 4.7 신단가 input = $5/MTok
    assert math.isclose(cost, 5.0, rel_tol=1e-6)


def test_cache_read_is_cheaper_than_input():
    u_cache = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=1_000_000,
    )
    u_input = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=1_000_000,
        output_tokens=0,
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
        cache_read_tokens=0,
    )
    assert pricing.compute_cost("claude-ghost-1", u) == 0.0


def test_sonnet_known():
    u = TurnUsage(
        model="claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_tokens=0,
    )
    assert pricing.compute_cost("claude-sonnet-4-6", u) == 3.0


def test_haiku_known():
    u = TurnUsage(
        model="claude-haiku-4-5",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_tokens=0,
    )
    assert pricing.compute_cost("claude-haiku-4-5", u) > 0.0


def test_prefix_match_opus_with_context_suffix():
    """Claude Code emits ids like 'claude-opus-4-7[1m]' — should fall back to prefix match."""
    u = TurnUsage(
        model="claude-opus-4-7[1m]",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_tokens=0,
    )
    # Opus 4.7 신단가 input = $5/MTok
    assert math.isclose(pricing.compute_cost("claude-opus-4-7[1m]", u), 5.0, rel_tol=1e-6)


def test_prefix_match_sonnet_with_date_suffix():
    """Date-suffixed ids like 'claude-sonnet-4-6-20260101' should also resolve."""
    u = TurnUsage(
        model="claude-sonnet-4-6-20260101",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_tokens=0,
    )
    assert pricing.compute_cost("claude-sonnet-4-6-20260101", u) == 3.0


def test_prefix_match_picks_longest_key():
    """If multiple keys prefix-match, pick the longest (most specific)."""
    from lib import pricing as p

    p.PRICING["claude-opus-4-7-turbo"] = {
        "input": 99.0,
        "output": 99.0,
        "cache_creation_5m": 99.0,
        "cache_creation_1h": 99.0,
        "cache_read": 99.0,
    }
    try:
        u = TurnUsage(
            model="claude-opus-4-7-turbo-2026",
            input_tokens=1_000_000,
            output_tokens=0,
            cache_read_tokens=0,
        )
        # Both "claude-opus-4-7" and "claude-opus-4-7-turbo" match; longer wins.
        assert math.isclose(p.compute_cost("claude-opus-4-7-turbo-2026", u), 99.0, rel_tol=1e-6)
    finally:
        del p.PRICING["claude-opus-4-7-turbo"]


def test_is_known_model_accepts_prefix():
    assert pricing.is_known_model("claude-opus-4-7[1m]") is True
    assert pricing.is_known_model("claude-unknown-x") is False


def test_effective_billing_model_prefers_known_sub_model():
    """sub.model이 알려진 정식 id면 sub 단가로 청구."""
    assert pricing.effective_billing_model(
        "claude-haiku-4-5", "claude-opus-4-7"
    ) == "claude-haiku-4-5"


def test_effective_billing_model_falls_back_when_sub_model_empty():
    """sub.model이 빈 문자열이면 부모 단가."""
    assert pricing.effective_billing_model("", "claude-opus-4-7") == "claude-opus-4-7"


def test_effective_billing_model_falls_back_when_sub_model_unknown_alias():
    """sub.model이 short alias 같은 unknown 값이면 silent $0이 아니라 부모 단가로 fallback.

    이게 v0.6.2의 silent $0 회귀 핵심 가드 — `Agent(model="sonnet")` 같은 alias는
    pricing 표에 없으므로 truthy하더라도 부모 단가로 떨어져야 한다.
    """
    assert pricing.effective_billing_model("sonnet", "claude-opus-4-7") == "claude-opus-4-7"
    assert pricing.effective_billing_model("haiku", "claude-opus-4-7") == "claude-opus-4-7"
    assert pricing.effective_billing_model("opus", "claude-opus-4-7") == "claude-opus-4-7"


def test_compute_cost_accepts_subagent_usage():
    """compute_cost는 duck-typing으로 SubagentUsage도 처리해야 한다 (D6 부모 모델 단가 추정 경로).

    aggregator는 부모 turn 모델로 SubagentUsage를 합산해 비용을 산정한다 — TurnUsage와
    같은 토큰 필드를 갖는 객체는 모두 동일한 결과를 내야 한다 (회귀 가드).
    """
    sub = SubagentUsage(
        agent_type="general-purpose",
        tool_use_id="toolu_xyz",
        input_tokens=1_000_000,
        output_tokens=500_000,
        cache_read_tokens=2_000_000,
    )
    turn = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=1_000_000,
        output_tokens=500_000,
        cache_read_tokens=2_000_000,
    )
    sub_cost = pricing.compute_cost("claude-opus-4-7", sub)
    turn_cost = pricing.compute_cost("claude-opus-4-7", turn)
    assert math.isclose(sub_cost, turn_cost, rel_tol=1e-9)
    # Sanity: Opus 4.7 신단가 — 1M input * $5 + 0.5M output * $25 + 2M cache_read * $0.50
    # = 5 + 12.5 + 1.0 = 18.5
    assert math.isclose(sub_cost, 18.5, rel_tol=1e-9)


def test_pricing_opus_4_7_all_rates_absolute():
    """Opus 4.7 단가 5개 절대값 가드 — 옛 단가($15/$75/$18.75/$1.5) 회귀 방지.
    단가 변경 시 같이 갱신 필요."""
    from lib.pricing import PRICING
    p = PRICING["claude-opus-4-7"]
    assert p["input"] == 5.0
    assert p["output"] == 25.0
    assert p["cache_creation_5m"] == 6.25
    assert p["cache_creation_1h"] == 10.0
    assert p["cache_read"] == 0.50


def test_pricing_sonnet_4_6_1h_is_6_dollars_per_mtok():
    from lib.pricing import PRICING
    assert PRICING["claude-sonnet-4-6"]["cache_creation_1h"] == 6.0
    assert PRICING["claude-sonnet-4-6"]["cache_creation_5m"] == 3.75


def test_pricing_haiku_4_5_1h_is_2_dollars_per_mtok():
    from lib.pricing import PRICING
    assert PRICING["claude-haiku-4-5"]["cache_creation_1h"] == 2.0
    assert PRICING["claude-haiku-4-5"]["cache_creation_5m"] == 1.25


def test_pricing_1h_more_expensive_than_5m_for_all_models():
    """tier 분리 누락 회귀 가드 — 1h가 5m보다 비싸야 정상."""
    from lib.pricing import PRICING
    for model, rates in PRICING.items():
        assert rates["cache_creation_1h"] > rates["cache_creation_5m"], (
            f"{model}: 1h {rates['cache_creation_1h']} <= 5m {rates['cache_creation_5m']}"
        )


def test_compute_cost_emits_stderr_for_unknown_model(capsys, monkeypatch):
    """미등록 model에 대해 stderr 경고가 한 번 나오고 그 후엔 silent."""
    from lib import pricing
    from lib.parser import TurnUsage
    monkeypatch.setattr(pricing, "_warned_unknown_models", set())
    usage = TurnUsage(
        model="unknown-future-model-99",
        input_tokens=1000,
        output_tokens=500,
    )
    cost1 = pricing.compute_cost("unknown-future-model-99", usage)
    assert cost1 == 0.0
    captured = capsys.readouterr()
    assert "unknown pricing model" in captured.err
    assert "unknown-future-model-99" in captured.err

    # 같은 model 두 번째 호출은 silent
    cost2 = pricing.compute_cost("unknown-future-model-99", usage)
    assert cost2 == 0.0
    captured2 = capsys.readouterr()
    assert captured2.err == ""


def test_compute_cost_combines_5m_and_1h_correctly():
    """5m + 1h 두 단가 정확 합산."""
    from lib.parser import TurnUsage
    from lib.pricing import compute_cost
    usage = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=1_000_000,    # = $5
        output_tokens=1_000_000,   # = $25
        cache_creation_5m_tokens=1_000_000,  # = $6.25
        cache_creation_1h_tokens=1_000_000,  # = $10
        cache_read_tokens=1_000_000,         # = $0.50
    )
    cost = compute_cost("claude-opus-4-7", usage)
    expected = 5.0 + 25.0 + 6.25 + 10.0 + 0.50
    assert abs(cost - expected) < 1e-6
