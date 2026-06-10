"""SessionStart hook 자동 갱신 흐름 테스트.

단위: _is_stale / _detect_new_models / _try_auto_update.
실제 네트워크 호출은 monkeypatch 로 mock — fetch_pricing_models 결과만 주입.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# hooks 디렉터리는 sys.path 에 없으므로 보조 import.
_HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(_HOOKS_DIR))

import on_session_start  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────
# _is_stale — 7일 stale 체크
# ──────────────────────────────────────────────────────────────────────────


def test_is_stale_true_when_meta_missing(tmp_path):
    """meta 파일 없음 → stale (강제 fetch)."""
    assert on_session_start._is_stale(tmp_path / "missing.json", 7) is True


def test_is_stale_false_when_within_interval(tmp_path):
    """meta 파일에 last_fetch 가 1일 전 → stale 아님."""
    meta = tmp_path / "meta.json"
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    meta.write_text(json.dumps({"last_fetch": yesterday}), encoding="utf-8")
    assert on_session_start._is_stale(meta, 7) is False


def test_is_stale_true_when_exceeds_interval(tmp_path):
    """meta 의 last_fetch 가 8일 전 → stale (7일 interval 초과)."""
    meta = tmp_path / "meta.json"
    eight_days_ago = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    meta.write_text(json.dumps({"last_fetch": eight_days_ago}), encoding="utf-8")
    assert on_session_start._is_stale(meta, 7) is True


def test_is_stale_true_when_meta_corrupt(tmp_path):
    """meta 손상 시 stale 로 간주 (강제 fetch — 갱신 시도)."""
    meta = tmp_path / "bad.json"
    meta.write_text("{not json", encoding="utf-8")
    assert on_session_start._is_stale(meta, 7) is True


def test_is_stale_true_when_last_fetch_missing_key(tmp_path):
    """meta 에 last_fetch 키 없음 → stale."""
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
    assert on_session_start._is_stale(meta, 7) is True


def test_is_stale_naive_datetime_treated_as_utc(tmp_path):
    """timezone naive 한 ISO timestamp 도 UTC 로 해석해 비교."""
    meta = tmp_path / "meta.json"
    # naive datetime — older than 8 days
    naive = (datetime.now(timezone.utc) - timedelta(days=8)).replace(tzinfo=None).isoformat()
    meta.write_text(json.dumps({"last_fetch": naive}), encoding="utf-8")
    assert on_session_start._is_stale(meta, 7) is True


# ──────────────────────────────────────────────────────────────────────────
# _detect_new_models
# ──────────────────────────────────────────────────────────────────────────


def test_detect_new_models_finds_added_keys():
    default = {"claude-opus-4-7": {}, "claude-sonnet-4-6": {}}
    fetched = {
        "claude-opus-4-7": {},
        "claude-sonnet-4-6": {},
        "claude-sonnet-4-7": {},  # new
        "claude-haiku-5": {},     # new
    }
    new = on_session_start._detect_new_models(default, fetched)
    assert new == ["claude-haiku-5", "claude-sonnet-4-7"]


def test_detect_new_models_empty_when_subset():
    """fetched 가 default 의 부분집합이면 새 모델 없음."""
    default = {"a": {}, "b": {}, "c": {}}
    fetched = {"a": {}, "b": {}}
    assert on_session_start._detect_new_models(default, fetched) == []


# ──────────────────────────────────────────────────────────────────────────
# _try_auto_update — 통합 흐름 (monkeypatch 로 네트워크 격리)
# ──────────────────────────────────────────────────────────────────────────


_FAKE_FETCHED = {
    "claude-opus-4-7": {
        "input": 5.0, "output": 25.0,
        "cache_creation_5m": 6.25, "cache_creation_1h": 10.0, "cache_read": 0.50,
    },
    "claude-sonnet-4-6": {
        "input": 3.0, "output": 15.0,
        "cache_creation_5m": 3.75, "cache_creation_1h": 6.0, "cache_read": 0.30,
    },
}


@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    """state_dir 을 tmp_path 로 격리."""
    state_d = tmp_path / "state"
    state_d.mkdir()

    def fake_state_dir():
        return state_d

    # paths.state_dir 을 monkeypatch
    from lib import paths
    monkeypatch.setattr(paths, "state_dir", fake_state_dir)
    return state_d


def test_try_auto_update_skips_when_not_stale(monkeypatch, isolated_state):
    """meta 가 interval (1일) 이내 — 1시간 전이면 fetch 호출 안 함 (early return)."""
    meta = isolated_state / "pricing_meta.json"
    an_hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    meta.write_text(json.dumps({"last_fetch": an_hour_ago}), encoding="utf-8")

    fetch_called = []

    def fake_fetch(timeout=3):
        fetch_called.append(True)
        return _FAKE_FETCHED

    from lib import pricing_fetch
    monkeypatch.setattr(pricing_fetch, "fetch_pricing_models", fake_fetch)

    on_session_start._try_auto_update()
    assert fetch_called == []  # fetch 호출 안 함


def test_try_auto_update_writes_state_when_stale(monkeypatch, isolated_state):
    """stale 일 때 fetch 성공 → state/pricing_data.json + meta 갱신."""
    from lib import pricing_fetch
    monkeypatch.setattr(pricing_fetch, "fetch_pricing_models", lambda timeout=3: _FAKE_FETCHED)

    on_session_start._try_auto_update()

    state_pricing = isolated_state / "pricing_data.json"
    meta = isolated_state / "pricing_meta.json"
    assert state_pricing.exists()
    assert meta.exists()

    payload = json.loads(state_pricing.read_text(encoding="utf-8"))
    assert "claude-opus-4-7" in payload["models"]

    meta_payload = json.loads(meta.read_text(encoding="utf-8"))
    assert meta_payload["last_fetch_status"] == "success"
    assert "last_fetch" in meta_payload


def test_try_auto_update_does_not_update_meta_on_fetch_failure(
    monkeypatch, isolated_state
):
    """fetch 실패 (None 반환) → meta 갱신 안 함 (다음 SessionStart 에 재시도)."""
    from lib import pricing_fetch
    monkeypatch.setattr(pricing_fetch, "fetch_pricing_models", lambda timeout=3: None)

    on_session_start._try_auto_update()

    meta = isolated_state / "pricing_meta.json"
    state_pricing = isolated_state / "pricing_data.json"
    assert not meta.exists()
    assert not state_pricing.exists()


def test_try_auto_update_announces_new_models(monkeypatch, isolated_state, capsys):
    """default 에 없고 fetched 에 있는 모델 발견 시 stderr 안내."""
    fetched_with_new = dict(_FAKE_FETCHED)
    fetched_with_new["claude-sonnet-4-7"] = {  # 새 모델
        "input": 3.0, "output": 15.0,
        "cache_creation_5m": 3.75, "cache_creation_1h": 6.0, "cache_read": 0.30,
    }
    from lib import pricing_fetch
    monkeypatch.setattr(pricing_fetch, "fetch_pricing_models", lambda timeout=3: fetched_with_new)

    on_session_start._try_auto_update()

    captured = capsys.readouterr()
    assert "새 모델" in captured.err
    assert "claude-sonnet-4-7" in captured.err


def test_try_auto_update_no_announcement_when_no_new_models(
    monkeypatch, isolated_state, capsys
):
    """default 와 동일하면 stderr 안내 없음 (조용)."""
    from lib import pricing_fetch
    # default 에 이미 있는 모델만 — 새 모델 없음
    monkeypatch.setattr(pricing_fetch, "fetch_pricing_models", lambda timeout=3: _FAKE_FETCHED)

    on_session_start._try_auto_update()

    captured = capsys.readouterr()
    assert "새 모델" not in captured.err
