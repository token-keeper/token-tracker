import math

from lib import aggregator
from lib.parser import TurnUsage


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


def test_single_turn():
    t = _mk(input_tokens=100, output_tokens=50, cache_read_tokens=200)
    s = aggregator.aggregate([t], elapsed=1.5)
    assert s.total_input_tokens == 300  # 100 input + 200 cache_read
    assert s.total_output_tokens == 50
    assert math.isclose(s.cache_hit_rate, 200 / 300)
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
