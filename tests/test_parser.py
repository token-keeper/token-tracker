import json
from pathlib import Path

import pytest

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
    assert t.cache_creation_5m_tokens == 0
    assert t.cache_creation_1h_tokens == 0
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
    assert sub.cache_creation_5m_tokens == 50
    assert sub.cache_creation_1h_tokens == 0
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
    assert sub.cache_creation_5m_tokens == 11
    assert sub.cache_creation_1h_tokens == 0
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
        cache_creation_5m_tokens=0,
        cache_creation_1h_tokens=0,
        cache_read_tokens=0,
    )
    assert sub.model == ""


def test_turn_usage_has_separate_5m_and_1h_fields():
    """TurnUsage가 cache_creation_5m_tokens / cache_creation_1h_tokens 두 필드를 가짐."""
    from lib.parser import TurnUsage
    t = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=10,
        output_tokens=20,
        cache_creation_5m_tokens=100,
        cache_creation_1h_tokens=200,
        cache_read_tokens=50,
    )
    assert t.cache_creation_5m_tokens == 100
    assert t.cache_creation_1h_tokens == 200
    assert not hasattr(t, "cache_creation_tokens")  # 옛 필드 제거 확인


def test_subagent_usage_has_separate_5m_and_1h_fields():
    from lib.parser import SubagentUsage
    s = SubagentUsage(
        agent_type="general-purpose",
        tool_use_id="x",
        input_tokens=1,
        output_tokens=2,
        cache_creation_5m_tokens=300,
        cache_creation_1h_tokens=400,
        cache_read_tokens=5,
    )
    assert s.cache_creation_5m_tokens == 300
    assert s.cache_creation_1h_tokens == 400
    assert not hasattr(s, "cache_creation_tokens")


@pytest.mark.parametrize("c5m,c1h", [(0, 0), (100, 0), (0, 200), (100, 200)])
def test_parse_line_extracts_5m_and_1h_matrix(c5m, c1h):
    from lib.parser import parse_line
    entry = {
        "type": "assistant",
        "message": {
            "id": "msg_1",
            "model": "claude-opus-4-7",
            "usage": {
                "input_tokens": 5,
                "output_tokens": 10,
                "cache_read_input_tokens": 20,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": c5m,
                    "ephemeral_1h_input_tokens": c1h,
                },
            },
            "content": [],
        },
        "timestamp": "2026-05-03T10:00:00Z",
    }
    t = parse_line(entry)
    assert t is not None
    assert t.cache_creation_5m_tokens == c5m
    assert t.cache_creation_1h_tokens == c1h


def test_parse_line_falls_back_to_legacy_when_no_cache_creation_obj():
    """구버전 entry: cache_creation 중첩 객체 없으면 합산값을 5m로 간주."""
    from lib.parser import parse_line
    entry = {
        "type": "assistant",
        "message": {
            "id": "msg_2",
            "model": "claude-opus-4-7",
            "usage": {
                "input_tokens": 5,
                "output_tokens": 10,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 999,
            },
            "content": [],
        },
        "timestamp": "2026-05-03T10:00:00Z",
    }
    t = parse_line(entry)
    assert t is not None
    assert t.cache_creation_5m_tokens == 999
    assert t.cache_creation_1h_tokens == 0


def test_parse_sidechain_assistant_extracts_5m_1h():
    from lib.parser import parse_sidechain_assistant
    entry = {
        "type": "assistant",
        "message": {
            "model": "claude-haiku-4-5",
            "usage": {
                "input_tokens": 5,
                "output_tokens": 10,
                "cache_read_input_tokens": 20,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 100,
                    "ephemeral_1h_input_tokens": 200,
                },
            },
        },
    }
    s = parse_sidechain_assistant(entry, "general-purpose", "tu_1")
    assert s is not None
    assert s.cache_creation_5m_tokens == 100
    assert s.cache_creation_1h_tokens == 200
    assert s.model == "claude-haiku-4-5"


def test_parse_tool_result_for_agent_extracts_5m_1h():
    from lib.parser import parse_tool_result_for_agent
    entry = {
        "type": "user",
        "toolUseResult": {
            "agentType": "general-purpose",
            "status": "completed",
            "totalDurationMs": 1234,
            "usage": {
                "input_tokens": 5,
                "output_tokens": 10,
                "cache_read_input_tokens": 20,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 100,
                    "ephemeral_1h_input_tokens": 200,
                },
            },
        },
        "message": {
            "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "ok"}],
        },
    }
    s = parse_tool_result_for_agent(entry)
    assert s is not None
    assert s.cache_creation_5m_tokens == 100
    assert s.cache_creation_1h_tokens == 200


# ---------------------------------------------------------------------------
# parse_user_prompt_text
# ---------------------------------------------------------------------------


def test_parse_user_prompt_text_string_content():
    from lib.parser import parse_user_prompt_text
    entry = {
        "type": "user",
        "timestamp": "2026-05-03T14:00:00Z",
        "message": {"content": "Hello, world!"},
    }
    assert parse_user_prompt_text(entry) == "Hello, world!"


def test_parse_user_prompt_text_list_content():
    from lib.parser import parse_user_prompt_text
    entry = {
        "type": "user",
        "timestamp": "2026-05-03T14:00:00Z",
        "message": {
            "content": [
                {"type": "text", "text": "Hello from list"},
                {"type": "image", "source": {}},
            ]
        },
    }
    assert parse_user_prompt_text(entry) == "Hello from list"


def test_parse_user_prompt_text_returns_none_for_non_user():
    from lib.parser import parse_user_prompt_text
    entry = {
        "type": "assistant",
        "timestamp": "2026-05-03T14:00:00Z",
        "message": {"content": "Not a user message"},
    }
    assert parse_user_prompt_text(entry) is None


def test_parse_user_prompt_text_returns_none_for_malformed():
    from lib.parser import parse_user_prompt_text
    assert parse_user_prompt_text({}) is None
    assert parse_user_prompt_text({"type": "user"}) is None
    assert parse_user_prompt_text({"type": "user", "message": "bad"}) is None


# ---------------------------------------------------------------------------
# parse_assistant_text / parse_thinking
# ---------------------------------------------------------------------------


def test_parse_assistant_text_basic():
    from lib.parser import parse_assistant_text
    entry = {
        "type": "assistant",
        "timestamp": "2026-05-03T14:23:00Z",
        "message": {
            "content": [
                {"type": "text", "text": "Hello user"},
                {"type": "tool_use", "name": "Read", "id": "tu_1", "input": {}},
            ]
        },
    }
    out = parse_assistant_text(entry)
    assert len(out) == 1
    assert out[0]["type"] == "assistant_text"
    assert out[0]["text"] == "Hello user"
    assert out[0]["ts"] > 0


def test_parse_assistant_text_skips_other_blocks():
    from lib.parser import parse_assistant_text
    entry = {
        "type": "assistant",
        "timestamp": "2026-05-03T14:23:00Z",
        "message": {
            "content": [
                {"type": "thinking", "thinking": "internal thought", "signature": "sig"},
                {"type": "tool_use", "name": "Bash", "id": "tu_2", "input": {}},
            ]
        },
    }
    out = parse_assistant_text(entry)
    assert out == []


def test_parse_thinking_basic():
    from lib.parser import parse_thinking
    entry = {
        "type": "assistant",
        "timestamp": "2026-05-03T14:23:00Z",
        "message": {
            "content": [
                {"type": "thinking", "thinking": "deep thought", "signature": "sig"},
                {"type": "text", "text": "answer"},
            ]
        },
    }
    out = parse_thinking(entry)
    assert len(out) == 1
    assert out[0]["type"] == "thinking"
    assert out[0]["text"] == "deep thought"
    assert out[0]["ts"] > 0


def test_parse_thinking_returns_empty_when_none():
    from lib.parser import parse_thinking
    entry = {
        "type": "assistant",
        "timestamp": "2026-05-03T14:23:00Z",
        "message": {"content": [{"type": "text", "text": "no thinking"}]},
    }
    out = parse_thinking(entry)
    assert out == []


# ---------------------------------------------------------------------------
# _normalize_tool_result_block
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block,expected", [
    # text
    ({"type": "text", "text": "hello"}, "hello"),
    ({"type": "text", "text": ""}, ""),
    ({"type": "text"}, ""),
    # tool_reference (MCP ToolSearch 결과)
    ({"type": "tool_reference", "tool_name": "TaskCreate"}, "[tool_reference] TaskCreate"),
    ({"type": "tool_reference"}, "[tool_reference]"),
    # image (Playwright screenshot 등)
    (
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "A" * 1024}},
        "[image: image/png, 768 bytes]",
    ),
    ({"type": "image", "source": {"media_type": "image/png"}}, "[image: image/png]"),
    ({"type": "image", "source": {"data": "A" * 1024}}, "[image: 768 bytes]"),
    ({"type": "image", "source": {}}, "[image]"),
    ({"type": "image"}, "[image]"),
    # unknown type 방어 placeholder
    ({"type": "some_new_block", "x": 1}, "[some_new_block]"),
    # type 키 누락 → skip
    ({}, ""),
])
def test_normalize_tool_result_block(block, expected):
    assert parser._normalize_tool_result_block(block) == expected


# ---------------------------------------------------------------------------
# parse_tool_call / parse_tool_result
# ---------------------------------------------------------------------------


def test_parse_tool_call_basic():
    from lib.parser import parse_tool_call
    entry = {
        "type": "assistant",
        "timestamp": "2026-05-03T14:23:00Z",
        "message": {
            "content": [
                {"type": "text", "text": "Let me read"},
                {
                    "type": "tool_use",
                    "id": "toolu_read_1",
                    "name": "Read",
                    "input": {"file_path": "/foo/bar.py"},
                },
            ]
        },
    }
    out = parse_tool_call(entry)
    assert len(out) == 1
    assert out[0]["type"] == "tool_call"
    assert out[0]["id"] == "toolu_read_1"
    assert out[0]["name"] == "Read"
    assert out[0]["input"] == {"file_path": "/foo/bar.py"}
    assert out[0]["ts"] > 0


def test_parse_tool_result_basic():
    from lib.parser import parse_tool_result
    entry = {
        "type": "user",
        "timestamp": "2026-05-03T14:23:01Z",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_read_1",
                    "content": "file contents here",
                }
            ]
        },
    }
    out = parse_tool_result(entry)
    assert len(out) == 1
    assert out[0]["type"] == "tool_result"
    assert out[0]["tool_use_id"] == "toolu_read_1"
    assert out[0]["content"] == "file contents here"
    assert out[0]["is_error"] is False
    assert out[0]["ts"] > 0


def test_parse_tool_result_list_content():
    from lib.parser import parse_tool_result
    entry = {
        "type": "user",
        "timestamp": "2026-05-03T14:23:01Z",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_bash_1",
                    "content": [
                        {"type": "text", "text": "line1"},
                        {"type": "text", "text": "line2"},
                    ],
                    "is_error": True,
                }
            ]
        },
    }
    out = parse_tool_result(entry)
    assert len(out) == 1
    assert out[0]["content"] == "line1\nline2"
    assert out[0]["is_error"] is True


def test_parse_tool_result_list_with_tool_reference():
    """MCP ToolSearch 같은 도구가 tool_reference block 을 반환할 때
    placeholder 줄바꿈 리스트로 정규화된다 (v0.8.1 회귀 가드)."""
    from lib.parser import parse_tool_result
    entry = {
        "type": "user",
        "timestamp": "2026-05-03T14:23:01Z",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_search_1",
                    "content": [
                        {"type": "tool_reference", "tool_name": "TaskCreate"},
                        {"type": "tool_reference", "tool_name": "TaskUpdate"},
                    ],
                }
            ]
        },
    }
    out = parse_tool_result(entry)
    assert len(out) == 1
    assert out[0]["content"] == "[tool_reference] TaskCreate\n[tool_reference] TaskUpdate"


def test_parse_tool_result_list_with_image():
    """image block 이 [image: ...] placeholder 로 정규화된다 (v0.8.1 회귀 가드).

    Playwright browser_take_screenshot 같은 도구가 image block 을 반환할 때
    parse_tool_result 가 빈 문자열로 떨어뜨리지 않음을 통합 레벨에서 가드."""
    from lib.parser import parse_tool_result
    entry = {
        "type": "user",
        "timestamp": "2026-05-03T14:23:01Z",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_screenshot_1",
                    "content": [
                        {"type": "image", "source": {"media_type": "image/png"}},
                    ],
                }
            ]
        },
    }
    out = parse_tool_result(entry)
    assert len(out) == 1
    assert out[0]["content"] == "[image: image/png]"


def test_parse_tool_result_list_mixed_text_and_tool_reference():
    """text + tool_reference 혼합 block 도 줄바꿈으로 join 된다."""
    from lib.parser import parse_tool_result
    entry = {
        "type": "user",
        "timestamp": "2026-05-03T14:23:01Z",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_mixed_1",
                    "content": [
                        {"type": "text", "text": "intro"},
                        {"type": "tool_reference", "tool_name": "Read"},
                    ],
                }
            ]
        },
    }
    out = parse_tool_result(entry)
    assert out[0]["content"] == "intro\n[tool_reference] Read"


def test_parse_tool_result_list_skips_blocks_without_type():
    """type 키가 없는 block 은 join 결과에서 빠진다 (빈 줄 안 생김)."""
    from lib.parser import parse_tool_result
    entry = {
        "type": "user",
        "timestamp": "2026-05-03T14:23:01Z",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_x",
                    "content": [
                        {"type": "text", "text": "a"},
                        {},
                        {"type": "text", "text": "b"},
                    ],
                }
            ]
        },
    }
    out = parse_tool_result(entry)
    assert out[0]["content"] == "a\nb"


# ---------------------------------------------------------------------------
# parse_transcript_for_history
# ---------------------------------------------------------------------------


def test_parse_transcript_for_history_orders_by_ts():
    entries = [
        {"type": "assistant", "timestamp": "2026-05-03T14:23:00Z",
         "message": {"content": [{"type": "text", "text": "hi"}]}},
        {"type": "user", "timestamp": "2026-05-03T14:23:01Z",
         "message": {"content": [{"type": "tool_result", "tool_use_id": "x",
                                  "content": "out"}]}},
        {"type": "assistant", "timestamp": "2026-05-03T14:23:02Z",
         "message": {"content": [{"type": "thinking", "thinking": "th"}]}},
    ]
    from lib.parser import parse_transcript_for_history
    out = parse_transcript_for_history(entries)
    assert [e["type"] for e in out] == ["assistant_text", "tool_result", "thinking"]


def test_parse_line_prefers_nested_cc_when_both_present():
    """이중 카운팅 회귀 가드: 중첩 객체와 legacy가 동시에 박혀도 중첩만 사용."""
    from lib.parser import parse_line
    entry = {
        "type": "assistant",
        "message": {
            "id": "msg_3",
            "model": "claude-opus-4-7",
            "usage": {
                "input_tokens": 5,
                "output_tokens": 10,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 3000,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 1000,
                    "ephemeral_1h_input_tokens": 2000,
                },
            },
            "content": [],
        },
        "timestamp": "2026-05-03T10:00:00Z",
    }
    t = parse_line(entry)
    assert t is not None
    assert t.cache_creation_5m_tokens == 1000
    assert t.cache_creation_1h_tokens == 2000
    assert (t.cache_creation_5m_tokens + t.cache_creation_1h_tokens) == 3000


# ---------------------------------------------------------------------------
# foreground sub: resolvedModel / agentId / toolStats buckets
# ---------------------------------------------------------------------------


def _completed_agent_entry(**tur_overrides):
    tur = {
        "agentType": "general-purpose",
        "status": "completed",
        "agentId": "ag123",
        "resolvedModel": "claude-haiku-4-5-20251001",
        "totalDurationMs": 1000,
        "toolStats": {
            "readCount": 3, "searchCount": 0, "bashCount": 1,
            "editFileCount": 0, "otherToolCount": 2,
        },
        "usage": {"input_tokens": 4, "output_tokens": 8},
    }
    tur.update(tur_overrides)
    return {
        "type": "user",
        "toolUseResult": tur,
        "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tu_x", "content": "ok"}
        ]},
    }


def test_fg_sub_model_from_resolved_model():
    from lib.parser import parse_tool_result_for_agent
    s = parse_tool_result_for_agent(_completed_agent_entry())
    assert s is not None
    assert s.model == "claude-haiku-4-5-20251001"
    assert s.agent_id == "ag123"


def test_fg_sub_tools_from_tool_stats_buckets():
    from lib.parser import parse_tool_result_for_agent
    s = parse_tool_result_for_agent(_completed_agent_entry())
    # readCount=3, bashCount=1, otherToolCount=2 → Read/Bash/기타, zero buckets skipped
    names = {t["name"]: t["count"] for t in s.tools_used}
    assert names == {"Read": 3, "Bash": 1, "기타": 2}


def test_fg_sub_tools_empty_when_no_tool_stats():
    from lib.parser import parse_tool_result_for_agent
    s = parse_tool_result_for_agent(_completed_agent_entry(toolStats=None))
    assert s.tools_used == []


def test_tools_from_tool_stats_orders_and_skips_zero():
    from lib.parser import _tools_from_tool_stats
    out = _tools_from_tool_stats({
        "bashCount": 2, "readCount": 1, "otherToolCount": 0, "editFileCount": 5,
    })
    # order follows _TOOL_STAT_BUCKETS: Read, Edit, Bash (otherToolCount=0 skipped)
    assert out == [
        {"name": "Read", "count": 1},
        {"name": "Edit", "count": 5},
        {"name": "Bash", "count": 2},
    ]
