#!/usr/bin/env python3
"""SessionStart hook — pricing 자동 갱신 (7일 주기).

흐름:
1. state/pricing_meta.json 의 last_fetch 검사
2. 7일 이내면 silent return (early)
3. 7일 이상이면:
   - pricing_fetch.fetch_pricing_models() 호출 (3초 timeout, fail-soft)
   - 성공: state/pricing_data.json 에 write + meta 갱신
   - 실패: meta 안 갱신 (다음 SessionStart 에 재시도) — silent

설계 원칙:
- **흐름 보호**: 어떤 예외도 hook return code 0 으로 끝남. SessionStart 가
  실패하면 사용자 세션 시작이 깨질 수 있어 절대 propagate 안 함.
- **idempotent**: 7일 이내면 no-op, 7일 이상이면 1회 fetch.
- **silent**: 자동 갱신 결과는 다음 응답의 token line / detail formatter 가
  새 단가 적용해 자연스레 노출. 별도 stderr 안내는 새 모델 발견 시에만.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path


_FETCH_INTERVAL_DAYS = 7


def _setup_sys_path() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        root = Path(env)
    else:
        root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    return root


def _log_error(msg: str) -> None:
    try:
        from lib.paths import log_dir
        log_file = log_dir() / "error.log"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _is_stale(meta_path: Path, interval_days: int) -> bool:
    """meta 파일의 last_fetch 가 interval_days 이상 지났으면 True.

    파일 없음 / 파싱 실패 / 키 누락 모두 stale 로 간주 (강제 fetch).
    """
    if not meta_path.exists():
        return True
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
        last = raw.get("last_fetch")
        if not isinstance(last, str):
            return True
        last_dt = datetime.fromisoformat(last)
    except Exception:
        return True
    now = datetime.now(timezone.utc)
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    return (now - last_dt) >= timedelta(days=interval_days)


def _write_state_pricing(state_pricing_path: Path, models: dict) -> None:
    """fetch 결과를 state/pricing_data.json 형식으로 저장."""
    payload = {
        "fetched": datetime.now(timezone.utc).date().isoformat(),
        "source": "https://platform.claude.com/docs/en/about-claude/pricing",
        "notes": "Auto-fetched by SessionStart hook. Overrides lib/pricing_data.json.",
        "models": models,
    }
    state_pricing_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_meta(meta_path: Path, status: str) -> None:
    """meta 갱신 — last_fetch + status."""
    payload = {
        "last_fetch": datetime.now(timezone.utc).isoformat(),
        "last_fetch_status": status,
    }
    meta_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _detect_new_models(default: dict, fetched: dict) -> list[str]:
    """default 에 없고 fetched 에 있는 새 모델 키 목록."""
    return sorted(set(fetched.keys()) - set(default.keys()))


def _try_auto_update() -> None:
    """자동 갱신 시도. 어떤 예외도 silent (caller 가 catch).

    절차: stale 검사 → fetch → state write + meta 갱신 → 새 모델 stderr 안내.
    """
    from lib.paths import state_dir
    from lib.pricing import _PRICING_DATA_PATH, _load_pricing_from
    from lib.pricing_fetch import fetch_pricing_models

    state_d = state_dir()
    state_pricing = state_d / "pricing_data.json"
    meta_path = state_d / "pricing_meta.json"

    if not _is_stale(meta_path, _FETCH_INTERVAL_DAYS):
        return  # 7일 이내 — skip

    fetched = fetch_pricing_models()
    if fetched is None:
        # 네트워크 / 파싱 실패 — meta 갱신 안 함 (다음 SessionStart 에 재시도)
        return

    # 새 모델 감지 (default 만 비교, state override 와 비교 안 함 — repo 의
    # baseline 기준으로 사용자에게 변경 인지 시켜주는 게 의도)
    try:
        default_models = _load_pricing_from(_PRICING_DATA_PATH)
    except Exception:
        default_models = {}
    new_models = _detect_new_models(default_models, fetched)

    _write_state_pricing(state_pricing, fetched)
    _write_meta(meta_path, "success")

    if new_models:
        sys.stderr.write(
            f"[token-tracker] pricing 자동 갱신: 새 모델 {len(new_models)}종 추가됨 "
            f"({', '.join(new_models)}). 다음 응답부터 정확 단가 적용.\n"
        )


def main() -> int:
    _setup_sys_path()
    try:
        # SessionStart 도 stdin 으로 hook input 받음 — 우리는 사용 안 하지만 drain.
        sys.stdin.read()
    except Exception:
        pass
    try:
        _try_auto_update()
    except Exception:
        # 어떤 예외도 hook return code 영향 안 주게 격리.
        _log_error("[on_session_start] auto-update failed:\n" + traceback.format_exc())
    return 0


if __name__ == "__main__":
    sys.exit(main())
