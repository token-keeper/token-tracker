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
        "agent-aaa-1": ("toolu_async_1", "claude-code-guide", ""),
        "agent-bbb-2": ("toolu_async_2", "general-purpose", ""),
    }


def test_extract_async_launches_returns_triple_with_model():
    """input.model이 있으면 (tool_use_id, agent_type, model) 트리플로 노출."""
    entries = [
        {
            "type": "assistant",
            "message": {
                "id": "msg_a",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_async_1",
                        "name": "Agent",
                        "input": {
                            "subagent_type": "general-purpose",
                            "model": "claude-haiku-4-5",
                        },
                    },
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_async_1", "content": "launched"}
                ],
            },
            "toolUseResult": {
                "agentType": "general-purpose",
                "agentId": "agent-aaa-1",
                "status": "async_launched",
            },
        },
    ]
    result = sidechain.extract_async_launches(entries)
    assert result == {
        "agent-aaa-1": ("toolu_async_1", "general-purpose", "claude-haiku-4-5"),
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

    launches = {"agent-1": ("toolu_async_1", "claude-code-guide", "")}
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
        "present": ("toolu_p", "type-A", ""),
        "missing": ("toolu_m", "type-B", ""),
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
        "../evil": ("toolu_x", "type-X", ""),
        "..": ("toolu_y", "type-Y", ""),
        "/abs/path": ("toolu_z", "type-Z", ""),
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

    launches = {"evil": ("toolu_x", "type-X", "")}
    subs = sidechain.collect_sidechain_subagents(sub_dir, launches)
    assert subs == []


def test_collect_handles_empty_sidechain_dir(tmp_path):
    """sidechain_dir이 존재하나 파일 0개. launches가 비어있지 않아도 빈 리스트 반환."""
    sub_dir = tmp_path / "sess" / "subagents"
    sub_dir.mkdir(parents=True)

    launches = {
        "alpha": ("toolu_a", "type-A", ""),
        "beta": ("toolu_b", "type-B", ""),
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
        "empty": ("toolu_e", "type-E", ""),
        "good": ("toolu_g", "type-G", ""),
    }
    subs = sidechain.collect_sidechain_subagents(sub_dir, launches)
    # Only the populated file contributes.
    assert len(subs) == 1
    assert subs[0].tool_use_id == "toolu_g"


def test_collect_sidechain_uses_assistant_model_first(tmp_path):
    """sidechain assistant 라인의 message.model이 우선이고, launches의 fallback
    model은 sidechain model이 빈 값일 때만 사용된다."""
    sub_dir = tmp_path / "sess" / "subagents"
    sub_dir.mkdir(parents=True)

    _write_sidechain_file(sub_dir, "agent-with-model", [
        {
            "type": "assistant",
            "timestamp": "2026-04-23T12:00:00Z",
            "message": {
                "id": "msg_a",
                "model": "claude-haiku-4-5",  # sidechain own model — should win
                "usage": {
                    "input_tokens": 1, "output_tokens": 2,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                },
                "content": [],
            },
        },
    ])
    _write_sidechain_file(sub_dir, "agent-no-model", [
        {
            "type": "assistant",
            "timestamp": "2026-04-23T12:00:00Z",
            "message": {
                "id": "msg_b",
                # message.model omitted — caller-side launch model is fallback
                "usage": {
                    "input_tokens": 3, "output_tokens": 4,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                },
                "content": [],
            },
        },
    ])

    launches = {
        # caller dispatched with model: sonnet, but sidechain says haiku → haiku wins
        "agent-with-model": ("toolu_w", "general-purpose", "claude-sonnet-4-6"),
        # caller dispatched with sonnet, sidechain has no model → fall back to sonnet
        "agent-no-model": ("toolu_n", "general-purpose", "claude-sonnet-4-6"),
    }
    subs = sidechain.collect_sidechain_subagents(sub_dir, launches)
    by_tu = {s.tool_use_id: s for s in subs}
    assert by_tu["toolu_w"].model == "claude-haiku-4-5"
    assert by_tu["toolu_n"].model == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# count_active_async_agents (D 옵션 — async 활성 중에는 Stop 출력 silent)
# ---------------------------------------------------------------------------


def _async_launch(tu_id: str, agent_id: str, agent_type: str = "general-purpose") -> list[dict]:
    """async dispatch 한 묶음: assistant tool_use + user async_launched."""
    return [
        {
            "type": "assistant",
            "message": {
                "id": f"msg_{agent_id}",
                "content": [
                    {
                        "type": "tool_use",
                        "id": tu_id,
                        "name": "Agent",
                        "input": {"subagent_type": agent_type},
                    }
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": tu_id, "content": "launched"}
                ],
            },
            "toolUseResult": {
                "agentType": agent_type,
                "agentId": agent_id,
                "status": "async_launched",
            },
        },
    ]


def _completion_notification(agent_id: str) -> dict:
    """task-notification XML for a completed async agent (queue-operation 라인)."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": (
                f"<task-notification>"
                f"<task-id>{agent_id}</task-id>"
                f"<status>completed</status>"
                f"</task-notification>"
            ),
        },
    }


def test_count_active_async_agents_returns_zero_when_no_launches():
    entries = [
        {"type": "user", "message": {"role": "user", "content": "hi"}},
    ]
    assert sidechain.count_active_async_agents(entries) == 0


def test_count_active_async_agents_counts_pending_launches():
    """launch만 있고 completed 알림 없으면 그 수만큼 active."""
    entries = []
    entries.extend(_async_launch("toolu_1", "agent-aaa"))
    entries.extend(_async_launch("toolu_2", "agent-bbb"))
    entries.extend(_async_launch("toolu_3", "agent-ccc"))
    assert sidechain.count_active_async_agents(entries) == 3


def test_count_active_async_agents_subtracts_completions():
    """active = launched - completed. 완료 알림이 있으면 그만큼 빠진다."""
    entries = []
    entries.extend(_async_launch("toolu_1", "agent-aaa"))
    entries.extend(_async_launch("toolu_2", "agent-bbb"))
    entries.extend(_async_launch("toolu_3", "agent-ccc"))
    # 1, 3 완료
    entries.append(_completion_notification("agent-aaa"))
    entries.append(_completion_notification("agent-ccc"))
    assert sidechain.count_active_async_agents(entries) == 1


def test_count_active_async_agents_returns_zero_when_all_complete():
    entries = []
    entries.extend(_async_launch("toolu_1", "agent-aaa"))
    entries.append(_completion_notification("agent-aaa"))
    assert sidechain.count_active_async_agents(entries) == 0


def test_count_active_async_agents_recognizes_attachment_queued_command():
    """attachment.type=='queued_command' + queued_command.content가 task-notification XML.

    Claude Code는 queue-operation 라인 외에도 attachment 형태로 같은 알림을 흘릴 수 있다.
    두 형태 모두 지원해야 한다.
    """
    entries = []
    entries.extend(_async_launch("toolu_1", "agent-zzz"))
    entries.append({
        "type": "attachment",
        "attachment": {
            "type": "queued_command",
            "content": (
                "<task-notification>"
                "<task-id>agent-zzz</task-id>"
                "<status>completed</status>"
                "</task-notification>"
            ),
        },
    })
    assert sidechain.count_active_async_agents(entries) == 0


def test_count_active_async_agents_ignores_non_completed_status():
    """status != completed 알림은 아직 끝나지 않은 것으로 간주."""
    entries = []
    entries.extend(_async_launch("toolu_1", "agent-aaa"))
    entries.append({
        "type": "user",
        "message": {
            "role": "user",
            "content": (
                "<task-notification>"
                "<task-id>agent-aaa</task-id>"
                "<status>running</status>"
                "</task-notification>"
            ),
        },
    })
    assert sidechain.count_active_async_agents(entries) == 1


# ---------------------------------------------------------------------------
# extract_async_launches_from_file (Bug A — file-based 전체 jsonl 스캔)
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, entries: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def test_extract_async_launches_from_file_reads_full_jsonl(tmp_path):
    """jsonl 파일을 처음부터 끝까지 읽어 launches를 추출한다.

    회귀 시나리오: dispatch 직후가 아닌 다음 turn에서 Stop hook이 발화하면
    `_read_tail(transcript_path, offset)`이 dispatch 라인 뒤만 read해서
    `extract_async_launches`가 launches를 잡지 못한다. file-based 변형은 offset
    무시하고 전체를 읽으므로 장면이 분리돼도 launches를 정상 매핑.
    """
    transcript = tmp_path / "session.jsonl"
    _write_jsonl(transcript, [
        # turn 1: dispatch (assistant tool_use + async_launched)
        {
            "type": "assistant",
            "message": {
                "id": "msg_a",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_async_1",
                        "name": "Agent",
                        "input": {"subagent_type": "claude-code-guide"},
                    },
                ],
            },
        },
        {
            "type": "user",
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
        # turn 2: 다른 user prompt + 다른 assistant 응답 (dispatch 와 무관)
        {"type": "user", "message": {"role": "user", "content": "next prompt"}},
        {
            "type": "assistant",
            "message": {
                "id": "msg_b",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {
                    "input_tokens": 1, "output_tokens": 1,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                },
            },
        },
    ])

    result = sidechain.extract_async_launches_from_file(str(transcript))
    assert result == {
        "agent-aaa-1": ("toolu_async_1", "claude-code-guide", ""),
    }


def test_extract_async_launches_from_file_returns_empty_when_no_launches(tmp_path):
    transcript = tmp_path / "session.jsonl"
    _write_jsonl(transcript, [
        {"type": "user", "message": {"role": "user", "content": "hi"}},
        {
            "type": "assistant",
            "message": {
                "id": "msg_x",
                "content": [{"type": "text", "text": "hi"}],
                "usage": {
                    "input_tokens": 1, "output_tokens": 1,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                },
            },
        },
    ])
    assert sidechain.extract_async_launches_from_file(str(transcript)) == {}


def test_extract_async_launches_from_file_returns_empty_when_path_missing(tmp_path):
    """파일이 없거나 빈 경로면 빈 dict (예외 없이 graceful)."""
    assert sidechain.extract_async_launches_from_file("") == {}
    assert sidechain.extract_async_launches_from_file(str(tmp_path / "no-such.jsonl")) == {}


def test_extract_async_launches_from_file_skips_corrupt_lines(tmp_path):
    """invalid JSON 라인은 skip하고 진행."""
    transcript = tmp_path / "session.jsonl"
    with transcript.open("w", encoding="utf-8") as f:
        f.write('{not valid json\n')
        f.write(json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg_a",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_async_1",
                        "name": "Agent",
                        "input": {"subagent_type": "general-purpose"},
                    },
                ],
            },
        }) + "\n")
        f.write('\n')  # blank
        f.write(json.dumps({
            "type": "user",
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_async_1", "content": "launched"}
                ],
            },
            "toolUseResult": {
                "agentType": "general-purpose",
                "agentId": "agent-bbb",
                "status": "async_launched",
            },
        }) + "\n")
        f.write('{"also":"broken"\n')

    result = sidechain.extract_async_launches_from_file(str(transcript))
    assert result == {"agent-bbb": ("toolu_async_1", "general-purpose", "")}


# ---------------------------------------------------------------------------
# count_active_async_agents_from_file (Bug A — file-based 변형)
# ---------------------------------------------------------------------------


def test_count_active_async_agents_from_file_reads_full_jsonl(tmp_path):
    """dispatch가 jsonl 앞부분에 있고 그 뒤에 다른 turn이 추가돼도 active 카운트가 정확.

    `count_active_async_agents(entries)`는 _read_tail offset 뒤만 보므로
    이전 turn의 dispatch를 못 본다. file-based 변형은 전체 jsonl 읽음.
    """
    transcript = tmp_path / "session.jsonl"
    _write_jsonl(transcript, [
        # turn 1: dispatch agent-aaa
        {
            "type": "assistant",
            "message": {
                "id": "msg_a",
                "content": [{
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "Agent",
                    "input": {"subagent_type": "general-purpose"},
                }],
            },
        },
        {
            "type": "user",
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "launched"}
            ]},
            "toolUseResult": {
                "agentType": "general-purpose",
                "agentId": "agent-aaa",
                "status": "async_launched",
            },
        },
        # turn 2: 다른 prompt + 응답 (dispatch 없음)
        {"type": "user", "message": {"role": "user", "content": "another"}},
        {
            "type": "assistant",
            "message": {
                "id": "msg_b",
                "content": [{"type": "text", "text": "ack"}],
                "usage": {
                    "input_tokens": 1, "output_tokens": 1,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                },
            },
        },
    ])
    # agent-aaa 미완 → active=1
    assert sidechain.count_active_async_agents_from_file(str(transcript)) == 1


def test_count_active_async_agents_from_file_subtracts_completions(tmp_path):
    transcript = tmp_path / "session.jsonl"
    _write_jsonl(transcript, [
        {
            "type": "assistant",
            "message": {
                "id": "msg_a",
                "content": [{
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "Agent",
                    "input": {"subagent_type": "general-purpose"},
                }],
            },
        },
        {
            "type": "user",
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "launched"}
            ]},
            "toolUseResult": {
                "agentType": "general-purpose",
                "agentId": "agent-aaa",
                "status": "async_launched",
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": (
                    "<task-notification>"
                    "<task-id>agent-aaa</task-id>"
                    "<status>completed</status>"
                    "</task-notification>"
                ),
            },
        },
    ])
    assert sidechain.count_active_async_agents_from_file(str(transcript)) == 0


def test_count_active_async_agents_from_file_returns_zero_when_path_missing(tmp_path):
    assert sidechain.count_active_async_agents_from_file("") == 0
    assert sidechain.count_active_async_agents_from_file(str(tmp_path / "no.jsonl")) == 0


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

    launches = {"corrupt": ("toolu_c", "type-X", "")}
    subs = sidechain.collect_sidechain_subagents(sub_dir, launches)
    assert len(subs) == 1
    assert subs[0].input_tokens == 9
    assert subs[0].output_tokens == 8
