from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path


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
_RESPONSE_CAP_BYTES = 50 * 1024


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


def _extract_response_text(transcript_entries: list[dict]) -> str:
    """Concatenate assistant_text bodies into a single response string,
    capped at 50KB to bound payload size."""
    parts: list[str] = []
    used = 0
    for e in transcript_entries:
        if e.get("type") != "assistant_text":
            continue
        text = str(e.get("text") or "")
        if not text:
            continue
        remaining = _RESPONSE_CAP_BYTES - used
        if remaining <= 0:
            break
        parts.append(text[:remaining])
        used += len(text)
    return "\n\n".join(parts)


def _flatten_entry(entry: dict) -> dict:
    """Map a history_store nested entry to the flat shape the design expects.

    Output keys: n, time, timeLabel, prompt, model, session, cost, in, out,
    cache, elapsed, response.
    """
    started_at = float(entry.get("started_at") or 0.0)
    summary = entry.get("summary") or {}
    user_prompt = entry.get("user_prompt") or {}
    models = entry.get("models_used") or []
    session_id = str(entry.get("session_id") or "")

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
        "response": _extract_response_text(entry.get("transcript_entries") or []),
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
