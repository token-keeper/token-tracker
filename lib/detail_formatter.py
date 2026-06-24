from __future__ import annotations

import os
import re
from dataclasses import dataclass

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
    align: str       # "left" or "right"


_COLUMNS = [
    Column("col_index", "right"),
    Column("col_model", "left"),
    Column("col_tools", "left"),
    Column("col_input_meta", "right"),
    Column("col_cc", "right"),
    Column("col_cr", "right"),
    Column("col_output", "right"),
    Column("col_cost", "right"),
    Column("col_time", "right"),
]
_MODEL_COL_INDEX = 1
_TOOLS_COL_INDEX = 2
_MODEL_COL_MAX_WIDTH = 35  # cap to keep table from growing absurdly wide
_TOOLS_COL_MAX_WIDTH = 28  # cap tools list so one busy turn can't blow up width
# Per-column hard caps. Numeric columns stay uncapped — their compact values
# (`_fmt_compact_number`) are already ≤~10 cells, so dynamic sizing alone keeps
# them tight. Only the two free-text columns can grow unbounded.
_COL_CAPS = {_MODEL_COL_INDEX: _MODEL_COL_MAX_WIDTH, _TOOLS_COL_INDEX: _TOOLS_COL_MAX_WIDTH}

# Numeric columns (input, cc, cr, output, cost, time). Index (#) and the two
# free-text columns are excluded.
_NUM_COL_INDICES = (3, 4, 5, 6, 7, 8)
# Minimum visible width for a numeric column, so short values ("2", "747") and
# narrow headers (cc/cr) still get a roomy cell instead of crowding together.
_NUM_MIN_WIDTH = 8

# Fallback one-line width used only when the real terminal width can't be
# detected (see `_detect_terminal_width`). Sized to fit common terminals once
# Claude Code's left gutter is accounted for.
_WIDTH_BUDGET = 100

# Cells reserved on the right: Claude Code renders the Stop hook's systemMessage
# with a small left gutter (~5 cells) plus our own 1-cell leading space, and we
# want a hair of breathing room so the table never wraps. Subtracted from the
# detected terminal width to get the table's target width.
_RENDER_MARGIN = 7
# Upper bound on table width when filling a detected terminal — keeps an
# ultrawide screen from scattering columns edge-to-edge.
_MAX_TABLE_WIDTH = 160


def _detect_terminal_width() -> int | None:
    """Best-effort real terminal width from inside a Stop hook.

    The hook runs as a subprocess whose stdout/stdin are pipes, so the usual
    `os.get_terminal_size()` returns the 80-col fallback. We instead:
      1. honour an explicit COLUMNS override, then
      2. ioctl the controlling pty directly via SSH_TTY / /dev/tty.
    Returns None when nothing reliable is found (caller then uses a fixed
    fallback budget and never expands — avoids wrapping on a wrong guess).
    """
    c = os.environ.get("COLUMNS")
    if c and c.isdigit() and int(c) > 0:
        return int(c)
    for path in (os.environ.get("SSH_TTY"), "/dev/tty"):
        if not path:
            continue
        try:
            fd = os.open(path, os.O_RDONLY)
            try:
                cols = os.get_terminal_size(fd).columns
            finally:
                os.close(fd)
            if cols > 0:
                return cols
        except OSError:
            continue
    return None


# Flex columns that absorb leftover budget — the two free-text columns whose
# content length is unbounded (model labels grow with subagent rows; tools
# lists grow with busy turns). Numeric columns stay content-sized.
_FLEX_COL_INDICES = (_MODEL_COL_INDEX, _TOOLS_COL_INDEX)


def _grow_flex_to_fill(widths: list[int], target: int) -> list[int]:
    """Distribute leftover budget across the flex columns (model + tools).

    The slack (target − minimal table width) is split between the two free-text
    columns in proportion to their current width, so the column that already
    holds more content grows more. Every other column stays content-sized and
    gaps stay tight at `_GAP`. No-op when there is no slack."""
    base = sum(widths) + _GAP * (len(widths) - 1) + 1  # +1 leading space
    slack = target - base
    if slack <= 0:
        return widths
    weight_total = sum(widths[i] for i in _FLEX_COL_INDICES)
    if weight_total <= 0:  # both empty — split evenly
        add, rem = divmod(slack, len(_FLEX_COL_INDICES))
        for k, i in enumerate(_FLEX_COL_INDICES):
            widths[i] += add + (1 if k < rem else 0)
        return widths
    given = 0
    for i in _FLEX_COL_INDICES[:-1]:
        share = slack * widths[i] // weight_total
        widths[i] += share
        given += share
    widths[_FLEX_COL_INDICES[-1]] += slack - given  # last col takes remainder
    return widths
# Min width a shrinkable text column may be cut to under budget pressure, so a
# truncated value ("...") still fits without overflowing the cell.
_MIN_TRUNC_WIDTH = 5
# Inter-column spacing. 2 cells keeps numbers from crowding; dynamic sizing
# already collapses the common row to ~60 cells so the gap costs little.
_GAP = 2


def _compute_widths(
    header_cells: list[str],
    body_rows: list[list[str]],
    caps: dict[int, int] | None = None,
) -> list[int]:
    """Per-column visible width = max(header label, all cell contents).

    When `caps` is given, free-text columns are clamped to their cap (used by
    the fixed-budget fallback so unbounded content can't blow up the table).
    When `caps` is None, columns are sized to full content — the real-terminal
    path relies on `_fit_to_budget` to shrink instead, so model/tools can show
    their full text whenever the terminal is wide enough."""
    caps = caps or {}
    widths: list[int] = []
    for ci in range(len(header_cells)):
        w = visual_width(header_cells[ci])
        for row in body_rows:
            cw = visual_width(row[ci])
            if cw > w:
                w = cw
        cap = caps.get(ci)
        if cap is not None and w > cap:
            w = cap
        if ci in _NUM_COL_INDICES and w < _NUM_MIN_WIDTH:
            w = _NUM_MIN_WIDTH  # floor so short numbers get a roomy cell
        widths.append(w)
    return widths


def _fit_to_budget(widths: list[int], header_cells: list[str], budget: int) -> list[int]:
    """Shrink flexible columns (tools, then model) until the table fits
    `budget`. Floors keep the header label readable and leave room for a
    truncation marker. Numeric columns are never shrunk — cutting them would
    corrupt the displayed values. If even the floors overflow, accept it (no
    safe further reduction exists)."""
    def total() -> int:
        return sum(widths) + _GAP * (len(widths) - 1) + 1  # +1 leading space

    for ci in (_TOOLS_COL_INDEX, _MODEL_COL_INDEX):
        over = total() - budget
        if over <= 0:
            break
        floor = max(visual_width(header_cells[ci]), _MIN_TRUNC_WIDTH)
        cut = min(over, widths[ci] - floor)
        if cut > 0:
            widths[ci] -= cut
    return widths


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


def _short_tool_name(name: str) -> str:
    """Compact display name for a tool.

    MCP tools arrive as `mcp__{server}__{tool}` (e.g.
    `mcp__claude_ai_Notion__notion-fetch`) which is far too wide for the
    column. Keep only the final `{tool}` segment (`notion-fetch`). Non-MCP
    names pass through unchanged.
    """
    if name.startswith("mcp__"):
        parts = name.split("__")
        if len(parts) >= 3 and parts[-1]:
            return parts[-1]
    return name


def _format_tools(tools: list[dict]) -> str:
    if not tools:
        return "—"
    rendered = [f"{_short_tool_name(t['name'])}×{t['count']}" for t in tools]
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
    columns = _COLUMNS
    header_cells = [s[c.key] for c in columns]

    # Pass 1: build every row's raw (unpadded) cells so column widths can be
    # sized to actual content, then fit to the one-line budget.
    body_rows: list[list[str]] = []
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
        body_rows.append([
            str(turn.index + 1),
            _short_model_name(turn.model),
            _format_tools(turn.tools_used),
            _fmt_compact_number(turn.input_tokens),
            _fmt_cc(turn.cache_creation_5m_tokens + turn.cache_creation_1h_tokens),
            _fmt_compact_number(turn.cache_read_tokens),
            _fmt_compact_number(turn.output_tokens),
            cost,
            t_str,
        ])

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
            body_rows.append([
                "",  # # column blank for child rows
                _sub_label(sub, sub_prefix),
                _format_tools(getattr(sub, "tools_used", [])),
                _fmt_compact_number(sub.input_tokens),
                _fmt_cc(sub.cache_creation_5m_tokens + sub.cache_creation_1h_tokens),
                _fmt_compact_number(sub.cache_read_tokens),
                _fmt_compact_number(sub.output_tokens),
                sub_cost,
                _sub_time_str(sub),
            ])

    # Pass 2: size columns to content. If the real terminal width is known,
    # target it (shrink if over, stretch gaps to fill if under) so the table
    # spans the full width edge-to-edge. Otherwise fall back to a fixed budget
    # and never stretch (a wrong guess would wrap).
    term_width = _detect_terminal_width()
    if term_width is not None:
        # Fill the detected width (minus gutter), but cap so an ultrawide
        # terminal doesn't scatter columns across the whole screen. Size flex
        # columns to full content (no caps), shrink to fit if over, then split
        # any leftover between model + tools so both grow dynamically.
        widths = _compute_widths(header_cells, body_rows)
        target = min(term_width - _RENDER_MARGIN, _MAX_TABLE_WIDTH)
        widths = _fit_to_budget(widths, header_cells, budget=target)
        widths = _grow_flex_to_fill(widths, target)
        gaps = [_GAP] * (len(widths) - 1)
    else:
        widths = _compute_widths(header_cells, body_rows, caps=_COL_CAPS)
        widths = _fit_to_budget(widths, header_cells, budget=_WIDTH_BUDGET)
        gaps = [_GAP] * (len(widths) - 1)

    def _render(cells: list[str]) -> str:
        padded = [
            _pad(c, w, col.align) for c, w, col in zip(cells, widths, columns)
        ]
        out = padded[0] if padded else ""
        for i in range(1, len(padded)):
            out += " " * gaps[i - 1] + padded[i]
        return out

    col_header_row = _render(header_cells)
    rows = [_render(c) for c in body_rows]

    row_width = visual_width(col_header_row)
    rule_width = max(row_width, visual_width(s["header_title"]))
    rule = "━" * rule_width

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
