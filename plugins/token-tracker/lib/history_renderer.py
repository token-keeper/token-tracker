from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from lib.pricing import compute_cost


_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills" / "token-history" / "templates" / "history.html.tmpl"
)
_CSS_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills" / "token-history" / "static" / "style.css"
)
_JS_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills" / "token-history" / "static" / "app.js"
)


_MODEL_NAME_RE = re.compile(r"^claude-([a-z]+)-(\d+)-(\d+)(?:[-\[].*)?$")
_TURN_TEXT_CAP_BYTES = 50 * 1024


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _safe_json_for_script(obj) -> str:
    """JSON-encode for inline <script> block.

    Two HTML5 script-data parser transitions can break out of the inline
    block with attacker-controlled string content:
      1. `</` → `</script>` close
      2. `<!--` → "script data escaped" state, then `<script>` flips to
         "script data double escaped" where the normal `</` escape is
         neutralized until a matching `</script>` (escaped) appears
    Both vectors are blocked by escaping every `<` as the JSON-spec valid
    `\\u003c`. The HTML5 script-data parser does not decode JSON unicode
    escapes, so neither `</` nor `<!--` ever materializes in the raw
    script body.
    """
    return (
        json.dumps(obj, ensure_ascii=False)
        .replace("<", "\\u003c")
    )


def _read_plugin_version() -> str:
    """Read version from plugin.json. Falls back to 'unknown'."""
    try:
        manifest = (
            Path(__file__).resolve().parent.parent
            / ".claude-plugin" / "plugin.json"
        )
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return data.get("version", "unknown")
    except Exception:
        return "unknown"


def _short_model_name(model: str) -> str:
    """`claude-opus-4-7[1m]` → `opus 4.7`. Mirrors detail_formatter logic."""
    if not model:
        return ""
    m = _MODEL_NAME_RE.match(model)
    if not m:
        return model
    family, major, minor = m.group(1), m.group(2), m.group(3)
    return f"{family} {major}.{minor}"


def _build_turn_cards(
    summary: dict, transcript_entries: list[dict], ended_at: float
) -> list[dict]:
    """Build per-turn cards by joining `summary.turns` with `transcript_entries`
    via timestamp ranges. Each turn N covers the half-open interval
    [turn[N].started_at, turn[N+1].started_at); the last turn extends to the
    prompt's `ended_at`. Returns the design-expected flat shape — see comment
    in `_flatten_entry`.
    """
    raw_turns = (summary or {}).get("turns") or []
    if not raw_turns:
        return []

    sorted_entries = sorted(
        transcript_entries or [], key=lambda e: float(e.get("ts") or 0.0)
    )

    cards: list[dict] = []
    for i, t in enumerate(raw_turns):
        t_start = float(t.get("started_at") or 0.0)
        if i + 1 < len(raw_turns):
            t_end = float(raw_turns[i + 1].get("started_at") or 0.0)
        else:
            t_end = float(ended_at or 0.0) if ended_at else float("inf")

        thinking_parts: list[str] = []
        assistant_parts: list[str] = []
        tool_calls_raw: list[dict] = []
        tool_results_raw: list[dict] = []
        for e in sorted_entries:
            ts = float(e.get("ts") or 0.0)
            if ts < t_start:
                continue
            if ts >= t_end and i + 1 < len(raw_turns):
                # Last-turn case (t_end == inf) keeps everything; for non-last
                # turns we stop at the next turn's boundary.
                break
            etype = e.get("type")
            if etype == "thinking":
                thinking_parts.append(str(e.get("text") or ""))
            elif etype == "assistant_text":
                assistant_parts.append(str(e.get("text") or ""))
            elif etype == "tool_call":
                tool_calls_raw.append({
                    "name": str(e.get("name") or ""),
                    "input": e.get("input") or {},
                    "tool_use_id": str(e.get("id") or ""),
                })
            elif etype == "tool_result":
                tool_results_raw.append({
                    "tool_use_id": str(e.get("tool_use_id") or ""),
                    "content": str(e.get("content") or "")[:_TURN_TEXT_CAP_BYTES],
                    "is_error": bool(e.get("is_error") or False),
                })

        # tool_use_id 기반 매칭 (call 순서대로 emit)
        results_by_id = {r["tool_use_id"]: r for r in tool_results_raw if r["tool_use_id"]}
        tool_pairs: list[dict] = []
        for c in tool_calls_raw:
            tuid = c["tool_use_id"]
            r = results_by_id.get(tuid)
            tool_pairs.append({
                "name": c["name"],
                "input": c["input"],
                "tool_use_id": tuid,
                "content": r["content"] if r else "",
                "is_error": r["is_error"] if r else False,
                "has_result": r is not None,
            })

        if i + 1 < len(raw_turns):
            elapsed = max(0.0, t_end - t_start)
        elif ended_at:
            elapsed = max(0.0, float(ended_at) - t_start)
        else:
            elapsed = 0.0

        usage_obj = SimpleNamespace(
            input_tokens=int(t.get("input_tokens") or 0),
            output_tokens=int(t.get("output_tokens") or 0),
            cache_creation_5m_tokens=int(t.get("cache_creation_5m_tokens") or 0),
            cache_creation_1h_tokens=int(t.get("cache_creation_1h_tokens") or 0),
            cache_read_tokens=int(t.get("cache_read_tokens") or 0),
        )
        model_id = str(t.get("model") or "")
        cost = compute_cost(model_id, usage_obj) if model_id else 0.0

        thinking_text = "\n\n".join(p for p in thinking_parts if p)[
            :_TURN_TEXT_CAP_BYTES
        ]
        assistant_text = "\n\n".join(p for p in assistant_parts if p)[
            :_TURN_TEXT_CAP_BYTES
        ]

        cards.append({
            "n": i + 1,
            "model": _short_model_name(model_id),
            "tools": list(t.get("tools_used") or []),
            "input": usage_obj.input_tokens,
            "cc": usage_obj.cache_creation_5m_tokens
                + usage_obj.cache_creation_1h_tokens,
            "cr": usage_obj.cache_read_tokens,
            "output": usage_obj.output_tokens,
            "cost": cost,
            "elapsed": elapsed,
            "thinking": thinking_text,
            "assistant_text": assistant_text,
            "tool_pairs": tool_pairs,
        })
    return cards


def _flatten_entry(entry: dict) -> dict:
    """Map a history_store nested entry to the flat shape the design expects.

    Output keys: n, time, timeLabel, prompt, model, session, cost, in, out,
    cache, elapsed, turns.
    """
    started_at = float(entry.get("started_at") or 0.0)
    ended_at = float(entry.get("ended_at") or 0.0)
    summary = entry.get("summary") or {}
    user_prompt = entry.get("user_prompt") or {}
    models = entry.get("models_used") or []
    session_id = str(entry.get("session_id") or "")
    transcript_entries = entry.get("transcript_entries") or []

    try:
        time_label = (
            datetime.fromtimestamp(started_at, tz=timezone.utc)
            .astimezone()
            .strftime("%H:%M")
        )
    except (ValueError, OSError, OverflowError):
        time_label = ""

    return {
        "n": str(entry.get("prompt_id") or ""),
        "time": started_at,
        "timeLabel": time_label,
        "prompt": str(user_prompt.get("text") or ""),
        "model": _short_model_name(models[0] if models else ""),
        "session": session_id[:8],
        "cost": float(summary.get("total_cost") or 0.0),
        "in": int(summary.get("total_input_tokens") or 0),
        "out": int(summary.get("total_output_tokens") or 0),
        "cache": float(summary.get("cache_hit_rate") or 0.0),
        "elapsed": float(summary.get("total_elapsed") or 0.0),
        "turns": _build_turn_cards(summary, transcript_entries, ended_at),
    }


def render_history_html(
    *, current: list[dict], all_sessions: list[dict], lang: str
) -> str:
    template = _read(_TEMPLATE_PATH)
    css = _read(_CSS_PATH)
    js = _read(_JS_PATH)

    generated_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    version = _read_plugin_version()

    flat_current = [_flatten_entry(e) for e in current]
    flat_all = [_flatten_entry(e) for e in all_sessions]

    replacements = {
        "__LANG__": lang if lang in ("ko", "en") else "en",
        "__GENERATED_AT__": generated_at,
        "__VERSION__": version,
        "__DATA_CURRENT__": _safe_json_for_script(flat_current),
        "__DATA_ALL__": _safe_json_for_script(flat_all),
        "__CSS__": css,
        "__JS__": js,
    }

    # Single-pass substitution. Chained str.replace would re-match placeholder
    # tokens that happen to appear inside an earlier replacement's payload
    # (e.g. user data containing literal "__DATA_ALL__"), corrupting JSON.
    pattern = re.compile("|".join(re.escape(k) for k in replacements))
    return pattern.sub(lambda m: replacements[m.group(0)], template)
