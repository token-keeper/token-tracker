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


def test_missing_state_still_succeeds(tmp_path):
    """Stop with no prior state should still emit a valid systemMessage."""
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
    assert "0 toks" not in msg, f"Expected non-zero tokens, got: {msg!r}"
    # Cache hit rate in fixture is 2000 / (10 + 100 + 2000) = ~95%
    assert "cache 95%" in msg, f"Expected cache 95%, got: {msg!r}"


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
    # Output is either valid summary JSON (0 turns) or diagnostic JSON; must parse.
    out = json.loads(r.stdout)
    assert "systemMessage" in out
    assert out.get("continue") is True
