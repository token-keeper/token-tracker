from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch


def _import_stop_main():
    plugin_root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "stop_skill_main",
        plugin_root / "skills" / "token-history-stop" / "scripts" / "stop.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main


def test_stop_skill_prints_stopped_when_killed(capsys):
    run = _import_stop_main()
    with patch("lib.http_server.stop", return_value=2):
        rc = run(["stop.py"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "stopped" in out.lower()


def test_stop_skill_prints_no_server_when_zero(capsys):
    run = _import_stop_main()
    with patch("lib.http_server.stop", return_value=0):
        rc = run(["stop.py"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "no server" in out.lower()


def test_stop_skill_handles_exception_gracefully(capsys):
    """lsof 가 시스템에 없거나 권한 부족 등 예외 시 stderr 출력 + non-zero return."""
    run = _import_stop_main()
    with patch("lib.http_server.stop", side_effect=FileNotFoundError("no lsof")):
        rc = run(["stop.py"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "no lsof" in err or "FileNotFoundError" in err
