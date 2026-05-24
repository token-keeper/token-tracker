from lib import formatter
from lib.aggregator import Summary


def _sum(**kw) -> Summary:
    base = dict(
        total_cost=0.018,
        total_input_tokens=1046,
        total_output_tokens=500,
        cache_hit_rate=0.85,
        total_elapsed=12.3,
        turns=[],
    )
    base.update(kw)
    return Summary(**base)


def test_ko_one_liner():
    s = _sum()
    out = formatter.format_summary(s, "ko")
    assert "비용 $0.0180" in out
    assert "1,546 toks" in out  # total = input + output
    assert "cache 85%" in out
    assert "12.3s" in out


def test_en_one_liner():
    s = _sum()
    out = formatter.format_summary(s, "en")
    assert out.startswith("cost $0.0180")
    assert "1,546 toks" in out


def test_unknown_language_falls_back_to_en():
    s = _sum()
    out = formatter.format_summary(s, "fr")
    assert out.startswith("cost $")


def test_zero_cost_and_cache():
    s = _sum(total_cost=0.0, cache_hit_rate=0.0, total_input_tokens=0, total_output_tokens=0)
    out = formatter.format_summary(s, "ko")
    assert "비용 $0.0000" in out
    assert "0 toks" in out
    assert "cache 0%" in out


def test_format_elapsed_under_one_minute():
    assert formatter.format_elapsed(0.0) == "0.0s"
    assert formatter.format_elapsed(1.5) == "1.5s"
    assert formatter.format_elapsed(59.9) == "59.9s"


def test_format_elapsed_at_one_minute_boundary():
    assert formatter.format_elapsed(60.0) == "1m 0s"
    assert formatter.format_elapsed(60.4) == "1m 0s"
    assert formatter.format_elapsed(61.5) == "1m 2s"


def test_format_elapsed_carry_when_seconds_round_to_60():
    assert formatter.format_elapsed(119.7) == "2m 0s"


def test_format_elapsed_long_minutes():
    assert formatter.format_elapsed(600.0) == "10m 0s"
    assert formatter.format_elapsed(3600.0) == "60m 0s"


def test_summary_uses_minute_format_when_over_60s():
    s = _sum(total_elapsed=125.0)
    out = formatter.format_summary(s, "ko")
    assert "2m 5s" in out
    assert "125.0s" not in out  # ensure raw seconds format isn't leaked


def test_summary_includes_turn_count():
    s = _sum(turns=[None] * 4)  # formatter only reads len(turns)
    out = formatter.format_summary(s, "ko")
    assert "4 turns" in out


def test_summary_turn_count_zero_when_empty():
    s = _sum()
    out = formatter.format_summary(s, "ko")
    assert "0 turns" in out


def test_summary_turn_count_singular_uses_same_label():
    s = _sum(turns=[None])
    out = formatter.format_summary(s, "ko")
    assert "1 turns" in out  # KISS: singular label not differentiated
