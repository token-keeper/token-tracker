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

## Install (local dev)

Hooks are registered via `.claude/settings.local.json` in this repo. When Claude Code is launched from this directory (or a subdir), the hooks fire automatically.

For permanent install, see Phase 2 (local marketplace packaging) — not yet shipped.

## Tests

```bash
pytest -v
```

38 tests across unit + e2e. Uses Python 3.10+ stdlib only.
