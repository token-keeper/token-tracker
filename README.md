<p align="center">
  <img src="assets/banner.png" alt="Token Tracker" width="420">
</p>

<p align="center">
  <strong>English</strong> · <a href="README.ko.md">한국어</a>
</p>

# Token Tracker

Claude Code plugin that displays per-request token cost on every `Stop`.

## What it shows

After every assistant response, a one-line summary appears below it:

```
cost $0.0180 · 1,546 toks · cache 85% · 12.3s
```

- **cost**: retail pay-per-token cost estimate for just this request.
- **toks**: total (input + output + cache_read) tokens consumed.
- **cache**: `cache_read / total_input` hit rate.
- **s**: wall-clock seconds from `UserPromptSubmit` to `Stop`.

## Detail view (verbose mode)

For a per-turn detail table at the end of every response, turn on verbose mode. The Stop hook then emits the one-line summary **plus** a per-turn breakdown:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Last request detail
 total $0.0180 | 1,546 toks | cache 85% | 12.3s

   #  model                   tools              input    cc       cr    output     cost      time
   1  opus-4-7[1m]            Read×3,Edit×1      120     400      800       450    $0.008     2.1s
   2  opus-4-7[1m]            —                   95       0    1,200       320    $0.006     3.5s
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Legend: cc=cache_creation, cr=cache_read
```

Three ways to toggle verbose mode:

### 1. Slash command (recommended)

```
/token-verbose on        # enable
/token-verbose off       # disable
/token-verbose status    # show current state (also works with no argument)
```

### 2. `config.json`

```json
{
  "language": "en",
  "verbose": true
}
```

### 3. Env var (one-off debugging)

```bash
export TOKEN_TRACKER_VERBOSE=1
```

All three paths emit via `systemMessage` directly from the hook, so output is **deterministic (no LLM in the loop) and costs zero tokens**.

## Cost is "retail" — it will not match the statusline

Claude Code's statusline `[💰 $X.XXX]` shows its **internal session-cumulative** cost tracker, which may reflect team/enterprise plan discounts or different cache-creation accounting. This plugin computes cost from Anthropic's **public pay-per-token rate card** (values hardcoded in `lib/pricing.py`).

Use this plugin's output as an **optimization signal** (did caching improve? is this prompt expensive relative to the last one?), not for billing.

## Token-saving tips

Patterns I've found useful while watching the numbers this plugin reports:

- **Claude Code keeps the prompt cache alive for ~1 hour by default.** If you step away for more than that, the cache expires and the next prompt is treated as a cold start.
- **Before a long break, run `/compact` or open a fresh session.** A compacted/empty context means the next "first prompt" rebuilds caches from a small base instead of the full conversation.
- **If you just resume a session after an hour idle, the entire accumulated context window goes through `cache creation` again** — that's the most expensive token tier and your usage will spike noticeably in a single turn. Watch for an unusually high `cost` / large `cc` count in the next line this plugin prints right after a long pause.

## Install

This repo is itself a self-contained Claude Code marketplace (`token-keeper`). Register it once with Claude Code and the hook fires regardless of which directory you run Claude Code from.

```bash
# Option A — register from GitHub (recommended)
/plugin marketplace add token-keeper/token-tracker

# Option B — point at a local clone (for development / offline use)
/plugin marketplace add /absolute/path/to/token-tracker

# Activate the plugin
/plugin install token-tracker@token-keeper
```

After activation, restart Claude Code. The Stop hook will then print a line like the one above after every response.

Disable: `/plugin disable token-tracker@token-keeper`
Uninstall: `/plugin uninstall token-tracker@token-keeper`

## Files of interest

- `docs/superpowers/specs/` — per-phase design specs
- `docs/superpowers/plans/` — per-phase implementation plans
- `docs/handoff/` — cross-session handoff notes
- `lib/pricing_data.json` — rate-card table (when Anthropic prices change, edit only the rows here and bump `fetched`)
- `lib/pricing.py` — JSON loader + cost computation (`compute_cost`, prefix-match resolver)
- `hooks/on_stop.py` — aggregation + output
- `lib/i18n/` — translated strings for ko/en

## Tests

From the repo root:

```bash
./venv/bin/pytest tests -q
```

436 tests across unit + integration + e2e (hook subprocess, skill script subprocess). Python 3.10+ stdlib only, pytest as the only dev dependency.
