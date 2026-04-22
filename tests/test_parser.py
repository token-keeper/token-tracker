import json
from pathlib import Path

from lib import parser


FIXTURE = Path(__file__).parent / "fixtures" / "sample_session.jsonl"


def _load_lines():
    return [json.loads(l) for l in FIXTURE.read_text().splitlines() if l.strip()]


def test_parse_user_line_returns_none():
    lines = _load_lines()
    assert parser.parse_line(lines[0]) is None


def test_parse_tool_result_user_line_returns_none():
    lines = _load_lines()
    assert parser.parse_line(lines[2]) is None


def test_parse_simple_assistant_line():
    lines = _load_lines()
    t = parser.parse_line(lines[1])
    assert t is not None
    assert t.model == "claude-opus-4-7"
    assert t.input_tokens == 10
    assert t.output_tokens == 5
    assert t.cache_creation_tokens == 0
    assert t.cache_read_tokens == 0
    assert t.tools_used == []


def test_parse_assistant_line_with_tool_uses():
    lines = _load_lines()
    t = parser.parse_line(lines[3])
    assert t.tools_used == ["Read", "Grep"]
    assert t.cache_read_tokens == 2000


def test_parse_assistant_line_exposes_timestamp():
    lines = _load_lines()
    t = parser.parse_line(lines[1])
    assert t.timestamp_iso == "2026-04-22T10:00:01.000Z"


def test_parse_malformed_line_returns_none():
    assert parser.parse_line({"type": "assistant"}) is None
    assert parser.parse_line({}) is None
