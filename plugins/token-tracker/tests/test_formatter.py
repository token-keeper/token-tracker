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
