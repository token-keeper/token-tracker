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
    # fixture has one Read + one Grep, both count=1
    assert t.tools_used == [{"name": "Read", "count": 1}, {"name": "Grep", "count": 1}]
    assert t.cache_read_tokens == 2000


def test_parse_assistant_line_aggregates_tool_use_counts():
    entry = {
        "type": "assistant",
        "timestamp": "2026-04-23T10:00:00Z",
        "message": {
            "id": "msg_1",
            "model": "claude-opus-4-7",
            "usage": {
                "input_tokens": 10, "output_tokens": 20,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
            "content": [
                {"type": "text", "text": "ok"},
                {"type": "tool_use", "name": "Read"},
                {"type": "tool_use", "name": "Read"},
                {"type": "tool_use", "name": "Edit"},
            ],
        },
    }
    t = parser.parse_line(entry)
    assert t is not None
    assert t.tools_used == [{"name": "Read", "count": 2}, {"name": "Edit", "count": 1}]


def test_parse_assistant_line_exposes_timestamp():
    lines = _load_lines()
    t = parser.parse_line(lines[1])
    assert t.timestamp_iso == "2026-04-22T10:00:01.000Z"


def test_parse_malformed_line_returns_none():
    assert parser.parse_line({"type": "assistant"}) is None
    assert parser.parse_line({}) is None


def test_parse_sets_started_at_from_iso_timestamp():
    entry = {
        "type": "assistant",
        "timestamp": "2026-04-23T10:00:00Z",
        "message": {
            "id": "m1", "model": "claude-opus-4-7",
            "usage": {"input_tokens": 1, "output_tokens": 1,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            "content": [],
        },
    }
    t = parser.parse_line(entry)
    # 2026-04-23T10:00:00Z = 2026-04-23 10:00:00 UTC
    from datetime import datetime, timezone
    expected = datetime(2026, 4, 23, 10, 0, 0, tzinfo=timezone.utc).timestamp()
    assert t.started_at == expected


def test_parse_missing_timestamp_leaves_started_at_none():
    entry = {
        "type": "assistant",
        "message": {
            "id": "m1", "model": "claude-opus-4-7",
            "usage": {"input_tokens": 1, "output_tokens": 1,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            "content": [],
        },
    }
    t = parser.parse_line(entry)
    assert t.started_at is None


def test_parse_invalid_timestamp_leaves_started_at_none():
    entry = {
        "type": "assistant",
        "timestamp": "not-a-date",
        "message": {
            "id": "m1", "model": "claude-opus-4-7",
            "usage": {"input_tokens": 1, "output_tokens": 1,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            "content": [],
        },
    }
    t = parser.parse_line(entry)
    assert t.started_at is None


# ---------------------------------------------------------------------------
# SubagentUsage / parse_tool_result_for_agent / parse_async_launch /
# parse_sidechain_assistant
# ---------------------------------------------------------------------------


def _completed_agent_user_entry():
    return {
        "type": "user",
        "timestamp": "2026-04-23T11:00:00Z",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_parent_001",
                    "content": "agent finished",
                }
            ],
        },
        "toolUseResult": {
            "agentType": "claude-code-guide",
            "agentId": "agent-abc-123",
            "status": "completed",
            "totalDurationMs": 12345,
            "totalTokens": 999,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 200,
                "cache_creation_input_tokens": 50,
                "cache_read_input_tokens": 1000,
            },
        },
    }


def test_parse_tool_result_returns_none_for_assistant_lines():
    entry = {
        "type": "assistant",
        "message": {"id": "m1", "model": "claude-opus-4-7", "usage": {}, "content": []},
    }
    assert parser.parse_tool_result_for_agent(entry) is None


def test_parse_tool_result_returns_none_when_no_agent_type():
    entry = {
        "type": "user",
        "message": {
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_x", "content": "ok"}
            ],
        },
        "toolUseResult": {"stdout": "hello"},
    }
    assert parser.parse_tool_result_for_agent(entry) is None


def test_parse_tool_result_extracts_completed_agent_usage():
    entry = _completed_agent_user_entry()
    sub = parser.parse_tool_result_for_agent(entry)
    assert sub is not None
    assert sub.agent_type == "claude-code-guide"
    assert sub.tool_use_id == "toolu_parent_001"
    assert sub.input_tokens == 100
    assert sub.output_tokens == 200
    assert sub.cache_creation_tokens == 50
    assert sub.cache_read_tokens == 1000
    assert sub.total_duration_ms == 12345


def test_parse_tool_result_returns_none_for_async_launched():
    entry = {
        "type": "user",
        "timestamp": "2026-04-23T11:00:00Z",
        "message": {
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_async_1", "content": "launched"}
            ],
        },
        "toolUseResult": {
            "agentType": "claude-code-guide",
            "agentId": "agent-async-1",
            "status": "async_launched",
        },
    }
    assert parser.parse_tool_result_for_agent(entry) is None


def test_parse_async_launch_extracts_pair():
    entry = {
        "type": "user",
        "timestamp": "2026-04-23T11:00:00Z",
        "message": {
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_async_1", "content": "launched"}
            ],
        },
        "toolUseResult": {
            "agentType": "claude-code-guide",
            "agentId": "agent-async-1",
            "status": "async_launched",
        },
    }
    pair = parser.parse_async_launch(entry)
    assert pair == ("toolu_async_1", "agent-async-1")


def test_parse_async_launch_returns_none_for_completed():
    entry = _completed_agent_user_entry()
    assert parser.parse_async_launch(entry) is None


def test_parse_sidechain_assistant_extracts_usage():
    entry = {
        "type": "assistant",
        "timestamp": "2026-04-23T12:34:56Z",
        "message": {
            "id": "msg_side_1",
            "model": "claude-haiku-4-5",
            "usage": {
                "input_tokens": 7,
                "output_tokens": 9,
                "cache_creation_input_tokens": 11,
                "cache_read_input_tokens": 13,
            },
            "content": [],
        },
    }
    sub = parser.parse_sidechain_assistant(
        entry,
        agent_type="claude-code-guide",
        tool_use_id="toolu_async_1",
    )
    assert sub is not None
    assert sub.agent_type == "claude-code-guide"
    assert sub.tool_use_id == "toolu_async_1"
    assert sub.input_tokens == 7
    assert sub.output_tokens == 9
    assert sub.cache_creation_tokens == 11
    assert sub.cache_read_tokens == 13
    assert sub.total_duration_ms == 0


def test_parse_sidechain_assistant_returns_none_for_user_lines():
    entry = {
        "type": "user",
        "timestamp": "2026-04-23T12:34:56Z",
        "message": {"content": []},
    }
    assert (
        parser.parse_sidechain_assistant(
            entry,
            agent_type="claude-code-guide",
            tool_use_id="toolu_async_1",
        )
        is None
    )


# ---------------------------------------------------------------------------
# TurnUsage.agent_tool_use_ids — parse_line collects Agent tool_use ids
# ---------------------------------------------------------------------------


def test_parse_line_collects_agent_tool_use_ids():
    entry = {
        "type": "assistant",
        "timestamp": "2026-04-23T10:00:00Z",
        "message": {
            "id": "msg_1",
            "model": "claude-opus-4-7",
            "usage": {
                "input_tokens": 10, "output_tokens": 20,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
            "content": [
                {"type": "text", "text": "ok"},
                {"type": "tool_use", "name": "Agent", "id": "toolu_agent_1"},
                {"type": "tool_use", "name": "Agent", "id": "toolu_agent_2"},
            ],
        },
    }
    t = parser.parse_line(entry)
    assert t is not None
    assert t.agent_tool_use_ids == ["toolu_agent_1", "toolu_agent_2"]


def test_parse_line_ignores_non_agent_tool_use():
    entry = {
        "type": "assistant",
        "timestamp": "2026-04-23T10:00:00Z",
        "message": {
            "id": "msg_1",
            "model": "claude-opus-4-7",
            "usage": {
                "input_tokens": 10, "output_tokens": 20,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
            "content": [
                {"type": "tool_use", "name": "Read", "id": "toolu_read_1"},
                {"type": "tool_use", "name": "Bash", "id": "toolu_bash_1"},
            ],
        },
    }
    t = parser.parse_line(entry)
    assert t is not None
    assert t.agent_tool_use_ids == []


# ---------------------------------------------------------------------------
# parse_agent_tool_uses — shared helper for (id, subagent_type) extraction
# ---------------------------------------------------------------------------


def test_parse_agent_tool_uses_single_agent_block():
    entry = {
        "type": "assistant",
        "message": {
            "id": "msg_1",
            "model": "claude-opus-4-7",
            "content": [
                {"type": "text", "text": "ok"},
                {
                    "type": "tool_use",
                    "name": "Agent",
                    "id": "toolu_a",
                    "input": {"subagent_type": "claude-code-guide"},
                },
            ],
        },
    }
    pairs = parser.parse_agent_tool_uses(entry)
    assert pairs == [("toolu_a", "claude-code-guide", "")]


def test_parse_agent_tool_uses_multiple_agent_blocks():
    entry = {
        "type": "assistant",
        "message": {
            "id": "msg_1",
            "content": [
                {
                    "type": "tool_use",
                    "name": "Agent",
                    "id": "toolu_a",
                    "input": {"subagent_type": "claude-code-guide"},
                },
                {"type": "tool_use", "name": "Read", "id": "toolu_read"},
                {
                    "type": "tool_use",
                    "name": "Agent",
                    "id": "toolu_b",
                    "input": {"subagent_type": "general-purpose"},
                },
                {
                    # Agent block without subagent_type → empty string
                    "type": "tool_use",
                    "name": "Agent",
                    "id": "toolu_c",
                },
            ],
        },
    }
    pairs = parser.parse_agent_tool_uses(entry)
    assert pairs == [
        ("toolu_a", "claude-code-guide", ""),
        ("toolu_b", "general-purpose", ""),
        ("toolu_c", "", ""),
    ]


def test_parse_agent_tool_uses_returns_empty_for_non_assistant_or_no_agent():
    # user line
    assert parser.parse_agent_tool_uses({"type": "user", "message": {}}) == []
    # assistant line with no Agent tool_use
    entry = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": "Read", "id": "toolu_read"},
                {"type": "text", "text": "hi"},
            ],
        },
    }
    assert parser.parse_agent_tool_uses(entry) == []
    # malformed
    assert parser.parse_agent_tool_uses({}) == []
    assert parser.parse_agent_tool_uses({"type": "assistant"}) == []


def test_parse_agent_tool_uses_extracts_model_when_present():
    """input.model이 명시된 Agent dispatch는 (id, type, model) 트리플로 반환."""
    entry = {
        "type": "assistant",
        "message": {
            "id": "msg_1",
            "content": [
                {
                    "type": "tool_use",
                    "name": "Agent",
                    "id": "toolu_a",
                    "input": {
                        "subagent_type": "general-purpose",
                        "model": "claude-haiku-4-5",
                    },
                },
            ],
        },
    }
    pairs = parser.parse_agent_tool_uses(entry)
    assert pairs == [("toolu_a", "general-purpose", "claude-haiku-4-5")]


def test_parse_agent_tool_uses_returns_empty_model_when_absent():
    """input.model이 없으면 model은 빈 문자열."""
    entry = {
        "type": "assistant",
        "message": {
            "id": "msg_1",
            "content": [
                {
                    "type": "tool_use",
                    "name": "Agent",
                    "id": "toolu_a",
                    "input": {"subagent_type": "general-purpose"},
                },
            ],
        },
    }
    pairs = parser.parse_agent_tool_uses(entry)
    assert pairs == [("toolu_a", "general-purpose", "")]


def test_parse_sidechain_assistant_fills_model_from_message():
    """sidechain assistant 라인의 message.model이 SubagentUsage.model에 들어가야 한다."""
    entry = {
        "type": "assistant",
        "timestamp": "2026-04-23T12:34:56Z",
        "message": {
            "id": "msg_side_1",
            "model": "claude-haiku-4-5",
            "usage": {
                "input_tokens": 7,
                "output_tokens": 9,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
            "content": [],
        },
    }
    sub = parser.parse_sidechain_assistant(
        entry,
        agent_type="general-purpose",
        tool_use_id="toolu_async_1",
    )
    assert sub is not None
    assert sub.model == "claude-haiku-4-5"


def test_subagent_usage_default_model_is_empty():
    sub = parser.SubagentUsage(
        agent_type="general-purpose",
        tool_use_id="tu",
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    assert sub.model == ""
