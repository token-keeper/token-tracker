from __future__ import annotations

import socket
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# is_alive
# ---------------------------------------------------------------------------


def test_is_alive_returns_false_when_no_listener():
    """8765 가 비어있으면 False."""
    from lib.http_server import is_alive
    # OS 가 임의 비어있는 포트 가정 — 일반적으로 65535 가 안 쓰임
    assert is_alive(host="127.0.0.1", port=65535) is False


def test_is_alive_returns_true_when_token_tracker_responds():
    from lib.http_server import is_alive
    fake_response = MagicMock()
    fake_response.status = 200
    fake_response.getheader.return_value = "1"  # X-Token-Tracker: 1
    with patch("lib.http_server._healthcheck", return_value=fake_response):
        assert is_alive(host="127.0.0.1", port=8765) is True


def test_is_alive_returns_false_when_other_process():
    """포트엔 응답하지만 X-Token-Tracker 헤더 없음 → False (다른 프로세스)."""
    from lib.http_server import is_alive
    fake_response = MagicMock()
    fake_response.status = 200
    fake_response.getheader.return_value = None
    with patch("lib.http_server._healthcheck", return_value=fake_response):
        assert is_alive(host="127.0.0.1", port=8765) is False


def test_is_alive_returns_false_on_connection_error():
    from lib.http_server import is_alive
    with patch("lib.http_server._healthcheck", side_effect=ConnectionRefusedError):
        assert is_alive(host="127.0.0.1", port=8765) is False


# ---------------------------------------------------------------------------
# ensure_server_running
# ---------------------------------------------------------------------------


def test_ensure_server_running_skips_when_already_alive():
    from lib.http_server import ensure_server_running
    with patch("lib.http_server.is_alive", return_value=True), \
         patch("subprocess.Popen") as popen:
        ensure_server_running()
        popen.assert_not_called()


def test_ensure_server_running_starts_when_dead_and_polls_until_alive():
    from lib.http_server import ensure_server_running
    # 처음엔 dead, Popen 후 polling 두 번 만에 alive
    alive_states = iter([False, False, True])
    with patch("lib.http_server.is_alive", side_effect=lambda *a, **k: next(alive_states)), \
         patch("subprocess.Popen") as popen, \
         patch("time.sleep"):
        ensure_server_running()
        popen.assert_called_once()
        # Popen 인자 확인: detach 옵션
        kwargs = popen.call_args.kwargs
        assert kwargs.get("start_new_session") is True


def test_ensure_server_running_raises_runtime_error_on_startup_timeout():
    from lib.http_server import ensure_server_running
    # 영원히 dead
    with patch("lib.http_server.is_alive", return_value=False), \
         patch("subprocess.Popen"), \
         patch("time.sleep"):
        with pytest.raises(RuntimeError, match="failed to start"):
            ensure_server_running()


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


def test_stop_returns_zero_when_no_listener():
    """포트 점유한 PID 없음 → 0 반환 (idempotent)."""
    from lib.http_server import stop
    with patch("subprocess.check_output", return_value=b""):
        n = stop()
        assert n == 0


def test_stop_kills_pids_returned_by_lsof():
    from lib.http_server import stop
    with patch("subprocess.check_output", return_value=b"123\n456\n"), \
         patch("lib.http_server.is_alive", return_value=False), \
         patch("os.kill") as kill, \
         patch("time.sleep"):
        n = stop()
        assert n == 2
        kill_calls = [c.args[0] for c in kill.call_args_list]
        assert 123 in kill_calls and 456 in kill_calls


def test_stop_handles_lsof_returning_no_pids_via_calledprocesserror():
    """lsof 가 매칭 없을 때 returncode 1 + 빈 stdout 으로 CalledProcessError 던짐."""
    from lib.http_server import stop
    err = subprocess.CalledProcessError(returncode=1, cmd=["lsof"], output=b"")
    with patch("subprocess.check_output", side_effect=err):
        assert stop() == 0
