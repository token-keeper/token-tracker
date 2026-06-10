from __future__ import annotations

import re
from dataclasses import dataclass, replace

from lib.aggregator import Summary
from lib.formatter import format_elapsed
from lib.i18n_loader import load_strings
from lib.parser import SubagentUsage, TurnUsage
from lib.pricing import compute_cost, effective_billing_model, is_known_model


# Sub-row label prefix for the agent_type. Kept as a module constant rather
# than i18n key — the literal "sub:" reads identically in ko/en (KISS).
_SUB_LABEL = "sub:"

# Pattern for `claude-{family}-{major}[-{minor}]` with optional date/variant
# suffix. Used by `_short_model_name` to render compact labels like
# "opus 4.7" / "fable 5" / "haiku 4.5" in the model column.
# minor 는 optional (claude-fable-5 처럼 단일 버전 모델). 버전 숫자는 1~2자리로
# 제한해 8자리 date suffix (-20250514) 가 minor 로 오인되지 않게 한다.
_MODEL_NAME_RE = re.compile(r"^claude-([a-z]+)-(\d{1,2})(?:-(\d{1,2}))?(?:[-\[].*)?$")


def _short_model_name(model: str) -> str:
    """Compact display name for a Claude model id.

    Examples:
        claude-opus-4-7              -> opus 4.7
        claude-opus-4-7[1m]          -> opus 4.7
        claude-fable-5               -> fable 5
        claude-fable-5[1m]           -> fable 5
        claude-sonnet-4-6-20250101   -> sonnet 4.6
        claude-haiku-4-5-20251001    -> haiku 4.5
        unknown                      -> unknown (passthrough)
    """
    if not model:
        return ""
    m = _MODEL_NAME_RE.match(model)
    if not m:
        return model
    family, major, minor = m.group(1), m.group(2), m.group(3)
    return f"{family} {major}.{minor}" if minor else f"{family} {major}"


@dataclass
class Column:
    key: str         # i18n key for header label
    width: int       # visible character cells
    align: str       # "left" or "right"


_COLUMNS = [
    Column("col_index", 3, "right"),
    Column("col_model", 15, "left"),
    Column("col_tools", 25, "left"),
    Column("col_input_meta", 10, "right"),
    Column("col_cc", 6, "right"),
    Column("col_cr", 7, "right"),
    Column("col_output", 8, "right"),
    Column("col_cost", 10, "right"),
    Column("col_time", 7, "right"),
]
_MODEL_COL_INDEX = 1
_MODEL_COL_MAX_WIDTH = 35  # cap to keep table from growing absurdly wide
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


def _fmt_compact_number(n: int, *, low_threshold: bool = False) -> str:
    """Compact token-count display, output ≤6 visible chars to fit table cells.

    Default thresholds (low_threshold=False):
        < 10,000           : comma (e.g. "9,999")
        10,000~99,994      : "NN.NNK" (2 decimals)
        99,995~999,949     : "NNN.NK" (1 decimal — keeps to 6 chars)
        999,950~99,994,999 : promote to M, same adaptive precision
        99,995,000~        : promote to B

    low_threshold=True (used by cc column): K suffix starts at 1,000 so
    cache_creation values like 1,234 render as "1.23K" instead of "1,234".
    """
    if low_threshold and 1_000 <= n < 10_000:
        return f"{n / 1_000:.2f}K"
    if n < 10_000:
        return f"{n:,}"
    if n < 1_000_000:
        scaled = n / 1_000
        if scaled < 99.995:
            return f"{scaled:.2f}K"
        if scaled < 999.95:
            return f"{scaled:.1f}K"
        return f"{n / 1_000_000:.2f}M"  # promote to keep ≤6 chars
    if n < 1_000_000_000:
        scaled = n / 1_000_000
        if scaled < 99.995:
            return f"{scaled:.2f}M"
        if scaled < 999.95:
            return f"{scaled:.1f}M"
        return f"{n / 1_000_000_000:.2f}B"
    scaled = n / 1_000_000_000
    if scaled < 99.995:
        return f"{scaled:.2f}B"
    return f"{scaled:.1f}B"


def _fmt_cc(n: int) -> str:
    """cc 컬럼 전용 — 1,000 이상이면 K 표기 (예: 1.23K)."""
    return _fmt_compact_number(n, low_threshold=True)


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


def _sub_label(sub: SubagentUsage, prefix: str) -> str:
    """Render the sub row's model-column label.

    Format:
        - model known: "{prefix}sub: {agent_type} [{short_model}]"
        - model unknown: "{prefix}sub: {agent_type}"  (no brackets)

    Brackets are dropped when model is empty so the row visibly signals
    "this is the parent-model fallback" instead of showing "[]".
    """
    name = sub.agent_type if sub.agent_type else "(unknown)"
    short = _short_model_name(getattr(sub, "model", ""))
    if short:
        return f"{prefix}{_SUB_LABEL} {name} [{short}]"
    return f"{prefix}{_SUB_LABEL} {name}"


def _sub_time_str(sub: SubagentUsage) -> str:
    if sub.total_duration_ms and sub.total_duration_ms > 0:
        return format_elapsed(sub.total_duration_ms / 1000)
    return "-"


def format_detail(summary: Summary, language: str) -> str:
    s = load_strings(language)

    if not summary.turns:
        return s["err_empty_turns"]

    sub_prefix = s["subagent_row_prefix"]

    # Compute dynamic model column width: max of header label, all turn
    # model strings, and all subagent labels (with prefix). Floor at the
    # default Column width so existing tests keep their truncation behavior.
    model_default_width = _COLUMNS[_MODEL_COL_INDEX].width
    candidates: list[str] = [s["col_model"]]
    for turn in summary.turns:
        candidates.append(_short_model_name(turn.model))
        for sub in turn.subagents:
            candidates.append(_sub_label(sub, sub_prefix))
    needed_width = max(visual_width(c) for c in candidates)
    dynamic_model_width = min(
        _MODEL_COL_MAX_WIDTH, max(model_default_width, needed_width)
    )

    # Build the resolved column list with the dynamic model width applied.
    columns = list(_COLUMNS)
    columns[_MODEL_COL_INDEX] = replace(
        columns[_MODEL_COL_INDEX], width=dynamic_model_width
    )

    header_cells = [_pad(s[c.key], c.width, c.align) for c in columns]
    col_header_row = (" " * _GAP).join(header_cells)

    row_width = visual_width(col_header_row)
    rule_width = max(row_width, visual_width(s["header_title"]))
    rule = "━" * rule_width

    rows: list[str] = []
    prior_sum = 0.0
    has_subagents = False
    has_unknown_sub_model = False
    for i, turn in enumerate(summary.turns):
        next_turn = summary.turns[i + 1] if i + 1 < len(summary.turns) else None
        t_sec = _turn_time(turn, next_turn, prior_sum, summary.total_elapsed)
        t_str = format_elapsed(t_sec) if t_sec is not None else "?"
        if t_sec is not None:
            prior_sum += t_sec

        cost = f"${compute_cost(turn.model, turn):.4f}"
        cells = [
            str(turn.index + 1),
            _short_model_name(turn.model),
            _format_tools(turn.tools_used),
            _fmt_compact_number(turn.input_tokens),
            _fmt_cc(turn.cache_creation_5m_tokens + turn.cache_creation_1h_tokens),
            _fmt_compact_number(turn.cache_read_tokens),
            _fmt_compact_number(turn.output_tokens),
            cost,
            t_str,
        ]
        padded = [_pad(c, col.width, col.align) for c, col in zip(cells, columns)]
        rows.append((" " * _GAP).join(padded))

        # Child rows for subagents under this parent turn.
        for sub in turn.subagents:
            has_subagents = True
            sub_model = getattr(sub, "model", "")
            # Treat both empty model and unknown aliases (e.g. "sonnet" from
            # `Agent(model="sonnet")` dispatch) as "unknown" for the legend
            # — both billing paths actually use the parent model rate.
            if not is_known_model(sub_model):
                has_unknown_sub_model = True
            # Cost: same fallback rule as aggregator (single helper).
            billing_model = effective_billing_model(sub_model, turn.model)
            sub_cost = f"${compute_cost(billing_model, sub):.4f}"
            sub_cells = [
                "",  # # column blank for child rows
                _sub_label(sub, sub_prefix),
                "",  # tools column blank for child rows (T6 future)
                _fmt_compact_number(sub.input_tokens),
                _fmt_cc(sub.cache_creation_5m_tokens + sub.cache_creation_1h_tokens),
                _fmt_compact_number(sub.cache_read_tokens),
                _fmt_compact_number(sub.output_tokens),
                sub_cost,
                _sub_time_str(sub),
            ]
            sub_padded = [
                _pad(c, col.width, col.align) for c, col in zip(sub_cells, columns)
            ]
            rows.append((" " * _GAP).join(sub_padded))

    parts = [
        rule,
        " " + s["header_title"],
        "",
        " " + col_header_row,
        *[" " + r for r in rows],
        rule,
        " " + s["legend"],
    ]
    # Show "* subagent cost is estimated from parent model rate" only when
    # at least one sub has an unknown model (so the disclaimer is accurate).
    # If every sub model is known, billing is exact and the note would be wrong.
    if has_subagents and has_unknown_sub_model:
        parts.append(" " + s["subagent_legend"])
    return "\n".join(parts)
