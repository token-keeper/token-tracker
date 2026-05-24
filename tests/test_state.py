import json
from pathlib import Path

from lib import state


def test_save_and_load_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    state.save_state("sess-1", {"offset": 1024, "started_at": 1700.5})
    assert state.load_state("sess-1") == {"offset": 1024, "started_at": 1700.5}


def test_save_creates_session_subdirectory(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    state.save_state("sess-sub", {"offset": 0, "started_at": 0.0})
    from lib import paths
    expected = paths.state_dir() / "sess-sub" / "offset.json"
    assert expected.is_file()


def test_load_missing_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert state.load_state("never-saved") is None


def test_load_corrupted_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib import paths
    session_dir = paths.state_dir() / "corrupt"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "offset.json").write_text("not json {{{", encoding="utf-8")
    assert state.load_state("corrupt") is None


def test_save_is_atomic_no_temp_leftover(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    state.save_state("sess-atomic", {"offset": 0, "started_at": 0.0})
    from lib import paths
    session_dir = paths.state_dir() / "sess-atomic"
    tempfiles = [f for f in session_dir.iterdir() if f.name.startswith(".tmp")]
    assert tempfiles == []
