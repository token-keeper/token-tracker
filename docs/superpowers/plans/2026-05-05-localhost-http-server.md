# localhost HTTP server — implementation plan (v0.9.0)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/token-history` 의 file:// 한계를 해소하기 위해 머신당 1개의 idempotent HTTP daemon 을 도입한다 (포트 8765, 127.0.0.1 only). 동적 렌더링으로 HTML 파일 디스크 저장 폐지. 신규 `/token-history-stop` skill 추가.

**Architecture:** `lib/server_daemon.py` 가 `http.server.ThreadingHTTPServer` 기반 정적 라우터로 동작 (GET `/healthz`, `/`, `/{session_id}`). `lib/http_server.py` 가 process 헬퍼 (is_alive / ensure_server_running / stop). skill 두 개가 각각 진입점.

**Tech Stack:** Python stdlib (`http.server`, `socket`, `subprocess`, `signal`, `os`) · pytest

**Spec:** `docs/superpowers/specs/2026-05-05-localhost-http-server-design.md`

---

## File Structure

| 파일 | 작업 | 책임 |
|---|---|---|
| `plugins/token-tracker/lib/server_daemon.py` | Create | HTTP daemon 본체 (handler 라우팅 + bind 8765) |
| `plugins/token-tracker/lib/http_server.py` | Create | process 헬퍼: `is_alive`, `ensure_server_running`, `stop` |
| `plugins/token-tracker/skills/token-history-stop/SKILL.md` | Create | stop skill 메타 |
| `plugins/token-tracker/skills/token-history-stop/scripts/stop.py` | Create | stop 진입점 |
| `plugins/token-tracker/tests/test_server_daemon.py` | Create | daemon handler 단위/통합 테스트 |
| `plugins/token-tracker/tests/test_http_server.py` | Create | process 헬퍼 단위/통합 테스트 |
| `plugins/token-tracker/tests/test_stop_skill.py` | Create | stop skill e2e 테스트 |
| `plugins/token-tracker/skills/token-history/scripts/history.py` | Modify | HTML 파일 저장 제거, ensure_server_running 호출, URL 변경 |
| `plugins/token-tracker/tests/test_history_skill_e2e.py` | Modify | HTML 파일 검증 제거, http:// URL 검증 |
| `plugins/token-tracker/.claude-plugin/plugin.json` | Modify | version 0.8.1 → 0.9.0 |
| `.claude-plugin/marketplace.json` | Modify | version 0.8.1 → 0.9.0 |

테스트 카운트: 346 → 약 366 (신규 단위 15 + 통합 5).

---

## Task 0: feature 브랜치 + spec/plan commit

**Files:** git branch state, spec/plan files (untracked).

- [ ] **Step 1: main 최신화 + feature 브랜치 생성**

```bash
cd /Users/brody/Desktop/token-tracker
git checkout main
git pull origin main
git checkout -b feature/v0.9.0-localhost-http-server
```

- [ ] **Step 2: spec + plan commit**

```bash
git add docs/superpowers/specs/2026-05-05-localhost-http-server-design.md docs/superpowers/plans/2026-05-05-localhost-http-server.md
git commit -m "$(cat <<'EOF'
docs(spec,plan): v0.9.0 localhost HTTP server 디자인 + plan

/token-history 의 file:// 한계를 해소하기 위해 머신당 1개의 idempotent
HTTP daemon (포트 8765, 127.0.0.1 only) 을 도입하는 디자인.
- HTML 파일 디스크 저장 폐지 (동적 렌더)
- /token-history-stop skill 신규
- 4 신규 + 3 변경 파일, 약 20개 신규 테스트 (단위 15 + 통합 5)
EOF
)"
```

---

## Task 1: `lib/server_daemon.py` — HTTP daemon 본체

**Files:**
- Create: `plugins/token-tracker/lib/server_daemon.py`
- Create: `plugins/token-tracker/tests/test_server_daemon.py`

`server_daemon.py` 는 daemon 본체. `__main__` 으로 실행하면 8765 에 bind 하고 무한 루프. handler 가 `/`, `/{sid}`, `/healthz` 라우팅.

### Step 1: 단위 테스트 작성 (Red)

`plugins/token-tracker/tests/test_server_daemon.py` 신규 파일:

```python
from __future__ import annotations

import json
import re
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import pytest


def _start_test_server(monkeypatch, tmp_path):
    """포트 0 (OS 임의 할당) 으로 daemon 띄우고 (host, port) 반환.
    각 테스트 종료 시 자동 stop 되도록 finalizer 등록은 caller 가."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.server_daemon import build_server
    httpd = build_server(host="127.0.0.1", port=0)
    port = httpd.server_address[1]
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    return httpd, port


def _http_get(port: int, path: str, follow_redirects: bool = False):
    conn = HTTPConnection("127.0.0.1", port, timeout=2.0)
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    return resp.status, dict(resp.getheaders()), body


def test_healthz_returns_200_with_token_tracker_header(tmp_path, monkeypatch):
    httpd, port = _start_test_server(monkeypatch, tmp_path)
    try:
        status, headers, body = _http_get(port, "/healthz")
        assert status == 200
        assert headers.get("X-Token-Tracker") == "1"
        payload = json.loads(body.decode())
        assert "version" in payload
    finally:
        httpd.shutdown()


def test_root_redirects_to_most_recent_session(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.history_store import append_or_update_history
    append_or_update_history(
        session_id="s_old", prompt_id="p_o", user_prompt_text="x",
        started_at=1.0, ended_at=2.0,
        summary_dict={"total_cost": 0.0, "total_input_tokens": 0,
                       "total_output_tokens": 0, "cache_hit_rate": 0.0,
                       "total_elapsed": 1.0, "turns": []},
        models_used=["claude-opus-4-7"],
        has_subagent_other_model=False,
        transcript_entries=[],
    )
    append_or_update_history(
        session_id="s_recent", prompt_id="p_r", user_prompt_text="y",
        started_at=10.0, ended_at=11.0,
        summary_dict={"total_cost": 0.0, "total_input_tokens": 0,
                       "total_output_tokens": 0, "cache_hit_rate": 0.0,
                       "total_elapsed": 1.0, "turns": []},
        models_used=["claude-opus-4-7"],
        has_subagent_other_model=False,
        transcript_entries=[],
    )
    httpd, port = _start_test_server(monkeypatch, tmp_path)
    try:
        status, headers, _ = _http_get(port, "/")
        assert status == 302
        assert headers.get("Location") == "/s_recent"
    finally:
        httpd.shutdown()


def test_root_returns_404_when_no_sessions(tmp_path, monkeypatch):
    httpd, port = _start_test_server(monkeypatch, tmp_path)
    try:
        status, _, body = _http_get(port, "/")
        assert status == 404
        assert b"no sessions" in body.lower()
    finally:
        httpd.shutdown()


def test_session_id_returns_html(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.history_store import append_or_update_history
    append_or_update_history(
        session_id="s_html", prompt_id="p_h", user_prompt_text="hi",
        started_at=1.0, ended_at=2.0,
        summary_dict={"total_cost": 0.0, "total_input_tokens": 0,
                       "total_output_tokens": 0, "cache_hit_rate": 0.0,
                       "total_elapsed": 1.0, "turns": []},
        models_used=["claude-opus-4-7"],
        has_subagent_other_model=False,
        transcript_entries=[],
    )
    httpd, port = _start_test_server(monkeypatch, tmp_path)
    try:
        status, headers, body = _http_get(port, "/s_html")
        assert status == 200
        assert headers.get("Content-Type", "").startswith("text/html")
        assert b"<!doctype html>" in body.lower() or b"<html" in body.lower()
        assert b"p_h" in body  # prompt_id 가 inline payload 에 들어감
    finally:
        httpd.shutdown()


def test_invalid_session_id_returns_400(tmp_path, monkeypatch):
    """path traversal 방어: 영숫자/하이픈/언더스코어 외 문자 거부."""
    httpd, port = _start_test_server(monkeypatch, tmp_path)
    try:
        status, _, _ = _http_get(port, "/../etc/passwd")
        assert status == 400
        status, _, _ = _http_get(port, "/sid with space")
        assert status == 400
    finally:
        httpd.shutdown()


def test_unknown_session_id_returns_404(tmp_path, monkeypatch):
    httpd, port = _start_test_server(monkeypatch, tmp_path)
    try:
        status, _, _ = _http_get(port, "/s_does_not_exist")
        assert status == 404
    finally:
        httpd.shutdown()


def test_favicon_returns_204(tmp_path, monkeypatch):
    httpd, port = _start_test_server(monkeypatch, tmp_path)
    try:
        status, _, _ = _http_get(port, "/favicon.ico")
        assert status == 204
    finally:
        httpd.shutdown()


def test_concurrent_requests_succeed(tmp_path, monkeypatch):
    """ThreadingHTTPServer 기반 — 동시 요청 2건 성공."""
    httpd, port = _start_test_server(monkeypatch, tmp_path)
    try:
        results = []
        def worker():
            status, _, _ = _http_get(port, "/healthz")
            results.append(status)
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert results == [200, 200]
    finally:
        httpd.shutdown()
```

### Step 2: 테스트 실행해서 fail 확인

```bash
cd /Users/brody/Desktop/token-tracker
./venv/bin/pytest plugins/token-tracker/tests/test_server_daemon.py -v
```

Expected: 모든 case `ImportError` 또는 `AttributeError` (build_server 없음).

### Step 3: `lib/server_daemon.py` 구현

`plugins/token-tracker/lib/server_daemon.py` 신규:

```python
"""token-tracker HTTP daemon.

머신당 1개 (포트 8765, 127.0.0.1 only). /token-history skill 이 호출 시
ensure_server_running 으로 idempotent 시작. 매 요청마다 history.jsonl 을
읽어 동적 렌더링 (디스크 HTML 캐시 없음).

Routes:
  GET /healthz          -> 200 + X-Token-Tracker: 1 + {"version": ...}
  GET /                 -> 302 to /{most_recent_session_id} (없으면 404)
  GET /{session_id}     -> 200 text/html (render_history_html)
  GET /favicon.ico      -> 204
  그 외                 -> 404
"""
from __future__ import annotations

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


_VERSION = "0.9.0"
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _setup_sys_path() -> Path:
    # lib/server_daemon.py -> lib -> plugin root
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    return root


def _most_recent_session_id() -> str | None:
    from lib.history_store import load_all_sessions_history
    sessions = load_all_sessions_history()
    if not sessions:
        return None
    # 가장 최근 prompt 의 ended_at 기준 (없으면 started_at). entries 가 비어있으면 skip.
    latest_sid = None
    latest_ts = -1.0
    for sid, entries in sessions.items():
        for e in entries:
            ts = float(e.get("ended_at") or e.get("started_at") or 0.0)
            if ts > latest_ts:
                latest_ts = ts
                latest_sid = sid
    return latest_sid


def _render_session_html(session_id: str) -> bytes:
    from lib.config import get_language, load_config
    from lib.history_renderer import render_history_html
    from lib.history_store import (
        load_all_sessions_history,
        load_session_history,
    )
    from lib.i18n_loader import load_strings
    plugin_root = Path(__file__).resolve().parent.parent
    lang = get_language(load_config(plugin_root))
    load_strings(lang)  # 캐시 워밍 (renderer 가 내부 사용)
    current = load_session_history(session_id)
    all_sessions = load_all_sessions_history()
    html = render_history_html(current=current, all_sessions=all_sessions, lang=lang)
    return html.encode("utf-8")


class _Handler(BaseHTTPRequestHandler):
    server_version = "token-tracker-daemon/" + _VERSION

    def log_message(self, format, *args):
        # stderr 누수 방지 (부모 hook 응답 깨짐 방지). 필요 시 향후 file logger.
        return

    def do_GET(self):
        path = self.path
        if path == "/healthz":
            return self._respond_healthz()
        if path == "/favicon.ico":
            return self._respond_favicon()
        if path == "/":
            return self._respond_root()
        # /{session_id} 형태 — leading slash 제거
        candidate = path[1:] if path.startswith("/") else path
        # query string 제거
        if "?" in candidate:
            candidate = candidate.split("?", 1)[0]
        if not _SESSION_ID_RE.match(candidate):
            return self._respond_text(400, "invalid session id")
        return self._respond_session(candidate)

    def _respond_healthz(self):
        body = json.dumps({"version": _VERSION}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Token-Tracker", "1")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _respond_favicon(self):
        self.send_response(204)
        self.end_headers()

    def _respond_root(self):
        sid = _most_recent_session_id()
        if not sid:
            return self._respond_text(404, "no sessions yet")
        self.send_response(302)
        self.send_header("Location", f"/{sid}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _respond_session(self, session_id: str):
        from lib.history_store import load_session_history
        entries = load_session_history(session_id)
        if not entries:
            return self._respond_text(404, "session not found")
        body = _render_session_html(session_id)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _respond_text(self, status: int, msg: str):
        body = msg.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), _Handler)


def main() -> int:
    _setup_sys_path()
    httpd = build_server()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### Step 4: 테스트 실행 + 통과 확인

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_server_daemon.py -v
```

Expected: 8 passed.

### Step 5: 전체 회귀

```bash
./venv/bin/pytest plugins/token-tracker/tests -q
```

Expected: 354 passed (346 + 8).

### Step 6: commit

```bash
git add plugins/token-tracker/lib/server_daemon.py plugins/token-tracker/tests/test_server_daemon.py
git commit -m "$(cat <<'EOF'
feat(server): HTTP daemon 본체 추가 (lib/server_daemon.py)

ThreadingHTTPServer 기반 정적 라우터.
- GET /healthz: 200 + X-Token-Tracker: 1 + version
- GET /: 가장 최근 세션으로 302 redirect (없으면 404)
- GET /{session_id}: 동적 렌더 (history_renderer.render_history_html)
- GET /favicon.ico: 204
- path traversal 방어: session_id [A-Za-z0-9_-]+ regex
- log_message override: stderr 누수 방지 (hook 응답 깨짐 방지)

신규 단위/통합 테스트 8건. 임의 포트 (port=0) 로 띄워 실제 GET 응답 검증.
EOF
)"
```

---

## Task 2: `lib/http_server.py` — process 헬퍼

**Files:**
- Create: `plugins/token-tracker/lib/http_server.py`
- Create: `plugins/token-tracker/tests/test_http_server.py`

### Step 1: 단위 테스트 작성 (Red)

`plugins/token-tracker/tests/test_http_server.py` 신규:

```python
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
```

### Step 2: 테스트 실행해서 fail 확인

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_http_server.py -v
```

Expected: 모든 case `ImportError` (`lib.http_server` 없음).

### Step 3: `lib/http_server.py` 구현

`plugins/token-tracker/lib/http_server.py` 신규:

```python
"""token-tracker HTTP daemon process 헬퍼.

skill 호출 시 idempotent 시작 (살아있으면 재사용, 없으면 띄움).
명시 종료는 lsof + os.kill.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from http.client import HTTPConnection, HTTPResponse
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
    except (ConnectionRefusedError, socket.timeout, OSError):
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
    # 짧게 대기 후 살아있으면 SIGKILL
    time.sleep(0.5)
    if is_alive():
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    return len(pids)
```

### Step 4: 테스트 실행 + 통과 확인

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_http_server.py -v
```

Expected: 10 passed.

### Step 5: 전체 회귀

```bash
./venv/bin/pytest plugins/token-tracker/tests -q
```

Expected: 364 passed (354 + 10).

### Step 6: commit

```bash
git add plugins/token-tracker/lib/http_server.py plugins/token-tracker/tests/test_http_server.py
git commit -m "$(cat <<'EOF'
feat(server): HTTP daemon process 헬퍼 추가 (lib/http_server.py)

3개 함수:
- is_alive: /healthz 호출 + X-Token-Tracker 헤더 검증으로 본인 daemon 식별.
- ensure_server_running: idempotent. dead 면 detached subprocess 로 start
  + healthcheck 폴링 (3s timeout). timeout 시 RuntimeError.
- stop: lsof 로 8765 점유 PID 수집 → SIGTERM, 살아있으면 SIGKILL.

신규 단위 테스트 10건 (mock 기반).
EOF
)"
```

---

## Task 3: `/token-history-stop` skill

**Files:**
- Create: `plugins/token-tracker/skills/token-history-stop/SKILL.md`
- Create: `plugins/token-tracker/skills/token-history-stop/scripts/stop.py`
- Create: `plugins/token-tracker/tests/test_stop_skill.py`

### Step 1: 테스트 작성 (Red)

`plugins/token-tracker/tests/test_stop_skill.py` 신규:

```python
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
```

### Step 2: fail 확인

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_stop_skill.py -v
```

Expected: ImportError (skill 디렉터리/파일 없음).

### Step 3: `SKILL.md` 작성

`plugins/token-tracker/skills/token-history-stop/SKILL.md` 신규:

```markdown
---
name: token-history-stop
description: token-history HTTP daemon (포트 8765) 을 명시적으로 종료
disable-model-invocation: true
---

<script-output>
!`python3 ${CLAUDE_SKILL_DIR}/scripts/stop.py`
</script-output>

**필수 규칙 — 반드시 준수:**
- 당신의 응답은 오직 위 `<script-output>` 태그 내부 텍스트를 **한 글자도 바꾸지 말고 그대로** 출력하는 것이다.
- 해석·요약·생략·추가 설명·맥락 언급·이전 대화 참조 절대 금지.
- 이 skill이 실행된 순간 이전 대화는 무시하라. 오직 위 블록만 출력한다.
- `<script-output>` 태그 자체는 출력에 포함하지 마라 (내부 텍스트만).
- 출력 전후에 어떤 문장도 추가하지 마라.
```

### Step 4: `scripts/stop.py` 작성

`plugins/token-tracker/skills/token-history-stop/scripts/stop.py` 신규:

```python
#!/usr/bin/env python3
"""token-history HTTP daemon stop 진입점."""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _setup_sys_path() -> None:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        root = Path(env)
    else:
        # scripts/stop.py -> scripts -> token-history-stop -> skills -> plugin root
        root = Path(__file__).resolve().parent.parent.parent.parent
    sys.path.insert(0, str(root))


def main(argv: list[str]) -> int:
    _setup_sys_path()
    try:
        from lib.http_server import stop
        n = stop()
        if n > 0:
            print(f"token-history server stopped ({n} process)")
        else:
            print("no server running")
        return 0
    except Exception:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

### Step 5: 테스트 실행 + 통과 확인

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_stop_skill.py -v
```

Expected: 3 passed.

### Step 6: 전체 회귀

```bash
./venv/bin/pytest plugins/token-tracker/tests -q
```

Expected: 367 passed (364 + 3).

### Step 7: commit

```bash
git add plugins/token-tracker/skills/token-history-stop plugins/token-tracker/tests/test_stop_skill.py
git commit -m "$(cat <<'EOF'
feat(skill): /token-history-stop skill 신규 추가

token-history HTTP daemon (포트 8765) 을 명시적으로 종료. lib.http_server.stop
호출 → 종료한 process 수 출력. 예외 시 stderr 출력 + non-zero return.

신규 e2e 테스트 3건 (stop / no server / exception 격리).
EOF
)"
```

---

## Task 4: `/token-history` skill 수정 (file:// → http://)

**Files:**
- Modify: `plugins/token-tracker/skills/token-history/scripts/history.py`
- Modify: `plugins/token-tracker/tests/test_history_skill_e2e.py`

### Step 1: 기존 e2e 테스트 갱신 (Red)

`plugins/token-tracker/tests/test_history_skill_e2e.py` 의 두 테스트 수정. **전체 파일** 을 다음으로 교체:

```python
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
```

### Step 2: 테스트 실행 — fail 확인

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_history_skill_e2e.py -v
```

Expected: 4개 모두 FAIL (`history.py` 가 아직 file:// 흐름).

### Step 3: `history.py` 수정

`plugins/token-tracker/skills/token-history/scripts/history.py` 의 `main` 함수에서 line 50 ~ line 80 영역 (HTML 파일 저장 + open 호출 부분) 을 다음으로 **교체**.

기존 코드:
```python
        current = load_session_history(session_id)
        all_sessions = load_all_sessions_history()

        html = render_history_html(current=current, all_sessions=all_sessions, lang=lang)

        out_dir = paths.state_dir() / session_id
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        out_path = out_dir / f"history-{ts}.html"
        out_path.write_text(html, encoding="utf-8")

        # Keep only the 2 most recent snapshots per session to bound disk usage.
        # Timestamp suffix is for browser cache-bust (spec §2); accumulating
        # every snapshot would silently grow disk over time.
        existing = sorted(out_dir.glob("history-*.html"))
        for old in existing[:-2]:
            try:
                old.unlink()
            except OSError:
                pass

        url = f"file://{out_path}"
        try:
            subprocess.run(["open", url], check=False)
        except FileNotFoundError:
            pass

        print(strings["opened_url"].format(url=url))
        return 0
```

신규 코드:
```python
        from lib.http_server import ensure_server_running

        # 데이터 존재 확인 (없으면 안 띄움)
        current = load_session_history(session_id)
        if not current:
            print(strings["no_data_message"])
            return 0

        # daemon 시작 (idempotent)
        ensure_server_running()

        url = f"http://127.0.0.1:8765/{session_id}"
        try:
            subprocess.run(["open", url], check=False)
        except FileNotFoundError:
            pass

        print(strings["opened_url"].format(url=url))
        return 0
```

추가로 이전에 사용되던 import / 변수 정리:
- `import time` 제거 (더 이상 ts 안 씀)
- `paths` import 는 유지 (다른 위치에서 사용 가능, 변경 없으면 그대로 둠. 안 쓰면 lint warning 만 — 일단 그대로)
- `from lib.history_store import (load_all_sessions_history, load_session_history,)` 중 `load_all_sessions_history` 미사용 → 그대로 두거나 제거 (사용자 룰 "unused 정리" 따라 제거 권장)
- `from lib.history_renderer import render_history_html` 미사용 → 제거

수정 후 import 영역:
```python
        from lib.config import get_language, load_config
        from lib import paths
        from lib.history_store import load_session_history
        from lib.i18n_loader import load_strings
        from lib.http_server import ensure_server_running
```

(`render_history_html`, `load_all_sessions_history`, `time`, `paths.state_dir` 모두 제거)

### Step 4: 테스트 통과 확인

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_history_skill_e2e.py -v
```

Expected: 4 passed.

### Step 5: 전체 회귀

```bash
./venv/bin/pytest plugins/token-tracker/tests -q
```

Expected: 367 passed (이전 367 - 기존 2 + 신규 4 = 369? 정확히는 기존 e2e 2 → 신규 4 로 +2. 354(Task1) + 10(Task2) + 3(Task3) + 2(this) = ...). 실제 숫자 확인 후 변동만 reporting.

### Step 6: commit

```bash
git add plugins/token-tracker/skills/token-history/scripts/history.py plugins/token-tracker/tests/test_history_skill_e2e.py
git commit -m "$(cat <<'EOF'
feat(skill): /token-history 가 HTTP daemon 으로 진입 (file:// 폐지)

- HTML 파일 디스크 저장 / cap 정책 제거 (동적 렌더로 대체)
- ensure_server_running 호출로 idempotent daemon 시작
- URL: file:///...html → http://127.0.0.1:8765/{session_id}
- 사용 안 하게 된 import 정리 (time, render_history_html, load_all_sessions_history, paths.state_dir)

기존 e2e 테스트 갱신 + daemon startup 실패 케이스 추가 (총 4건).
EOF
)"
```

---

## Task 5: 버전 bump (v0.8.1 → v0.9.0)

**Files:**
- Modify: `plugins/token-tracker/.claude-plugin/plugin.json` (line 4)
- Modify: `.claude-plugin/marketplace.json` (line 12)

### Step 1: plugin.json bump

`/Users/brody/Desktop/token-tracker/plugins/token-tracker/.claude-plugin/plugin.json` 의 `"version": "0.8.1"` → `"version": "0.9.0"`.

### Step 2: marketplace.json bump

`/Users/brody/Desktop/token-tracker/.claude-plugin/marketplace.json` 의 `"version": "0.8.1"` → `"version": "0.9.0"`.

### Step 3: server_daemon.py 의 _VERSION 도 동기화

`lib/server_daemon.py:24` 의 `_VERSION = "0.9.0"` 이 plugin.json 과 일치하는지 확인. 일치해야 healthcheck 응답의 version 필드가 정확.

### Step 4: 전체 회귀

```bash
./venv/bin/pytest plugins/token-tracker/tests -q
```

Expected: 모든 테스트 통과 (Task 4 종료 시점의 카운트와 동일).

### Step 5: commit

```bash
git add plugins/token-tracker/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "$(cat <<'EOF'
chore(release): v0.9.0 — localhost HTTP server

plugin.json + marketplace.json 버전 0.8.1 → 0.9.0.

변경 내용:
- /token-history 가 머신당 1개의 HTTP daemon (8765, 127.0.0.1) 통해 진입
- 동적 렌더링 (HTML 파일 디스크 저장 폐지)
- /token-history-stop skill 신규
- file:// 한계 (fetch / module / CORS) 해소
EOF
)"
```

---

## Task 6: PR 생성 + 사용자 리뷰 요청

**Files:** (코드 변경 없음)

### Step 1: feature 브랜치 push

```bash
git push -u origin feature/v0.9.0-localhost-http-server
```

### Step 2: PR 생성

```bash
gh pr create --title "v0.9.0: localhost HTTP server" --body "$(cat <<'EOF'
## Summary
머신당 1개의 idempotent HTTP daemon (포트 8765, 127.0.0.1 only) 도입으로 /token-history 의 file:// 한계 (fetch / ES module / CORS) 해소. 동적 렌더링으로 HTML 파일 디스크 저장 폐지. /token-history-stop skill 신규.

## 신규 동작
- `/token-history` → daemon 살아있으면 재사용, 없으면 띄움 → 브라우저 `http://127.0.0.1:8765/{session_id}`
- `/token-history-stop` → daemon 종료 (포트 8765 점유 PID kill)
- daemon 라이프사이클: 안 죽음 (재부팅까지 살아있음, 명시 stop 으로만 종료)

## 라우팅
- `GET /healthz` — 200 + X-Token-Tracker: 1
- `GET /` — 가장 최근 활동 세션으로 302 redirect
- `GET /{session_id}` — 200 text/html (매 요청 동적 렌더)
- `GET /favicon.ico` — 204
- 그 외 — 400 (path traversal 방어) / 404

## Test plan
- [x] `lib/server_daemon` 단위/통합 8건 (handler 라우팅 + path traversal + 동시 요청)
- [x] `lib/http_server` 단위 10건 (is_alive / ensure_server_running / stop 분기)
- [x] `/token-history-stop` skill e2e 3건
- [x] `/token-history` skill e2e 4건 (URL 변경 + HTML 파일 미생성 + open 실패 격리 + daemon startup 실패)
- [x] 전체 회귀: 약 366/366 passing

## Spec / Plan
- spec: `docs/superpowers/specs/2026-05-05-localhost-http-server-design.md`
- plan: `docs/superpowers/plans/2026-05-05-localhost-http-server.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

### Step 3: PR URL 보고 + 머지 대기

PR URL 출력 후 사용자에게 plugin reinstall + reload 절차 안내. 머지는 사용자 명시 승인 후만.

---

## Self-Review

- **Spec coverage**:
  - §4.1 신규 `lib/http_server.py` → Task 2 ✓
  - §4.1 신규 `lib/server_daemon.py` → Task 1 ✓
  - §4.1 신규 `skills/token-history-stop/` → Task 3 ✓
  - §4.2 `history.py` 변경 → Task 4 ✓
  - §4.2 plugin.json / marketplace.json → Task 5 ✓
  - §5 라이프사이클 (is_alive 헤더 검증, Popen detach, lsof+kill) → Task 1/2 코드에 반영 ✓
  - §6 라우팅 5가지 → Task 1 테스트 7건 + 구현 ✓ (favicon, root, sid, invalid sid, unknown sid, healthz, 동시 요청)
  - §7.1 history.py import 정리 → Task 4 Step 3 명시 ✓
  - §7.2 stop SKILL.md 형식 → Task 3 Step 3 ✓
  - §8 테스트 카운트 (단위 15 + 통합 5 = ~20) → Task 1 (8) + Task 2 (10) + Task 3 (3) + Task 4 (4) = 25. spec 보다 5건 많음 — 보강이라 OK.
  - §9 호환성 → schema/SUPPORTED_SCHEMA_VERSIONS 변경 없음 (Task 1~5 어디서도 안 건드림) ✓
  - §10 DoD → Task 5 (회귀) + Task 6 (PR) + 수동 검증은 머지 후 사용자가 ✓
  - §11 리스크 (lsof / detach / stderr / port 충돌 / firewall / Python interpreter) → 코드 자체로 처리 (DEVNULL/log 파일, sys.executable, header check) ✓

- **Placeholder scan**: TBD/TODO 없음. 모든 step 에 실제 코드/명령어.

- **Type consistency**:
  - `is_alive(host, port)` — Task 2 정의, Task 2/4 호출 일치
  - `ensure_server_running()` — 인자 없음, Task 2 정의, Task 4 호출 일치
  - `stop() -> int` — Task 2 정의, Task 3 호출 (반환값 사용) 일치
  - `build_server(host, port)` — Task 1 정의, Task 1 테스트에서 호출 일치
  - `_SESSION_ID_RE` — Task 1 내부 사용, 외부 노출 없음

- **테스트 카운트 추정**: 346 + 8 + 10 + 3 + (4 - 2 기존) = 369. spec 의 "약 366" 과 차이 있음 (간이 추산이라 OK). 실제 숫자는 Task 5 Step 4 에서 검증.
