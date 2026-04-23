from lib.detail_formatter import format_detail, visual_width
from lib.aggregator import Summary
from lib.parser import TurnUsage


def _turn(**overrides):
    base = dict(
        model="claude-opus-4-7", input_tokens=100, output_tokens=50,
        cache_creation_tokens=0, cache_read_tokens=0,
        tools_used=[], timestamp_iso="", message_id="m",
        index=0,
    )
    base.update(overrides)
    return TurnUsage(**base)


def _summary(turns):
    return Summary(
        total_cost=0.01,
        total_input_tokens=sum(
            t.input_tokens + t.cache_read_tokens + t.cache_creation_tokens
            for t in turns
        ),
        total_output_tokens=sum(t.output_tokens for t in turns),
        cache_hit_rate=0.5, total_elapsed=10.0, turns=list(turns),
    )


def test_format_ko_contains_header_title():
    out = format_detail(_summary([_turn()]), "ko")
    assert "직전 request 상세" in out


def test_format_en_contains_header_title():
    out = format_detail(_summary([_turn()]), "en")
    assert "Last request detail" in out


def test_format_unknown_language_falls_back_to_en():
    out = format_detail(_summary([_turn()]), "zz")
    assert "Last request detail" in out


def test_empty_turns_shows_empty_turns_message():
    s = _summary([])
    out = format_detail(s, "ko")
    assert "응답이 없습니다" in out


def test_tool_with_counts_rendered():
    turn = _turn(tools_used=[{"name": "Read", "count": 3}, {"name": "Edit", "count": 1}])
    out = format_detail(_summary([turn]), "ko")
    assert "Read×3" in out
    assert "Edit×1" in out


def test_tools_empty_shows_dash():
    out = format_detail(_summary([_turn(tools_used=[])]), "ko")
    assert "—" in out


def test_tools_over_three_shows_ellipsis():
    turn = _turn(tools_used=[
        {"name": "A", "count": 1}, {"name": "B", "count": 1},
        {"name": "C", "count": 1}, {"name": "D", "count": 1},
        {"name": "E", "count": 1},
    ])
    out = format_detail(_summary([turn]), "ko")
    assert "...+2" in out


def test_long_model_name_truncated():
    long_name = "claude-opus-" + "x" * 30
    out = format_detail(_summary([_turn(model=long_name)]), "ko")
    assert "..." in out


def test_visual_width_hangul_counts_as_two():
    assert visual_width("abc") == 3
    assert visual_width("가나다") == 6
    assert visual_width("a가") == 3


def test_multi_turn_all_rows_present():
    turns = [
        _turn(index=0, model="opus", message_id="a"),
        _turn(index=1, model="sonnet", message_id="b"),
        _turn(index=2, model="haiku", message_id="c"),
    ]
    out = format_detail(_summary(turns), "ko")
    lines = out.splitlines()
    row_starts = [l.strip().split()[0] for l in lines if l.strip() and l.strip()[0].isdigit()]
    assert row_starts == ["1", "2", "3"]


def test_header_total_contains_summary_values():
    s = _summary([_turn()])
    s.total_cost = 0.0180
    s.total_elapsed = 12.3
    out = format_detail(s, "ko")
    assert "$0.0180" in out
    assert "12.3" in out


def test_legend_included():
    out = format_detail(_summary([_turn()]), "ko")
    assert "cc=cache_creation" in out
    out_en = format_detail(_summary([_turn()]), "en")
    assert "cc=cache_creation" in out_en
