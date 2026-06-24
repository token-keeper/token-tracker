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
# cache-necromancer 의 auto-wake 는 Stop hook 의 exit-2 + stderr ping 으로 Claude
# 를 재기동한다. Claude Code 는 이 ping 을 transcript 에 **isMeta 없는** 일반
# `type:user` 엔트리로 기록하며, content 는 Claude Code 가 생성한 래퍼다(실측):
#   <task-notification><summary>Stop hook feedback</summary></task-notification>
#   <system-reminder>
#   Stop hook blocking error from command "Stop": ... [cn:keepalive HH:MM, N/M] ...
#   </system-reminder>
# offset 윈도우의 가장 최근 user 엔트리가 이 wake ping 이면 이 Stop 은 실제
# 사용자 입력이 아니라 wake turn 에서 fire 된 것 → emit 억제 대상이다.


def _user(content):
    return {"type": "user", "message": {"role": "user", "content": content}}


def _assistant():
    return {"type": "assistant", "message": {"role": "assistant", "content": "ok"}}


def _cn_wake(ping="[cn:keepalive 21:26, 1/5] reply with exactly 'ok @21:26 (1/5)'."):
    """Claude Code 가 cn auto-wake 를 기록하는 실제 user 엔트리 형식.

    isMeta 키 없음, content 는 task-notification + system-reminder 래퍼이며
    `Stop hook blocking error from command "Stop":` 안에 keepalive ping 이 들어간다.
    """
    content = (
        "<task-notification>\n<summary>Stop hook feedback</summary>\n"
        "</task-notification>\n<system-reminder>\n"
        'Stop hook blocking error from command "Stop": '
        "[cn:warn] deprecated v0.2.x config 옵션 감지\n"
        f"{ping} No tools, no analysis. Use minimal output tokens.\n"
        "</system-reminder>"
    )
    return _user(content)


def test_latest_user_is_cn_wake_returns_true():
    from hooks.on_stop import _is_cn_wake_stop

    entries = [
        _user("real prompt"),
        _assistant(),
        _cn_wake(),
    ]
    assert _is_cn_wake_stop(entries) is True


def test_latest_user_is_real_prompt_returns_false():
    from hooks.on_stop import _is_cn_wake_stop

    entries = [_assistant(), _user("please do the thing")]
    assert _is_cn_wake_stop(entries) is False


def test_cn_warn_only_without_keepalive_returns_false():
    """`[cn:warn]` deprecation stderr 만 있고 keepalive ping 이 없으면 wake 아님."""
    from hooks.on_stop import _is_cn_wake_stop

    content = (
        "<task-notification>\n<summary>Stop hook feedback</summary>\n"
        "</task-notification>\n<system-reminder>\n"
        'Stop hook blocking error from command "Stop": [cn:warn] deprecated config\n'
        "</system-reminder>"
    )
    entries = [_assistant(), _user(content)]
    assert _is_cn_wake_stop(entries) is False


def test_prompt_with_keepalive_text_but_no_stop_error_returns_false():
    """사용자가 프롬프트에 `[cn:keepalive` 텍스트를 직접 넣어도, Claude Code 의
    Stop-hook-error 래퍼가 없으면 억제하지 않는다(false positive 방지)."""
    from hooks.on_stop import _is_cn_wake_stop

    entries = [_assistant(), _user("이거 봐: [cn:keepalive 가 뭐야?")]
    assert _is_cn_wake_stop(entries) is False


def test_list_content_does_not_crash_and_detects():
    from hooks.on_stop import _is_cn_wake_stop

    entries = [
        _assistant(),
        _user(
            [
                {
                    "type": "text",
                    "text": 'Stop hook blocking error from command "Stop": '
                    "[cn:keepalive 1:00, 1/3]",
                }
            ]
        ),
    ]
    assert _is_cn_wake_stop(entries) is True


def test_no_user_entry_returns_false():
    from hooks.on_stop import _is_cn_wake_stop

    assert _is_cn_wake_stop([_assistant()]) is False
    assert _is_cn_wake_stop([]) is False


# --- main() integration: cn wake Stop 은 wake turn 만 표시 -------------------


def _assistant_turn(
    *, cache_read=304_000, output=12, ts="2026-06-23T12:00:00.000Z", mid="msg_wake"
):
    """wake turn 의 assistant 응답("ok ...") 엔트리 — usage 포함."""
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "role": "assistant",
            "model": "claude-opus-4-8",
            "id": mid,
            "usage": {
                "input_tokens": 5,
                "output_tokens": output,
                "cache_read_input_tokens": cache_read,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 0,
                    "ephemeral_1h_input_tokens": 0,
                },
            },
            "content": [{"type": "text", "text": "ok @21:26 (1/5)"}],
        },
    }


def _run_stop(payload: dict, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "hooks" / "on_stop.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )


def test_cn_wake_emits_wake_turn_only(tmp_path, monkeypatch):
    """cn wake Stop 은 침묵하지 않고 wake turn '만' 집계해 표시한다.
    직전 실제 turn(fixture)을 재합산하지 않으며(turns==1), last_summary·history
    도 오염시키지 않는다(wake 는 사용자 turn 이 아님)."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"
    # fixture(실제 turn들) 뒤에 [cn wake ping] + [wake assistant 응답] 을 덧붙인다.
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    ping = json.dumps(_cn_wake(), ensure_ascii=False)
    wake_assistant = json.dumps(_assistant_turn(), ensure_ascii=False)
    session_path.write_text(
        "\n".join(lines + [ping, wake_assistant]) + "\n", encoding="utf-8"
    )

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
    out = json.loads(r.stdout)
    msg = out["systemMessage"]
    assert "🪦 캐시 연장 turn" in msg, msg
    # wake turn 만 — fixture 의 turn 들을 재합산하지 않았음을 turn 수로 검증.
    assert "· 1 turns" in msg, msg

    # wake 는 last_summary·history 를 오염시키지 않는다.
    monkeypatch.setenv("HOME", str(fake_home))
    from lib.summary_store import load_last_summary
    from lib.history_store import load_session_history

    assert load_last_summary("cn-wake-1") is None
    assert load_session_history("cn-wake-1") == []


def test_cn_wake_without_assistant_yet_stays_silent(tmp_path):
    """ping 만 있고 wake assistant 응답이 아직 flush 안 됐으면 침묵(1회성 손실)."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    ping = json.dumps(_cn_wake(), ensure_ascii=False)
    session_path.write_text("\n".join(lines + [ping]) + "\n", encoding="utf-8")

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)
    payload = {
        "session_id": "cn-wake-2",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "Stop",
    }
    r = _run_stop(payload, env)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", f"expected silence, got: {r.stdout!r}"


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
