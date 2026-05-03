from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _import_history_main():
    """Import skills/token-history/scripts/history.py by file path
    (디렉터리명에 `-` 포함되어 일반 import 불가)."""
    plugin_root = Path(__file__).resolve().parents[1]  # plugins/token-tracker/
    spec = importlib.util.spec_from_file_location(
        "history_skill_main",
        plugin_root / "skills" / "token-history" / "scripts" / "history.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main


def _seed_history(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.history_store import append_or_update_history
    append_or_update_history(
        session_id="s_skill", prompt_id="p_1", user_prompt_text="hello",
        started_at=1.0, ended_at=2.0,
        summary_dict={"total_cost": 0.01, "total_input_tokens": 1,
                       "total_output_tokens": 1, "cache_hit_rate": 0.0,
                       "total_elapsed": 1.0, "turns": []},
        models_used=["claude-opus-4-7"],
        has_subagent_other_model=False,
        transcript_entries=[],
    )


def test_history_script_writes_html_and_prints_url(tmp_path, monkeypatch, capsys):
    _seed_history(monkeypatch, tmp_path)
    run_history = _import_history_main()
    with patch("subprocess.run") as mocked:
        run_history(["history.py", "s_skill"])
        assert mocked.called

    out = capsys.readouterr().out
    assert "opened:" in out

    from lib import paths
    candidates = list((paths.state_dir() / "s_skill").glob("history-*.html"))
    assert len(candidates) == 1
    assert "p_1" in candidates[0].read_text(encoding="utf-8")


def test_history_script_prints_url_even_when_open_fails(tmp_path, monkeypatch, capsys):
    _seed_history(monkeypatch, tmp_path)
    run_history = _import_history_main()
    with patch("subprocess.run", side_effect=FileNotFoundError("no open")):
        run_history(["history.py", "s_skill"])
    out = capsys.readouterr().out
    assert "opened:" in out  # URL still printed
