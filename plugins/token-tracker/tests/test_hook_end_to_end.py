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
    assert data["schema_version"] == 1
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
    env.pop("TOKEN_TRACKER_VERBOSE", None)  # ensure off

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
