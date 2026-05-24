from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest


def _run_hook(monkeypatch, tmp_path, payload: dict, transcript_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps(payload))
    )
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text("", encoding="utf-8")

    from importlib import reload
    import hooks.on_user_prompt as h
    reload(h)
    return h.main()


def test_real_prompt_assigns_prompt_id_and_saves_state(tmp_path, monkeypatch):
    transcript = tmp_path / "transcript.jsonl"
    rc = _run_hook(monkeypatch, tmp_path, {
        "session_id": "s1", "transcript_path": str(transcript),
        "prompt": "hello world",
    }, transcript)
    assert rc == 0

    from lib.state import load_state
    st = load_state("s1")
    assert st is not None
    assert "prompt_id" in st and st["prompt_id"].startswith("p_")
    assert st.get("prompt_text") == "hello world"
    assert "started_at" in st


def test_synthetic_prompt_does_not_assign_prompt_id(tmp_path, monkeypatch):
    transcript = tmp_path / "transcript.jsonl"
    # First, real prompt
    _run_hook(monkeypatch, tmp_path, {
        "session_id": "s2", "transcript_path": str(transcript),
        "prompt": "real input",
    }, transcript)
    from lib.state import load_state
    real = load_state("s2")
    real_pid = real["prompt_id"]

    # Now, synthetic — should NOT change prompt_id
    _run_hook(monkeypatch, tmp_path, {
        "session_id": "s2", "transcript_path": str(transcript),
        "prompt": "<system-reminder>\n...stuff...",
    }, transcript)
    after = load_state("s2")
    assert after["prompt_id"] == real_pid
