import os
from pathlib import Path

from lib import paths


def test_plugin_root_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    assert paths.plugin_root() == tmp_path


def test_plugin_root_fallback_to_file(monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    root = paths.plugin_root()
    assert (root / "lib" / "paths.py").exists()


def test_state_dir_creates_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    d = paths.state_dir()
    assert d.exists()
    assert d.is_dir()
    assert d == tmp_path / ".claude" / "plugins" / "token-tracker" / "state"


def test_log_dir_creates_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    d = paths.log_dir()
    assert d.exists()
    assert d == tmp_path / ".claude" / "plugins" / "token-tracker" / "log"
