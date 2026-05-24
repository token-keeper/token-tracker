import math

import pytest

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


def test_effective_billing_model_resolves_short_alias_to_latest_family_member():
    """v0.11.0 변경 — short alias 가 family-prefix latest 로 자동 매핑되어 정확 단가 청구.

    이전 동작 (v0.10.0 까지): `Agent(model="sonnet")` → unknown → 부모 모델 단가 fallback.
    신 동작: alias 자동 탐지 → claude-sonnet-{latest} 단가로 정확 청구.
    parent fallback 은 빈 문자열이거나 family 매칭 실패 시에만.
    """
    # alias 가 known 으로 인식되면 sub_model 그대로 반환 (fallback 안 함)
    assert pricing.effective_billing_model("sonnet", "claude-opus-4-7") == "sonnet"
    assert pricing.effective_billing_model("haiku", "claude-opus-4-7") == "haiku"
    assert pricing.effective_billing_model("opus", "claude-opus-4-7") == "opus"
    # is_known_model 도 true 여야 함
    assert pricing.is_known_model("sonnet")
    assert pricing.is_known_model("haiku")
    assert pricing.is_known_model("opus")


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


# ──────────────────────────────────────────────────────────────────────────
# 모델별 단가 절대값 가드 — pricing_data.json 회귀 방지.
# tier 단가표를 한 곳(_RATE_TIERS)에서 정의하고 (model_id, tier) 매핑만
# parametrize 로 늘려쓴다. 단가 변경 시 _RATE_TIERS 한 곳만 갱신.
# ──────────────────────────────────────────────────────────────────────────

_RATE_TIERS: dict[str, dict[str, float]] = {
    # Opus 4.5 부터 적용된 신단가 (4.5 / 4.6 / 4.7 공통)
    "opus_new": {
        "input": 5.0, "output": 25.0,
        "cache_creation_5m": 6.25, "cache_creation_1h": 10.0,
        "cache_read": 0.50,
    },
    # Opus 4.0 / 4.1 옛 단가
    "opus_old": {
        "input": 15.0, "output": 75.0,
        "cache_creation_5m": 18.75, "cache_creation_1h": 30.0,
        "cache_read": 1.50,
    },
    # Sonnet 4.0 / 4.5 / 4.6 공통
    "sonnet": {
        "input": 3.0, "output": 15.0,
        "cache_creation_5m": 3.75, "cache_creation_1h": 6.0,
        "cache_read": 0.30,
    },
    "haiku_4_5": {
        "input": 1.0, "output": 5.0,
        "cache_creation_5m": 1.25, "cache_creation_1h": 2.0,
        "cache_read": 0.10,
    },
    "haiku_3_5": {
        "input": 0.80, "output": 4.0,
        "cache_creation_5m": 1.0, "cache_creation_1h": 1.6,
        "cache_read": 0.08,
    },
}

_MODEL_TIER_MAP: list[tuple[str, str]] = [
    ("claude-opus-4-7",    "opus_new"),
    ("claude-opus-4-6",    "opus_new"),
    ("claude-opus-4-5",    "opus_new"),
    ("claude-opus-4-1",    "opus_old"),
    ("claude-opus-4",      "opus_old"),
    ("claude-sonnet-4-6",  "sonnet"),
    ("claude-sonnet-4-5",  "sonnet"),
    ("claude-sonnet-4",    "sonnet"),
    ("claude-haiku-4-5",   "haiku_4_5"),
    ("claude-haiku-3-5",   "haiku_3_5"),
]


@pytest.mark.parametrize("model_id,tier", _MODEL_TIER_MAP)
def test_pricing_absolute_rates_per_model(model_id: str, tier: str):
    """모든 등록 모델의 5개 단가 절대값 가드. 단가 변경 시 _RATE_TIERS 갱신 필요."""
    expected = _RATE_TIERS[tier]
    p = pricing.PRICING[model_id]
    for key, value in expected.items():
        assert p[key] == value, f"{model_id}.{key}: got {p[key]}, expected {value}"


def test_pricing_1h_more_expensive_than_5m_for_all_models():
    """tier 분리 누락 회귀 가드 — 1h가 5m보다 비싸야 정상."""
    for model, rates in pricing.PRICING.items():
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


# ──────────────────────────────────────────────────────────────────────────
# prefix match 회귀 가드 — Opus 4.0 키 추가로 4.x 가 4.0 단가로 잘못 매치되면 안 됨
# ──────────────────────────────────────────────────────────────────────────


def test_prefix_match_opus_4_x_not_billed_as_opus_4_0():
    """`claude-opus-4-7-20260101` 같은 dated id 가 `claude-opus-4` (4.0 단가) 로
    잘못 매치되면 안 됨. longest-prefix 가 4.7/4.6/4.5/4.1 을 우선 매치해야 함."""
    one_mtok_input = TurnUsage(
        model="claude-opus-4-7-20260101",
        input_tokens=1_000_000,
        output_tokens=0,
    )
    # Opus 4.7 신단가 = $5/MTok input. 만약 4.0 ($15) 으로 매치되면 fail.
    assert math.isclose(
        pricing.compute_cost("claude-opus-4-7-20260101", one_mtok_input), 5.0, rel_tol=1e-6
    )


def test_prefix_match_opus_4_0_exact():
    """`claude-opus-4` 단독 id 는 4.0 단가 ($15) 매치."""
    u = TurnUsage(model="claude-opus-4", input_tokens=1_000_000, output_tokens=0)
    assert math.isclose(pricing.compute_cost("claude-opus-4", u), 15.0, rel_tol=1e-6)


# ──────────────────────────────────────────────────────────────────────────
# pricing_data.json 로드 가드 — 파일 형태 / 키 누락 시 fail-fast
# ──────────────────────────────────────────────────────────────────────────


def test_pricing_data_json_exists_and_loads():
    """배포 사고 회귀 가드 — 파일 존재 + import 시 PRICING 채워짐."""
    assert pricing._PRICING_DATA_PATH.exists()
    # _MODEL_TIER_MAP 의 모든 모델이 PRICING 에 등록되어 있어야 함
    for model_id, _ in _MODEL_TIER_MAP:
        assert model_id in pricing.PRICING


def test_pricing_data_json_load_rejects_empty_models(tmp_path, monkeypatch):
    """models 가 빈 dict 면 즉시 RuntimeError."""
    bad = tmp_path / "bad.json"
    bad.write_text('{"models": {}}', encoding="utf-8")
    monkeypatch.setattr(pricing, "_PRICING_DATA_PATH", bad)
    with pytest.raises(RuntimeError, match="empty"):
        pricing._load_pricing()


def test_pricing_data_json_load_rejects_missing_models_key(tmp_path, monkeypatch):
    """models 키 자체가 없으면 RuntimeError."""
    bad = tmp_path / "bad.json"
    bad.write_text('{"fetched": "x"}', encoding="utf-8")
    monkeypatch.setattr(pricing, "_PRICING_DATA_PATH", bad)
    with pytest.raises(RuntimeError, match="missing or not an object"):
        pricing._load_pricing()


def test_pricing_data_json_load_rejects_models_not_dict(tmp_path, monkeypatch):
    """models 가 dict 아닌 타입 (list 등) 이면 RuntimeError."""
    bad = tmp_path / "bad.json"
    bad.write_text('{"models": []}', encoding="utf-8")
    monkeypatch.setattr(pricing, "_PRICING_DATA_PATH", bad)
    with pytest.raises(RuntimeError, match="missing or not an object"):
        pricing._load_pricing()


def test_pricing_data_json_load_rejects_top_level_not_object(tmp_path, monkeypatch):
    """top-level 이 dict 아니면 RuntimeError."""
    bad = tmp_path / "bad.json"
    bad.write_text('[1, 2, 3]', encoding="utf-8")
    monkeypatch.setattr(pricing, "_PRICING_DATA_PATH", bad)
    with pytest.raises(RuntimeError, match="top-level"):
        pricing._load_pricing()


def test_pricing_data_json_load_propagates_json_decode_error(tmp_path, monkeypatch):
    """JSON 파싱 실패는 원본 예외 자연 전파 (fail-fast 정책)."""
    bad = tmp_path / "bad.json"
    bad.write_text('{not valid json', encoding="utf-8")
    monkeypatch.setattr(pricing, "_PRICING_DATA_PATH", bad)
    import json as _json
    with pytest.raises(_json.JSONDecodeError):
        pricing._load_pricing()


def test_pricing_data_json_load_propagates_file_not_found(tmp_path, monkeypatch):
    """파일 누락은 원본 FileNotFoundError 자연 전파 (fail-fast 정책)."""
    monkeypatch.setattr(pricing, "_PRICING_DATA_PATH", tmp_path / "missing.json")
    with pytest.raises(FileNotFoundError):
        pricing._load_pricing()


def test_pricing_data_json_all_models_have_required_keys():
    """모든 row 가 5개 단가 키 (input/output/5m/1h/read) 를 갖고 있어야 함.
    누락 row 가 silent KeyError 로 새벽 4시 hook crash 내는 회귀 방지."""
    required = {"input", "output", "cache_creation_5m", "cache_creation_1h", "cache_read"}
    for model, rates in pricing.PRICING.items():
        missing = required - rates.keys()
        assert not missing, f"{model}: missing keys {missing}"
