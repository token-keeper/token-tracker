import json
from pathlib import Path

from lib import paths, summary_store
from lib.aggregator import Summary
from lib.parser import TurnUsage


def _sample_summary() -> Summary:
    turns = [
        TurnUsage(
            model="claude-opus-4-7",
            input_tokens=10, output_tokens=20,
            cache_creation_tokens=0, cache_read_tokens=5,
            tools_used=[{"name": "Read", "count": 2}],
            timestamp_iso="2026-04-23T10:00:00Z",
            message_id="m1",
            index=0,
        )
    ]
    return Summary(
        total_cost=0.001, total_input_tokens=15,
        total_output_tokens=20, cache_hit_rate=0.33,
        total_elapsed=1.5, turns=turns,
    )


def test_save_load_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    summary_store.save_last_summary("sess-1", _sample_summary())
    loaded = summary_store.load_last_summary("sess-1")
    assert loaded is not None
    assert loaded.total_cost == 0.001
    assert len(loaded.turns) == 1
    assert loaded.turns[0].tools_used == [{"name": "Read", "count": 2}]


def test_save_creates_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    summary_store.save_last_summary("sess-2", _sample_summary())
    assert (paths.state_dir() / "sess-2" / "last_summary.json").is_file()


def test_load_missing_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert summary_store.load_last_summary("nonexistent") is None


def test_load_corrupted_json_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    d = paths.state_dir() / "sess-3"
    d.mkdir(parents=True, exist_ok=True)
    (d / "last_summary.json").write_text("{not valid", encoding="utf-8")
    assert summary_store.load_last_summary("sess-3") is None


def test_load_unsupported_schema_version_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    d = paths.state_dir() / "sess-4"
    d.mkdir(parents=True, exist_ok=True)
    (d / "last_summary.json").write_text(
        json.dumps({"schema_version": 99, "summary": {}}),
        encoding="utf-8",
    )
    assert summary_store.load_last_summary("sess-4") is None


def test_load_missing_summary_field_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    d = paths.state_dir() / "sess-5"
    d.mkdir(parents=True, exist_ok=True)
    (d / "last_summary.json").write_text(
        json.dumps({"schema_version": 1}),
        encoding="utf-8",
    )
    assert summary_store.load_last_summary("sess-5") is None


def test_save_is_atomic_no_temp_leftover(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    summary_store.save_last_summary("sess-6", _sample_summary())
    d = paths.state_dir() / "sess-6"
    temps = [p for p in d.iterdir() if p.name.startswith(".tmp-")]
    assert temps == []
