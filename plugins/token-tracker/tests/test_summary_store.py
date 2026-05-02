import json
from pathlib import Path

from lib import paths, summary_store
from lib.aggregator import Summary
from lib.parser import SubagentUsage, TurnUsage


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


def test_save_writes_schema_version_2(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    summary_store.save_last_summary("sess-v2", _sample_summary())
    target = paths.state_dir() / "sess-v2" / "last_summary.json"
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2


def test_load_v1_normalizes_subagents_to_empty_list(monkeypatch, tmp_path):
    """A schema_version=1 file (no `subagents` field on turns) loads cleanly,
    and every TurnUsage gets a default empty subagents list."""
    monkeypatch.setenv("HOME", str(tmp_path))
    d = paths.state_dir() / "sess-v1"
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "session_id": "sess-v1",
        "saved_at": 1745301234.5,
        "summary": {
            "total_cost": 0.001,
            "total_input_tokens": 15,
            "total_output_tokens": 20,
            "cache_hit_rate": 0.33,
            "total_elapsed": 1.5,
            "turns": [{
                "model": "claude-opus-4-7",
                "input_tokens": 10, "output_tokens": 20,
                "cache_creation_tokens": 0, "cache_read_tokens": 5,
                "tools_used": [{"name": "Read", "count": 2}],
                "timestamp_iso": "2026-04-23T10:00:00Z",
                "message_id": "m1", "index": 0,
            }],
        },
    }
    (d / "last_summary.json").write_text(json.dumps(payload), encoding="utf-8")

    loaded = summary_store.load_last_summary("sess-v1")
    assert loaded is not None
    assert len(loaded.turns) == 1
    assert loaded.turns[0].subagents == []
    assert loaded.turns[0].agent_tool_use_ids == []


def _sub(tool_use_id: str = "toolu_a", **overrides) -> SubagentUsage:
    base = dict(
        agent_type="general-purpose",
        tool_use_id=tool_use_id,
        input_tokens=100,
        output_tokens=50,
        cache_creation_tokens=10,
        cache_read_tokens=20,
        total_duration_ms=1234,
    )
    base.update(overrides)
    return SubagentUsage(**base)


def test_load_v2_round_trips_subagents(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    sub = _sub()
    turns = [
        TurnUsage(
            model="claude-opus-4-7",
            input_tokens=10, output_tokens=20,
            cache_creation_tokens=0, cache_read_tokens=5,
            tools_used=[{"name": "Agent", "count": 1}],
            timestamp_iso="2026-04-23T10:00:00Z",
            message_id="m1", index=0,
            agent_tool_use_ids=["toolu_a"],
            subagents=[sub],
        )
    ]
    summary = Summary(
        total_cost=0.002, total_input_tokens=145,
        total_output_tokens=70, cache_hit_rate=0.18,
        total_elapsed=2.0, turns=turns,
    )
    summary_store.save_last_summary("sess-v2-rt", summary)
    loaded = summary_store.load_last_summary("sess-v2-rt")
    assert loaded is not None
    assert len(loaded.turns) == 1
    subs = loaded.turns[0].subagents
    assert len(subs) == 1
    assert isinstance(subs[0], SubagentUsage)
    assert subs[0].agent_type == "general-purpose"
    assert subs[0].tool_use_id == "toolu_a"
    assert subs[0].input_tokens == 100
    assert subs[0].output_tokens == 50
    assert subs[0].cache_creation_tokens == 10
    assert subs[0].cache_read_tokens == 20
    assert subs[0].total_duration_ms == 1234


def test_load_v2_round_trips_multiple_subagents_per_turn(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    sub_a = _sub(tool_use_id="toolu_a", agent_type="agent-a", input_tokens=1)
    sub_b = _sub(tool_use_id="toolu_b", agent_type="agent-b", input_tokens=2)
    turns = [
        TurnUsage(
            model="claude-opus-4-7",
            input_tokens=10, output_tokens=20,
            cache_creation_tokens=0, cache_read_tokens=5,
            tools_used=[{"name": "Agent", "count": 2}],
            timestamp_iso="2026-04-23T10:00:00Z",
            message_id="m1", index=0,
            agent_tool_use_ids=["toolu_a", "toolu_b"],
            subagents=[sub_a, sub_b],
        )
    ]
    summary = Summary(
        total_cost=0.003, total_input_tokens=200,
        total_output_tokens=120, cache_hit_rate=0.2,
        total_elapsed=3.0, turns=turns,
    )
    summary_store.save_last_summary("sess-v2-multi", summary)
    loaded = summary_store.load_last_summary("sess-v2-multi")
    assert loaded is not None
    subs = loaded.turns[0].subagents
    assert len(subs) == 2
    assert {s.agent_type for s in subs} == {"agent-a", "agent-b"}
    assert {s.input_tokens for s in subs} == {1, 2}
    for s in subs:
        assert isinstance(s, SubagentUsage)
