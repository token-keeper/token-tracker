from __future__ import annotations

import importlib.util
import json
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


def test_history_script_starts_server_and_prints_http_url(tmp_path, monkeypatch, capsys):
    _seed_history(monkeypatch, tmp_path)
    run_history = _import_history_main()
    with patch("lib.http_server.ensure_server_running") as ensure, \
         patch("subprocess.run") as opened:
        rc = run_history(["history.py", "s_skill"])
    assert rc == 0
    ensure.assert_called_once()
    opened.assert_called_once()
    out = capsys.readouterr().out
    assert "opened:" in out
    assert "http://127.0.0.1:8765/s_skill" in out


def test_history_script_does_not_write_html_file(tmp_path, monkeypatch):
    """동적 렌더 도입 후 디스크 HTML 파일 더 이상 생성 안 됨."""
    _seed_history(monkeypatch, tmp_path)
    run_history = _import_history_main()
    with patch("lib.http_server.ensure_server_running"), \
         patch("subprocess.run"):
        run_history(["history.py", "s_skill"])
    from lib import paths
    candidates = list((paths.state_dir() / "s_skill").glob("history-*.html"))
    assert candidates == []


def test_history_script_prints_url_even_when_open_fails(tmp_path, monkeypatch, capsys):
    """`open` 실행 실패해도 URL 은 stdout 에 출력."""
    _seed_history(monkeypatch, tmp_path)
    run_history = _import_history_main()
    with patch("lib.http_server.ensure_server_running"), \
         patch("subprocess.run", side_effect=FileNotFoundError("no open")):
        run_history(["history.py", "s_skill"])
    out = capsys.readouterr().out
    assert "opened:" in out


def test_history_script_handles_server_startup_failure(tmp_path, monkeypatch, capsys):
    """ensure_server_running 이 RuntimeError 던지면 traceback stderr 출력 + 0 이외 return."""
    _seed_history(monkeypatch, tmp_path)
    run_history = _import_history_main()
    with patch("lib.http_server.ensure_server_running",
               side_effect=RuntimeError("daemon failed to start")):
        rc = run_history(["history.py", "s_skill"])
    err = capsys.readouterr().err
    assert "daemon failed" in err or "RuntimeError" in err
