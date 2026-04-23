from __future__ import annotations

from dataclasses import dataclass

from lib.aggregator import Summary
from lib.i18n_loader import load_strings
from lib.parser import TurnUsage
from lib.pricing import compute_cost


@dataclass
class Column:
    key: str         # i18n key for header label
    width: int       # visible character cells
    align: str       # "left" or "right"


_COLUMNS = [
    Column("col_index", 3, "right"),
    Column("col_model", 22, "left"),
    Column("col_tools", 20, "left"),
    Column("col_input", 8, "right"),
    Column("col_cc", 6, "right"),
    Column("col_cr", 7, "right"),
    Column("col_output", 8, "right"),
    Column("col_cost", 10, "right"),
    Column("col_time", 7, "right"),
]
_GAP = 2


def visual_width(s: str) -> int:
    """Return visible width on a monospace terminal, counting CJK as 2."""
    return sum(2 if ord(c) > 0x2E80 else 1 for c in s)


def _truncate(s: str, width: int) -> str:
    out = ""
    used = 0
    for c in s:
        cw = 2 if ord(c) > 0x2E80 else 1
        if used + cw > width - 3:
            return out + "..."
        out += c
        used += cw
    return out


def _pad(s: str, width: int, align: str) -> str:
    w = visual_width(s)
    if w > width:
        return _truncate(s, width)
    pad = " " * (width - w)
    return pad + s if align == "right" else s + pad


def _format_tools(tools: list[dict]) -> str:
    if not tools:
        return "—"
    rendered = [f"{t['name']}×{t['count']}" for t in tools]
    if len(rendered) <= 3:
        return ",".join(rendered)
    shown = rendered[:3]
    remainder = len(rendered) - 3
    return ",".join(shown) + f",...+{remainder}"


def _turn_time(turn: TurnUsage, next_turn: TurnUsage | None,
               prior_sum: float, total_elapsed: float) -> float | None:
    started = getattr(turn, "started_at", None)
    ended = getattr(turn, "ended_at", None)
    if started is not None and ended is not None:
        return max(0.0, ended - started)
    if started is not None and next_turn is not None:
        next_started = getattr(next_turn, "started_at", None)
        if next_started is not None:
            return max(0.0, next_started - started)
    if next_turn is None:
        remaining = total_elapsed - prior_sum
        return max(0.0, remaining)
    return None


def format_detail(summary: Summary, language: str) -> str:
    s = load_strings(language)

    if not summary.turns:
        return s["err_empty_turns"]

    cost_str = f"${summary.total_cost:.4f}"
    total_tokens = summary.total_input_tokens + summary.total_output_tokens
    cache_rate = f"{int(round(summary.cache_hit_rate * 100))}%"
    elapsed = f"{summary.total_elapsed:.1f}s"
    header_line = s["header_total"].format(
        cost=cost_str, tokens=f"{total_tokens:,}",
        rate=cache_rate, elapsed=elapsed,
    )

    header_cells = [_pad(s[c.key], c.width, c.align) for c in _COLUMNS]
    col_header_row = (" " * _GAP).join(header_cells)

    row_width = visual_width(col_header_row)
    rule_width = max(row_width, visual_width(header_line), visual_width(s["header_title"]))
    rule = "━" * rule_width

    rows: list[str] = []
    prior_sum = 0.0
    for i, turn in enumerate(summary.turns):
        next_turn = summary.turns[i + 1] if i + 1 < len(summary.turns) else None
        t_sec = _turn_time(turn, next_turn, prior_sum, summary.total_elapsed)
        t_str = f"{t_sec:.1f}s" if t_sec is not None else "?"
        if t_sec is not None:
            prior_sum += t_sec

        cost = f"${compute_cost(turn.model, turn):.4f}"
        cells = [
            str(turn.index + 1),
            turn.model,
            _format_tools(turn.tools_used),
            f"{turn.input_tokens:,}",
            f"{turn.cache_creation_tokens:,}",
            f"{turn.cache_read_tokens:,}",
            f"{turn.output_tokens:,}",
            cost,
            t_str,
        ]
        padded = [_pad(c, col.width, col.align) for c, col in zip(cells, _COLUMNS)]
        rows.append((" " * _GAP).join(padded))

    parts = [
        rule,
        " " + s["header_title"],
        " " + header_line,
        "",
        " " + col_header_row,
        *[" " + r for r in rows],
        rule,
        " " + s["legend"],
    ]
    return "\n".join(parts)
