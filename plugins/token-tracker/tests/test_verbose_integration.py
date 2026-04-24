"""Integration tests: verbose config + env override + toggle→stop sequence.

These tests use a **tmp plugin root** (with config.json initially set to
verbose=true) to verify env whitelist fallback and the toggle→stop handoff.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REAL_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REAL_ROOT / "tests" / "fixtures" / "sample_session.jsonl"


@pytest.fixture
def tmp_plugin_root(tmp_path: Path) -> Path:
    """Tmp plugin root that mirrors the real layout but with an isolated config.json."""
    root = tmp_path / "plugin"
    root.mkdir()
    # Symlink hooks + lib so the hook subprocess finds its dependencies.
    (root / "hooks").symlink_to(REAL_ROOT / "hooks")
    (root / "lib").symlink_to(REAL_ROOT / "lib")

    # Copy the skill script to its canonical location (not a symlink, we'll write its config).
    script_dir = root / "skills" / "token-verbose" / "scripts"
    script_dir.mkdir(parents=True)
    shutil.copy2(
        REAL_ROOT / "skills" / "token-verbose" / "scripts" / "verbose_toggle.py",
        script_dir / "verbose_toggle.py",
    )
    # Seed config with verbose=true so env override behavior is observable.
    (root / "config.json").write_text(
        json.dumps({"language": "ko", "verbose": True}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return root


def _run_stop(tmp_path: Path, plugin_root: Path, env_overrides: dict) -> str:
    """Run UserPromptSubmit + Stop and return the systemMessage."""
    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    session_path = tmp_path / "session.jsonl"
    session_path.write_text("", encoding="utf-8")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    for k, v in env_overrides.items():
        if v is None:
            env.pop(k, None)
        else:
            env[k] = v

    session_id = "sess-integration"
    payload = {
        "session_id": session_id,
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    subprocess.run(
        [sys.executable, str(plugin_root / "hooks" / "on_user_prompt.py")],
        input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=5,
    )
    session_path.write_bytes(FIXTURE.read_bytes())
    payload["hook_event_name"] = "Stop"
    r = subprocess.run(
        [sys.executable, str(plugin_root / "hooks" / "on_stop.py")],
        input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=5,
    )
    return json.loads(r.stdout)["systemMessage"]


def _run_toggle(plugin_root: Path, arg: str) -> subprocess.CompletedProcess:
    script = plugin_root / "skills" / "token-verbose" / "scripts" / "verbose_toggle.py"
    env = {
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "PATH": "",
        "TOKEN_TRACKER_VERBOSE_ARG": arg,
    }
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True, text=True, env=env, timeout=5,
    )


# --- F-1: env whitelist fallback -------------------------------------------


def test_empty_env_value_falls_back_to_config_true(tmp_plugin_root, tmp_path):
    """TOKEN_TRACKER_VERBOSE="" should NOT override config=true (empty is not a valid signal)."""
    msg = _run_stop(tmp_path, tmp_plugin_root, {"TOKEN_TRACKER_VERBOSE": ""})
    assert "━" in msg, "empty env must fall back to config (verbose:true → table present)"


def test_invalid_env_value_falls_back_to_config_true(tmp_plugin_root, tmp_path):
    """TOKEN_TRACKER_VERBOSE=enabled / 2 / garbage should fall back to config."""
    for bogus in ("enabled", "2", "garbage"):
        msg = _run_stop(tmp_path, tmp_plugin_root, {"TOKEN_TRACKER_VERBOSE": bogus})
        assert "━" in msg, f"env={bogus!r} must fall back to config=true"


def test_explicit_off_env_overrides_config_true(tmp_plugin_root, tmp_path):
    """Sanity: whitelisted off values (0/false/off) still override config=true."""
    for off in ("0", "false", "off", "no"):
        msg = _run_stop(tmp_path, tmp_plugin_root, {"TOKEN_TRACKER_VERBOSE": off})
        assert "━" not in msg, f"env={off!r} must force off even when config=true"


# --- F-2: toggle → stop continuous flow ------------------------------------


def test_toggle_off_then_stop_emits_single_line(tmp_plugin_root, tmp_path):
    """`/token-verbose off` must persist; subsequent Stop hook omits the detail table."""
    r = _run_toggle(tmp_plugin_root, "off")
    assert r.returncode == 0
    assert "on → off" in r.stdout

    # No env override — rely solely on config.json written by toggle.
    msg = _run_stop(tmp_path, tmp_plugin_root, {"TOKEN_TRACKER_VERBOSE": None})
    assert "toks" in msg
    assert "━" not in msg, "toggle off must be reflected in the next Stop hook"


def test_toggle_on_then_stop_emits_detail_table(tmp_plugin_root, tmp_path):
    """Starting from verbose=false, `/token-verbose on` then Stop shows detail."""
    # Start from false.
    (tmp_plugin_root / "config.json").write_text(
        json.dumps({"language": "ko", "verbose": False}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    r = _run_toggle(tmp_plugin_root, "on")
    assert r.returncode == 0
    assert "off → on" in r.stdout

    msg = _run_stop(tmp_path, tmp_plugin_root, {"TOKEN_TRACKER_VERBOSE": None})
    assert "━" in msg, "toggle on must surface the detail table on next Stop"


# --- MINOR: SKILL.md manifest sanity ---------------------------------------


def _read_skill_frontmatter(skill_md: Path) -> dict:
    text = skill_md.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{skill_md} missing frontmatter fence"
    end = text.find("\n---\n", 4)
    assert end > 0, f"{skill_md} frontmatter not closed"
    body = text[4:end]
    result = {}
    for line in body.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            result[k.strip()] = v.strip()
    return result


def test_token_verbose_skill_manifest():
    fm = _read_skill_frontmatter(REAL_ROOT / "skills" / "token-verbose" / "SKILL.md")
    assert fm["name"] == "token-verbose"
    assert fm.get("disable-model-invocation") == "true", (
        "token-verbose must be disable-model-invocation:true so LLM cannot auto-call it"
    )
    assert len(fm.get("description", "")) > 10


def test_token_detail_skill_manifest():
    fm = _read_skill_frontmatter(REAL_ROOT / "skills" / "token-detail" / "SKILL.md")
    assert fm["name"] == "token-detail"
    assert fm.get("disable-model-invocation") == "true"
    assert len(fm.get("description", "")) > 10
