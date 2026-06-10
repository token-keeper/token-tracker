from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib import pricing_fetch
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
# SessionStart hook 의 자동 fetch + unknown 모델 감지 시 즉시 fetch
# (_try_refresh_for_unknown) + scripts/update-pricing.sh 의 수동 갱신
# 결과가 이 경로에 저장됨. 존재 시 default 단가에 덮어씌움 (merge — override 키
# 우선, default 만의 키도 유지).
# 권한 / git / cache 일관성 위험 회피 — state 디렉터리는 plugin 데이터 영역으로
# reinstall 영향이 없다.
_STATE_DIR = Path.home() / ".claude" / "plugins" / "token-tracker" / "state"
_STATE_PRICING_PATH = _STATE_DIR / "pricing_data.json"
_STATE_META_PATH = _STATE_DIR / "pricing_meta.json"

# unknown 모델 트리거 fetch 의 최소 재시도 간격. 페이지에 아직 단가가 없는 모델
# 이거나 오프라인이면 fetch 가 매번 실패하는데, Stop 마다 3초 네트워크 stall 을
# 도는 것을 막는다 (실패한 시도도 cooldown 에 포함).
_UNKNOWN_FETCH_COOLDOWN = timedelta(hours=1)


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

# 프로세스 내 모델별 마지막 fetch 시도 시각. 단명 hook 에선 사실상 1회 가드,
# 장수 프로세스 (server_daemon) 에선 cooldown 경과 후 자연 재시도를 허용한다 —
# 영구 set 이면 daemon 이 한 번 실패한 모델을 재시작 전까지 영영 안 본다.
# 디스크 (meta) cooldown 과 별개로 메모리에 두는 이유: meta write 가 불가능한
# 환경에서도 같은 프로세스가 render 마다 3초 네트워크 stall 을 돌지 않게.
_fetch_attempts: dict[str, datetime] = {}


def _read_meta() -> dict:
    try:
        raw = json.loads(_STATE_META_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _within_unknown_fetch_cooldown() -> bool:
    """마지막 fetch 시도 (성공/실패 무관) 가 cooldown 이내면 True."""
    meta = _read_meta()
    last = meta.get("last_fetch_attempt") or meta.get("last_fetch")
    if not isinstance(last, str):
        return False
    try:
        last_dt = datetime.fromisoformat(last)
    except ValueError:
        return False
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last_dt < _UNKNOWN_FETCH_COOLDOWN


def _write_meta(meta: dict) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_META_PATH.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _try_refresh_for_unknown(model: str) -> bool:
    """미등록 모델 감지 시 즉시 pricing fetch → state override write → PRICING reload.

    새 모델 출시 직후의 $0 표시를 다음 SessionStart fetch 주기까지 기다리지 않고
    그 자리에서 해소하는 경로. Returns True 면 PRICING 이 갱신됨 (caller 가
    재조회). fail-soft — 어떤 예외도 전파하지 않고 False.

    남용 방지 2중 가드 (모두 cooldown 경과 후 재시도 허용 — 영구 차단 없음):
    - 프로세스 내 모델별 시도 시각 (_fetch_attempts) 기준 1시간 cooldown
    - meta 의 last_fetch_attempt 기준 1시간 cooldown — 시도 자체를 기록하므로
      실패가 반복돼도 1시간에 1번만 네트워크를 탄다.
    """
    now = datetime.now(timezone.utc)
    last_attempt = _fetch_attempts.get(model)
    if last_attempt is not None and now - last_attempt < _UNKNOWN_FETCH_COOLDOWN:
        return False
    _fetch_attempts[model] = now
    try:
        if _within_unknown_fetch_cooldown():
            return False
        meta = _read_meta()
        meta["last_fetch_attempt"] = now.isoformat()
        _write_meta(meta)

        models = pricing_fetch.fetch_pricing_models()
        if not models:
            return False

        _STATE_PRICING_PATH.write_text(
            json.dumps({
                "fetched": now.date().isoformat(),
                "source": "https://platform.claude.com/docs/en/about-claude/pricing",
                "notes": "Auto-fetched on unknown-model detection. Overrides lib/pricing_data.json.",
                "models": models,
            }, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        meta["last_fetch"] = now.isoformat()
        meta["last_fetch_status"] = "success"
        _write_meta(meta)

        # in-place reload — 장수 프로세스 (http server) 가 들고 있는 참조도 갱신.
        new_pricing = _load_pricing()
        PRICING.clear()
        PRICING.update(new_pricing)
        return True
    except Exception:
        return False


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
    if rates is None and _try_refresh_for_unknown(model):
        rates = _resolve_rates(model)
    if rates is None:
        # Silent $0 안전장치 — 미등록 모델 alias 발견 시 stderr 1회 경고.
        # 즉시 fetch 시도 후에도 미등록 = 페이지 미반영 / fetch 실패 / cooldown.
        if model not in _warned_unknown_models:
            _warned_unknown_models.add(model)
            sys.stderr.write(
                f"[token-tracker] unknown pricing model: {model} — "
                f"즉시 갱신 시도 후에도 단가 미등록 (1시간 후 자동 재시도). "
                f"수동: ./scripts/update-pricing.sh\n"
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
