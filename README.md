# token-tracker

Claude Code plugin: display per-request token cost on every `Stop`.

## What it shows

After every assistant response, a one-line summary appears below it:

```
비용 $0.0180 · 1,546 toks · cache 85% · 12.3s
```

- **비용**: retail pay-per-token cost estimate for just this request.
- **toks**: total (input + output + cache_read) tokens consumed.
- **cache**: `cache_read / total_input` hit rate.
- **s**: wall-clock seconds from `UserPromptSubmit` to `Stop`.

## Detail view: `/token-detail`

직전 request의 **turn별** 토큰·비용·툴 사용 내역을 표로 보고 싶다면:

```
/token-detail
```

출력 예시:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 직전 request 상세
 총 비용 $0.0180 | 1,546 toks | cache 85% | 12.3s

   #  모델                    툴                 input    cc       cr    output     비용      시간
   1  opus-4-7[1m]            Read×3,Edit×1      120     400      800       450    $0.008     2.1s
   2  opus-4-7[1m]            —                   95       0    1,200       320    $0.006     3.5s
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 범례: cc=cache_creation, cr=cache_read
```

skill은 `disable-model-invocation: true`로 등록돼 있어 Claude가 자동으로 호출하지 않고, 사용자가 `/token-detail`을 직접 입력해야만 실행됩니다. 스크립트 실행 + minimal SKILL.md 본문이라 토큰 소비는 수백 수준.

## Cost is "retail" — it will not match the statusline

Claude Code's statusline `[💰 $X.XXX]` shows its **internal session-cumulative** cost tracker, which may reflect team/enterprise plan discounts or different cache-creation accounting. This plugin computes cost from Anthropic's **public pay-per-token rate card** (values hardcoded in `lib/pricing.py`).

Use this plugin's output for **optimization signal** (did caching improve? is this prompt expensive relative to the last one?), not for billing.

## Files of interest

- `docs/superpowers/specs/` — design specs (Phase 1 overall + Phase 2-B `/token-detail`)
- `docs/superpowers/plans/` — implementation plans per phase
- `docs/handoff/` — cross-session handoff notes
- `plugins/token-tracker/lib/pricing.py` — static rate card (update when Anthropic prices change)
- `plugins/token-tracker/hooks/on_stop.py` — aggregation + output
- `plugins/token-tracker/lib/i18n/` — translated strings for ko/en

## Install (local marketplace)

이 repo 자체가 self-contained Claude Code marketplace입니다. Claude Code CLI에서 한 번만 등록하면 이후 어느 디렉터리에서 Claude Code를 실행해도 hook이 발화합니다.

```bash
# 1. marketplace 등록 (repo를 clone 한 경로를 가리킨다)
/plugin marketplace add /absolute/path/to/token-tracker

# 2. plugin 활성화
/plugin install token-tracker@token-tracker-local
```

활성화 후 Claude Code를 재시작하면 Stop hook이 응답마다 아래 같은 한 줄을 출력합니다:

```
비용 $0.0180 · 1,546 toks · cache 85% · 12.3s
```

비활성화: `/plugin disable token-tracker@token-tracker-local`
제거: `/plugin uninstall token-tracker@token-tracker-local`

### 개발 모드

repo를 수정하면서 바로 반영하려면 symlink 방식을 쓸 수 있습니다:

```bash
ln -s /Users/you/Desktop/token-tracker ~/.claude/marketplaces/token-tracker-local
```

그 외 `.claude/settings.local.json`에 hook을 직접 등록하는 이전 방식은 더 이상 사용하지 않습니다.

## Tests

repo 루트에서:

```bash
./venv/bin/pytest plugins/token-tracker/tests -q
```

80 tests across unit + integration + e2e (hook subprocess, skill script subprocess). Python 3.10+ stdlib only, pytest as the only dev dependency.
