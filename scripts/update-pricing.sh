#!/usr/bin/env bash
# 즉시 pricing fetch + state override write — 7일 stale 체크 무시.
# 사용자가 새 모델 출시 인지 시 실행하거나, SessionStart 자동 갱신을 강제.
#
# 동작:
# 1. Anthropic pricing 페이지 fetch (timeout 10s)
# 2. 파싱 → models dict
# 3. ~/.claude/plugins/token-tracker/state/pricing_data.json 에 write (덮어씀)
# 4. ~/.claude/plugins/token-tracker/state/pricing_meta.json 에 last_fetch 갱신
# 5. lib/pricing_data.json (default) 에 없는 새 모델 발견 시 stderr 안내
#
# Exit: 0 성공, 1 실패 (네트워크 / 페이지 형식 변경).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/../plugins/token-tracker" && pwd)"

exec env \
    CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" \
    PYTHONPATH="$PLUGIN_ROOT" \
    python3 - <<'PY'
import json
import sys
from datetime import datetime, timezone

from lib.paths import state_dir
from lib.pricing import _PRICING_DATA_PATH, _load_pricing_from
from lib.pricing_fetch import fetch_pricing_models

print("Fetching Anthropic pricing page...", file=sys.stderr)
models = fetch_pricing_models(timeout=10)
if models is None:
    print("fetch failed (network error or page format change)", file=sys.stderr)
    sys.exit(1)

state_d = state_dir()
state_pricing = state_d / "pricing_data.json"
meta_path = state_d / "pricing_meta.json"

state_pricing.write_text(
    json.dumps({
        "fetched": datetime.now(timezone.utc).date().isoformat(),
        "source": "https://platform.claude.com/docs/en/about-claude/pricing",
        "notes": "Manually refreshed via scripts/update-pricing.sh.",
        "models": models,
    }, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
meta_path.write_text(
    json.dumps({
        "last_fetch": datetime.now(timezone.utc).isoformat(),
        "last_fetch_status": "success",
    }, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

try:
    default = _load_pricing_from(_PRICING_DATA_PATH)
except Exception:
    default = {}
new_models = sorted(set(models.keys()) - set(default.keys()))
if new_models:
    print(f"새 모델 {len(new_models)}종: {', '.join(new_models)}", file=sys.stderr)
print(f"pricing 갱신 완료. {len(models)} 모델 → {state_pricing}", file=sys.stderr)
PY
