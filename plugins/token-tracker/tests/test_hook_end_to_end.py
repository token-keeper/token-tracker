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
    """Stop hook must persist the aggregated Summary so /token-detail can read it."""
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
    assert data["schema_version"] == 2
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
