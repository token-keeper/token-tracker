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
        # 공백은 %20 으로 percent-encode (Python 3.14 HTTPClient 가 raw 공백 거부)
        status, _, _ = _http_get(port, "/sid%20with%20space")
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
