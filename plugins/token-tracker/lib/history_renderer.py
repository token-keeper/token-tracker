from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from lib.i18n_loader import load_strings


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
    Both vectors are blocked here. Trust boundary is the local user, but
    spec §1.4 acknowledges tool_result content can include adversarial
    file content, so we harden by default.
    """
    return (
        json.dumps(obj, ensure_ascii=False)
        .replace("</", "<\\/")
        .replace("<!--", "<\\!--")
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


def render_history_html(
    *, current: list[dict], all_sessions: list[dict], lang: str
) -> str:
    s = load_strings(lang)
    template = _read(_TEMPLATE_PATH)
    css = _read(_CSS_PATH)
    js = _read(_JS_PATH)

    generated_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    version = _read_plugin_version()

    i18n_subset = {k: s[k] for k in s if k.startswith((
        "tab_", "col_history_", "search_", "filter_", "expand_",
        "total_label", "no_data_message", "opened_url",
        "html_title", "html_generated_at", "html_version_label",
    ))}

    replacements = {
        "__LANG__": lang if lang in ("ko", "en") else "en",
        "__HTML_TITLE__": s["html_title"],
        "__GENERATED_AT__": s["html_generated_at"].format(ts=generated_at),
        "__VERSION_LABEL__": s["html_version_label"].format(version=version),
        "__TAB_CURRENT__": s["tab_current"].format(n=len(current)),
        "__TAB_ALL__": s["tab_all"].format(n=len(all_sessions)),
        "__SEARCH_PLACEHOLDER__": s["search_placeholder"],
        "__FILTER_MODEL_ALL__": s["filter_model_all"],
        "__FILTER_SESSION_ALL__": s["filter_session_all"],
        "__NO_DATA_MESSAGE__": s["no_data_message"],
        "__DATA_CURRENT__": _safe_json_for_script(current),
        "__DATA_ALL__": _safe_json_for_script(all_sessions),
        "__I18N_JSON__": _safe_json_for_script(i18n_subset),
        "__CSS__": css,
        "__JS__": js,
    }

    out = template
    for k, v in replacements.items():
        out = out.replace(k, v)
    return out
