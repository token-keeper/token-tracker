from __future__ import annotations

from lib.aggregator import Summary


_MESSAGES = {
    "ko": {
        "summary": "비용 ${cost:.4f} · {tokens:,} toks · cache {cache}% · {elapsed:.1f}s",
    },
    "en": {
        "summary": "cost ${cost:.4f} · {tokens:,} toks · cache {cache}% · {elapsed:.1f}s",
    },
}


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
        elapsed=summary.total_elapsed,
    )
