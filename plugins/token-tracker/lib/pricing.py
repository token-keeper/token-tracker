from __future__ import annotations

import json
import sys
from pathlib import Path

from lib.parser import TurnUsage


# Pricing data lives in pricing_data.json (sibling of this file).
# 분리 이유: 단가 변경마다 코드 PR 대신 1줄 data diff 로 끝내기 위함.
# 형식: { "fetched": "YYYY-MM-DD", "source": "...", "models": { "<model_id>": {...} } }
#
# 가정 (옛 dict 시절과 동일):
# - prompt cache write 는 5m / 1h 두 tier 만 존재. 새 tier 추가 시 JSON 키 + parser
#   + summary_store v4 bump 필요.
# - cache_read 는 모든 tier 단가 동일. 향후 분리되면 spec/회귀 재검토.
# - 단가 변경 시 tests/test_pricing.py 의 절대값 가드 테스트도 함께 갱신.
_PRICING_DATA_PATH = Path(__file__).parent / "pricing_data.json"


def _load_pricing() -> dict[str, dict[str, float]]:
    """Load pricing table from pricing_data.json at module import time.

    fail-fast 정책:
    - 파일 없음 / JSON 파싱 실패: 원본 예외 (FileNotFoundError, json.JSONDecodeError) 자연 전파.
      hook process import 가 실패하며 stderr 에 traceback 남음 → 배포 사고 즉시 인지.
    - top-level 이 dict 아님 / models 키 누락 / models 가 dict 아님 / 빈 dict:
      RuntimeError 로 케이스별 메시지 변환.
    """
    raw = json.loads(_PRICING_DATA_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError(
            f"pricing_data.json: top-level must be an object ({_PRICING_DATA_PATH})"
        )
    models = raw.get("models")
    if not isinstance(models, dict):
        raise RuntimeError(
            f"pricing_data.json: 'models' key missing or not an object ({_PRICING_DATA_PATH})"
        )
    if not models:
        raise RuntimeError(
            f"pricing_data.json: 'models' is empty ({_PRICING_DATA_PATH})"
        )
    return models


PRICING: dict[str, dict[str, float]] = _load_pricing()


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
