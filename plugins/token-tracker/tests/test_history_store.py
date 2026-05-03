from __future__ import annotations

import json
from pathlib import Path

import pytest


def _build_summary_dict():
    return {
        "total_cost": 0.01,
        "total_input_tokens": 100,
        "total_output_tokens": 200,
        "cache_hit_rate": 0.5,
        "total_elapsed": 2.0,
        "turns": [],
    }


def test_append_creates_file_and_writes_one_line(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.history_store import (
        SCHEMA_VERSION,
        append_or_update_history,
        load_session_history,
    )

    sess = "sess_a"
    append_or_update_history(
        session_id=sess,
        prompt_id="p_001",
        user_prompt_text="hello",
        started_at=1.0,
        ended_at=2.0,
        summary_dict=_build_summary_dict(),
        models_used=["claude-opus-4-7"],
        has_subagent_other_model=False,
        transcript_entries=[],
    )

    path = tmp_path / ".claude/plugins/token-tracker/state" / sess / "history.jsonl"
    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["schema_version"] == SCHEMA_VERSION
    assert entry["prompt_id"] == "p_001"
    assert entry["user_prompt"] == {"text": "hello", "ts": 1.0}
    assert entry["models_used"] == ["claude-opus-4-7"]


def test_load_session_history_returns_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.history_store import append_or_update_history, load_session_history

    append_or_update_history(
        session_id="s", prompt_id="p_1", user_prompt_text="a",
        started_at=1.0, ended_at=2.0, summary_dict=_build_summary_dict(),
        models_used=[], has_subagent_other_model=False, transcript_entries=[],
    )
    out = load_session_history("s")
    assert len(out) == 1 and out[0]["prompt_id"] == "p_1"


def test_load_session_history_empty_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.history_store import load_session_history
    assert load_session_history("nonexistent") == []


def test_load_skips_corrupted_lines(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.history_store import load_session_history
    from lib import paths
    p = paths.state_dir() / "s" / "history.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        '{"schema_version":1,"prompt_id":"p_1","session_id":"s","started_at":1,"ended_at":2,"user_prompt":{"text":"","ts":1},"summary":{},"models_used":[],"has_subagent_other_model":false,"transcript_entries":[]}\n'
        '{not json}\n'
        '{"schema_version":1,"prompt_id":"p_2","session_id":"s","started_at":3,"ended_at":4,"user_prompt":{"text":"","ts":3},"summary":{},"models_used":[],"has_subagent_other_model":false,"transcript_entries":[]}\n',
        encoding="utf-8",
    )
    out = load_session_history("s")
    assert len(out) == 2
    assert [e["prompt_id"] for e in out] == ["p_1", "p_2"]
    err = capsys.readouterr().err
    assert "corrupted" in err


def test_load_skips_unsupported_schema(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.history_store import load_session_history
    from lib import paths
    p = paths.state_dir() / "s" / "history.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        '{"schema_version":99,"prompt_id":"p_x"}\n', encoding="utf-8"
    )
    out = load_session_history("s")
    assert out == []
    assert "unsupported schema_version" in capsys.readouterr().err
