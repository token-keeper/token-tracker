from __future__ import annotations

from lib.aggregator import Summary


_MESSAGES = {
    "ko": {
        "summary": "비용 ${cost:.4f} · {tokens:,} toks · cache {cache}% · {elapsed} · {turns} turns",
    },
    "en": {
        "summary": "cost ${cost:.4f} · {tokens:,} toks · cache {cache}% · {elapsed} · {turns} turns",
    },
}


def format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    rem_int = int(round(seconds - minutes * 60))
    if rem_int == 60:
        minutes += 1
        rem_int = 0
    return f"{minutes}m {rem_int}s"


def _select_lang(lang: str) -> str:
    return lang if lang in _MESSAGES else "en"


def format_summary(summary: Summary, lang: str) -> str:
    total_tokens = summary.total_input_tokens + summary.total_output_tokens
    cache_pct = int(round(summary.cache_hit_rate * 100))
    tpl = _MESSAGES[_select_lang(lang)]["summary"]
    return tpl.format(
        cost=summary.total_cost,
        tokens=total_tokens,
        cache=cache_pct,
        elapsed=format_elapsed(summary.total_elapsed),
        turns=len(summary.turns),
    )
