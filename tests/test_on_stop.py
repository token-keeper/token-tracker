from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "sample_session.jsonl"

sys.path.insert(0, str(REPO))


# --- _is_cn_wake_stop unit tests --------------------------------------------
#
# cache-necromancer 의 auto-wake 는 Stop hook 의 stderr ping 으로 Claude 를
# 재기동하며, Claude Code 는 이 wake 를 transcript 에 `type:user, isMeta:true`,
# content 에 `[cn:keepalive ...]` 를 포함한 "Stop hook feedback" 엔트리로 남긴다.
# offset 윈도우의 가장 최근 user 엔트리가 이 wake ping 이면 이 Stop 은 실제
# 사용자 입력이 아니라 wake turn 에서 fire 된 것 → emit 억제 대상이다.


def _user(content, *, is_meta=False):
    e = {"type": "user", "message": {"role": "user", "content": content}}
    if is_meta:
        e["isMeta"] = True
    return e


def _assistant():
    return {"type": "assistant", "message": {"role": "assistant", "content": "ok"}}


def test_latest_user_is_keepalive_meta_returns_true():
    from hooks.on_stop import _is_cn_wake_stop

    entries = [
        _user("real prompt"),
        _assistant(),
        _user(
            "Stop hook feedback:\n[refresh.py]: [cn:keepalive @12:00, 3/5]",
            is_meta=True,
        ),
    ]
    assert _is_cn_wake_stop(entries) is True


def test_latest_user_is_real_prompt_returns_false():
    from hooks.on_stop import _is_cn_wake_stop

    entries = [_assistant(), _user("please do the thing")]
    assert _is_cn_wake_stop(entries) is False


def test_meta_but_not_keepalive_returns_false():
    from hooks.on_stop import _is_cn_wake_stop

    entries = [
        _assistant(),
        _user(
            "Stop hook feedback:\n<system-reminder>some reminder</system-reminder>",
            is_meta=True,
        ),
    ]
    assert _is_cn_wake_stop(entries) is False


def test_list_content_does_not_crash_and_detects():
    from hooks.on_stop import _is_cn_wake_stop

    entries = [
        _assistant(),
        _user(
            [{"type": "text", "text": "Stop hook feedback:\n[cn:keepalive @1:00, 1/3]"}],
            is_meta=True,
        ),
    ]
    assert _is_cn_wake_stop(entries) is True


def test_no_user_entry_returns_false():
    from hooks.on_stop import _is_cn_wake_stop

    assert _is_cn_wake_stop([_assistant()]) is False
    assert _is_cn_wake_stop([]) is False


# --- main() integration: cn wake Stop stays silent --------------------------


def _run_stop(payload: dict, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "hooks" / "on_stop.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )


def test_cn_wake_stop_emits_nothing(tmp_path, monkeypatch):
    """가장 최근 user 엔트리가 cn keepalive wake 면 on_stop 은 침묵(미출력)하고
    last_summary·history 도 건드리지 않는다(early return → 오염 방지)."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"
    # 실제 turn(fixture) 뒤에 cn wake meta 엔트리를 덧붙인다.
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    wake = json.dumps(
        _user(
            "Stop hook feedback:\n[refresh.py]: [cn:keepalive @12:00, 3/5]",
            is_meta=True,
        ),
        ensure_ascii=False,
    )
    session_path.write_text("\n".join(lines + [wake]) + "\n", encoding="utf-8")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)
    payload = {
        "session_id": "cn-wake-1",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "Stop",
    }
    r = _run_stop(payload, env)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", f"expected silence, got: {r.stdout!r}"

    # 같은 fake HOME 으로 store 를 조회해 side-effect 미발생을 검증한다.
    monkeypatch.setenv("HOME", str(fake_home))
    from lib.summary_store import load_last_summary
    from lib.history_store import load_session_history

    assert load_last_summary("cn-wake-1") is None
    assert load_session_history("cn-wake-1") == []


def test_real_stop_still_emits(tmp_path):
    """대조군: 최근 user 엔트리가 진짜 turn 이면 정상적으로 systemMessage emit."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"
    session_path.write_bytes(FIXTURE.read_bytes())

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)
    payload = {
        "session_id": "real-stop-1",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "Stop",
    }
    r = _run_stop(payload, env)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert "systemMessage" in out
