import json
import os
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "sample_session.jsonl"


def _run(script: str, payload: dict, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "hooks" / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )


def test_full_cycle_format(tmp_path):
    """Verify the systemMessage JSON structure is emitted, even with zero new turns."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"
    session_path.write_bytes(FIXTURE.read_bytes())

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)

    payload = {
        "session_id": "e2e-1",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    r1 = _run("on_user_prompt.py", payload, env)
    assert r1.returncode == 0, r1.stderr

    payload["hook_event_name"] = "Stop"
    r2 = _run("on_stop.py", payload, env)
    assert r2.returncode == 0, r2.stderr

    out = json.loads(r2.stdout)
    assert out.get("continue") is True
    msg = out.get("systemMessage", "")
    assert "toks" in msg
    assert "cache" in msg


def test_missing_state_with_turns_emits(tmp_path):
    """Stop with no prior state but readable turns should still emit."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"
    session_path.write_bytes(FIXTURE.read_bytes())

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)

    payload = {
        "session_id": "no-state",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "Stop",
    }
    r = _run("on_stop.py", payload, env)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out.get("continue") is True
    assert "systemMessage" in out


def test_missing_state_empty_transcript_stays_silent(tmp_path):
    """Spurious Stop (no UserPromptSubmit beforehand) with no turns should produce no
    systemMessage — avoids noisy "$0.0000 · 0 toks · cache 0%" output."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"
    session_path.write_text("", encoding="utf-8")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)

    payload = {
        "session_id": "silent",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "Stop",
    }
    r = _run("on_stop.py", payload, env)
    assert r.returncode == 0
    assert r.stdout.strip() == "", f"Expected silent stdout, got: {r.stdout!r}"


def test_last_summary_saved_after_stop(tmp_path):
    """Stop hook must persist the aggregated Summary for downstream readers (verbose mode, future tools)."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"
    # Start with empty transcript — UserPromptSubmit records offset=0.
    session_path.write_text("", encoding="utf-8")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)

    session_id = "sess-persist"
    payload = {
        "session_id": session_id,
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0

    # Simulate the assistant response arriving: append fixture turns.
    session_path.write_bytes(FIXTURE.read_bytes())

    payload["hook_event_name"] = "Stop"
    assert _run("on_stop.py", payload, env).returncode == 0

    summary_file = (
        fake_home / ".claude" / "plugins" / "token-tracker"
        / "state" / session_id / "last_summary.json"
    )
    assert summary_file.is_file(), f"last_summary.json not saved at {summary_file}"
    data = json.loads(summary_file.read_text(encoding="utf-8"))
    assert data["schema_version"] == 3
    assert data["session_id"] == session_id
    assert isinstance(data["summary"]["turns"], list)
    assert len(data["summary"]["turns"]) >= 1


def test_verbose_env_appends_detail_table_to_system_message(tmp_path):
    """TOKEN_TRACKER_VERBOSE=1 이면 Stop hook이 한 줄 요약 + 상세 표를 함께 emit해야 한다."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"
    session_path.write_text("", encoding="utf-8")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)
    env["TOKEN_TRACKER_VERBOSE"] = "1"

    session_id = "sess-verbose"
    payload = {
        "session_id": session_id,
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0

    # Assistant response arrives
    session_path.write_bytes(FIXTURE.read_bytes())

    payload["hook_event_name"] = "Stop"
    r = _run("on_stop.py", payload, env)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    msg = out["systemMessage"]
    # one-liner still present
    assert "toks" in msg
    # detail table markers present
    assert "━" in msg
    assert "cc=cache_creation" in msg


def test_verbose_off_keeps_single_line_system_message(tmp_path):
    """verbose가 꺼져 있으면 기존처럼 한 줄만 emit하고 표는 포함 안 된다."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"
    session_path.write_text("", encoding="utf-8")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)
    # env가 config을 override — 실제 repo의 config.json이 verbose:true여도 test는 격리.
    env["TOKEN_TRACKER_VERBOSE"] = "0"

    payload = {
        "session_id": "sess-quiet",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0
    session_path.write_bytes(FIXTURE.read_bytes())
    payload["hook_event_name"] = "Stop"
    r = _run("on_stop.py", payload, env)
    out = json.loads(r.stdout)
    msg = out["systemMessage"]
    assert "toks" in msg
    assert "━" not in msg


def test_last_summary_not_saved_when_no_turns(tmp_path):
    """If the hook produces zero turns (silent-skip path), do not persist an empty summary."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"
    session_path.write_text("", encoding="utf-8")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)

    session_id = "sess-empty"
    payload = {
        "session_id": session_id,
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "Stop",
    }
    _run("on_stop.py", payload, env)

    summary_file = (
        fake_home / ".claude" / "plugins" / "token-tracker"
        / "state" / session_id / "last_summary.json"
    )
    assert not summary_file.exists(), (
        f"Unexpected last_summary.json at {summary_file}"
    )


def test_realistic_cycle_counts_new_turns(tmp_path):
    """Simulate production flow:
    1. session.jsonl has only a user line initially.
    2. UserPromptSubmit hook records offset at end of user line.
    3. Claude responds — assistant lines get appended to JSONL.
    4. Stop hook reads from recorded offset → captures only new assistant turns.

    Assert that the emitted summary has non-zero tokens (proving aggregation works).
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"

    # Read fixture lines (4 total: user, assistant, tool_result, assistant).
    all_lines = FIXTURE.read_text().splitlines()
    user_only = all_lines[0] + "\n"
    rest = "\n".join(all_lines[1:]) + "\n"

    # Step 1: only user line is present when UserPromptSubmit fires.
    session_path.write_text(user_only, encoding="utf-8")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)

    payload = {
        "session_id": "realistic",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    r1 = _run("on_user_prompt.py", payload, env)
    assert r1.returncode == 0

    # Step 2: simulate Claude appending assistant turns to JSONL.
    with session_path.open("a", encoding="utf-8") as f:
        f.write(rest)

    # Step 3: Stop hook should read only the appended portion.
    payload["hook_event_name"] = "Stop"
    r2 = _run("on_stop.py", payload, env)
    assert r2.returncode == 0, r2.stderr
    out = json.loads(r2.stdout)
    assert out["continue"] is True

    msg = out["systemMessage"]
    # Aggregation sanity: 2 assistant turns with usage should not produce "0 toks".
    import re
    m = re.search(r"([\d,]+) toks", msg)
    assert m, f"expected 'N toks' in output, got: {msg!r}"
    assert int(m.group(1).replace(",", "")) > 0
    # Cache hit rate = cache_read / (input + cache_creation + cache_read)
    # Fixture totals: in=10+100=110, cc=0+500=500, cr=0+2000=2000 → 2000/2610 ≈ 77%
    assert "cache 77%" in msg, f"Expected cache 77%, got: {msg!r}"


def test_stop_polls_for_delayed_flush(tmp_path):
    """If the JSONL has grown past our offset but the new content is only
    non-assistant lines initially, the hook should retry once more content
    arrives. Simulate by starting a background writer that appends the
    assistant line after a short delay."""
    import threading
    import time as _time

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"

    all_lines = FIXTURE.read_text().splitlines()
    # Start: user + a non-assistant line (attachment-like) already present.
    prefix = all_lines[0] + "\n" + all_lines[2] + "\n"  # user + tool_result
    # After delay: append an assistant line with usage.
    assistant_line = all_lines[3] + "\n"

    session_path.write_text(prefix, encoding="utf-8")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)

    # Record offset *inside* the prefix (before the assistant arrives).
    payload = {
        "session_id": "poll",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    _run("on_user_prompt.py", payload, env)

    def _delayed_append():
        _time.sleep(0.15)
        with session_path.open("a", encoding="utf-8") as f:
            f.write(assistant_line)

    t = threading.Thread(target=_delayed_append)
    t.start()
    try:
        payload["hook_event_name"] = "Stop"
        r = _run("on_stop.py", payload, env)
    finally:
        t.join()

    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    msg = out["systemMessage"]
    # Extract the "N toks" number; must be > 0 (polling caught the late assistant line).
    import re
    m = re.search(r"([\d,]+) toks", msg)
    assert m, f"expected 'N toks' in output, got: {msg!r}"
    toks = int(m.group(1).replace(",", ""))
    assert toks > 0, f"polling should have caught the delayed assistant line, got {toks} toks in: {msg!r}"


def test_stop_polls_until_subagent_result_lands(tmp_path):
    """Agent dispatch turn: assistant 라인은 이미 jsonl에 있지만 subagent의
    tool_result(toolUseResult.status=="completed") 라인은 아직 flush 전.
    polling 조건이 'turns가 비었을 때'만이면 turns≥1이라 즉시 종료 → fg sub drop.
    polling을 sub 매칭 미완에도 적용하면 backgrounded writer가 라인을 append할 때까지
    기다렸다가 sub usage를 합산해야 한다."""
    import threading
    import time as _time

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"

    user_line = {
        "type": "user",
        "uuid": "u-1",
        "timestamp": "2026-04-23T10:00:00.000Z",
        "message": {"role": "user", "content": "go"},
    }
    assistant_with_agent = {
        "type": "assistant",
        "uuid": "a-1",
        "timestamp": "2026-04-23T10:00:01.000Z",
        "message": {
            "id": "msg_main_1",
            "role": "assistant",
            "model": "claude-opus-4-7",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_X",
                    "name": "Agent",
                    "input": {"subagent_type": "claude-code-guide"},
                }
            ],
            "usage": {
                "input_tokens": 50,
                "output_tokens": 10,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
    }
    delayed_tool_result = {
        "type": "user",
        "uuid": "u-2",
        "timestamp": "2026-04-23T10:00:02.000Z",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_X", "content": "ok"}
            ],
        },
        "toolUseResult": {
            "agentType": "claude-code-guide",
            "status": "completed",
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 200,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
            "totalDurationMs": 5000,
        },
    }

    # Step 1: only the user line at UserPromptSubmit time
    with session_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(user_line) + "\n")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)

    payload = {
        "session_id": "poll-sub",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0

    # Step 2: append the assistant turn now (turns≥1 immediately on Stop read)
    with session_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(assistant_with_agent) + "\n")

    # Step 3: writer thread appends the sub tool_result after 200ms — within
    # polling window (5×100ms = 500ms).
    def _delayed_append():
        _time.sleep(0.2)
        with session_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(delayed_tool_result) + "\n")

    t = threading.Thread(target=_delayed_append)
    t.start()
    try:
        payload["hook_event_name"] = "Stop"
        r = _run("on_stop.py", payload, env)
    finally:
        t.join()

    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    msg = out["systemMessage"]

    # Expected: main(50+10=60) + sub(1000+200=1200) = 1260 toks.
    # If polling stopped early on turns≥1 only, sub would be dropped → 60 toks.
    import re
    m = re.search(r"([\d,]+) toks", msg)
    assert m, f"expected 'N toks' in output, got: {msg!r}"
    toks = int(m.group(1).replace(",", ""))
    assert toks == 1260, (
        f"polling should have waited for sub tool_result; expected 1260 toks, "
        f"got {toks} in: {msg!r}"
    )


def test_stop_returns_after_max_polls_when_subagent_never_arrives(tmp_path):
    """assistant 라인의 Agent tool_use가 있어도 sub 결과가 영영 안 들어오면
    hook은 ~500ms (5×100ms) 안에 종료해야 한다 (무한 대기 X). systemMessage는
    메인 turn만 출력 — sub 0건 graceful degradation."""
    import time as _time

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"

    user_line = {
        "type": "user",
        "uuid": "u-1",
        "timestamp": "2026-04-23T10:00:00.000Z",
        "message": {"role": "user", "content": "go"},
    }
    assistant_with_agent = {
        "type": "assistant",
        "uuid": "a-1",
        "timestamp": "2026-04-23T10:00:01.000Z",
        "message": {
            "id": "msg_main_1",
            "role": "assistant",
            "model": "claude-opus-4-7",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_NEVER",
                    "name": "Agent",
                    "input": {"subagent_type": "claude-code-guide"},
                }
            ],
            "usage": {
                "input_tokens": 50,
                "output_tokens": 10,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
    }

    with session_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(user_line) + "\n")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)

    payload = {
        "session_id": "poll-nobody",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0

    with session_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(assistant_with_agent) + "\n")

    payload["hook_event_name"] = "Stop"
    start = _time.time()
    r = _run("on_stop.py", payload, env)
    elapsed = _time.time() - start

    assert r.returncode == 0, r.stderr
    # 500ms polling cap + subprocess overhead. Generous upper bound: 3s.
    # The test's value is the < ∞ check — confirm bounded.
    assert elapsed < 3.0, f"hook took {elapsed:.2f}s — polling cap not enforced"

    out = json.loads(r.stdout)
    msg = out["systemMessage"]
    import re
    m = re.search(r"([\d,]+) toks", msg)
    assert m, f"expected 'N toks' in output, got: {msg!r}"
    toks = int(m.group(1).replace(",", ""))
    # Sub never landed → only main(60) counted; graceful degradation.
    assert toks == 60, f"expected main-only 60 toks, got {toks} in: {msg!r}"


def test_sidechain_async_subagent_tokens_included_in_summary(tmp_path):
    """When the transcript launches an async Agent and a sidechain jsonl exists,
    the Stop hook must read the sidechain assistant turns and include their
    tokens in the systemMessage one-liner."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # transcript path stem must match the sidechain dir name.
    session_stem = "sess-side"
    session_path = tmp_path / f"{session_stem}.jsonl"
    sidechain_dir = tmp_path / session_stem / "subagents"
    sidechain_dir.mkdir(parents=True)

    # Main transcript: user → assistant (Agent tool_use) → user (async_launched)
    main_lines = [
        {
            "type": "user",
            "uuid": "u-main-1",
            "timestamp": "2026-04-23T10:00:00.000Z",
            "message": {"role": "user", "content": "go"},
        },
        {
            "type": "assistant",
            "uuid": "a-main-1",
            "timestamp": "2026-04-23T10:00:01.000Z",
            "message": {
                "id": "msg_main_1",
                "role": "assistant",
                "model": "claude-opus-4-7",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_async_1",
                        "name": "Agent",
                        "input": {"subagent_type": "claude-code-guide"},
                    }
                ],
                "usage": {
                    "input_tokens": 50,
                    "output_tokens": 10,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        },
        {
            "type": "user",
            "uuid": "u-launch-1",
            "timestamp": "2026-04-23T10:00:02.000Z",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_async_1", "content": "launched"}
                ],
            },
            "toolUseResult": {
                "agentType": "claude-code-guide",
                "agentId": "agent-side-1",
                "status": "async_launched",
            },
        },
        # active=0 시점에서 emit 검증 — D 옵션 default가 silent를 유발하지 않게 completed 추가.
        {
            "type": "user",
            "uuid": "u-done-1",
            "timestamp": "2026-04-23T10:00:05.000Z",
            "message": {
                "role": "user",
                "content": (
                    "<task-notification>"
                    "<task-id>agent-side-1</task-id>"
                    "<status>completed</status>"
                    "</task-notification>"
                ),
            },
        },
    ]
    # Step 1: only user line is present at UserPromptSubmit time
    # so the recorded offset starts before assistant lines.
    with session_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(main_lines[0]) + "\n")

    # Sidechain jsonl with one assistant turn (subagent's own tokens).
    sidechain_lines = [
        {
            "type": "assistant",
            "timestamp": "2026-04-23T10:00:03.000Z",
            "message": {
                "id": "msg_side_1",
                "role": "assistant",
                "model": "claude-haiku-4-5",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 200,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        }
    ]
    side_file = sidechain_dir / "agent-agent-side-1.jsonl"
    with side_file.open("w", encoding="utf-8") as f:
        for ln in sidechain_lines:
            f.write(json.dumps(ln) + "\n")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)

    payload = {
        "session_id": "e2e-side",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0

    # Step 2: assistant + async_launched lines arrive after UserPromptSubmit
    with session_path.open("a", encoding="utf-8") as f:
        for ln in main_lines[1:]:
            f.write(json.dumps(ln) + "\n")

    payload["hook_event_name"] = "Stop"
    r = _run("on_stop.py", payload, env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    msg = out["systemMessage"]

    # Expected tokens: main(50+10) + sidechain(1000+200) = 1260
    # input side counts input + cache_creation + cache_read; here cache=0.
    import re
    m = re.search(r"([\d,]+) toks", msg)
    assert m, f"expected 'N toks' in output, got: {msg!r}"
    toks = int(m.group(1).replace(",", ""))
    assert toks == 1260, (
        f"expected main(60) + sidechain(1200) = 1260 toks, got {toks} in: {msg!r}"
    )


def test_foreground_sub_model_filled_from_tool_use_input(tmp_path):
    """foreground sub은 메인 jsonl의 Agent tool_use input.model에서 model이
    채워져 last_summary.json에 저장돼야 한다."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"

    user_line = {
        "type": "user",
        "uuid": "u-1",
        "timestamp": "2026-04-23T10:00:00.000Z",
        "message": {"role": "user", "content": "go"},
    }
    assistant_with_agent = {
        "type": "assistant",
        "uuid": "a-1",
        "timestamp": "2026-04-23T10:00:01.000Z",
        "message": {
            "id": "msg_main_1",
            "role": "assistant",
            "model": "claude-opus-4-7",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_FG",
                    "name": "Agent",
                    "input": {
                        "subagent_type": "general-purpose",
                        "model": "claude-haiku-4-5",  # explicit dispatch model
                    },
                }
            ],
            "usage": {
                "input_tokens": 50,
                "output_tokens": 10,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        },
    }
    fg_tool_result = {
        "type": "user",
        "uuid": "u-2",
        "timestamp": "2026-04-23T10:00:02.000Z",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_FG", "content": "ok"}
            ],
        },
        "toolUseResult": {
            "agentType": "general-purpose",
            "status": "completed",
            "usage": {
                "input_tokens": 100, "output_tokens": 20,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
            "totalDurationMs": 5000,
        },
    }

    with session_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(user_line) + "\n")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)

    session_id = "fg-model"
    payload = {
        "session_id": session_id,
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0

    with session_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(assistant_with_agent) + "\n")
        f.write(json.dumps(fg_tool_result) + "\n")

    payload["hook_event_name"] = "Stop"
    r = _run("on_stop.py", payload, env)
    assert r.returncode == 0

    summary_file = (
        fake_home / ".claude" / "plugins" / "token-tracker"
        / "state" / session_id / "last_summary.json"
    )
    data = json.loads(summary_file.read_text(encoding="utf-8"))
    turns = data["summary"]["turns"]
    assert len(turns) == 1
    subs = turns[0]["subagents"]
    assert len(subs) == 1
    assert subs[0]["model"] == "claude-haiku-4-5"


def test_systemMessage_omits_legend_when_all_subs_have_model(tmp_path):
    """모든 sub의 model이 알려져 있으면 verbose 표 footer에 sub legend가 출력되지 않아야 한다."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"

    user_line = {
        "type": "user",
        "uuid": "u-1",
        "timestamp": "2026-04-23T10:00:00.000Z",
        "message": {"role": "user", "content": "go"},
    }
    assistant_with_agent = {
        "type": "assistant",
        "uuid": "a-1",
        "timestamp": "2026-04-23T10:00:01.000Z",
        "message": {
            "id": "msg_main_1",
            "role": "assistant",
            "model": "claude-opus-4-7",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_FG2",
                    "name": "Agent",
                    "input": {
                        "subagent_type": "general-purpose",
                        "model": "claude-haiku-4-5",
                    },
                }
            ],
            "usage": {
                "input_tokens": 50, "output_tokens": 10,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
        },
    }
    fg_tool_result = {
        "type": "user",
        "uuid": "u-2",
        "timestamp": "2026-04-23T10:00:02.000Z",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_FG2", "content": "ok"}
            ],
        },
        "toolUseResult": {
            "agentType": "general-purpose",
            "status": "completed",
            "usage": {
                "input_tokens": 100, "output_tokens": 20,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
            "totalDurationMs": 5000,
        },
    }

    with session_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(user_line) + "\n")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)
    env["TOKEN_TRACKER_VERBOSE"] = "1"

    payload = {
        "session_id": "no-legend",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0
    with session_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(assistant_with_agent) + "\n")
        f.write(json.dumps(fg_tool_result) + "\n")

    payload["hook_event_name"] = "Stop"
    r = _run("on_stop.py", payload, env)
    out = json.loads(r.stdout)
    msg = out["systemMessage"]
    # ko legend text — should NOT appear when all sub models known
    assert "subagent 비용은 부모 모델 단가로 추정" not in msg, (
        f"legend should be omitted when all sub models known; got: {msg!r}"
    )


def test_stop_silent_when_async_agents_still_active(tmp_path):
    """async background dispatch가 활성 중이면 systemMessage emit 생략 (옵션 D).

    fixture: async_launched 라인 1개 + completed 알림 0개 → active=1 →
    Stop hook은 stdout이 비어있어야 한다 (또는 systemMessage 없음).
    단 last_summary는 여전히 저장돼서 active=0 시점의 emit이 누적치를 보여주도록.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"

    user_line = {
        "type": "user",
        "uuid": "u-1",
        "timestamp": "2026-04-23T10:00:00.000Z",
        "message": {"role": "user", "content": "go"},
    }
    assistant_with_async_agent = {
        "type": "assistant",
        "uuid": "a-1",
        "timestamp": "2026-04-23T10:00:01.000Z",
        "message": {
            "id": "msg_main_1",
            "role": "assistant",
            "model": "claude-opus-4-7",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_BG",
                    "name": "Agent",
                    "input": {"subagent_type": "general-purpose"},
                }
            ],
            "usage": {
                "input_tokens": 50, "output_tokens": 10,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
        },
    }
    async_launched = {
        "type": "user",
        "uuid": "u-2",
        "timestamp": "2026-04-23T10:00:02.000Z",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_BG", "content": "launched"}
            ],
        },
        "toolUseResult": {
            "agentType": "general-purpose",
            "agentId": "agent-bg-1",
            "status": "async_launched",
        },
    }

    with session_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(user_line) + "\n")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)
    # verbose off — silent path
    env["TOKEN_TRACKER_VERBOSE"] = "0"

    session_id = "active-bg"
    payload = {
        "session_id": session_id,
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0

    with session_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(assistant_with_async_agent) + "\n")
        f.write(json.dumps(async_launched) + "\n")

    payload["hook_event_name"] = "Stop"
    r = _run("on_stop.py", payload, env)
    assert r.returncode == 0
    # Silent: either empty stdout, or JSON without systemMessage
    if r.stdout.strip():
        out = json.loads(r.stdout)
        assert "systemMessage" not in out or not out.get("systemMessage"), (
            f"expected silent output while async agents active, got: {r.stdout!r}"
        )

    # last_summary는 그대로 저장돼야 한다 — emit만 silent.
    summary_file = (
        fake_home / ".claude" / "plugins" / "token-tracker"
        / "state" / session_id / "last_summary.json"
    )
    assert summary_file.is_file(), (
        "last_summary should still be persisted while async active"
    )


def test_stop_emits_when_all_async_agents_done(tmp_path):
    """모든 async agent가 completed면 정상 emit (active=0)."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"

    user_line = {
        "type": "user",
        "uuid": "u-1",
        "timestamp": "2026-04-23T10:00:00.000Z",
        "message": {"role": "user", "content": "go"},
    }
    assistant_with_async_agent = {
        "type": "assistant",
        "uuid": "a-1",
        "timestamp": "2026-04-23T10:00:01.000Z",
        "message": {
            "id": "msg_main_1",
            "role": "assistant",
            "model": "claude-opus-4-7",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_BG2",
                    "name": "Agent",
                    "input": {"subagent_type": "general-purpose"},
                }
            ],
            "usage": {
                "input_tokens": 50, "output_tokens": 10,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
        },
    }
    async_launched = {
        "type": "user",
        "uuid": "u-2",
        "timestamp": "2026-04-23T10:00:02.000Z",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_BG2", "content": "launched"}
            ],
        },
        "toolUseResult": {
            "agentType": "general-purpose",
            "agentId": "agent-bg-2",
            "status": "async_launched",
        },
    }
    completion_notification = {
        "type": "user",
        "uuid": "u-3",
        "timestamp": "2026-04-23T10:00:10.000Z",
        "message": {
            "role": "user",
            "content": (
                "<task-notification>"
                "<task-id>agent-bg-2</task-id>"
                "<status>completed</status>"
                "</task-notification>"
            ),
        },
    }

    with session_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(user_line) + "\n")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)
    env["TOKEN_TRACKER_VERBOSE"] = "0"

    payload = {
        "session_id": "all-done",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0

    with session_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(assistant_with_async_agent) + "\n")
        f.write(json.dumps(async_launched) + "\n")
        f.write(json.dumps(completion_notification) + "\n")

    payload["hook_event_name"] = "Stop"
    r = _run("on_stop.py", payload, env)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    msg = out.get("systemMessage", "")
    assert "toks" in msg, f"expected normal emit when all async done, got: {msg!r}"


def test_stop_emits_normally_when_no_async_dispatch(tmp_path):
    """async dispatch가 아예 없는 일반 sync turn은 그대로 매번 emit (현재 동작 유지)."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"
    session_path.write_bytes(FIXTURE.read_bytes())

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)
    env["TOKEN_TRACKER_VERBOSE"] = "0"

    payload = {
        "session_id": "no-async",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "Stop",
    }
    r = _run("on_stop.py", payload, env)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    msg = out.get("systemMessage", "")
    assert "toks" in msg, f"sync-only stop should emit normally, got: {msg!r}"


def test_stop_silent_when_async_active_even_with_verbose(tmp_path):
    """verbose 모드여도 background sub agent 진행 중에는 silent (옵션 D default).

    verbose는 "한 줄 요약 vs 상세 표"의 출력 형식 차이일 뿐, "언제 emit할지"는
    active=0 시점 한 번이어야 한다. 진행 중에 매 Stop마다 끼어들면 안 됨.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"

    user_line = {
        "type": "user",
        "uuid": "u-1",
        "timestamp": "2026-04-23T10:00:00.000Z",
        "message": {"role": "user", "content": "go"},
    }
    assistant_with_async_agent = {
        "type": "assistant",
        "uuid": "a-1",
        "timestamp": "2026-04-23T10:00:01.000Z",
        "message": {
            "id": "msg_main_1",
            "role": "assistant",
            "model": "claude-opus-4-7",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_BG3",
                    "name": "Agent",
                    "input": {"subagent_type": "general-purpose"},
                }
            ],
            "usage": {
                "input_tokens": 50, "output_tokens": 10,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
        },
    }
    async_launched = {
        "type": "user",
        "uuid": "u-2",
        "timestamp": "2026-04-23T10:00:02.000Z",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_BG3", "content": "launched"}
            ],
        },
        "toolUseResult": {
            "agentType": "general-purpose",
            "agentId": "agent-bg-3",
            "status": "async_launched",
        },
    }

    with session_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(user_line) + "\n")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)
    env["TOKEN_TRACKER_VERBOSE"] = "1"  # verbose여도 active>0이면 silent

    session_id = "verbose-bg-active"
    payload = {
        "session_id": session_id,
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0

    with session_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(assistant_with_async_agent) + "\n")
        f.write(json.dumps(async_launched) + "\n")

    payload["hook_event_name"] = "Stop"
    r = _run("on_stop.py", payload, env)
    assert r.returncode == 0
    # Silent: empty stdout or JSON without systemMessage
    if r.stdout.strip():
        out = json.loads(r.stdout)
        assert "systemMessage" not in out or not out.get("systemMessage"), (
            f"expected silent output even in verbose while async active, got: {r.stdout!r}"
        )

    # last_summary는 silent 케이스에서도 정상 누적 갱신돼야 한다.
    summary_file = (
        fake_home / ".claude" / "plugins" / "token-tracker"
        / "state" / session_id / "last_summary.json"
    )
    assert summary_file.is_file(), (
        "last_summary should still be persisted while async active in verbose mode"
    )


def test_stop_emits_with_verbose_table_when_async_done(tmp_path):
    """verbose=true + active=0이면 한 줄 요약 + 상세 표 둘 다 포함하여 emit."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"

    user_line = {
        "type": "user",
        "uuid": "u-1",
        "timestamp": "2026-04-23T10:00:00.000Z",
        "message": {"role": "user", "content": "go"},
    }
    assistant_with_async_agent = {
        "type": "assistant",
        "uuid": "a-1",
        "timestamp": "2026-04-23T10:00:01.000Z",
        "message": {
            "id": "msg_main_1",
            "role": "assistant",
            "model": "claude-opus-4-7",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_BGV",
                    "name": "Agent",
                    "input": {"subagent_type": "general-purpose"},
                }
            ],
            "usage": {
                "input_tokens": 50, "output_tokens": 10,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
        },
    }
    async_launched = {
        "type": "user",
        "uuid": "u-2",
        "timestamp": "2026-04-23T10:00:02.000Z",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_BGV", "content": "launched"}
            ],
        },
        "toolUseResult": {
            "agentType": "general-purpose",
            "agentId": "agent-bgv",
            "status": "async_launched",
        },
    }
    completion_notification = {
        "type": "user",
        "uuid": "u-3",
        "timestamp": "2026-04-23T10:00:10.000Z",
        "message": {
            "role": "user",
            "content": (
                "<task-notification>"
                "<task-id>agent-bgv</task-id>"
                "<status>completed</status>"
                "</task-notification>"
            ),
        },
    }

    with session_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(user_line) + "\n")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)
    env["TOKEN_TRACKER_VERBOSE"] = "1"  # verbose ON

    payload = {
        "session_id": "verbose-bg-done",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0

    with session_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(assistant_with_async_agent) + "\n")
        f.write(json.dumps(async_launched) + "\n")
        f.write(json.dumps(completion_notification) + "\n")

    payload["hook_event_name"] = "Stop"
    r = _run("on_stop.py", payload, env)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    msg = out.get("systemMessage", "")
    # 한 줄 요약 표시: "toks" 포함
    assert "toks" in msg, f"expected one-line summary, got: {msg!r}"
    # 상세 표 표시: detail_formatter가 만드는 표 헤더에 "Turn"과 "$"가 포함됨
    # (verbose 표는 줄바꿈 + 표 형태 → 한 줄보다 길고 줄바꿈 다수 포함)
    assert "\n" in msg, f"expected verbose table appended, got: {msg!r}"
    assert msg.count("\n") >= 2, (
        f"expected verbose detail table (multi-line), got: {msg!r}"
    )


def test_e2e_sub_with_short_alias_resolves_to_latest_family_rate(tmp_path):
    """v0.11.0 변경 회귀 가드.

    풀체인: 메인 jsonl Agent tool_use input.model="sonnet" (short alias) +
    completed tool_result. on_stop 이 fg_sub.model="sonnet" 으로 채우고,
    aggregator/formatter 가 alias 자동 탐지로 latest sonnet 단가 ($3) 청구.
    이전 (v0.10.0): parent opus rate ($5) fallback. 신: sonnet rate ($3).
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"

    user_line = {
        "type": "user",
        "uuid": "u-1",
        "timestamp": "2026-04-23T10:00:00.000Z",
        "message": {"role": "user", "content": "go"},
    }
    assistant_with_agent = {
        "type": "assistant",
        "uuid": "a-1",
        "timestamp": "2026-04-23T10:00:01.000Z",
        "message": {
            "id": "msg_main_1",
            "role": "assistant",
            "model": "claude-opus-4-7",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_ALIAS",
                    "name": "Agent",
                    "input": {
                        "subagent_type": "general-purpose",
                        "model": "sonnet",  # short alias — NOT in PRICING table
                    },
                }
            ],
            "usage": {
                "input_tokens": 0, "output_tokens": 0,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
        },
    }
    fg_tool_result = {
        "type": "user",
        "uuid": "u-2",
        "timestamp": "2026-04-23T10:00:02.000Z",
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_ALIAS", "content": "ok"}
            ],
        },
        "toolUseResult": {
            "agentType": "general-purpose",
            "status": "completed",
            "usage": {
                "input_tokens": 1_000_000, "output_tokens": 0,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
            "totalDurationMs": 5000,
        },
    }

    with session_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(user_line) + "\n")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)

    payload = {
        "session_id": "alias-fallback",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0

    with session_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(assistant_with_agent) + "\n")
        f.write(json.dumps(fg_tool_result) + "\n")

    payload["hook_event_name"] = "Stop"
    r = _run("on_stop.py", payload, env)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    msg = out["systemMessage"]

    # Cost extraction from one-liner: "$X.XXXX" near the start
    import re
    m = re.search(r"\$([0-9]+\.[0-9]+)", msg)
    assert m, f"expected $cost in output, got: {msg!r}"
    cost = float(m.group(1))
    # Expected: 1M sub input * latest sonnet rate ($3/MTok) = $3.0
    # alias 자동 탐지가 sonnet → claude-sonnet-{latest} 매핑 → 정확 단가 청구.
    # 이전 동작 (parent opus $5) 또는 silent $0 모두 회귀.
    assert 2.5 < cost < 3.5, (
        f"sub with short alias 'sonnet' should bill at latest sonnet rate "
        f"(~$3.0), got ${cost} in: {msg!r}"
    )


def test_e2e_active_count_remains_when_dispatch_in_earlier_turn(tmp_path):
    """v0.6.3 회귀 가드 (Bug A).

    시나리오: turn 1에서 async dispatch (active>0이라 silent) → turn 2 시작
    (UserPromptSubmit이 file 끝 offset 기록) → turn 2의 Stop hook 발화.

    이 시점 `_read_tail(transcript_path, offset)`은 turn 2 라인만 보므로 기존
    in-memory `extract_async_launches(entries)`는 launches 0개로 추출 →
    `count_active_async_agents`도 0 → silent guard 풀려 매번 끼어드는 회귀.

    Fix: file-based `count_active_async_agents_from_file`으로 jsonl 전체를 읽으면
    이전 turn의 dispatch도 보여 active=1 → silent 유지.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    session_stem = "sess-window"
    session_path = tmp_path / f"{session_stem}.jsonl"

    # Turn 1: dispatch + async_launched, completion 알림 없음 (sub 미완)
    turn1_lines = [
        {
            "type": "user",
            "uuid": "u-1",
            "timestamp": "2026-04-23T10:00:00.000Z",
            "message": {"role": "user", "content": "go"},
        },
        {
            "type": "assistant",
            "uuid": "a-1",
            "timestamp": "2026-04-23T10:00:01.000Z",
            "message": {
                "id": "msg_main_1",
                "role": "assistant",
                "model": "claude-opus-4-7",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_async_W",
                        "name": "Agent",
                        "input": {"subagent_type": "general-purpose"},
                    }
                ],
                "usage": {
                    "input_tokens": 50, "output_tokens": 10,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                },
            },
        },
        {
            "type": "user",
            "uuid": "u-2",
            "timestamp": "2026-04-23T10:00:02.000Z",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_async_W", "content": "launched"}
                ],
            },
            "toolUseResult": {
                "agentType": "general-purpose",
                "agentId": "agent-window-1",
                "status": "async_launched",
            },
        },
    ]

    with session_path.open("w", encoding="utf-8") as f:
        for ln in turn1_lines:
            f.write(json.dumps(ln) + "\n")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)
    env["TOKEN_TRACKER_VERBOSE"] = "0"

    # Turn 2 시작: UserPromptSubmit이 file 끝(=turn 1 끝)을 offset으로 기록
    payload = {
        "session_id": "window-bug",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0

    # Turn 2 응답: 메인 assistant 1개, dispatch 없음. sub은 여전히 미완.
    turn2_lines = [
        {
            "type": "user",
            "uuid": "u-t2-1",
            "timestamp": "2026-04-23T10:00:10.000Z",
            "message": {"role": "user", "content": "next"},
        },
        {
            "type": "assistant",
            "uuid": "a-t2-1",
            "timestamp": "2026-04-23T10:00:11.000Z",
            "message": {
                "id": "msg_main_2",
                "role": "assistant",
                "model": "claude-opus-4-7",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {
                    "input_tokens": 5, "output_tokens": 5,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                },
            },
        },
    ]
    with session_path.open("a", encoding="utf-8") as f:
        for ln in turn2_lines:
            f.write(json.dumps(ln) + "\n")

    # Turn 2 Stop. 기존(in-memory) 코드는 active=0으로 잘못 계산해 emit. fix 후엔
    # active=1 (turn 1 dispatch, 미완) → silent 유지여야 한다.
    payload["hook_event_name"] = "Stop"
    r = _run("on_stop.py", payload, env)
    assert r.returncode == 0
    # silent: stdout 비거나, JSON에 systemMessage 없음
    if r.stdout.strip():
        out = json.loads(r.stdout)
        assert "systemMessage" not in out or not out.get("systemMessage"), (
            f"expected silent output (active=1 from earlier turn dispatch), "
            f"got: {r.stdout!r}"
        )


def test_offset_not_advanced_by_stop_so_summary_accumulates_across_turns(tmp_path):
    """v0.6.4 회귀 가드 (offset 누적 정책).

    한 사용자 입력에 메인이 여러 응답 turn(예: dispatch → 결과 도착
    system_notification → 또 응답)을 만들면, on_stop은 매 발화마다 user_prompt
    시점부터의 entries 전체를 read해 last_summary를 누적해야 한다. on_stop이
    file_size로 offset을 갱신하면 두 번째 Stop의 last_summary가 두 번째 turn만
    가져 sub 데이터가 흩어지는 회귀가 생긴다.

    검증: 두 번 Stop을 호출해 두 번째 last_summary의 turns 길이 ≥ 2 +
    total_input_tokens가 첫 번째보다 큼.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"

    user_line = {
        "type": "user",
        "uuid": "u-1",
        "timestamp": "2026-04-23T10:00:00.000Z",
        "message": {"role": "user", "content": "go"},
    }
    assistant_turn_1 = {
        "type": "assistant",
        "uuid": "a-1",
        "timestamp": "2026-04-23T10:00:01.000Z",
        "message": {
            "id": "msg_main_1",
            "role": "assistant",
            "model": "claude-opus-4-7",
            "content": [{"type": "text", "text": "first response"}],
            "usage": {
                "input_tokens": 100, "output_tokens": 20,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
        },
    }
    system_notification = {
        "type": "user",
        "uuid": "u-sys-1",
        "timestamp": "2026-04-23T10:00:05.000Z",
        "message": {
            "role": "user",
            "content": "<system-reminder>some notification</system-reminder>",
        },
    }
    assistant_turn_2 = {
        "type": "assistant",
        "uuid": "a-2",
        "timestamp": "2026-04-23T10:00:06.000Z",
        "message": {
            "id": "msg_main_2",
            "role": "assistant",
            "model": "claude-opus-4-7",
            "content": [{"type": "text", "text": "second response"}],
            "usage": {
                "input_tokens": 200, "output_tokens": 30,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
        },
    }

    # UserPromptSubmit: only user line present, offset=end-of-user-line
    with session_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(user_line) + "\n")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)
    env["TOKEN_TRACKER_VERBOSE"] = "0"

    session_id = "accumulate"
    payload = {
        "session_id": session_id,
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0

    # First batch: only assistant turn 1 written → first Stop
    with session_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(assistant_turn_1) + "\n")

    payload["hook_event_name"] = "Stop"
    r1 = _run("on_stop.py", payload, env)
    assert r1.returncode == 0

    summary_file = (
        fake_home / ".claude" / "plugins" / "token-tracker"
        / "state" / session_id / "last_summary.json"
    )
    assert summary_file.is_file()
    snap1 = json.loads(summary_file.read_text(encoding="utf-8"))
    turns1 = snap1["summary"]["turns"]
    in_tokens_1 = snap1["summary"]["total_input_tokens"]
    assert len(turns1) == 1, f"first stop should see 1 turn, got {len(turns1)}"

    # Second batch: system_notification + assistant turn 2 appended → second Stop
    with session_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(system_notification) + "\n")
        f.write(json.dumps(assistant_turn_2) + "\n")

    r2 = _run("on_stop.py", payload, env)
    assert r2.returncode == 0

    snap2 = json.loads(summary_file.read_text(encoding="utf-8"))
    turns2 = snap2["summary"]["turns"]
    in_tokens_2 = snap2["summary"]["total_input_tokens"]

    # Second Stop should accumulate turn 1 + turn 2 (offset NOT advanced by first Stop)
    assert len(turns2) >= 2, (
        f"second stop should accumulate turns from user_prompt onward, "
        f"got {len(turns2)} turns: {turns2!r}"
    )
    assert in_tokens_2 > in_tokens_1, (
        f"second snapshot tokens ({in_tokens_2}) must exceed first ({in_tokens_1})"
    )


def test_offset_resets_on_new_user_prompt(tmp_path):
    """v0.6.4: 새 user_prompt가 들어오면 그 시점의 file_size가 새 offset.
    이후 Stop은 그 시점부터 읽으므로 이전 user_prompt의 turn은 last_summary에서 제외.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"

    user_line_1 = {
        "type": "user",
        "uuid": "u-1",
        "timestamp": "2026-04-23T10:00:00.000Z",
        "message": {"role": "user", "content": "first"},
    }
    assistant_1 = {
        "type": "assistant",
        "uuid": "a-1",
        "timestamp": "2026-04-23T10:00:01.000Z",
        "message": {
            "id": "msg_main_1",
            "role": "assistant",
            "model": "claude-opus-4-7",
            "content": [{"type": "text", "text": "first"}],
            "usage": {
                "input_tokens": 100, "output_tokens": 20,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
        },
    }
    user_line_2 = {
        "type": "user",
        "uuid": "u-2",
        "timestamp": "2026-04-23T10:00:10.000Z",
        "message": {"role": "user", "content": "second"},
    }
    assistant_2 = {
        "type": "assistant",
        "uuid": "a-2",
        "timestamp": "2026-04-23T10:00:11.000Z",
        "message": {
            "id": "msg_main_2",
            "role": "assistant",
            "model": "claude-opus-4-7",
            "content": [{"type": "text", "text": "second"}],
            "usage": {
                "input_tokens": 7, "output_tokens": 3,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
        },
    }

    # First user_prompt + first assistant + first Stop (full cycle for prompt 1)
    with session_path.open("w", encoding="utf-8") as f:
        f.write(json.dumps(user_line_1) + "\n")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)
    env["TOKEN_TRACKER_VERBOSE"] = "0"

    session_id = "reset-offset"
    payload = {
        "session_id": session_id,
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0

    with session_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(assistant_1) + "\n")

    payload["hook_event_name"] = "Stop"
    assert _run("on_stop.py", payload, env).returncode == 0

    # Second user_prompt arrives (offset reset to current file_size)
    with session_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(user_line_2) + "\n")

    payload["hook_event_name"] = "UserPromptSubmit"
    assert _run("on_user_prompt.py", payload, env).returncode == 0

    with session_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(assistant_2) + "\n")

    payload["hook_event_name"] = "Stop"
    assert _run("on_stop.py", payload, env).returncode == 0

    summary_file = (
        fake_home / ".claude" / "plugins" / "token-tracker"
        / "state" / session_id / "last_summary.json"
    )
    snap = json.loads(summary_file.read_text(encoding="utf-8"))
    turns = snap["summary"]["turns"]
    # Second user_prompt's offset only sees assistant_2 (input=7, output=3) — NOT assistant_1.
    assert len(turns) == 1, (
        f"new user_prompt offset should exclude prior turn; got {len(turns)} turns"
    )
    # input_tokens=7 from assistant_2; if offset wasn't reset, would also include assistant_1's 100.
    assert snap["summary"]["total_input_tokens"] == 7, (
        f"expected only assistant_2 input tokens (7), got {snap['summary']['total_input_tokens']}"
    )


def test_error_path_emits_diagnostic(tmp_path):
    """An exception inside the hook should still produce a systemMessage and exit 0."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)

    # transcript_path points to a directory — will raise OSError on getsize
    bogus = tmp_path / "not-a-file"
    bogus.mkdir()

    payload = {
        "session_id": "err",
        "transcript_path": str(bogus),
        "cwd": str(tmp_path),
        "hook_event_name": "Stop",
    }
    r = _run("on_stop.py", payload, env)
    # Hook must never propagate non-zero exit; should degrade gracefully.
    assert r.returncode == 0
    # When no state AND no turns are readable, the hook stays silent (no noisy
    # "$0.00 · 0 toks" on spurious Stop events). Any non-empty stdout must still
    # be valid JSON with continue=True.
    if r.stdout.strip():
        out = json.loads(r.stdout)
        assert out.get("continue") is True


def test_user_prompt_skips_offset_update_for_task_notification(tmp_path):
    """v0.6.5 회귀 가드: UserPromptSubmit이 task-notification(synthetic prompt)에
    대해서는 offset을 갱신하지 않아야 한다.

    Claude Code는 background agent 완료 알림을 `type=user, message.content=
    <task-notification>...</task-notification>` 라인으로 jsonl에 쓰면서
    UserPromptSubmit hook도 발화시킨다. 만약 hook이 매번 offset을 file_size로
    덮어쓰면, 다음 Stop의 `_read_tail(offset)` 윈도우는 이전 dispatch turn을
    놓쳐 sub들이 부모 turn에 attach 안 되고 silent drop된다 (사용자 보고:
    "sub 0개").
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"
    session_path.write_text("first user line\n", encoding="utf-8")
    initial_size = session_path.stat().st_size

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)

    session_id = "synthetic-prompt"
    # First: real user prompt records offset = current file_size
    real_payload = {
        "session_id": session_id,
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
        "prompt": "리뷰해",
    }
    assert _run("on_user_prompt.py", real_payload, env).returncode == 0

    # File grows (background activity)
    session_path.write_text("first\nsecond\nthird\n", encoding="utf-8")

    # Synthetic task-notification fires UserPromptSubmit again — must NOT update offset
    synthetic_payload = dict(real_payload)
    synthetic_payload["prompt"] = (
        "<task-notification>\n<task-id>abc123</task-id>\n"
        "<status>completed</status>\n</task-notification>"
    )
    assert _run("on_user_prompt.py", synthetic_payload, env).returncode == 0

    # offset.json should still be at initial_size (NOT bumped by synthetic prompt)
    offset_file = (
        fake_home / ".claude" / "plugins" / "token-tracker"
        / "state" / session_id / "offset.json"
    )
    assert offset_file.is_file()
    state = json.loads(offset_file.read_text(encoding="utf-8"))
    assert state["offset"] == initial_size, (
        f"synthetic task-notification must not bump offset; "
        f"expected {initial_size}, got {state['offset']}"
    )


def test_user_prompt_updates_offset_for_slash_command_prompt(tmp_path):
    """v0.6.5: synthetic prompt detection must NOT false-positive on slash commands.

    `<command-name>/foo</command-name>` wrappers, bash invocations, and
    command stdout are user-driven turns and should keep updating offset.
    Otherwise normal slash command usage would break the per-prompt
    accumulation semantics.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"
    session_path.write_text("seed\n", encoding="utf-8")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)

    session_id = "slash-cmd"
    payload = {
        "session_id": session_id,
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
        "prompt": "<command-name>/token-verbose</command-name>",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0

    expected = session_path.stat().st_size
    offset_file = (
        fake_home / ".claude" / "plugins" / "token-tracker"
        / "state" / session_id / "offset.json"
    )
    state = json.loads(offset_file.read_text(encoding="utf-8"))
    assert state["offset"] == expected, (
        f"slash command prompt must update offset; expected {expected}, "
        f"got {state['offset']}"
    )


def test_e2e_sub_visible_when_dispatch_and_result_in_distinct_turns_after_task_notification(tmp_path):
    """v0.6.5 회귀 가드 (T19): 실측 회귀 재현.

    시나리오 (사용자 보고와 동일):
      1. 사용자 입력 (UserPromptSubmit, real prompt)
      2. 메인이 7개 async Agent dispatch (assistant turn 1)
      3. async_launched user lines 7개
      4. 메인 응답 turn 2 (간단한 대기 메시지)
      5. background agent 1개 완료 → task-notification user line +
         UserPromptSubmit hook 재발화 (synthetic prompt)
      6. 메인 응답 turn 3
      7. ... (반복) ...
      N. 마지막 task-notification 후 메인의 종합 응답 turn
      N+1. Stop hook 발화

    버그(fix 전): 5의 hook 재발화가 매번 offset을 file_size로 덮어써,
    Stop의 `_read_tail`이 dispatch turn(1)을 놓쳐 sub 7개 모두 silent drop.

    Fix 후: synthetic prompt는 offset 갱신 skip → dispatch turn 보존 →
    last_summary.turns[].subagents에 모든 sub이 attach.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_stem = "sess-distinct-turns"
    session_path = tmp_path / f"{session_stem}.jsonl"
    sidechain_dir = tmp_path / session_stem / "subagents"
    sidechain_dir.mkdir(parents=True)

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)
    env["TOKEN_TRACKER_VERBOSE"] = "0"
    session_id = "distinct-turns"

    # ---- Step 1: real user prompt arrives ----
    user_line = {
        "type": "user",
        "uuid": "u-1",
        "timestamp": "2026-04-23T10:00:00.000Z",
        "message": {"role": "user", "content": "리뷰해"},
    }
    session_path.write_text(json.dumps(user_line) + "\n", encoding="utf-8")

    payload = {
        "session_id": session_id,
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
        "prompt": "리뷰해",
    }
    assert _run("on_user_prompt.py", payload, env).returncode == 0

    # ---- Step 2: dispatch turn (assistant with 3 Agent tool_uses, same message_id) ----
    # Claude Code splits the response into 1 line per content block but copies usage.
    # We simulate 3 dispatch lines (one per Agent block) sharing message_id.
    agent_ids = ["agent-rv-1", "agent-rv-2", "agent-rv-3"]
    tool_use_ids = ["toolu_RV1", "toolu_RV2", "toolu_RV3"]
    dispatch_lines = []
    for i, tu_id in enumerate(tool_use_ids):
        dispatch_lines.append({
            "type": "assistant",
            "uuid": f"a-disp-{i}",
            "timestamp": f"2026-04-23T10:00:0{i+1}.000Z",
            "message": {
                "id": "msg_dispatch",  # same message_id across blocks
                "role": "assistant",
                "model": "claude-opus-4-7",
                "content": [
                    {
                        "type": "tool_use",
                        "id": tu_id,
                        "name": "Agent",
                        "input": {"subagent_type": "general-purpose"},
                    }
                ],
                "usage": {
                    "input_tokens": 50, "output_tokens": 10,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                },
            },
        })

    # ---- Step 3: async_launched lines (one per dispatch) ----
    launched_lines = []
    for i, (tu_id, aid) in enumerate(zip(tool_use_ids, agent_ids)):
        launched_lines.append({
            "type": "user",
            "uuid": f"u-launch-{i}",
            "timestamp": f"2026-04-23T10:00:1{i}.000Z",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": tu_id, "content": "launched"}
                ],
            },
            "toolUseResult": {
                "agentType": "general-purpose",
                "agentId": aid,
                "status": "async_launched",
            },
        })

    # ---- Sidechain jsonls (one per agent, with assistant turn) ----
    sub_in, sub_out = 1000, 200
    for aid in agent_ids:
        sf = sidechain_dir / f"agent-{aid}.jsonl"
        sf.write_text(json.dumps({
            "type": "assistant",
            "timestamp": "2026-04-23T10:01:00.000Z",
            "message": {
                "id": f"msg_side_{aid}",
                "role": "assistant",
                "model": "claude-haiku-4-5",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {
                    "input_tokens": sub_in, "output_tokens": sub_out,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                },
            },
        }) + "\n", encoding="utf-8")

    # Append dispatch + launched lines to main jsonl
    with session_path.open("a", encoding="utf-8") as f:
        for ln in dispatch_lines + launched_lines:
            f.write(json.dumps(ln) + "\n")

    # ---- Step 4-N: task-notifications interleave with assistant responses.
    # Each task-notification fires UserPromptSubmit hook with synthetic prompt.
    for i, aid in enumerate(agent_ids):
        # Append a brief assistant filler turn between notifications
        filler = {
            "type": "assistant",
            "uuid": f"a-fill-{i}",
            "timestamp": f"2026-04-23T10:0{i+2}:00.000Z",
            "message": {
                "id": f"msg_fill_{i}",
                "role": "assistant",
                "model": "claude-opus-4-7",
                "content": [{"type": "text", "text": f"waiting {i}"}],
                "usage": {
                    "input_tokens": 5, "output_tokens": 5,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                },
            },
        }
        with session_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(filler) + "\n")

        # Now write task-notification user line
        notif_xml = (
            f"<task-notification>\n<task-id>{aid}</task-id>\n"
            f"<status>completed</status>\n</task-notification>"
        )
        notif_line = {
            "type": "user",
            "uuid": f"u-notif-{i}",
            "timestamp": f"2026-04-23T10:0{i+2}:30.000Z",
            "message": {"role": "user", "content": notif_xml},
        }
        with session_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(notif_line) + "\n")

        # Fire UserPromptSubmit with synthetic prompt — must NOT bump offset
        synthetic_payload = dict(payload)
        synthetic_payload["prompt"] = notif_xml
        assert _run("on_user_prompt.py", synthetic_payload, env).returncode == 0

    # ---- Step N+1: Final assistant summary turn after all 3 done ----
    final = {
        "type": "assistant",
        "uuid": "a-final",
        "timestamp": "2026-04-23T10:10:00.000Z",
        "message": {
            "id": "msg_final",
            "role": "assistant",
            "model": "claude-opus-4-7",
            "content": [{"type": "text", "text": "all 3 reviews done"}],
            "usage": {
                "input_tokens": 100, "output_tokens": 30,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
        },
    }
    with session_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(final) + "\n")

    # Stop hook fires
    payload["hook_event_name"] = "Stop"
    payload.pop("prompt", None)
    r = _run("on_stop.py", payload, env)
    assert r.returncode == 0, r.stderr

    # Verify last_summary captured all 3 sub launches
    summary_file = (
        fake_home / ".claude" / "plugins" / "token-tracker"
        / "state" / session_id / "last_summary.json"
    )
    assert summary_file.is_file()
    snap = json.loads(summary_file.read_text(encoding="utf-8"))
    turns = snap["summary"]["turns"]

    total_subs = sum(len(t["subagents"]) for t in turns)
    assert total_subs == len(agent_ids), (
        f"expected {len(agent_ids)} subs attached across turns, got {total_subs}; "
        f"turns: {[(t.get('message_id'), len(t['subagents'])) for t in turns]}"
    )

    # Cost check: input total must include sub tokens (1000+200) * 3 + main turn tokens
    # If subs were silently dropped, only main tokens would be counted.
    in_total = snap["summary"]["total_input_tokens"]
    expected_subs_input = sub_in * len(agent_ids)  # 3000
    assert in_total >= expected_subs_input, (
        f"sub input tokens not included; got {in_total}, expected ≥ {expected_subs_input}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase E (Plan Task 12): 신규 e2e 3건
# ─────────────────────────────────────────────────────────────────────────────


def test_e2e_pricing_with_real_transcript_shape():
    """진단에서 캡처한 1h-heavy 실제 shape으로 cost 정확 계산."""
    from lib.parser import parse_line
    from lib.aggregator import aggregate
    entry = {
        "type": "assistant",
        "message": {
            "id": "msg_real",
            "model": "claude-opus-4-7",
            "usage": {
                "input_tokens": 6,
                "output_tokens": 1058,
                "cache_read_input_tokens": 15433,
                "cache_creation_input_tokens": 42180,  # legacy
                "cache_creation": {
                    "ephemeral_1h_input_tokens": 42180,
                    "ephemeral_5m_input_tokens": 0,
                },
            },
            "content": [],
        },
        "timestamp": "2026-05-03T10:00:00Z",
    }
    t = parse_line(entry)
    s = aggregate([t], elapsed=1.0)
    expected = (
        6 * 5.0 / 1_000_000
        + 1058 * 25.0 / 1_000_000
        + 42180 * 10.0 / 1_000_000
        + 15433 * 0.50 / 1_000_000
    )
    assert abs(s.total_cost - expected) < 1e-6


def test_e2e_v2_summary_load_returns_none_then_next_save_creates_v3_at_same_path(tmp_path, monkeypatch):
    """v2 파일은 None 반환 → 다음 save가 같은 경로에 v3로 덮어쓰기 (자연 마이그레이션)."""
    from lib import summary_store, paths
    from lib.aggregator import Summary
    from lib.parser import TurnUsage
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    sid = "test_natural_migration"
    sdir = tmp_path / sid
    sdir.mkdir()
    target = sdir / "last_summary.json"
    target.write_text(json.dumps({
        "schema_version": 2,
        "session_id": sid,
        "saved_at": 0,
        "summary": {"total_cost": 0.5, "total_input_tokens": 100,
                    "total_output_tokens": 50, "cache_hit_rate": 0.0,
                    "total_elapsed": 1.0, "turns": []},
    }))
    assert summary_store.load_last_summary(sid) is None

    new_summary = Summary(
        total_cost=0.1, total_input_tokens=10, total_output_tokens=5,
        cache_hit_rate=0.0, total_elapsed=0.5,
        turns=[TurnUsage(model="claude-opus-4-7", input_tokens=1, output_tokens=1,
                         cache_creation_5m_tokens=0, cache_creation_1h_tokens=0,
                         cache_read_tokens=0, message_id="m_new")],
    )
    summary_store.save_last_summary(sid, new_summary)

    assert target.exists()
    with target.open() as f:
        data = json.load(f)
    assert data["schema_version"] == 3


def test_e2e_detail_renders_after_v3_save(tmp_path, monkeypatch):
    """v3 save → load → detail formatter rendering OK (CRITICAL #1, #2 회귀 가드)."""
    from lib import summary_store, paths
    from lib.aggregator import Summary
    from lib.parser import TurnUsage
    from lib.detail_formatter import format_detail
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    sid = "test_detail_e2e"
    summary = Summary(
        total_cost=0.1, total_input_tokens=550, total_output_tokens=20,
        cache_hit_rate=0.5, total_elapsed=1.0,
        turns=[TurnUsage(
            model="claude-opus-4-7", input_tokens=10, output_tokens=20,
            cache_creation_5m_tokens=300, cache_creation_1h_tokens=200,
            cache_read_tokens=50, message_id="m_e2e",
        )],
    )
    summary_store.save_last_summary(sid, summary)
    loaded = summary_store.load_last_summary(sid)
    assert loaded is not None
    text = format_detail(loaded, language="ko")
    assert "500" in text  # 5m 300 + 1h 200


def test_on_stop_appends_history_when_prompt_id_present(tmp_path, monkeypatch):
    """A complete flow: on_user_prompt → on_stop → history.jsonl has 1 row."""
    from lib import paths
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "log_dir", lambda: tmp_path / "log")

    # Transcript starts empty — on_user_prompt records offset=0.
    # Then we append the assistant turn (simulating Claude's response).
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("", encoding="utf-8")  # empty at prompt time

    # Run on_user_prompt first (assigns prompt_id, offset=0)
    import io, importlib
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "s_e2e", "transcript_path": str(transcript),
        "prompt": "hi",
    })))
    import hooks.on_user_prompt as up
    importlib.reload(up)
    up.main()

    # Now append the assistant turn (Claude responded after the prompt)
    with transcript.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "type": "assistant",
            "timestamp": "2026-05-03T14:23:00Z",
            "message": {
                "id": "msg_1",
                "model": "claude-opus-4-7",
                "content": [{"type": "text", "text": "hi"}],
                "usage": {"input_tokens": 10, "output_tokens": 5,
                          "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            },
        }) + "\n")

    # Run on_stop
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "s_e2e", "transcript_path": str(transcript),
    })))
    import hooks.on_stop as os_hook
    importlib.reload(os_hook)
    os_hook.main()

    # Verify
    from lib.history_store import load_session_history
    out = load_session_history("s_e2e")
    assert len(out) == 1
    assert out[0]["user_prompt"]["text"] == "hi"
    assert out[0]["models_used"] == ["claude-opus-4-7"]


def test_on_stop_skips_history_when_no_prompt_id(tmp_path, monkeypatch):
    """If prompt_id is missing in state (e.g., hook never ran), skip history."""
    from lib import paths
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "log_dir", lambda: tmp_path / "log")
    from lib.state import save_state
    save_state("s_skip", {"offset": 0, "started_at": 1.0})  # no prompt_id

    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        json.dumps({
            "type": "assistant", "timestamp": "2026-05-03T14:23:00Z",
            "message": {"id": "m", "model": "claude-opus-4-7",
                        "content": [{"type": "text", "text": "x"}],
                        "usage": {"input_tokens": 1, "output_tokens": 1,
                                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}},
        }) + "\n",
        encoding="utf-8",
    )

    import io, importlib
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "s_skip", "transcript_path": str(transcript),
    })))
    import hooks.on_stop as os_hook
    importlib.reload(os_hook)
    os_hook.main()

    from lib.history_store import load_session_history
    assert load_session_history("s_skip") == []  # skipped


def test_on_stop_history_failure_does_not_break_last_summary(tmp_path, monkeypatch):
    """history_store throwing must not break last_summary save."""
    from lib import paths
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(paths, "log_dir", lambda: tmp_path / "log")
    from lib.state import save_state
    save_state("s_fail", {"offset": 0, "started_at": 1.0,
                           "prompt_id": "p_x", "prompt_text": "x"})

    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        json.dumps({
            "type": "assistant", "timestamp": "2026-05-03T14:23:00Z",
            "message": {"id": "m", "model": "claude-opus-4-7",
                        "content": [{"type": "text", "text": "x"}],
                        "usage": {"input_tokens": 1, "output_tokens": 1,
                                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}},
        }) + "\n",
        encoding="utf-8",
    )

    # Sabotage history_store
    import lib.history_store as hs
    monkeypatch.setattr(hs, "append_or_update_history",
                        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    import io, importlib
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "s_fail", "transcript_path": str(transcript),
    })))
    import hooks.on_stop as os_hook
    importlib.reload(os_hook)
    rc = os_hook.main()
    assert rc == 0  # hook still returns OK

    # last_summary still saved
    from lib.summary_store import load_last_summary
    summ = load_last_summary("s_fail")
    assert summ is not None
