"""alias 자동 탐지 + state override 인프라 단위 테스트.

`_resolve_alias` (family-prefix latest) 와 `_load_pricing` (state override)
동작 가드.
"""
from __future__ import annotations

import json

import pytest

from lib import pricing


# ──────────────────────────────────────────────────────────────────────────
# _resolve_alias — family-prefix latest 자동 탐지
# ──────────────────────────────────────────────────────────────────────────


def test_resolve_alias_sonnet_picks_latest_in_family():
    """`sonnet` → 가장 큰 버전 sonnet (현재 4-6) 매핑."""
    target = pricing._resolve_alias("sonnet")
    assert target == "claude-sonnet-4-6"


def test_resolve_alias_haiku_picks_latest():
    target = pricing._resolve_alias("haiku")
    assert target == "claude-haiku-4-5"


def test_resolve_alias_opus_picks_latest():
    target = pricing._resolve_alias("opus")
    assert target == "claude-opus-4-7"


def test_resolve_alias_unknown_family_returns_none():
    """없는 family — None."""
    assert pricing._resolve_alias("ghost") is None
    assert pricing._resolve_alias("phantom") is None


def test_resolve_alias_rejects_dashed_input():
    """이미 정식 model id 형태 ('claude-...' / dashed) 면 alias 가 아님 → None.
    prefix-match 가 처리하도록 양보."""
    assert pricing._resolve_alias("claude-sonnet-4-6") is None
    assert pricing._resolve_alias("claude-opus") is None


def test_resolve_alias_empty_input_returns_none():
    assert pricing._resolve_alias("") is None


def test_resolve_alias_auto_picks_new_model_when_added(monkeypatch):
    """새 모델 row 가 PRICING 에 추가되면 alias 도 자동 갱신 (latest 이동).

    sonnet 4.7 가 추가되면 alias("sonnet") 가 4.6 대신 4.7 가리키게 — 별도 매핑 dict 갱신 없이.
    """
    new_pricing = dict(pricing.PRICING)
    new_pricing["claude-sonnet-4-7"] = {
        "input": 3.0, "output": 15.0,
        "cache_creation_5m": 3.75, "cache_creation_1h": 6.0, "cache_read": 0.30,
    }
    monkeypatch.setattr(pricing, "PRICING", new_pricing)
    target = pricing._resolve_alias("sonnet")
    assert target == "claude-sonnet-4-7"


def test_version_tuple_orders_correctly():
    """tuple 정렬: (4,6) > (4,5) > (4,) > ()."""
    assert pricing._version_tuple("claude-sonnet-4-6") == (4, 6)
    assert pricing._version_tuple("claude-sonnet-4") == (4,)
    assert pricing._version_tuple("claude-sonnet-3-5") == (3, 5)
    assert pricing._version_tuple("not-a-claude-id") == ()
    # 비교
    assert pricing._version_tuple("claude-sonnet-4-6") > pricing._version_tuple("claude-sonnet-4-5")
    assert pricing._version_tuple("claude-sonnet-4-5") > pricing._version_tuple("claude-sonnet-4")


# ──────────────────────────────────────────────────────────────────────────
# _resolve_rates 통합 — exact > alias > prefix 우선순위
# ──────────────────────────────────────────────────────────────────────────


def test_resolve_rates_exact_match_priority():
    """exact match 가 alias / prefix 보다 우선."""
    rates = pricing._resolve_rates("claude-sonnet-4-6")
    assert rates is not None
    assert rates["input"] == 3.0


def test_resolve_rates_alias_resolves_to_latest():
    """short alias → latest family."""
    rates = pricing._resolve_rates("sonnet")
    assert rates is not None
    assert rates["input"] == 3.0  # latest sonnet


def test_resolve_rates_prefix_match_for_suffixed_id():
    """suffix 붙은 dated id → prefix-match (alias 분기 안 거침)."""
    rates = pricing._resolve_rates("claude-opus-4-7-20260101")
    assert rates is not None
    assert rates["input"] == 5.0


def test_is_known_model_recognizes_alias():
    """alias 도 known 으로 인식 (effective_billing_model 의 fallback 경로 영향)."""
    assert pricing.is_known_model("sonnet")
    assert pricing.is_known_model("haiku")
    assert pricing.is_known_model("opus")
    assert pricing.is_known_model("unknown-junk") is False


# ──────────────────────────────────────────────────────────────────────────
# _load_pricing — state override 인프라
# ──────────────────────────────────────────────────────────────────────────


def _write_state_pricing(path, models: dict) -> None:
    payload = {
        "fetched": "2026-05-06",
        "source": "test",
        "notes": "test fixture",
        "models": models,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_pricing_no_state_returns_default(monkeypatch, tmp_path):
    """state override 없으면 default lib/pricing_data.json 만 사용."""
    monkeypatch.setattr(pricing, "_STATE_PRICING_PATH", tmp_path / "missing.json")
    loaded = pricing._load_pricing()
    # default 의 모델 모두 있어야 함
    assert "claude-opus-4-7" in loaded
    assert "claude-sonnet-4-6" in loaded
    assert "claude-haiku-4-5" in loaded


def test_load_pricing_state_override_takes_priority(monkeypatch, tmp_path):
    """state override 의 row 단가가 default 보다 우선."""
    state_path = tmp_path / "state_pricing.json"
    # opus 4.7 단가를 state 에서 다른 값으로 override
    _write_state_pricing(state_path, {
        "claude-opus-4-7": {
            "input": 999.0, "output": 999.0,
            "cache_creation_5m": 999.0, "cache_creation_1h": 999.0,
            "cache_read": 999.0,
        }
    })
    monkeypatch.setattr(pricing, "_STATE_PRICING_PATH", state_path)
    loaded = pricing._load_pricing()
    assert loaded["claude-opus-4-7"]["input"] == 999.0  # state override
    # default 만의 모델은 그대로
    assert "claude-haiku-4-5" in loaded


def test_load_pricing_state_adds_new_model(monkeypatch, tmp_path):
    """state override 가 default 에 없는 새 모델 row 도 추가."""
    state_path = tmp_path / "state_pricing.json"
    _write_state_pricing(state_path, {
        "claude-sonnet-4-7": {  # 가상 새 모델
            "input": 3.0, "output": 15.0,
            "cache_creation_5m": 3.75, "cache_creation_1h": 6.0, "cache_read": 0.30,
        }
    })
    monkeypatch.setattr(pricing, "_STATE_PRICING_PATH", state_path)
    loaded = pricing._load_pricing()
    assert "claude-sonnet-4-7" in loaded
    # default 의 기존 모델도 유지
    assert "claude-opus-4-7" in loaded


def test_load_pricing_state_corrupt_falls_back_to_default(
    monkeypatch, tmp_path, capsys
):
    """state override 파일 손상 시 silent fallback (default 만 사용) + stderr 안내."""
    bad = tmp_path / "bad_state.json"
    bad.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(pricing, "_STATE_PRICING_PATH", bad)
    loaded = pricing._load_pricing()
    # default 모두 있음
    assert "claude-opus-4-7" in loaded
    captured = capsys.readouterr()
    assert "state pricing override broken" in captured.err


def test_load_pricing_state_empty_models_falls_back(monkeypatch, tmp_path, capsys):
    """state override 가 empty models 면 RuntimeError → silent fallback."""
    bad = tmp_path / "empty_state.json"
    _write_state_pricing(bad, {})
    monkeypatch.setattr(pricing, "_STATE_PRICING_PATH", bad)
    loaded = pricing._load_pricing()
    assert "claude-opus-4-7" in loaded  # default fallback
    captured = capsys.readouterr()
    assert "state pricing override broken" in captured.err


# ──────────────────────────────────────────────────────────────────────────
# unknown model 메시지 강화
# ──────────────────────────────────────────────────────────────────────────


def test_unknown_model_warning_includes_update_guidance(monkeypatch, capsys):
    """unknown model stderr 메시지에 갱신 안내가 포함되어야 함."""
    from lib.parser import TurnUsage
    monkeypatch.setattr(pricing, "_warned_unknown_models", set())
    usage = TurnUsage(
        model="claude-future-99",
        input_tokens=1000,
        output_tokens=500,
    )
    pricing.compute_cost("claude-future-99", usage)
    captured = capsys.readouterr()
    assert "unknown pricing model" in captured.err
    assert "update-pricing.sh" in captured.err  # 갱신 안내 포함
