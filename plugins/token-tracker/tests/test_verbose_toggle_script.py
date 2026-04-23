"""End-to-end tests for the /token-verbose slash skill script.

These tests run the script via subprocess against a **temporary plugin root**
so the real config.json is never mutated.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REAL_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_RELATIVE = Path("skills") / "token-verbose" / "scripts" / "verbose_toggle.py"


@pytest.fixture
def tmp_plugin_root(tmp_path: Path) -> Path:
    """Create a tmp plugin root with config.json + symlinked lib/ + copied script."""
    root = tmp_path / "plugin"
    root.mkdir()

    # Symlink lib so i18n_loader / paths resolve against the real resources.
    (root / "lib").symlink_to(REAL_ROOT / "lib")

    # Copy the script to its canonical location under the tmp root.
    script_dir = root / "skills" / "token-verbose" / "scripts"
    script_dir.mkdir(parents=True)
    shutil.copy2(REAL_ROOT / SCRIPT_RELATIVE, script_dir / "verbose_toggle.py")

    return root


def _write_config(root: Path, cfg: dict) -> None:
    (root / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_config(root: Path) -> dict:
    return json.loads((root / "config.json").read_text(encoding="utf-8"))


def _run(root: Path, arg: str | None) -> subprocess.CompletedProcess:
    script = root / SCRIPT_RELATIVE
    argv = [sys.executable, str(script)]
    if arg is not None:
        argv.append(arg)
    env = {"CLAUDE_PLUGIN_ROOT": str(root), "PATH": ""}
    return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=5)


def test_status_query_shows_off_when_config_false(tmp_plugin_root: Path):
    _write_config(tmp_plugin_root, {"language": "ko", "verbose": False})
    r = _run(tmp_plugin_root, "")
    assert r.returncode == 0
    assert "off" in r.stdout
    # config unchanged
    assert _read_config(tmp_plugin_root)["verbose"] is False


def test_status_query_shows_on_when_config_true(tmp_plugin_root: Path):
    _write_config(tmp_plugin_root, {"language": "ko", "verbose": True})
    r = _run(tmp_plugin_root, "")
    assert r.returncode == 0
    assert "on" in r.stdout
    assert _read_config(tmp_plugin_root)["verbose"] is True


def test_on_flips_false_to_true(tmp_plugin_root: Path):
    _write_config(tmp_plugin_root, {"language": "ko", "verbose": False})
    r = _run(tmp_plugin_root, "on")
    assert r.returncode == 0
    assert "off" in r.stdout and "on" in r.stdout  # "off → on"
    assert _read_config(tmp_plugin_root)["verbose"] is True


def test_off_flips_true_to_false(tmp_plugin_root: Path):
    _write_config(tmp_plugin_root, {"language": "ko", "verbose": True})
    r = _run(tmp_plugin_root, "off")
    assert r.returncode == 0
    assert "on" in r.stdout and "off" in r.stdout  # "on → off"
    assert _read_config(tmp_plugin_root)["verbose"] is False


def test_on_when_already_on_reports_no_change(tmp_plugin_root: Path):
    _write_config(tmp_plugin_root, {"language": "ko", "verbose": True})
    r = _run(tmp_plugin_root, "on")
    assert r.returncode == 0
    assert "변경 없음" in r.stdout or "no change" in r.stdout
    assert _read_config(tmp_plugin_root)["verbose"] is True


def test_unknown_arg_prints_usage_and_does_not_mutate(tmp_plugin_root: Path):
    _write_config(tmp_plugin_root, {"language": "ko", "verbose": False})
    r = _run(tmp_plugin_root, "enable")
    assert r.returncode == 0
    assert "사용법" in r.stdout or "usage" in r.stdout.lower()
    assert _read_config(tmp_plugin_root)["verbose"] is False


def test_preserves_other_config_keys(tmp_plugin_root: Path):
    _write_config(tmp_plugin_root, {"language": "ko", "verbose": False, "extra": 42})
    r = _run(tmp_plugin_root, "on")
    assert r.returncode == 0
    cfg = _read_config(tmp_plugin_root)
    assert cfg["verbose"] is True
    assert cfg["language"] == "ko"
    assert cfg["extra"] == 42


def test_english_language_output(tmp_plugin_root: Path):
    _write_config(tmp_plugin_root, {"language": "en", "verbose": False})
    r = _run(tmp_plugin_root, "")
    assert r.returncode == 0
    assert "token-tracker verbose" in r.stdout
    assert "off" in r.stdout


def test_corrupted_config_falls_back_to_defaults(tmp_plugin_root: Path):
    (tmp_plugin_root / "config.json").write_text("{not json", encoding="utf-8")
    # Should not crash; default verbose=False, default lang=en
    r = _run(tmp_plugin_root, "")
    assert r.returncode == 0
    assert "off" in r.stdout


def test_missing_config_creates_on_first_write(tmp_plugin_root: Path):
    # No config.json exists; turning "on" must create it.
    r = _run(tmp_plugin_root, "on")
    assert r.returncode == 0
    assert (tmp_plugin_root / "config.json").exists()
    assert _read_config(tmp_plugin_root)["verbose"] is True


def test_aliases_accepted_1_true_yes_for_on(tmp_plugin_root: Path):
    for alias in ("1", "true", "yes", "ON", "True"):
        _write_config(tmp_plugin_root, {"language": "en", "verbose": False})
        r = _run(tmp_plugin_root, alias)
        assert r.returncode == 0, f"alias={alias!r} failed"
        assert _read_config(tmp_plugin_root)["verbose"] is True, f"alias={alias!r}"


def test_aliases_accepted_0_false_no_for_off(tmp_plugin_root: Path):
    for alias in ("0", "false", "no", "OFF", "False"):
        _write_config(tmp_plugin_root, {"language": "en", "verbose": True})
        r = _run(tmp_plugin_root, alias)
        assert r.returncode == 0, f"alias={alias!r} failed"
        assert _read_config(tmp_plugin_root)["verbose"] is False, f"alias={alias!r}"
