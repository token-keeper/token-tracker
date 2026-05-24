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
    entries = load_all_sessions_history()
    if not entries:
        return None
    # 가장 최근 prompt 의 ended_at 기준 (없으면 started_at).
    latest_sid = None
    latest_ts = -1.0
    for e in entries:
        ts = float(e.get("ended_at") or e.get("started_at") or 0.0)
        if ts > latest_ts:
            latest_ts = ts
            latest_sid = e.get("session_id")
    return latest_sid


def _render_session_html(session_id: str, current_entries: list[dict]) -> bytes:
    from lib.config import get_language, load_config
    from lib.history_renderer import render_history_html
    from lib.history_store import load_all_sessions_history
    plugin_root = Path(__file__).resolve().parent.parent
    lang = get_language(load_config(plugin_root))
    all_sessions = load_all_sessions_history()
    html = render_history_html(current=current_entries, all_sessions=all_sessions, lang=lang)
    return html.encode("utf-8")


class _Handler(BaseHTTPRequestHandler):
    server_version = "token-tracker-daemon/" + _VERSION

    def log_message(self, format, *args):
        # stderr 누수 방지 (부모 hook 응답 깨짐 방지). 필요 시 향후 file logger.
        return

    def do_GET(self):
        clean_path = self.path.split("?", 1)[0].split("#", 1)[0]
        if clean_path == "/healthz":
            return self._respond_healthz()
        if clean_path == "/favicon.ico":
            return self._respond_favicon()
        if clean_path == "/":
            return self._respond_root()
        # /{session_id} 형태 — leading slash 제거
        candidate = clean_path[1:] if clean_path.startswith("/") else clean_path
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
        body = _render_session_html(session_id, entries)
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
