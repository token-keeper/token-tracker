"""token-tracker HTTP daemon process 헬퍼.

skill 호출 시 idempotent 시작 (살아있으면 재사용, 없으면 띄움).
명시 종료는 lsof + os.kill.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from http.client import HTTPConnection, HTTPException, HTTPResponse
from pathlib import Path


_HOST = "127.0.0.1"
_PORT = 8765
_STARTUP_TIMEOUT = 3.0  # 총 대기 시간 (초)
_STARTUP_POLL_INTERVAL = 0.2  # polling 주기


def _healthcheck(host: str, port: int, timeout: float = 0.5) -> HTTPResponse:
    """daemon 의 /healthz 호출. ConnectionRefusedError 등은 caller 가 catch."""
    conn = HTTPConnection(host, port, timeout=timeout)
    conn.request("GET", "/healthz")
    return conn.getresponse()


def is_alive(host: str = _HOST, port: int = _PORT) -> bool:
    """포트에 우리 daemon 이 살아있는지 (X-Token-Tracker 헤더로 판별)."""
    try:
        resp = _healthcheck(host, port)
    except (OSError, HTTPException):
        return False
    if resp.status != 200:
        return False
    return resp.getheader("X-Token-Tracker") == "1"


def _plugin_root() -> Path:
    # lib/http_server.py -> lib -> plugin root
    return Path(__file__).resolve().parent.parent


def ensure_server_running() -> None:
    """살아있으면 no-op, 아니면 daemon 시작 + healthcheck 폴링.
    timeout 시 RuntimeError raise (caller 의 try/except 가 처리)."""
    if is_alive():
        return
    plugin_root = _plugin_root()
    # subprocess.Popen 으로 detach 시작
    log_path = plugin_root / "log" / "server_daemon.stderr.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fp = open(log_path, "ab")
    subprocess.Popen(
        [sys.executable, "-m", "lib.server_daemon"],
        cwd=str(plugin_root),
        stdout=subprocess.DEVNULL,
        stderr=log_fp,
        start_new_session=True,
    )
    log_fp.close()  # subprocess 가 fd 상속 후 부모는 close
    # polling
    deadline = time.time() + _STARTUP_TIMEOUT
    while time.time() < deadline:
        if is_alive():
            return
        time.sleep(_STARTUP_POLL_INTERVAL)
    raise RuntimeError(f"token-tracker daemon failed to start within {_STARTUP_TIMEOUT}s (port {_PORT})")


def stop() -> int:
    """8765 점유한 PID 들에 SIGTERM, 살아있으면 SIGKILL.
    종료한 PID 수 반환 (없으면 0)."""
    try:
        out = subprocess.check_output(
            ["lsof", "-t", "-i", f":{_PORT}"],
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        # lsof returncode 1 = 매칭 없음
        return 0
    pids = [int(p) for p in out.decode().split() if p.strip().isdigit()]
    if not pids:
        return 0
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    # 짧게 대기 후 각 PID 별로 생존 체크 → 살아있으면 SIGKILL
    time.sleep(0.5)
    for pid in pids:
        try:
            os.kill(pid, 0)  # 0 = signal 없음, 생존 확인용
        except ProcessLookupError:
            continue  # 이미 죽음
        # 살아있음 → SIGKILL
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    return len(pids)
