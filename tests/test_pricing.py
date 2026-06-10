import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from lib import pricing, pricing_fetch
from lib.parser import SubagentUsage, TurnUsage

# conftest 의 autouse fixture 가 setattr 로 막기 전의 실제 함수 참조 —
# refresh 동작 검증 테스트에서 복원용.
_REAL_REFRESH = pricing._try_refresh_for_unknown


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


def test_prefix_match_fable_with_context_suffix():
    """Fable 5 1M context id ('claude-fable-5[1m]') 도 prefix match 로 과금."""
    u = TurnUsage(
        model="claude-fable-5[1m]",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_tokens=0,
    )
    assert math.isclose(pricing.compute_cost("claude-fable-5[1m]", u), 10.0, rel_tol=1e-6)


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
# unknown 모델 즉시 fetch — _try_refresh_for_unknown
# ──────────────────────────────────────────────────────────────────────────

_GHOST_RATES = {
    "input": 7.0, "output": 21.0,
    "cache_creation_5m": 8.75, "cache_creation_1h": 14.0,
    "cache_read": 0.70,
}


@pytest.fixture
def refresh_env(monkeypatch, tmp_path):
    """unknown 모델 즉시 fetch 검증용 환경.

    conftest 가 차단한 실제 refresh 함수를 복원하고, state 경로를 tmp 로 격리,
    PRICING 전역은 snapshot/restore 로 오염 방지.
    """
    monkeypatch.setattr(pricing, "_try_refresh_for_unknown", _REAL_REFRESH)
    monkeypatch.setattr(pricing, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(pricing, "_STATE_PRICING_PATH", tmp_path / "pricing_data.json")
    monkeypatch.setattr(pricing, "_STATE_META_PATH", tmp_path / "pricing_meta.json")
    monkeypatch.setattr(pricing, "_fetch_attempts", {})
    monkeypatch.setattr(pricing, "_warned_unknown_models", set())
    snapshot = dict(pricing.PRICING)
    yield tmp_path
    pricing.PRICING.clear()
    pricing.PRICING.update(snapshot)


def test_unknown_model_triggers_immediate_fetch(refresh_env, monkeypatch):
    """$0 (미등록 모델) 감지 → 즉시 fetch → state write → 같은 호출에서 정확 단가."""
    monkeypatch.setattr(
        pricing_fetch, "fetch_pricing_models",
        lambda timeout=3: {"claude-ghost-9": dict(_GHOST_RATES)},
    )
    u = TurnUsage(model="claude-ghost-9", input_tokens=1_000_000, output_tokens=0)
    cost = pricing.compute_cost("claude-ghost-9", u)
    assert math.isclose(cost, 7.0, rel_tol=1e-6)
    # state override + meta 가 기록됨
    state = json.loads((refresh_env / "pricing_data.json").read_text(encoding="utf-8"))
    assert "claude-ghost-9" in state["models"]
    meta = json.loads((refresh_env / "pricing_meta.json").read_text(encoding="utf-8"))
    assert meta["last_fetch_status"] == "success"
    assert "last_fetch_attempt" in meta


def test_unknown_model_fetch_fail_returns_zero_and_records_attempt(refresh_env, monkeypatch):
    """fetch 실패 → 기존처럼 $0 + 경고. 단 시도는 meta 에 기록 (cooldown 시작)."""
    monkeypatch.setattr(pricing_fetch, "fetch_pricing_models", lambda timeout=3: None)
    u = TurnUsage(model="claude-ghost-9", input_tokens=1_000_000, output_tokens=0)
    assert pricing.compute_cost("claude-ghost-9", u) == 0.0
    meta = json.loads((refresh_env / "pricing_meta.json").read_text(encoding="utf-8"))
    assert "last_fetch_attempt" in meta
    assert "last_fetch" not in meta  # 실패는 last_fetch 안 건드림 (stale 체크 보존)


def test_unknown_model_fetch_respects_cooldown(refresh_env, monkeypatch):
    """최근 시도 (1시간 이내) 가 meta 에 있으면 네트워크를 아예 안 탄다."""
    recent = datetime.now(timezone.utc) - timedelta(minutes=10)
    (refresh_env / "pricing_meta.json").write_text(
        json.dumps({"last_fetch_attempt": recent.isoformat()}), encoding="utf-8"
    )
    calls: list[int] = []
    monkeypatch.setattr(
        pricing_fetch, "fetch_pricing_models",
        lambda timeout=3: calls.append(1) or None,
    )
    u = TurnUsage(model="claude-ghost-9", input_tokens=1_000_000, output_tokens=0)
    assert pricing.compute_cost("claude-ghost-9", u) == 0.0
    assert calls == []


def test_unknown_model_fetch_after_cooldown_expired(refresh_env, monkeypatch):
    """cooldown (1시간) 지난 시도 기록은 fetch 를 막지 않는다."""
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    (refresh_env / "pricing_meta.json").write_text(
        json.dumps({"last_fetch_attempt": old.isoformat()}), encoding="utf-8"
    )
    monkeypatch.setattr(
        pricing_fetch, "fetch_pricing_models",
        lambda timeout=3: {"claude-ghost-9": dict(_GHOST_RATES)},
    )
    u = TurnUsage(model="claude-ghost-9", input_tokens=1_000_000, output_tokens=0)
    assert math.isclose(pricing.compute_cost("claude-ghost-9", u), 7.0, rel_tol=1e-6)


def test_unknown_model_fetch_once_per_process_within_cooldown(refresh_env, monkeypatch):
    """같은 모델 연속 compute_cost 는 fetch 재시도 안 함 (프로세스 내 cooldown)."""
    calls: list[int] = []
    monkeypatch.setattr(
        pricing_fetch, "fetch_pricing_models",
        lambda timeout=3: calls.append(1) or None,
    )
    u = TurnUsage(model="claude-ghost-9", input_tokens=1_000_000, output_tokens=0)
    pricing.compute_cost("claude-ghost-9", u)
    pricing.compute_cost("claude-ghost-9", u)
    assert len(calls) == 1


def test_unknown_model_fetch_retries_in_process_after_cooldown(refresh_env, monkeypatch):
    """장수 프로세스 (server_daemon) 회귀 가드 — 실패한 모델도 cooldown 경과 후
    같은 프로세스에서 재시도된다 (영구 set 이었으면 재시작 전까지 $0 고착)."""
    calls: list[int] = []
    monkeypatch.setattr(
        pricing_fetch, "fetch_pricing_models",
        lambda timeout=3: calls.append(1) or {"claude-ghost-9": dict(_GHOST_RATES)},
    )
    u = TurnUsage(model="claude-ghost-9", input_tokens=1_000_000, output_tokens=0)
    # 1차 시도가 cooldown 한참 전이었던 상황 시뮬레이션 (메모리 + meta 둘 다 과거)
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    pricing._fetch_attempts["claude-ghost-9"] = old
    (refresh_env / "pricing_meta.json").write_text(
        json.dumps({"last_fetch_attempt": old.isoformat()}), encoding="utf-8"
    )
    assert math.isclose(pricing.compute_cost("claude-ghost-9", u), 7.0, rel_tol=1e-6)
    assert calls == [1]


def test_unknown_model_fetch_does_not_lose_default_models(refresh_env, monkeypatch):
    """reload 후에도 default (repo baseline) 모델들이 PRICING 에 유지 (merge 회귀 가드)."""
    monkeypatch.setattr(
        pricing_fetch, "fetch_pricing_models",
        lambda timeout=3: {"claude-ghost-9": dict(_GHOST_RATES)},
    )
    u = TurnUsage(model="claude-ghost-9", input_tokens=1_000_000, output_tokens=0)
    pricing.compute_cost("claude-ghost-9", u)
    assert "claude-fable-5" in pricing.PRICING
    assert "claude-opus-4-7" in pricing.PRICING


# ──────────────────────────────────────────────────────────────────────────
# 모델별 단가 절대값 가드 — pricing_data.json 회귀 방지.
# tier 단가표를 한 곳(_RATE_TIERS)에서 정의하고 (model_id, tier) 매핑만
# parametrize 로 늘려쓴다. 단가 변경 시 _RATE_TIERS 한 곳만 갱신.
# ──────────────────────────────────────────────────────────────────────────

_RATE_TIERS: dict[str, dict[str, float]] = {
    "fable": {
        "input": 10.0, "output": 50.0,
        "cache_creation_5m": 12.5, "cache_creation_1h": 20.0,
        "cache_read": 1.0,
    },
    # Opus 4.5 부터 적용된 신단가 (4.5 / 4.6 / 4.7 / 4.8 공통)
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
    ("claude-fable-5",     "fable"),
    ("claude-opus-4-8",    "opus_new"),
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
