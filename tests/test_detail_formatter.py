from lib.detail_formatter import format_detail, visual_width
from lib.aggregator import Summary
from lib.parser import SubagentUsage, TurnUsage
from lib.pricing import compute_cost


def _turn(**overrides):
    # Phase D 마이그레이션 편의: legacy 호출이 cache_creation_tokens=N으로
    # 호출하면 보수적으로 5m tier(가격 동일)에 매핑.
    if "cache_creation_tokens" in overrides:
        overrides["cache_creation_5m_tokens"] = overrides.pop("cache_creation_tokens")
    base = dict(
        model="claude-opus-4-7", input_tokens=100, output_tokens=50,
        cache_creation_5m_tokens=0, cache_creation_1h_tokens=0,
        cache_read_tokens=0,
        tools_used=[], timestamp_iso="", message_id="m",
        index=0,
    )
    base.update(overrides)
    return TurnUsage(**base)


def _summary(turns):
    return Summary(
        total_cost=0.01,
        total_input_tokens=sum(
            t.input_tokens + t.cache_read_tokens
            + t.cache_creation_5m_tokens + t.cache_creation_1h_tokens
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


def test_many_tools_all_shown_via_wrap(monkeypatch):
    # 툴이 많아도 (+N 축약 없이) 전부 표시된다 — 넓은 터미널이면 한 줄,
    # 좁으면 개행(wrap)으로 흐른다.
    monkeypatch.setenv("COLUMNS", "160")
    turn = _turn(tools_used=[
        {"name": "A", "count": 1}, {"name": "B", "count": 1},
        {"name": "C", "count": 1}, {"name": "D", "count": 1},
        {"name": "E", "count": 1},
    ])
    out = format_detail(_summary([turn]), "ko")
    for name in ("A×1", "B×1", "C×1", "D×1", "E×1"):
        assert name in out
    assert "...+" not in out  # 축약 폐기됨


def test_long_model_name_truncated(monkeypatch):
    # 좁은 터미널에선 긴 모델명이 들어갈 자리가 없어 잘린다 (동적 width 하에서
    # 트렁케이션은 '안 들어갈 때만' 발생).
    monkeypatch.setenv("COLUMNS", "60")
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


def test_header_does_not_duplicate_total_cost():
    """v0.x: header_total 라인 제거됨 — 같은 정보가 format_summary로 위에
    이미 표시되어 verbose 출력 시 중복이었기 때문. header_title은 유지."""
    s = _summary([_turn()])
    s.total_cost = 0.0180
    out = format_detail(s, "ko")
    assert "직전 request 상세" in out
    assert "총 비용 $" not in out  # header_total line gone


def test_legend_included():
    out = format_detail(_summary([_turn()]), "ko")
    assert "cc=cache_creation" in out
    out_en = format_detail(_summary([_turn()]), "en")
    assert "cc=cache_creation" in out_en


def _sub(**overrides):
    # Phase D 마이그레이션 편의: legacy 호출이 cache_creation_tokens=N으로
    # 호출하면 보수적으로 5m tier(가격 동일)에 매핑.
    if "cache_creation_tokens" in overrides:
        overrides["cache_creation_5m_tokens"] = overrides.pop("cache_creation_tokens")
    base = dict(
        agent_type="claude-code-guide",
        tool_use_id="tu-1",
        input_tokens=4,
        output_tokens=368,
        cache_creation_5m_tokens=10506,
        cache_creation_1h_tokens=0,
        cache_read_tokens=23497,
        total_duration_ms=19500,
    )
    base.update(overrides)
    return SubagentUsage(**base)


def test_detail_renders_subagent_row_under_parent():
    turn = _turn()
    turn.subagents = [_sub(agent_type="claude-code-guide")]
    out = format_detail(_summary([turn]), "ko")
    lines = out.splitlines()
    # find the parent row (starts with "1") and assert next non-empty line
    # contains the subagent prefix + agent_type.
    parent_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("1 ") or stripped.startswith("1\t") or stripped == "1":
            parent_idx = i
            break
        # row begins with index — first token is "1"
        toks = stripped.split()
        if toks and toks[0] == "1":
            parent_idx = i
            break
    assert parent_idx is not None, f"parent row not found in:\n{out}"
    child_line = lines[parent_idx + 1]
    assert "└" in child_line
    assert "claude-code-guide" in child_line


def test_detail_renders_multiple_subagents_under_same_parent():
    turn = _turn()
    turn.subagents = [
        _sub(agent_type="general-purpose", tool_use_id="tu-a"),
        _sub(agent_type="general-purpose", tool_use_id="tu-b"),
    ]
    out = format_detail(_summary([turn]), "ko")
    lines = out.splitlines()
    child_lines = [l for l in lines if "└" in l]
    assert len(child_lines) == 2
    for cl in child_lines:
        assert "general-purpose" in cl


def test_detail_subagent_legend_only_when_subagents_present():
    legend_text = "subagent 비용은 부모 모델 단가로 추정"

    # Without subagents: legend should NOT be present
    out_no = format_detail(_summary([_turn()]), "ko")
    assert legend_text not in out_no

    # With subagents: legend present
    turn = _turn()
    turn.subagents = [_sub()]
    out_yes = format_detail(_summary([turn]), "ko")
    assert legend_text in out_yes


def test_detail_subagent_cost_uses_parent_model_rate():
    turn = _turn(model="claude-opus-4-7")
    sub = _sub(
        input_tokens=4,
        output_tokens=368,
        cache_creation_tokens=10506,
        cache_read_tokens=23497,
    )
    turn.subagents = [sub]
    expected_cost = compute_cost("claude-opus-4-7", sub)
    expected_str = f"${expected_cost:.4f}"

    out = format_detail(_summary([turn]), "ko")
    lines = out.splitlines()
    child_line = next(l for l in lines if "└" in l)
    assert expected_str in child_line


def test_detail_table_alignment_with_subagent_rows():
    # When the subagent agent_type is long, the model column width must
    # expand so all rows (parent and child) align.
    long_name = "really-long-agent-type-name"
    turn = _turn(model="opus")
    turn.subagents = [_sub(agent_type=long_name)]
    out = format_detail(_summary([turn]), "ko")
    lines = out.splitlines()

    # Identify the rows: header row (col_header), parent row, child row.
    # All non-empty rows that aren't decoration ("━") should have equal
    # visual width.
    body_rows = [
        l for l in lines
        if l and not l.startswith("━") and "━" not in set(l)
    ]
    # Filter to rows that contain the model column content (parent or child).
    parent_row = next(l for l in body_rows if "opus" in l and "└" not in l)
    child_row = next(l for l in body_rows if "└" in l)
    assert visual_width(parent_row) == visual_width(child_row)


# ---------------------------------------------------------------------------
# T12: sub 행 model 표시 + 정확 비용
# ---------------------------------------------------------------------------


def test_subagent_row_model_column_shows_sub_model(monkeypatch):
    """sub.model이 채워지면 모델 컬럼은 '└ sub: {short}', agent_type 은 툴 컬럼
    첫 줄로 분리된다 (대괄호 형식 폐기)."""
    monkeypatch.setenv("COLUMNS", "140")
    turn = _turn()
    turn.subagents = [_sub(agent_type="general-purpose")]
    turn.subagents[0].model = "claude-sonnet-4-6"
    out = format_detail(_summary([turn]), "ko")
    child_line = next(l for l in out.splitlines() if "└" in l)
    assert "sub: sonnet 4.6" in child_line   # 모델 컬럼
    assert "general-purpose" in child_line    # agent_type = 툴 컬럼 첫 줄
    assert "[sonnet 4.6]" not in child_line   # 대괄호 형식 폐기


def test_subagent_row_shows_question_mark_when_model_unknown(monkeypatch):
    """sub.model이 빈 문자열이면 모델 컬럼은 '└ sub: ?' (부모 단가 폴백 신호)."""
    monkeypatch.setenv("COLUMNS", "140")
    turn = _turn()
    turn.subagents = [_sub(agent_type="general-purpose")]
    turn.subagents[0].model = ""
    out = format_detail(_summary([turn]), "ko")
    child_line = next(l for l in out.splitlines() if "└" in l)
    assert "sub: ?" in child_line
    assert "general-purpose" in child_line  # agent_type 은 툴 컬럼
    assert "[" not in child_line


def test_legend_omitted_when_all_sub_models_known():
    """모든 sub model이 알려진 경우 sub legend(추정 안내)는 출력되지 않는다."""
    turn = _turn()
    sub = _sub(agent_type="general-purpose")
    sub.model = "claude-haiku-4-5"
    turn.subagents = [sub]
    out_ko = format_detail(_summary([turn]), "ko")
    assert "subagent 비용은 부모 모델 단가로 추정" not in out_ko
    out_en = format_detail(_summary([turn]), "en")
    assert "estimated using parent model rate" not in out_en


def test_legend_present_when_any_sub_model_unknown():
    """하나라도 model이 비면 legend(추정 안내)는 표시된다."""
    turn = _turn()
    s1 = _sub(agent_type="agent-a", tool_use_id="tu-a")
    s1.model = "claude-haiku-4-5"
    s2 = _sub(agent_type="agent-b", tool_use_id="tu-b")
    s2.model = ""  # unknown
    turn.subagents = [s1, s2]
    out = format_detail(_summary([turn]), "ko")
    assert "subagent 비용은 부모 모델 단가로 추정" in out


def test_short_model_name_normalizes_known_ids():
    from lib.detail_formatter import _short_model_name

    assert _short_model_name("claude-opus-4-7") == "opus 4.7"
    assert _short_model_name("claude-opus-4-7[1m]") == "opus 4.7"
    assert _short_model_name("claude-sonnet-4-6") == "sonnet 4.6"
    assert _short_model_name("claude-sonnet-4-6-20250101") == "sonnet 4.6"
    assert _short_model_name("claude-haiku-4-5-20251001") == "haiku 4.5"
    # 단일 버전 모델 (minor 없음) — claude-fable-5
    assert _short_model_name("claude-fable-5") == "fable 5"
    assert _short_model_name("claude-fable-5[1m]") == "fable 5"
    # date suffix 가 minor 로 오인되면 안 됨 — claude-opus-4-20250514
    assert _short_model_name("claude-opus-4-20250514") == "opus 4"
    # unknown → original
    assert _short_model_name("some-other-model") == "some-other-model"
    # empty → empty
    assert _short_model_name("") == ""


def test_detail_subagent_cost_uses_sub_model_rate_when_set():
    """sub.model이 있으면 표시 비용도 sub 단가 기준."""
    turn = _turn(model="claude-opus-4-7")
    sub = _sub(input_tokens=1_000_000, output_tokens=0,
               cache_creation_tokens=0, cache_read_tokens=0)
    sub.model = "claude-haiku-4-5"
    turn.subagents = [sub]
    out = format_detail(_summary([turn]), "ko")
    child_line = next(l for l in out.splitlines() if "└" in l)
    # haiku input rate = $1.0/MTok → $1.0000
    assert "$1.0000" in child_line


def test_detail_short_alias_sub_model_uses_latest_family_rate_for_row_cost():
    """v0.11.0 변경 — short alias sub.model 이 family-prefix latest 단가로 청구.

    이전 동작: sub.model="sonnet" → unknown → parent opus rate ($5).
    신 동작: alias 자동 탐지 → latest sonnet rate ($3) 로 정확 청구.
    """
    turn = _turn(model="claude-opus-4-7")
    sub = _sub(input_tokens=1_000_000, output_tokens=0,
               cache_creation_tokens=0, cache_read_tokens=0)
    sub.model = "sonnet"  # short alias → latest sonnet 자동 매핑
    turn.subagents = [sub]
    out = format_detail(_summary([turn]), "ko")
    child_line = next(l for l in out.splitlines() if "└" in l)
    # latest sonnet input rate = $3.0/MTok → $3.0000 (NOT parent opus $5.0000)
    assert "$3.0000" in child_line, f"expected latest sonnet rate in: {child_line!r}"


def test_detail_formatter_renders_with_5m_1h_fields():
    """detail_formatter가 신규 5m/1h 필드를 합산해 cache 칼럼에 표시.
    Phase B에서 cache_creation_tokens 필드 제거 후 AttributeError 회귀 가드."""
    summary = Summary(
        total_cost=1.0, total_input_tokens=1000, total_output_tokens=100,
        cache_hit_rate=0.5, total_elapsed=2.0,
        turns=[TurnUsage(
            model="claude-opus-4-7", input_tokens=10, output_tokens=20,
            cache_creation_5m_tokens=300, cache_creation_1h_tokens=200,
            cache_read_tokens=50, message_id="m1",
        )],
    )
    text = format_detail(summary, "ko")
    # cache 칼럼이 합산 500을 표시 (5m 300 + 1h 200)
    assert "500" in text


def test_detail_no_legend_when_short_alias_resolves_to_latest_family():
    """v0.11.0 변경 — short alias 가 정확한 latest family 단가로 청구되므로
    "부모 단가 추정" legend 가 더 이상 표시되지 않음. legend 는 진짜 unknown
    (family 도 매칭 안 되는) 케이스에서만 출력."""
    turn = _turn()
    sub = _sub(agent_type="general-purpose")
    sub.model = "sonnet"  # alias 자동 탐지로 known 처리
    turn.subagents = [sub]
    out_ko = format_detail(_summary([turn]), "ko")
    assert "subagent 비용은 부모 모델 단가로 추정" not in out_ko, (
        f"alias 가 known 으로 해석되면 legend 안 나와야 함; got:\n{out_ko}"
    )


def test_detail_legend_present_when_sub_model_is_truly_unknown():
    """진짜 unknown 모델 ('claude-future-99' 같은 family 매칭 안 되는 id) 에서는
    legend 표시 — parent rate 로 fallback 되었음을 안내."""
    turn = _turn()
    sub = _sub(agent_type="general-purpose")
    sub.model = "claude-future-99"  # family alias 도 매칭 안 됨 → unknown
    turn.subagents = [sub]
    out_ko = format_detail(_summary([turn]), "ko")
    assert "subagent 비용은 부모 모델 단가로 추정" in out_ko, (
        f"truly unknown model should trigger legend; got:\n{out_ko}"
    )


# --- K/M compact number formatting ---

def test_fmt_compact_number_under_10k_uses_comma():
    from lib.detail_formatter import _fmt_compact_number
    assert _fmt_compact_number(0) == "0"
    assert _fmt_compact_number(123) == "123"
    assert _fmt_compact_number(1500) == "1,500"
    assert _fmt_compact_number(9999) == "9,999"


def test_fmt_compact_number_low_threshold_uses_K_at_1000():
    """cc 컬럼용: 1,000 이상이면 K 표기 (예: 1.50K)."""
    from lib.detail_formatter import _fmt_compact_number
    assert _fmt_compact_number(999, low_threshold=True) == "999"
    assert _fmt_compact_number(1_000, low_threshold=True) == "1.00K"
    assert _fmt_compact_number(1_234, low_threshold=True) == "1.23K"
    assert _fmt_compact_number(9_999, low_threshold=True) == "10.00K"
    # 10K 이상은 기존 동작과 동일
    assert _fmt_compact_number(12_345, low_threshold=True) == "12.35K"


def test_format_detail_cc_column_uses_K_when_over_1000():
    """cc 값이 1,000 ~ 9,999 범위에 있을 때 K 표기로 출력되는지 회귀 가드."""
    turn = _turn(cache_creation_5m_tokens=1_234)
    out = format_detail(_summary([turn]), "ko")
    assert "1.23K" in out
    assert "1,234" not in out


def test_format_detail_input_column_label_renamed_from_input_meta():
    """v0.x: input-meta → input 라벨 변경."""
    out_ko = format_detail(_summary([_turn()]), "ko")
    assert "input-meta" not in out_ko
    out_en = format_detail(_summary([_turn()]), "en")
    assert "input-meta" not in out_en


def test_fmt_compact_number_thousands_uses_K():
    from lib.detail_formatter import _fmt_compact_number
    assert _fmt_compact_number(10_000) == "10.00K"   # 6 chars
    assert _fmt_compact_number(12_345) == "12.35K"   # 6 chars
    assert _fmt_compact_number(99_994) == "99.99K"   # 2-decimal upper bound
    assert _fmt_compact_number(99_995) == "100.0K"   # promote precision: 6 chars
    assert _fmt_compact_number(421_180) == "421.2K"  # 6 chars (1-decimal)
    assert _fmt_compact_number(999_949) == "999.9K"  # last K value
    assert _fmt_compact_number(999_950) == "1.00M"   # promote to M
    assert _fmt_compact_number(999_999) == "1.00M"


def test_fmt_compact_number_millions_uses_M():
    from lib.detail_formatter import _fmt_compact_number
    assert _fmt_compact_number(1_000_000) == "1.00M"
    assert _fmt_compact_number(1_500_000) == "1.50M"
    assert _fmt_compact_number(12_345_678) == "12.35M"
    assert _fmt_compact_number(421_000_000) == "421.0M"  # 1-decimal


def test_fmt_compact_number_billions_uses_B():
    from lib.detail_formatter import _fmt_compact_number
    assert _fmt_compact_number(1_000_000_000) == "1.00B"
    assert _fmt_compact_number(2_500_000_000) == "2.50B"


def test_format_detail_uses_compact_for_large_cache_creation():
    """Regression for the user-reported `421...` truncation."""
    turn = _turn(input_tokens=6, cache_creation_5m_tokens=421_180,
                 cache_creation_1h_tokens=0, cache_read_tokens=15_526,
                 output_tokens=2_144)
    out = format_detail(_summary([turn]), "ko")
    assert "421.2K" in out  # adaptive precision (was "421...")
    assert "15.53K" in out  # cache_read_tokens
    assert "421..." not in out  # truncation gone


def test_format_detail_uses_minute_format_for_long_elapsed():
    s = _summary([_turn()])
    s.total_elapsed = 125.0
    out = format_detail(s, "ko")
    assert "2m 5s" in out
    assert "125.0s" not in out


def test_format_detail_renders_all_turn_rows():
    """header_total 라인이 없어진 뒤에도 turn row가 모두 렌더되는지 확인."""
    turns = [_turn(index=0, message_id="a"), _turn(index=1, message_id="b"),
             _turn(index=2, message_id="c"), _turn(index=3, message_id="d")]
    out = format_detail(_summary(turns), "ko")
    lines = out.splitlines()
    row_starts = [
        l.strip().split()[0] for l in lines
        if l.strip() and l.strip()[0].isdigit()
    ]
    assert row_starts == ["1", "2", "3", "4"]


def test_flex_columns_absorb_terminal_slack_numeric_tail_fixed(monkeypatch):
    """넓은 터미널에서 슬랙은 flex 컬럼(모델+툴)이 흡수한다 — 숫자 컬럼은
    content-sized, 간격(_GAP)도 고정. 따라서 첫 숫자 컬럼부터 행 끝까지의 tail
    문자열은 터미널 폭과 무관하게 동일하고, 모델/툴만 넓어져 행이 길어진다."""
    turn = _turn(
        model="claude-opus-4-8", input_tokens=1234, output_tokens=4200,
        cache_creation_5m_tokens=5000, cache_read_tokens=99000,
        tools_used=[{"name": "Bash", "count": 3}, {"name": "Read", "count": 2}],
    )

    def row_for(cols):
        monkeypatch.setenv("COLUMNS", str(cols))
        out = format_detail(_summary([turn]), "ko")
        return next(l for l in out.splitlines() if l.strip().startswith("1 "))

    narrow, wide = row_for(80), row_for(160)
    # flex 컬럼이 넓어진 만큼 행 전체가 길어진다.
    assert visual_width(wide) > visual_width(narrow)
    # 첫 숫자 컬럼(input "1,234")부터 끝까지 tail 은 두 폭에서 동일.
    tail_n = narrow[narrow.index("1,234"):]
    tail_w = wide[wide.index("1,234"):]
    assert tail_n == tail_w


def test_model_column_grows_for_long_subagent_label_on_wide_terminal(monkeypatch):
    """서브에이전트가 모델 컬럼 라벨을 길게 만들면, 넓은 터미널에서 모델 컬럼이
    잘리지 않고 전체가 보여야 한다 (모델도 동적 width)."""
    long_type = "very-long-subagent-agent-type-name-that-needs-room"
    sub = _sub(agent_type=long_type, model="claude-opus-4-8")
    turn = _turn(model="claude-opus-4-8", tools_used=[{"name": "Bash", "count": 1}])
    turn.subagents = [sub]

    monkeypatch.setenv("COLUMNS", "200")
    out = format_detail(_summary([turn]), "ko")
    # 긴 agent_type 가 잘리지 않고 (… 없이) 그대로 렌더된다.
    assert long_type in out
    assert "..." not in out


def test_numeric_columns_have_minimum_width():
    """숫자 컬럼(input~시간)은 짧은 값이라도 _NUM_MIN_WIDTH 이상 폭을 갖는다
    (예산 여유 시). floor 는 _apply_num_floor 가 부여한다."""
    from lib.detail_formatter import (
        _NUM_COL_INDICES, _NUM_MIN_WIDTH, _apply_num_floor, _compute_widths,
    )
    # 모든 셀이 1글자인 행 — floor 없으면 숫자 컬럼이 1~2칸으로 쪼그라든다.
    header = ["#", "m", "t", "in", "cc", "cr", "out", "$", "T"]
    rows = [["1", "x", "y", "2", "4", "7", "3", "1", "5"]]
    content = _compute_widths(header, rows)
    # _compute_widths 자체는 floor 미적용 (순수 content)
    assert content[_NUM_COL_INDICES[0]] < _NUM_MIN_WIDTH
    widths = _apply_num_floor(content)
    for ci in _NUM_COL_INDICES:
        assert widths[ci] >= _NUM_MIN_WIDTH


def test_narrow_terminal_reclaims_numeric_floor_without_truncating(monkeypatch):
    """아주 좁은 터미널에선 숫자 floor 패딩을 반납해 줄바꿈을 피하되, 숫자 값
    자체는 안 잘린다 (한 줄 유지)."""
    monkeypatch.setenv("COLUMNS", "60")
    turn = _turn(
        model="claude-opus-4-8", input_tokens=7610, output_tokens=322,
        cache_creation_5m_tokens=174, cache_read_tokens=99810,
        tools_used=[{"name": "mcp__claude_ai_Notion__notion-search", "count": 1}],
    )
    out = format_detail(_summary([turn]), "ko")
    rows = [l for l in out.splitlines() if l.strip().startswith("1 ")]
    assert rows, "data row missing"
    row = rows[0]
    # 숫자 값은 온전히 보존
    for v in ("7,610", "99.81K", "322"):
        assert v in row
    # 한 줄 폭이 터미널(60)을 넘지 않음 — 줄바꿈 방지
    assert visual_width(row) <= 60


# ---------------------------------------------------------------------------
# subagent tools column: real names, MCP shortening, em-dash when empty
# ---------------------------------------------------------------------------


def test_short_tool_name_shortens_mcp():
    from lib.detail_formatter import _short_tool_name
    assert _short_tool_name("mcp__claude_ai_Notion__notion-fetch") == "mcp:notion-fetch"
    assert _short_tool_name("mcp__plugin_pw_pw__browser_click") == "mcp:browser_click"
    assert _short_tool_name("Bash") == "Bash"
    assert _short_tool_name("mcp__weird") == "mcp__weird"  # too few segments


def test_subagent_row_renders_tools_with_mcp_shortened(monkeypatch):
    monkeypatch.setenv("COLUMNS", "160")
    turn = _turn(model="claude-opus-4-8", tools_used=[{"name": "Agent", "count": 1}])
    sub = _sub(agent_type="general-purpose", model="claude-haiku-4-5-20251001")
    sub.tools_used = [
        {"name": "mcp__claude_ai_Notion__notion-fetch", "count": 12},
        {"name": "Bash", "count": 1},
    ]
    turn.subagents = [sub]
    out = format_detail(_summary([turn]), "ko")
    # 툴은 agent_type 다음 줄(들)에 wrap — 전체 출력에서 검사
    assert "mcp:notion-fetch×12" in out
    assert "Bash×1" in out
    assert "mcp__" not in out  # full MCP id never shown


def test_subagent_row_shows_dash_when_no_tools(monkeypatch):
    monkeypatch.setenv("COLUMNS", "160")
    turn = _turn(model="claude-opus-4-8", tools_used=[{"name": "Agent", "count": 1}])
    sub = _sub(agent_type="Explore", model="claude-opus-4-8")
    sub.tools_used = []
    turn.subagents = [sub]
    out = format_detail(_summary([turn]), "ko")
    # agent_type 'Explore' 다음 줄에 '—'
    assert "Explore" in out
    assert "—" in out


def test_layout5_sub_structure(monkeypatch):
    """레이아웃 ⑤ 구조 잠금: 모델 컬럼='└ sub: {model}', 툴 컬럼 첫 줄=agent_type,
    그 다음 줄(들)=툴 wrap, 숫자는 agent_type 줄에만."""
    monkeypatch.setenv("COLUMNS", "120")
    turn = _turn(model="claude-opus-4-8", tools_used=[{"name": "Agent", "count": 1}])
    sub = _sub(agent_type="general-purpose", model="claude-opus-4-8")
    sub.tools_used = [
        {"name": "mcp__claude_ai_Notion__notion-fetch", "count": 3},
        {"name": "Read", "count": 1},
    ]
    turn.subagents = [sub]
    lines = format_detail(_summary([turn]), "ko").splitlines()
    # agent_type 줄 = '└' 포함 + 모델 컬럼에 'sub: opus 4.8' + 툴 첫 줄 'general-purpose' + 숫자
    head = next(l for l in lines if "└" in l)
    assert "sub: opus 4.8" in head
    assert "general-purpose" in head
    assert "368" in head  # output 숫자 = 첫 줄에만
    # 그 다음 줄 = 툴 continuation (숫자 없음)
    hi = lines.index(head)
    cont = lines[hi + 1]
    assert "mcp:notion-fetch×3" in cont or "Read×1" in cont
    assert "368" not in cont  # 숫자는 continuation 에 없음
    assert "└" not in cont    # continuation 은 새 sub 아님
