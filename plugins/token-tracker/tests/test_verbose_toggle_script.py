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
SCRIPT_RELATIVE = Path("scripts") / "verbose_toggle.py"


@pytest.fixture
def tmp_plugin_root(tmp_path: Path) -> Path:
    """Create a tmp plugin root with config.json + symlinked lib/ + copied script."""
    root = tmp_path / "plugin"
    root.mkdir()

    # Symlink lib so i18n_loader / paths resolve against the real resources.
    (root / "lib").symlink_to(REAL_ROOT / "lib")

    # Copy the script to its canonical location under the tmp root.
    script_dir = root / "scripts"
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
    env = {"CLAUDE_PLUGIN_ROOT": str(root), "PATH": ""}
    if arg is not None:
        env["TOKEN_TRACKER_VERBOSE_ARG"] = arg
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


def test_status_keyword_shows_off_when_config_false(tmp_plugin_root: Path):
    """The literal 'status' keyword behaves the same as an empty argument."""
    _write_config(tmp_plugin_root, {"language": "ko", "verbose": False})
    r = _run(tmp_plugin_root, "status")
    assert r.returncode == 0
    assert "off" in r.stdout
    assert _read_config(tmp_plugin_root)["verbose"] is False


def test_status_keyword_shows_on_when_config_true(tmp_plugin_root: Path):
    _write_config(tmp_plugin_root, {"language": "ko", "verbose": True})
    r = _run(tmp_plugin_root, "status")
    assert r.returncode == 0
    assert "on" in r.stdout
    assert _read_config(tmp_plugin_root)["verbose"] is True


def test_status_keyword_case_insensitive(tmp_plugin_root: Path):
    _write_config(tmp_plugin_root, {"language": "ko", "verbose": False})
    r = _run(tmp_plugin_root, "STATUS")
    assert r.returncode == 0
    assert "off" in r.stdout
    assert _read_config(tmp_plugin_root)["verbose"] is False


def test_usage_message_lists_status_option(tmp_plugin_root: Path):
    """An unknown arg must print usage text that documents on|off|status."""
    _write_config(tmp_plugin_root, {"language": "en", "verbose": False})
    r = _run(tmp_plugin_root, "enable")
    assert r.returncode == 0
    assert "on|off|status" in r.stdout


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


def test_arg_with_shell_metacharacters_is_literal(tmp_plugin_root: Path):
    """$ARGUMENTS-origin values must not be re-evaluated by the script."""
    # Evil-looking payloads — script must see them as literal strings.
    for payload in ("$(rm -rf /)", "`whoami`", "on; echo pwned", '"; cat /etc/passwd; "'):
        # Reset config before each payload so a regression in one iteration
        # doesn't leak into the next.
        _write_config(tmp_plugin_root, {"language": "en", "verbose": False})
        r = _run(tmp_plugin_root, payload)
        assert r.returncode == 0, f"payload={payload!r} crashed: {r.stderr}"
        # Any non-canonical token falls to the "usage" branch, not mutation.
        assert _read_config(tmp_plugin_root)["verbose"] is False, \
            f"payload={payload!r} mutated config"


def test_missing_env_var_behaves_like_status_query(tmp_plugin_root: Path):
    """When TOKEN_TRACKER_VERBOSE_ARG is not set at all (not even empty),
    the script should fall through to the status-query branch — same as
    passing an empty string."""
    _write_config(tmp_plugin_root, {"language": "en", "verbose": False})
    # _run(root, None) deliberately does NOT insert TOKEN_TRACKER_VERBOSE_ARG
    # into the subprocess env, exercising the default branch of
    # os.environ.get("TOKEN_TRACKER_VERBOSE_ARG", "").
    r = _run(tmp_plugin_root, None)
    assert r.returncode == 0, f"unexpected crash: {r.stderr}"
    assert "off" in r.stdout  # status query shows current state
    # config untouched
    assert _read_config(tmp_plugin_root)["verbose"] is False


def test_os_replace_failure_returns_exit_1(tmp_plugin_root: Path):
    """Isolate the os.replace failure path: writable parent dir, tmp write
    succeeds, but the replace target is a directory (POSIX refuses to
    overwrite a directory with a regular file). This is the one failure mode
    NOT covered by the readonly-dir test.
    """
    # Sabotage config.json by making it a directory, not a file.
    target = tmp_plugin_root / "config.json"
    if target.exists():
        target.unlink()
    target.mkdir()
    try:
        r = _run(tmp_plugin_root, "on")
        assert r.returncode == 1, f"expected exit 1, got {r.returncode}: {r.stdout!r} / {r.stderr!r}"
        combined = r.stdout + r.stderr
        # verbose_error_io message must appear (en locale falls back from defaults).
        # "directory" appears in the IsADirectoryError strerror on both macOS and Linux.
        assert ("directory" in combined.lower()
                or "permission" in combined.lower()
                or "failed to write" in combined.lower()), \
            f"expected verbose_error_io message, got {combined!r}"
        # n3: ensure {reason} actually interpolates str(e), not a blank.
        assert "[Errno" in combined, \
            f"expected [Errno N] from str(OSError) to be interpolated, got {combined!r}"
    finally:
        target.rmdir()


def test_readonly_dir_returns_exit_1(tmp_plugin_root: Path):
    """Read-only plugin root dir: tmp write itself fails → exit 1."""
    _write_config(tmp_plugin_root, {"language": "en", "verbose": False})
    tmp_plugin_root.chmod(0o500)
    try:
        r = _run(tmp_plugin_root, "on")
        assert r.returncode == 1, f"expected exit 1, got {r.returncode}"
        combined = r.stdout + r.stderr
        # n3: {reason} must contain str(OSError) (e.g., "[Errno 13]").
        assert "[Errno" in combined, \
            f"expected [Errno N] from str(OSError) to be interpolated, got {combined!r}"
    finally:
        tmp_plugin_root.chmod(0o700)


def test_ko_language_uses_korean_message(tmp_plugin_root: Path):
    """Verify ko locale picks the Korean i18n message for the IO error.

    We need config.json readable (so load_config picks up language=ko) AND
    an IO failure on write. Keep config.json as a normal file, but create
    config.json.tmp as a directory so tmp.write_text(...) inside
    update_config fails with IsADirectoryError (subclass of OSError).
    """
    _write_config(tmp_plugin_root, {"language": "ko", "verbose": False})
    tmp_target = tmp_plugin_root / "config.json.tmp"
    tmp_target.mkdir()
    try:
        r = _run(tmp_plugin_root, "on")
        assert r.returncode == 1
        combined = r.stdout + r.stderr
        assert "권한" in combined or "쓰기에 실패" in combined, \
            f"expected Korean verbose_error_io message, got {combined!r}"
        # n3: {reason} must contain str(OSError).
        assert "[Errno" in combined, \
            f"expected [Errno N] from str(OSError), got {combined!r}"
    finally:
        tmp_target.rmdir()
