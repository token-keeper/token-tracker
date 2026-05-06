from __future__ import annotations

import json
import re
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

# State override (사용자 머신 전용):
# SessionStart hook 의 자동 fetch 결과 + scripts/update-pricing.sh 의 수동 갱신
# 결과가 이 경로에 저장됨. 존재 시 default 단가에 덮어씌움 (merge — override 키
# 우선, default 만의 키도 유지).
# 권한 / git / cache 일관성 위험 회피 — state 디렉터리는 plugin 데이터 영역으로
# reinstall 영향 없고 dev-mode 의 작업 폴더 git 도 더럽히지 않음.
_STATE_DIR = Path.home() / ".claude" / "plugins" / "token-tracker" / "state"
_STATE_PRICING_PATH = _STATE_DIR / "pricing_data.json"


def _load_pricing_from(path: Path) -> dict[str, dict[str, float]]:
    """Validating loader for a pricing JSON file.

    fail-fast 정책:
    - 파일 없음 / JSON 파싱 실패: 원본 예외 (FileNotFoundError, json.JSONDecodeError) 자연 전파.
    - top-level 이 dict 아님 / models 키 누락 / models 가 dict 아님 / 빈 dict:
      RuntimeError 로 케이스별 메시지 변환.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError(
            f"pricing_data.json: top-level must be an object ({path})"
        )
    models = raw.get("models")
    if not isinstance(models, dict):
        raise RuntimeError(
            f"pricing_data.json: 'models' key missing or not an object ({path})"
        )
    if not models:
        raise RuntimeError(
            f"pricing_data.json: 'models' is empty ({path})"
        )
    return models


def _load_pricing() -> dict[str, dict[str, float]]:
    """Load pricing data. State override takes priority over default.

    default = repo 의 lib/pricing_data.json (배포 시점 단가)
    override = ~/.claude/plugins/token-tracker/state/pricing_data.json (자동/수동 갱신)

    State override 손상 시 silent fallback — SessionStart hook 이 다음 cycle 에 정정.
    """
    default = _load_pricing_from(_PRICING_DATA_PATH)
    if not _STATE_PRICING_PATH.exists():
        return default
    try:
        override = _load_pricing_from(_STATE_PRICING_PATH)
    except Exception:
        # state 파일 손상 — default 만으로 진행, hook 이 다음 fetch 시 덮어씀.
        sys.stderr.write(
            f"[token-tracker] state pricing override broken at {_STATE_PRICING_PATH}; "
            f"using default pricing_data.json. Run ./scripts/update-pricing.sh to refresh.\n"
        )
        return default
    # merge: override 의 모델 row 우선, default 만의 row 도 유지
    return {**default, **override}


PRICING: dict[str, dict[str, float]] = _load_pricing()


_warned_unknown_models: set[str] = set()


# claude-{family}-{ver1}[-{ver2}...] 패턴 — alias 자동 탐지에 사용.
# group(1)=family ("opus"/"sonnet"/"haiku"), group(2)=version segments ("-4-7" / "-4")
_FAMILY_VER_RE = re.compile(r"^claude-([a-z]+)((?:-\d+)+)$")


def _version_tuple(model_key: str) -> tuple[int, ...]:
    """Tuple sort key — claude-sonnet-4-6 → (4, 6), claude-sonnet-4 → (4,).

    Tuple comparison: (4, 6) > (4, 5) > (4,) automatically.
    Non-matching keys → empty tuple (lowest priority).
    """
    m = _FAMILY_VER_RE.match(model_key)
    if not m:
        return ()
    return tuple(int(p) for p in m.group(2).strip("-").split("-"))


def _resolve_alias(short: str) -> str | None:
    """Find latest model id for a family-short alias like "sonnet" / "haiku" / "opus".

    Claude Code emits short aliases via `Agent(model="sonnet")` dispatch — we
    map these to the highest-version key starting with `claude-{short}` so the
    sub-agent gets billed at the correct family rate (not parent fallback).

    family-prefix latest 자동 탐지: PRICING 에 새 모델 row 가 추가되면 alias 도
    자동 갱신됨 (별도 매핑 dict 갱신 불필요).
    """
    if not short or "-" in short or "/" in short:
        # 정식 model id ("claude-...") 나 dated suffix 는 alias 가 아님 — 차단
        return None
    prefix_dash = f"claude-{short}-"
    base_only = f"claude-{short}"
    candidates = [k for k in PRICING if k.startswith(prefix_dash) or k == base_only]
    if not candidates:
        return None
    return max(candidates, key=_version_tuple)


def _resolve_rates(model: str) -> dict[str, float] | None:
    """Look up pricing for a model id.

    분기 우선순위:
      1) exact match (PRICING dict)
      2) family-short alias (sonnet/haiku/opus → latest 자동 탐지)
      3) longest-prefix match (claude-opus-4-7[1m] / -20260101 같은 suffixed ids)
    """
    if model in PRICING:
        return PRICING[model]
    alias_target = _resolve_alias(model)
    if alias_target:
        return PRICING[alias_target]
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
        # Silent $0 안전장치 — 미등록 모델 alias 발견 시 stderr 1회 경고.
        # 갱신 안내 포함 — SessionStart hook 자동 fetch / 수동 헬퍼 둘 다 안내.
        if model not in _warned_unknown_models:
            _warned_unknown_models.add(model)
            sys.stderr.write(
                f"[token-tracker] unknown pricing model: {model} — "
                f"pricing_data.json 갱신 필요. SessionStart 자동 갱신 대기 또는 "
                f"./scripts/update-pricing.sh 실행.\n"
            )
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

    Returns ``sub_model`` when it's a known pricing key (exact, alias, or
    prefix match); otherwise falls back to ``parent_model``. With alias auto-
    detection, short ids like ``"sonnet"`` from ``Agent(model="sonnet")``
    dispatch now resolve to the latest sonnet row instead of falling back —
    sub-agent gets billed at correct family rate.
    """
    if sub_model and is_known_model(sub_model):
        return sub_model
    return parent_model
