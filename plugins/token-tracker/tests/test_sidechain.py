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


# ---------------------------------------------------------------------------
# count_active_async_agents_from_file — graceful 동작 회귀 가드
# ---------------------------------------------------------------------------


def _async_launch_lines(tu_id: str, agent_id: str, agent_type: str = "general-purpose") -> list[dict]:
    """async dispatch 한 묶음 (assistant tool_use + user async_launched)."""
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
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": tu_id, "content": "launched"}
            ]},
            "toolUseResult": {
                "agentType": agent_type,
                "agentId": agent_id,
                "status": "async_launched",
            },
        },
    ]


def test_count_active_returns_1_when_sidechain_dir_missing_and_no_notification(tmp_path):
    """sidechain dir 자체가 없고 알림도 없으면 active=1 (정말로 진행 중)."""
    transcript = tmp_path / "session.jsonl"
    _write_jsonl(transcript, _async_launch_lines("toolu_1", "agent-ccc"))

    # session/subagents dir 만들지 않음
    assert sidechain.count_active_async_agents_from_file(str(transcript)) == 1


def test_count_active_treats_path_traversal_agent_id_as_no_match(tmp_path):
    """agent_id가 ../evil 같은 path traversal 시도여도 graceful — 외부 파일을
    읽고 완료로 오인하지 않는다."""
    transcript = tmp_path / "session.jsonl"
    # agent_id에 '/'가 들어가면 파싱 단계에서 잡히지 않을 수 있어
    # parse_async_launch가 그대로 받아들이는 케이스를 시뮬레이트하기 위해
    # agentId에 unsafe 문자열을 넣은 jsonl을 만든다.
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
                "agentId": "../evil",
                "status": "async_launched",
            },
        },
    ])

    # session/subagents 위치보다 한 단계 위에 evil.jsonl 배치
    sub_dir = tmp_path / "session" / "subagents"
    sub_dir.mkdir(parents=True)
    outside = tmp_path / "session" / "evil.jsonl"
    with outside.open("w", encoding="utf-8") as f:
        f.write(json.dumps({
            "type": "assistant",
            "message": {
                "id": "msg_evil",
                "model": "claude-haiku-4-5",
                "usage": {
                    "input_tokens": 1, "output_tokens": 1,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                },
                "content": [],
            },
        }) + "\n")

    # path traversal 시도는 silent skip → outside의 assistant 라인은 무시 →
    # active = 1 (launch만 있고 완료 없음)
    assert sidechain.count_active_async_agents_from_file(str(transcript)) == 1


def test_count_active_treats_completion_via_notification_first(tmp_path):
    """두 경로(notification, sidechain assistant) 중 어느 하나라도 통과하면 완료.

    이 테스트는 notification만 있고 sidechain 파일은 없는 케이스 — 기존 회귀
    회피 동작이 그대로 유지됨을 검증한다.
    """
    transcript = tmp_path / "session.jsonl"
    entries = _async_launch_lines("toolu_1", "agent-ddd")
    entries.append({
        "type": "user",
        "message": {
            "role": "user",
            "content": (
                "<task-notification>"
                "<task-id>agent-ddd</task-id>"
                "<status>completed</status>"
                "</task-notification>"
            ),
        },
    })
    _write_jsonl(transcript, entries)

    # sidechain dir 없음 → notification 경로만으로 완료 인식
    assert sidechain.count_active_async_agents_from_file(str(transcript)) == 0


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


# ---------------------------------------------------------------------------
# _completed_agent_ids — task-notification 형식별 매칭 회귀 가드 (T17)
# ---------------------------------------------------------------------------


def test_completed_agent_ids_from_queue_operation_line():
    """type=queue-operation + 최상위 content가 XML 문자열 (실측 가장 흔한 형태).

    회귀 시나리오: T16 이전 코드는 message.content와 attachment.content만 봤기
    때문에 queue-operation 라인에 들어온 task-notification을 놓쳤다 → active가
    줄지 않음. 이 형태도 잡아야 한다.
    """
    entry = {
        "type": "queue-operation",
        "content": (
            "<task-notification>\n"
            "<task-id>agent-queueop</task-id>\n"
            "<status>completed</status>\n"
            "</task-notification>"
        ),
    }
    assert sidechain._completed_agent_ids(entry) == ["agent-queueop"]


def test_completed_agent_ids_from_user_with_list_content():
    """type=user, message.content가 list of dict 형태 (각 block의 text/content 필드).

    Claude Code 일부 버전·세션 전환 케이스에서 task-notification이 user 라인의
    tool_result block 안에 끼어 들어오는 경우가 있다. status=completed라면 이
    경우도 권위 신호로 인정.
    """
    entry = {
        "type": "user",
        "message": {
            "content": [
                {"type": "tool_result", "tool_use_id": "tu_x", "content": "noise"},
                {
                    "type": "tool_result",
                    "tool_use_id": "tu_y",
                    "content": (
                        "preview line:\n"
                        "<task-notification>"
                        "<task-id>agent-listblock</task-id>"
                        "<status>completed</status>"
                        "</task-notification>"
                    ),
                },
            ],
        },
    }
    assert sidechain._completed_agent_ids(entry) == ["agent-listblock"]


def test_completed_agent_ids_from_user_with_list_text_field():
    """list block의 'text' 필드(예: assistant 응답 mirror)에 XML이 있어도 매칭."""
    entry = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "text",
                    "text": (
                        "<task-notification>"
                        "<task-id>agent-textfield</task-id>"
                        "<status>completed</status>"
                        "</task-notification>"
                    ),
                },
            ],
        },
    }
    assert sidechain._completed_agent_ids(entry) == ["agent-textfield"]


def test_completed_agent_ids_from_attachment_prompt_field():
    """type=attachment, attachment.prompt에 XML — 실측 attachment 라인의 표준 형태.

    기존 코드는 attachment.content만 봤지만 실측 jsonl에서는 prompt 필드가 채워진다.
    """
    entry = {
        "type": "attachment",
        "attachment": {
            "type": "queued_command",
            "prompt": (
                "<task-notification>"
                "<task-id>agent-prompt</task-id>"
                "<status>completed</status>"
                "</task-notification>"
            ),
            "commandMode": "task-notification",
        },
    }
    assert sidechain._completed_agent_ids(entry) == ["agent-prompt"]


def test_completed_agent_ids_ignores_non_completed_in_list_block():
    """list block 안의 status=running은 완료로 인정하지 않는다."""
    entry = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "content": (
                        "<task-notification>"
                        "<task-id>agent-running</task-id>"
                        "<status>running</status>"
                        "</task-notification>"
                    ),
                },
            ],
        },
    }
    assert sidechain._completed_agent_ids(entry) == []


def test_completed_agent_ids_ignores_non_queue_operation_top_content():
    """type이 queue-operation이 아닌데 top-level content에 XML이 있으면 무시.

    상위 content 필드가 우연히 채워진 다른 타입에 영향 받지 않도록.
    """
    entry = {
        "type": "system",
        "content": (
            "<task-notification>"
            "<task-id>agent-noop</task-id>"
            "<status>completed</status>"
            "</task-notification>"
        ),
    }
    assert sidechain._completed_agent_ids(entry) == []


def test_count_active_from_file_with_queue_operation_completions(tmp_path):
    """e2e 시뮬레이션: 3개 launch + 3개 queue-operation 완료 알림 → active=0.

    실측 jsonl 형태(launch 라인 + queue-operation 라인)를 그대로 재현해서
    `count_active_async_agents_from_file`이 모두 정상 매칭하는지 확인한다.
    """
    transcript = tmp_path / "session.jsonl"
    entries: list[dict] = []
    aids = ["agent-q1", "agent-q2", "agent-q3"]
    for i, aid in enumerate(aids, start=1):
        entries.extend(_async_launch_lines(f"toolu_{i}", aid))
    for aid in aids:
        entries.append({
            "type": "queue-operation",
            "content": (
                f"<task-notification>\n"
                f"<task-id>{aid}</task-id>\n"
                f"<tool-use-id>toolu_x</tool-use-id>\n"
                f"<status>completed</status>\n"
                f"</task-notification>"
            ),
        })
    _write_jsonl(transcript, entries)

    assert sidechain.count_active_async_agents_from_file(str(transcript)) == 0
