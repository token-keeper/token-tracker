import math

from lib import aggregator
from lib.parser import SubagentUsage, TurnUsage


def _mk(model="claude-opus-4-7", **kw) -> TurnUsage:
    defaults = dict(
        model=model,
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
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
    assert math.isclose(s.total_cost, 15.0 + 3.0, rel_tol=1e-6)


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
    expected_cost = (6 * 15 + 210 * 75 + 319489 * 18.75) / 1_000_000
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
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    model: str = "",
    agent_type: str = "claude-code-guide",
    agent_id: str = "agent-1",
) -> SubagentUsage:
    return SubagentUsage(
        agent_type=agent_type,
        agent_id=agent_id,
        tool_use_id=tool_use_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        model=model,
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


def test_aggregate_total_cost_uses_parent_model_rate_for_subagent():
    """subagent 의 model 이 비어있으면 부모 model 단가로 비용 산정."""
    parent = _mk(
        model="claude-opus-4-7",
        input_tokens=0, output_tokens=0, message_id="p1",
    )
    parent.agent_tool_use_ids = ["toolu_a"]
    # sub: 1M input tokens, model 비어있음 → 부모(opus) 단가 = $15
    sub = _mk_sub(tool_use_id="toolu_a", input_tokens=1_000_000, model="")
    s = aggregator.aggregate([parent], elapsed=0.0, subagents=[sub])
    # parent cost = 0, sub cost = 1M * 15 / 1M = 15.0 (opus input rate)
    assert math.isclose(s.total_cost, 15.0, rel_tol=1e-6)
