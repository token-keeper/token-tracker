import math

from lib import aggregator
from lib.parser import SubagentUsage, TurnUsage


def _mk(model="claude-opus-4-7", **kw) -> TurnUsage:
    # Phase B/C 마이그레이션 편의: legacy 테스트가 cache_creation_tokens=N으로
    # 넘기면 5m tier에 매핑한다 (보수적 가정 — 1h는 더 비싸므로 5m으로 두면
    # cost가 과소산정 위험 없이 균형). 신규 테스트는 5m/1h를 명시적으로 사용.
    if "cache_creation_tokens" in kw:
        kw["cache_creation_5m_tokens"] = kw.pop("cache_creation_tokens")
    defaults = dict(
        model=model,
        input_tokens=0,
        output_tokens=0,
        cache_creation_5m_tokens=0,
        cache_creation_1h_tokens=0,
        cache_read_tokens=0,
    )
    defaults.update(kw)
    return TurnUsage(**defaults)


def test_empty_returns_zero_summary():
    s = aggregator.aggregate([], elapsed=0.0)
    assert s.total_cost == 0.0
    assert s.total_input_tokens == 0
    assert s.total_output_tokens == 0
    assert s.cache_hit_rate == 0.0
    assert s.total_elapsed == 0.0
    assert s.turns == []


def test_single_turn_sums_all_input_kinds():
    t = _mk(input_tokens=100, output_tokens=50, cache_creation_tokens=400, cache_read_tokens=200)
    s = aggregator.aggregate([t], elapsed=1.5)
    assert s.total_input_tokens == 700  # 100 + 400 + 200
    assert s.total_output_tokens == 50
    assert math.isclose(s.cache_hit_rate, 200 / 700)
    assert s.total_elapsed == 1.5


def test_multiple_turns_sum():
    ts = [
        _mk(input_tokens=100, cache_read_tokens=0),
        _mk(input_tokens=100, cache_read_tokens=900),
    ]
    s = aggregator.aggregate(ts, elapsed=2.0)
    assert s.total_input_tokens == 1100
    assert math.isclose(s.cache_hit_rate, 900 / 1100)


def test_cache_hit_rate_with_zero_input():
    s = aggregator.aggregate([_mk()], elapsed=0.0)
    assert s.cache_hit_rate == 0.0


def test_total_cost_sums_per_turn():
    ts = [
        _mk(model="claude-opus-4-7", input_tokens=1_000_000),
        _mk(model="claude-sonnet-4-6", input_tokens=1_000_000),
    ]
    s = aggregator.aggregate(ts, elapsed=0.0)
    # Opus 4.7 신단가 input = $5/MT, Sonnet 4.6 input = $3/MT
    assert math.isclose(s.total_cost, 5.0 + 3.0, rel_tol=1e-6)


def test_dedupe_by_message_id():
    """Claude Code writes one JSONL line per content block but copies the
    same usage into each. Aggregator must count each unique message_id once."""
    ts = [
        _mk(input_tokens=6, output_tokens=210, cache_creation_tokens=319489, message_id="msg_A"),
        _mk(input_tokens=6, output_tokens=210, cache_creation_tokens=319489, message_id="msg_A"),  # dup
        _mk(input_tokens=6, output_tokens=210, cache_creation_tokens=319489, message_id="msg_A"),  # dup
    ]
    s = aggregator.aggregate(ts, elapsed=0.0)
    # Should be charged once, not 3x.
    # Opus 4.7 신단가: input $5, output $25, cache_creation_5m $6.25 (legacy
    # cache_creation_tokens는 _mk가 5m으로 매핑).
    expected_cost = (6 * 5 + 210 * 25 + 319489 * 6.25) / 1_000_000
    assert math.isclose(s.total_cost, expected_cost, rel_tol=1e-6)
    assert len(s.turns) == 1


def test_dedupe_keeps_distinct_message_ids():
    ts = [
        _mk(input_tokens=100, message_id="msg_A"),
        _mk(input_tokens=200, message_id="msg_B"),
    ]
    s = aggregator.aggregate(ts, elapsed=0.0)
    assert s.total_input_tokens == 300
    assert len(s.turns) == 2


def test_turns_without_message_id_are_preserved():
    """Legacy/fallback: turns lacking message_id can't be deduped, keep all."""
    ts = [
        _mk(input_tokens=100, message_id=""),
        _mk(input_tokens=100, message_id=""),
    ]
    s = aggregator.aggregate(ts, elapsed=0.0)
    assert s.total_input_tokens == 200
    assert len(s.turns) == 2


def test_aggregate_assigns_sequential_index():
    ts = [
        _mk(input_tokens=1, output_tokens=1, message_id="a"),
        _mk(input_tokens=1, output_tokens=1, message_id="b"),
        _mk(input_tokens=1, output_tokens=1, message_id="c"),
    ]
    s = aggregator.aggregate(ts, elapsed=1.0)
    assert [t.index for t in s.turns] == [0, 1, 2]


def test_aggregate_index_after_dedupe():
    dup = _mk(input_tokens=1, output_tokens=1, message_id="a")
    ts = [
        dup,
        _mk(input_tokens=1, output_tokens=1, message_id="a"),  # duplicate message_id, deduped
        _mk(input_tokens=1, output_tokens=1, message_id="b"),
    ]
    s = aggregator.aggregate(ts, elapsed=1.0)
    assert [t.index for t in s.turns] == [0, 1]


# ---------------------------------------------------------------------------
# Subagent attach + Summary 합계 (T2)
# ---------------------------------------------------------------------------


def _mk_sub(
    tool_use_id: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation_tokens: int = 0,  # legacy alias → 5m tier로 매핑
    cache_read_tokens: int = 0,
    agent_type: str = "claude-code-guide",
) -> SubagentUsage:
    return SubagentUsage(
        agent_type=agent_type,
        tool_use_id=tool_use_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_5m_tokens=cache_creation_tokens,
        cache_creation_1h_tokens=0,
        cache_read_tokens=cache_read_tokens,
    )


def test_aggregate_default_subagents_none_keeps_legacy_behavior():
    """subagents 인자를 안 넘기면 기존 결과와 동일해야 한다."""
    ts = [_mk(input_tokens=100, output_tokens=50, message_id="a")]
    s_legacy = aggregator.aggregate(ts, elapsed=1.0)
    s_none = aggregator.aggregate(ts, elapsed=1.0, subagents=None)
    assert s_legacy.total_cost == s_none.total_cost
    assert s_legacy.total_input_tokens == s_none.total_input_tokens
    assert s_legacy.total_output_tokens == s_none.total_output_tokens
    # 기본값: turns 의 subagents 는 빈 리스트
    assert s_none.turns[0].subagents == []


def test_aggregate_with_empty_subagents_list_matches_legacy():
    """subagents=[] 도 None과 동일한 legacy 결과여야 한다 (회귀 가드)."""
    ts = [
        _mk(input_tokens=100, output_tokens=50, cache_read_tokens=10, message_id="a"),
        _mk(input_tokens=200, output_tokens=70, message_id="b"),
    ]
    s_legacy = aggregator.aggregate(ts, elapsed=0.0)
    s_empty = aggregator.aggregate(ts, elapsed=0.0, subagents=[])
    assert s_legacy.total_cost == s_empty.total_cost
    assert s_legacy.total_input_tokens == s_empty.total_input_tokens
    assert s_legacy.total_output_tokens == s_empty.total_output_tokens
    assert s_legacy.cache_hit_rate == s_empty.cache_hit_rate
    assert len(s_legacy.turns) == len(s_empty.turns)
    for tl, te in zip(s_legacy.turns, s_empty.turns):
        assert tl.subagents == [] and te.subagents == []


def test_aggregate_attaches_subagent_to_parent_by_tool_use_id():
    parent = _mk(
        input_tokens=10, output_tokens=20, message_id="p1",
    )
    parent.agent_tool_use_ids = ["toolu_a"]
    sub = _mk_sub(tool_use_id="toolu_a", input_tokens=5, output_tokens=7)
    s = aggregator.aggregate([parent], elapsed=0.0, subagents=[sub])
    assert len(s.turns) == 1
    assert len(s.turns[0].subagents) == 1
    assert s.turns[0].subagents[0].tool_use_id == "toolu_a"


def test_aggregate_drops_unmatched_subagent():
    parent = _mk(input_tokens=10, output_tokens=20, message_id="p1")
    parent.agent_tool_use_ids = ["toolu_a"]
    matched = _mk_sub(tool_use_id="toolu_a", input_tokens=5, output_tokens=7)
    orphan = _mk_sub(tool_use_id="toolu_orphan", input_tokens=999, output_tokens=999)
    s = aggregator.aggregate([parent], elapsed=0.0, subagents=[matched, orphan])
    # 부모의 subagents 에는 matched 만
    assert len(s.turns[0].subagents) == 1
    assert s.turns[0].subagents[0].tool_use_id == "toolu_a"
    # 합계에 orphan 토큰은 미포함 (parent + matched 만)
    # parent: 10 input + 0 cc + 0 cr = 10 ; matched: 5 input + 0 + 0 = 5
    assert s.total_input_tokens == 15
    assert s.total_output_tokens == 20 + 7


def test_aggregate_total_tokens_includes_subagent_usage():
    parent = _mk(
        input_tokens=100, output_tokens=50,
        cache_creation_tokens=200, cache_read_tokens=300,
        message_id="p1",
    )
    parent.agent_tool_use_ids = ["toolu_a"]
    sub = _mk_sub(
        tool_use_id="toolu_a",
        input_tokens=10, output_tokens=20,
        cache_creation_tokens=30, cache_read_tokens=40,
    )
    s = aggregator.aggregate([parent], elapsed=0.0, subagents=[sub])
    # parent input-side: 100 + 200 + 300 = 600 ; sub: 10 + 30 + 40 = 80
    assert s.total_input_tokens == 680
    assert s.total_output_tokens == 50 + 20


def test_aggregate_cache_hit_rate_includes_subagent_cache():
    parent = _mk(
        input_tokens=100, cache_creation_tokens=0, cache_read_tokens=0,
        message_id="p1",
    )
    parent.agent_tool_use_ids = ["toolu_a"]
    sub = _mk_sub(
        tool_use_id="toolu_a",
        input_tokens=0, cache_read_tokens=900,
    )
    s = aggregator.aggregate([parent], elapsed=0.0, subagents=[sub])
    # input-side total: 100 (parent) + 900 (sub cache_read) = 1000
    # cache_read total: 900
    assert s.total_input_tokens == 1000
    assert math.isclose(s.cache_hit_rate, 900 / 1000)


def test_dedupe_merges_tools_used_from_duplicate_message_id():
    """Bug B: Claude Code splits a single API response into multiple JSONL lines
    (thinking, tool_use, text). Each line shares the same message_id but
    `tools_used` only appears on the tool_use line. dedupe was keeping the
    first line (often thinking with tools_used=[]) and dropping subsequent
    lines entirely → tools_used 손실 → detail 표 `툴` 칼럼이 모두 `—`.

    fix: 같은 message_id 만나면 tools_used도 kept turn에 merge한다.
    """
    t1 = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=1, output_tokens=1,
        message_id="m1",
        tools_used=[],  # thinking line — empty tools
    )
    t2 = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=1, output_tokens=1,
        message_id="m1",
        tools_used=[{"name": "Bash", "count": 2}],  # tool_use line
    )
    out = aggregator._dedupe_by_message_id([t1, t2])
    assert len(out) == 1
    assert out[0].tools_used == [{"name": "Bash", "count": 2}]


def test_dedupe_merges_tools_used_with_count_aggregation():
    """같은 tool name이 여러 라인에 나뉘어 있으면 count가 합산돼야 한다."""
    t1 = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=1, output_tokens=1,
        message_id="m1",
        tools_used=[{"name": "Read", "count": 1}],
    )
    t2 = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=1, output_tokens=1,
        message_id="m1",
        tools_used=[{"name": "Read", "count": 3}, {"name": "Bash", "count": 1}],
    )
    out = aggregator._dedupe_by_message_id([t1, t2])
    assert len(out) == 1
    # Read는 1+3=4, Bash는 신규 1. 순서는 stable (먼저 들어온 게 앞).
    by_name = {item["name"]: item["count"] for item in out[0].tools_used}
    assert by_name == {"Read": 4, "Bash": 1}


def test_dedupe_merges_agent_tool_use_ids_from_duplicate_message_id():
    """Claude Code splits a single API response into multiple JSONL lines
    (thinking, text, tool_use). Each line shares the same message_id but only
    the tool_use line carries `agent_tool_use_ids`. Dedupe must merge those
    ids onto the kept turn instead of dropping them silently."""
    t1 = _mk(input_tokens=1, output_tokens=1, message_id="m1")  # thinking line
    t2 = _mk(input_tokens=1, output_tokens=1, message_id="m1")  # tool_use line
    t2.agent_tool_use_ids = ["toolu_X"]
    out = aggregator._dedupe_by_message_id([t1, t2])
    assert len(out) == 1
    assert out[0].agent_tool_use_ids == ["toolu_X"]


def test_aggregate_attaches_subagent_when_tool_use_on_separate_line_with_same_msg_id():
    """End-to-end: parent turn arrives as 2 JSONL lines (same message_id) where
    only the second line has agent_tool_use_ids. After dedupe-merge, the sub
    must still attach to the surviving turn and contribute to Summary totals."""
    t1 = _mk(input_tokens=10, output_tokens=20, message_id="p1")  # thinking
    t2 = _mk(input_tokens=10, output_tokens=20, message_id="p1")  # tool_use
    t2.agent_tool_use_ids = ["toolu_X"]
    sub = _mk_sub(tool_use_id="toolu_X", input_tokens=5, output_tokens=7)
    s = aggregator.aggregate([t1, t2], elapsed=0.0, subagents=[sub])
    assert len(s.turns) == 1
    assert len(s.turns[0].subagents) == 1
    assert s.turns[0].subagents[0].tool_use_id == "toolu_X"
    # Summary includes sub: parent input 10 + sub input 5 = 15
    assert s.total_input_tokens == 15
    assert s.total_output_tokens == 20 + 7


def test_aggregate_total_cost_uses_parent_model_rate_for_subagent():
    """subagent 의 model 이 비어있으면 부모 model 단가로 비용 산정."""
    parent = _mk(
        model="claude-opus-4-7",
        input_tokens=0, output_tokens=0, message_id="p1",
    )
    parent.agent_tool_use_ids = ["toolu_a"]
    # sub: 1M input tokens → 부모(opus 4.7 신단가 input $5) (sub.model 빈 문자열)
    sub = _mk_sub(tool_use_id="toolu_a", input_tokens=1_000_000)
    s = aggregator.aggregate([parent], elapsed=0.0, subagents=[sub])
    # parent cost = 0, sub cost = 1M * $5 / 1M = $5.0 (opus 신단가 input rate)
    assert math.isclose(s.total_cost, 5.0, rel_tol=1e-6)


def test_aggregate_uses_sub_model_for_cost_when_set():
    """sub.model이 채워져 있으면 부모 단가가 아닌 sub 자체 단가로 비용 산정."""
    parent = _mk(
        model="claude-opus-4-7",
        input_tokens=0, output_tokens=0, message_id="p1",
    )
    parent.agent_tool_use_ids = ["toolu_a"]
    # sub: 1M input tokens, 자체 model = haiku → haiku input rate $1.0/MTok
    sub = _mk_sub(tool_use_id="toolu_a", input_tokens=1_000_000)
    sub.model = "claude-haiku-4-5"
    s = aggregator.aggregate([parent], elapsed=0.0, subagents=[sub])
    # parent cost = 0, sub cost = 1M * 1.0 / 1M = 1.0 (haiku input rate, not opus $15)
    assert math.isclose(s.total_cost, 1.0, rel_tol=1e-6)


def test_total_input_includes_both_5m_and_1h():
    from lib.aggregator import aggregate
    from lib.parser import TurnUsage
    turns = [
        TurnUsage(
            model="claude-opus-4-7",
            input_tokens=100,
            output_tokens=10,
            cache_creation_5m_tokens=1000,
            cache_creation_1h_tokens=2000,
            cache_read_tokens=500,
            message_id="msg_a",
        )
    ]
    s = aggregate(turns, elapsed=1.0)
    assert s.total_input_tokens == 100 + 1000 + 2000 + 500


def test_aggregate_cost_uses_per_tier_rates():
    """5m + 1h 두 단가가 정확히 적용."""
    from lib.aggregator import aggregate
    from lib.parser import TurnUsage
    turns = [
        TurnUsage(
            model="claude-opus-4-7",
            input_tokens=0,
            output_tokens=0,
            cache_creation_5m_tokens=1_000_000,  # = $6.25
            cache_creation_1h_tokens=1_000_000,  # = $10.0
            cache_read_tokens=0,
            message_id="msg_b",
        )
    ]
    s = aggregate(turns, elapsed=1.0)
    assert abs(s.total_cost - (6.25 + 10.0)) < 1e-6


def test_aggregate_5m_1h_uses_sub_model_rates():
    """sub model이 parent와 다르면 sub 단가로 계산."""
    from lib.aggregator import aggregate
    from lib.parser import TurnUsage, SubagentUsage
    sub = SubagentUsage(
        agent_type="general-purpose",
        tool_use_id="tu_1",
        input_tokens=0,
        output_tokens=0,
        cache_creation_5m_tokens=0,
        cache_creation_1h_tokens=1_000_000,  # haiku 1h = $2.0
        cache_read_tokens=0,
        model="claude-haiku-4-5",
    )
    parent = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=0,
        output_tokens=0,
        cache_creation_5m_tokens=0,
        cache_creation_1h_tokens=0,
        cache_read_tokens=0,
        message_id="msg_c",
        agent_tool_use_ids=["tu_1"],
    )
    s = aggregate([parent], elapsed=1.0, subagents=[sub])
    # haiku 1h $2/MT × 1M tokens = $2.0 (opus $10이 아닌)
    assert abs(s.total_cost - 2.0) < 1e-6


def test_aggregate_short_alias_resolves_to_latest_family_rate():
    """v0.11.0 변경 — short alias 가 family-prefix latest 단가로 정확 청구.

    이전 동작 (v0.10.0 까지): `Agent(model="sonnet")` → unknown → parent rate fallback.
    신 동작: alias 자동 탐지 → claude-sonnet-{latest} 단가 ($3 input, parent opus 의 $5 가 아님).
    silent $0 는 여전히 회귀 — 정확 단가가 청구되어야 한다.
    """
    parent = _mk(
        model="claude-opus-4-7",
        input_tokens=0, output_tokens=0, message_id="p1",
    )
    parent.agent_tool_use_ids = ["toolu_a"]
    sub = _mk_sub(tool_use_id="toolu_a", input_tokens=1_000_000)
    sub.model = "sonnet"  # short alias — alias 자동 탐지로 latest sonnet 매핑
    s = aggregator.aggregate([parent], elapsed=0.0, subagents=[sub])
    # Expected: 1M * $3 / 1M = $3.0 (latest sonnet input rate, NOT parent opus $5)
    assert math.isclose(s.total_cost, 3.0, rel_tol=1e-6), (
        f"short alias should resolve to latest sonnet rate ($3), got cost={s.total_cost}"
    )
