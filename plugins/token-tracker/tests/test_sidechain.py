from __future__ import annotations

import json
from pathlib import Path

from lib import sidechain
from lib.parser import SubagentUsage


# ---------------------------------------------------------------------------
# find_sidechain_dir
# ---------------------------------------------------------------------------


def test_find_sidechain_dir_returns_none_when_missing(tmp_path):
    transcript = tmp_path / "abc-session-id.jsonl"
    transcript.write_text("", encoding="utf-8")
    assert sidechain.find_sidechain_dir(str(transcript)) is None


def test_find_sidechain_dir_returns_path_when_exists(tmp_path):
    transcript = tmp_path / "sess-1.jsonl"
    transcript.write_text("", encoding="utf-8")
    sub_dir = tmp_path / "sess-1" / "subagents"
    sub_dir.mkdir(parents=True)

    result = sidechain.find_sidechain_dir(str(transcript))
    assert result is not None
    assert Path(result) == sub_dir


# ---------------------------------------------------------------------------
# extract_async_launches
# ---------------------------------------------------------------------------


def test_extract_async_launches_pairs_id_and_type():
    entries = [
        # assistant turn issuing two Agent tool_use blocks
        {
            "type": "assistant",
            "message": {
                "id": "msg_a",
                "model": "claude-opus-4-7",
                "usage": {
                    "input_tokens": 1, "output_tokens": 2,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                },
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_async_1",
                        "name": "Agent",
                        "input": {"subagent_type": "claude-code-guide"},
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_async_2",
                        "name": "Agent",
                        "input": {"subagent_type": "general-purpose"},
                    },
                ],
            },
        },
        # user line: async_launched for first
        {
            "type": "user",
            "timestamp": "2026-04-23T11:00:00Z",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_async_1", "content": "launched"}
                ],
            },
            "toolUseResult": {
                "agentType": "claude-code-guide",
                "agentId": "agent-aaa-1",
                "status": "async_launched",
            },
        },
        # user line: async_launched for second
        {
            "type": "user",
            "timestamp": "2026-04-23T11:00:01Z",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_async_2", "content": "launched"}
                ],
            },
            "toolUseResult": {
                "agentType": "general-purpose",
                "agentId": "agent-bbb-2",
                "status": "async_launched",
            },
        },
    ]

    result = sidechain.extract_async_launches(entries)
    assert result == {
        "agent-aaa-1": ("toolu_async_1", "claude-code-guide"),
        "agent-bbb-2": ("toolu_async_2", "general-purpose"),
    }


def test_extract_async_launches_empty_when_no_launches():
    entries = [
        {
            "type": "assistant",
            "message": {
                "id": "msg_x", "model": "claude-opus-4-7",
                "usage": {"input_tokens": 1, "output_tokens": 1,
                          "cache_creation_input_tokens": 0,
                          "cache_read_input_tokens": 0},
                "content": [{"type": "text", "text": "hi"}],
            },
        },
        {
            "type": "user",
            "message": {"role": "user", "content": "hi"},
        },
    ]
    assert sidechain.extract_async_launches(entries) == {}


# ---------------------------------------------------------------------------
# collect_sidechain_subagents
# ---------------------------------------------------------------------------


def _write_sidechain_file(dir_path: Path, agent_id: str, lines: list[dict]) -> None:
    path = dir_path / f"agent-{agent_id}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for ln in lines:
            f.write(json.dumps(ln) + "\n")


def test_collect_sidechain_subagents_parses_existing_file(tmp_path):
    sub_dir = tmp_path / "sess" / "subagents"
    sub_dir.mkdir(parents=True)

    _write_sidechain_file(sub_dir, "agent-1", [
        {"type": "user", "message": {"role": "user", "content": "go"}},
        {
            "type": "assistant",
            "timestamp": "2026-04-23T12:00:00Z",
            "message": {
                "id": "msg_s1",
                "model": "claude-haiku-4-5",
                "usage": {
                    "input_tokens": 5,
                    "output_tokens": 7,
                    "cache_creation_input_tokens": 11,
                    "cache_read_input_tokens": 13,
                },
                "content": [{"type": "text", "text": "ack"}],
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-04-23T12:00:05Z",
            "message": {
                "id": "msg_s2",
                "model": "claude-haiku-4-5",
                "usage": {
                    "input_tokens": 1,
                    "output_tokens": 2,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 4,
                },
                "content": [{"type": "text", "text": "done"}],
            },
        },
    ])

    launches = {"agent-1": ("toolu_async_1", "claude-code-guide")}
    subs = sidechain.collect_sidechain_subagents(sub_dir, launches)
    assert len(subs) == 2
    assert all(isinstance(s, SubagentUsage) for s in subs)
    assert subs[0].agent_type == "claude-code-guide"
    assert subs[0].tool_use_id == "toolu_async_1"
    assert subs[0].input_tokens == 5
    assert subs[0].output_tokens == 7
    assert subs[1].input_tokens == 1
    assert subs[1].output_tokens == 2


def test_collect_sidechain_subagents_skips_missing_file(tmp_path):
    sub_dir = tmp_path / "sess" / "subagents"
    sub_dir.mkdir(parents=True)

    # Only agent-present.jsonl exists
    _write_sidechain_file(sub_dir, "present", [
        {
            "type": "assistant",
            "timestamp": "2026-04-23T12:00:00Z",
            "message": {
                "id": "msg_p1",
                "model": "claude-haiku-4-5",
                "usage": {
                    "input_tokens": 3, "output_tokens": 4,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                },
                "content": [],
            },
        },
    ])

    launches = {
        "present": ("toolu_p", "type-A"),
        "missing": ("toolu_m", "type-B"),
    }
    subs = sidechain.collect_sidechain_subagents(sub_dir, launches)
    # only present has a file → 1 SubagentUsage
    assert len(subs) == 1
    assert subs[0].tool_use_id == "toolu_p"
    assert subs[0].agent_type == "type-A"


def test_collect_skips_path_traversal_agent_id(tmp_path):
    """agent_id가 ../evil 같은 경로 탈출 문자를 포함하면 silent skip."""
    sub_dir = tmp_path / "sess" / "subagents"
    sub_dir.mkdir(parents=True)

    # Create a file outside sub_dir that traversal would resolve to.
    outside = tmp_path / "sess" / "evil.jsonl"
    outside.write_text(
        json.dumps({
            "type": "assistant",
            "timestamp": "2026-04-23T12:00:00Z",
            "message": {
                "id": "msg_evil", "model": "claude-haiku-4-5",
                "usage": {"input_tokens": 999, "output_tokens": 999,
                          "cache_creation_input_tokens": 0,
                          "cache_read_input_tokens": 0},
                "content": [],
            },
        }) + "\n",
        encoding="utf-8",
    )

    launches = {
        "../evil": ("toolu_x", "type-X"),
        "..": ("toolu_y", "type-Y"),
        "/abs/path": ("toolu_z", "type-Z"),
    }
    subs = sidechain.collect_sidechain_subagents(sub_dir, launches)
    assert subs == []


def test_collect_skips_symlink_targets(tmp_path):
    """sidechain dir 안의 agent-X.jsonl 이 symlink면 silent skip."""
    sub_dir = tmp_path / "sess" / "subagents"
    sub_dir.mkdir(parents=True)

    # Real file outside sub_dir.
    target = tmp_path / "outside.jsonl"
    target.write_text(
        json.dumps({
            "type": "assistant",
            "timestamp": "2026-04-23T12:00:00Z",
            "message": {
                "id": "msg_t", "model": "claude-haiku-4-5",
                "usage": {"input_tokens": 1, "output_tokens": 1,
                          "cache_creation_input_tokens": 0,
                          "cache_read_input_tokens": 0},
                "content": [],
            },
        }) + "\n",
        encoding="utf-8",
    )

    # Create symlink agent-evil.jsonl pointing to outside.
    link = sub_dir / "agent-evil.jsonl"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):  # platforms without symlink support
        import pytest
        pytest.skip("symlink not supported on this platform")

    launches = {"evil": ("toolu_x", "type-X")}
    subs = sidechain.collect_sidechain_subagents(sub_dir, launches)
    assert subs == []


def test_collect_handles_empty_sidechain_dir(tmp_path):
    """sidechain_dir이 존재하나 파일 0개. launches가 비어있지 않아도 빈 리스트 반환."""
    sub_dir = tmp_path / "sess" / "subagents"
    sub_dir.mkdir(parents=True)

    launches = {
        "alpha": ("toolu_a", "type-A"),
        "beta": ("toolu_b", "type-B"),
    }
    subs = sidechain.collect_sidechain_subagents(sub_dir, launches)
    assert subs == []


def test_collect_handles_empty_jsonl_file(tmp_path):
    """agent-X.jsonl이 0바이트. silent skip + 결과에 미포함."""
    sub_dir = tmp_path / "sess" / "subagents"
    sub_dir.mkdir(parents=True)

    # Empty (0-byte) file
    (sub_dir / "agent-empty.jsonl").write_text("", encoding="utf-8")
    # Real file as control
    _write_sidechain_file(sub_dir, "good", [
        {
            "type": "assistant",
            "timestamp": "2026-04-23T12:00:00Z",
            "message": {
                "id": "msg_g", "model": "claude-haiku-4-5",
                "usage": {"input_tokens": 5, "output_tokens": 6,
                          "cache_creation_input_tokens": 0,
                          "cache_read_input_tokens": 0},
                "content": [],
            },
        },
    ])

    launches = {
        "empty": ("toolu_e", "type-E"),
        "good": ("toolu_g", "type-G"),
    }
    subs = sidechain.collect_sidechain_subagents(sub_dir, launches)
    # Only the populated file contributes.
    assert len(subs) == 1
    assert subs[0].tool_use_id == "toolu_g"


def test_collect_sidechain_subagents_handles_corrupt_lines(tmp_path):
    sub_dir = tmp_path / "sess" / "subagents"
    sub_dir.mkdir(parents=True)

    path = sub_dir / "agent-corrupt.jsonl"
    with path.open("w", encoding="utf-8") as f:
        f.write('{not valid json\n')  # corrupt
        f.write(json.dumps({
            "type": "assistant",
            "timestamp": "2026-04-23T12:00:00Z",
            "message": {
                "id": "msg_c1",
                "model": "claude-haiku-4-5",
                "usage": {
                    "input_tokens": 9, "output_tokens": 8,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                },
                "content": [],
            },
        }) + "\n")
        f.write('\n')  # blank line
        f.write('{"also":"broken"\n')  # another corrupt

    launches = {"corrupt": ("toolu_c", "type-X")}
    subs = sidechain.collect_sidechain_subagents(sub_dir, launches)
    assert len(subs) == 1
    assert subs[0].input_tokens == 9
    assert subs[0].output_tokens == 8
