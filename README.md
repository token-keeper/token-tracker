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

## Cost is "retail" — it will not match the statusline

Claude Code's statusline `[💰 $X.XXX]` shows its **internal session-cumulative** cost tracker, which may reflect team/enterprise plan discounts or different cache-creation accounting. This plugin computes cost from Anthropic's **public pay-per-token rate card** (values hardcoded in `lib/pricing.py`).

Use this plugin's output for **optimization signal** (did caching improve? is this prompt expensive relative to the last one?), not for billing.

## Files of interest

- `docs/superpowers/specs/2026-04-22-token-tracker-plugin-design.md` — design spec
- `docs/superpowers/plans/2026-04-22-token-tracker-phase1-mvp.md` — implementation plan
- `lib/pricing.py` — static rate card (update when Anthropic prices change)
- `hooks/on_stop.py` — aggregation + output

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

```bash
pytest -v
```

38 tests across unit + e2e. Uses Python 3.10+ stdlib only.
