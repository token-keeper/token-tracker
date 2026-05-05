# localhost HTTP server — design (v0.9.0)

> 목적: `/token-history` 의 file:// 한계를 해소하기 위해 머신당 1개의 idempotent HTTP daemon 을 도입한다.

---

## 1. 배경

`/token-history` (v0.8.x) 는 HTML 파일을 디스크에 쓰고 `open file://...html` 로 브라우저를 띄운다. file:// 스킴은 fetch / module import / CORS 의존 기능이 차단되어 모던 web API 활용이 막혀 있다. 또한 디스크에 HTML snapshot 을 누적하지 않으려고 "세션당 최근 2개" cap 을 들고 있는데, 이 자체가 디스크 caching 의 부담.

머신당 1개의 작은 HTTP daemon 을 띄우면:
- 브라우저는 정상 web origin (http://127.0.0.1:8765) 에서 페이지 로드 → fetch / ES module / CORS 정책 정상 작동
- HTML 을 디스크에 저장할 필요 없음 (서버가 매 요청마다 동적 렌더 → 항상 최신)
- 다중 Claude Code 세션이 같은 daemon 을 공유 (idempotent)

## 2. 목표

1. 머신당 1개의 HTTP daemon (포트 8765, `127.0.0.1` only) 도입.
2. `/token-history` skill 이 호출될 때 daemon 살아있으면 재사용, 없으면 띄움 (idempotent).
3. URL 단순화: `http://127.0.0.1:8765/{session_id}` (HTML 파일 디스크 저장 폐지).
4. `/token-history-stop` skill 추가 (명시 종료 수단).
5. 기존 `/token-history` 외부 인터페이스 호환 — 호출 방식 동일, 출력 URL 만 변경.

## 3. 비목표 (out-of-scope)

- DB 도입 (history.jsonl 그대로) — v0.10.0 후보로 분리.
- 토큰 인증 / 다중 user 보안 — 개인 macbook 가정. 회사·공유 머신은 별도 follow-up.
- HTTPS — loopback only 라 불필요.
- daemon idle timeout / 활성 세션 카운트 — 합의 결정: 안 죽임 (재부팅 시 자연 종료).
- 다중 머신 history sync.
- 옛 `state_dir/{sid}/history-*.html` 파일 자동 정리 — 일회성 마이그레이션 안 함 (사용자가 원하면 `rm`).
- 포트 8765 충돌 시 fallback 포트 자동 검색 — 점유 안내만 출력.

## 4. 아키텍처

```
┌──────────────────────────────────────────────────┐
│ Claude Code 세션                                  │
│                                                  │
│  /token-history skill                            │
│    ↓                                             │
│  scripts/history.py (수정)                        │
│    1. ensure_server_running()  ← 신규             │
│    2. open http://127.0.0.1:8765/{session_id}    │
└──────────────────────────────────────────────────┘
                       │
                       ▼ TCP 8765
┌──────────────────────────────────────────────────┐
│ HTTP daemon (백그라운드 Python 프로세스)            │
│                                                  │
│  - http.server.ThreadingHTTPServer                │
│  - bind: ("127.0.0.1", 8765)                     │
│  - GET /{session_id} → 매 요청마다 동적 렌더         │
│  - GET / → 가장 최근 활동 세션으로 redirect          │
└──────────────────────────────────────────────────┘
                       ▲
                       │ kill
┌──────────────────────────────────────────────────┐
│ /token-history-stop skill                        │
│    ↓                                             │
│  scripts/stop.py                                 │
│    - lsof 로 8765 PID 찾아 kill                   │
└──────────────────────────────────────────────────┘
```

### 4.1 신규 파일

| 파일 | 책임 |
|---|---|
| `lib/http_server.py` | daemon process 헬퍼: `ensure_server_running()`, `is_running()`, `stop()` |
| `lib/server_daemon.py` | daemon 본체 (background entry point). `__main__` 으로 실행 |
| `skills/token-history-stop/SKILL.md` | stop skill 메타 |
| `skills/token-history-stop/scripts/stop.py` | stop 진입점 |

### 4.2 변경 파일

| 파일 | 변경 |
|---|---|
| `skills/token-history/scripts/history.py` | HTML 파일 저장 제거, `ensure_server_running()` 호출, URL 변환 |
| `plugins/token-tracker/.claude-plugin/plugin.json` | version 0.8.1 → 0.9.0 + skills 등록 (필요 시) |
| `.claude-plugin/marketplace.json` | version 0.8.1 → 0.9.0 |

## 5. daemon 라이프사이클

### 5.1 시작 (`ensure_server_running`)

```python
def ensure_server_running() -> None:
    if _is_alive():
        return
    _start_daemon()
    _wait_until_alive(timeout=2.0, retries=3)
```

- `_is_alive()` — `socket.create_connection(("127.0.0.1", 8765), timeout=0.5)` 성공 + healthcheck 응답에 `X-Token-Tracker: 1` 헤더 확인. 본인 daemon 이면 True. 다른 프로세스가 점유 중이면 False (그러나 start 도 실패하므로 안내 후 종료).
- `_start_daemon()` — `subprocess.Popen([sys.executable, "-m", "lib.server_daemon"], cwd=plugin_root, start_new_session=True, stdout=DEVNULL, stderr=PIPE→error.log)`. 부모 세션과 detach.
- 시작 실패 / port 점유 / startup timeout 시 `RuntimeError` raise. 호출자 (`history.py`) 의 기존 `try/except` 가 받아 `error.log` 기록 + stderr 출력 (기존 패턴 활용).

### 5.2 stop (`stop()`)

`subprocess.check_output(["lsof", "-t", "-i", ":8765"])` 로 PID 수집 → `os.kill(pid, signal.SIGTERM)`. 0.5s 대기 후 살아있으면 SIGKILL.

### 5.3 죽지 않음 (idle/session-end 종료 안 함)

- 합의: daemon 은 자연 죽음만 인정 (머신 재부팅, 명시 stop, OOM kill).
- multi-session 간 간섭 없음.
- 메모리 ~5MB 수준이라 부담 없음.

## 6. HTTP 라우팅

| Method · Path | 응답 |
|---|---|
| `GET /` | 가장 최근 prompt 가 있는 세션의 sid 찾아 `302 Location: /{sid}`. 없으면 `404 no sessions yet` |
| `GET /{session_id}` | `text/html`, body = `render_history_html(current=load_session_history(sid), all_sessions=load_all_sessions_history(), lang=...)` |
| `GET /healthz` | `200 ok`, header `X-Token-Tracker: 1`, body = `{"version": "0.9.0"}` |
| `GET /favicon.ico` | `204 no content` |
| 그 외 | `404 not found` |

### 6.1 매 요청 동적 렌더링

- `lang` 은 매 요청마다 `load_config(plugin_root)` 로 읽음 (config 변경 즉시 반영).
- `load_session_history` / `load_all_sessions_history` 도 매 요청마다 호출 (jsonl 파일 직접 읽음).
- 단일 머신 personal use 라 동시 요청 빈도 낮음. caching 안 함 (YAGNI).

### 6.2 보안 모델

- `127.0.0.1` only bind → 외부 네트워크 차단.
- 같은 머신 내 다른 user 접근은 가능 (개인 macbook 가정, 회사·공유 머신은 follow-up).
- Path traversal 방어: handler 가 `session_id` 를 `[a-zA-Z0-9-_]+` 정규식으로 validate. 매칭 안 되면 400.

## 7. skill 변경

### 7.1 `/token-history` (`scripts/history.py`)

- 기존 line 57~71 (HTML 파일 디스크 저장 + cap) 제거.
- 기존 line 73 `url = f"file://{out_path}"` 를 `url = f"http://127.0.0.1:8765/{session_id}"` 로 변경.
- `ensure_server_running()` 호출을 `subprocess.run(["open", url])` 직전에 추가.
- session_id 가 없는 경우 (`if not session_id`) 흐름은 기존 그대로 유지 (`no_data_message` 출력).

### 7.2 `/token-history-stop` (신규)

`SKILL.md` 형식:
```yaml
---
name: token-history-stop
description: token-history HTTP daemon 종료
disable-model-invocation: true
---

<script-output>
!`python3 ${CLAUDE_SKILL_DIR}/scripts/stop.py`
</script-output>

(필수 규칙 — 기존 token-history skill 과 동일한 출력 디시플린 블록)
```

`scripts/stop.py` 는 `lib/http_server.stop()` 호출 → 결과 1줄 출력 (`token-history server stopped` 또는 `no server running`).

## 8. 테스트

신규 약 20건 (단위 15 + 통합 5).

### 8.1 단위 — `lib/http_server`
- `_is_alive` 가 정상 응답 / 헤더 누락 / connect 실패 / 다른 프로세스 응답 4 case 처리
- `ensure_server_running` 가 살아있을 때 Popen 호출 안 함
- `ensure_server_running` 가 없을 때 Popen 호출 + healthcheck 폴링 → 성공
- `ensure_server_running` 가 startup timeout 시 `RuntimeError` raise (호출자 `history.py` 의 try/except 가 처리)
- `stop` 가 lsof 결과 PID 들에 SIGTERM, 살아있으면 SIGKILL

### 8.2 단위 — `lib/server_daemon` (handler 라우팅)
- `GET /healthz` → 200 + 헤더 + version
- `GET /` → 가장 최근 활동 세션으로 302 redirect
- `GET /{valid_sid}` → 200 text/html
- `GET /{invalid_sid_with_slash}` → 400 (path traversal 방어)
- `GET /unknown` → 404

### 8.3 통합 — daemon 띄우고 실제 요청
- 임의 포트 (`port=0`) 로 daemon 시작 → `GET /healthz` / `GET /{sid}` 실제 응답 검증
- 동시 요청 2건 (threading)
- daemon stop 후 connect 실패 검증

### 8.4 통합 — `/token-history` skill
- 기존 `test_history_skill_e2e.py` 갱신: file:// → http:// URL, HTML 파일 미생성 검증

## 9. 호환성

- **history.jsonl schema**: 변경 없음.
- **`SUPPORTED_SCHEMA_VERSIONS`**: bump 안 함.
- **외부 인터페이스**: `/token-history` 호출 방식 동일, 출력 URL 만 `file://` → `http://127.0.0.1:8765/...` 로 변경.
- **옛 `state_dir/{sid}/history-*.html`**: 사용자가 원하면 직접 삭제 가능. 자동 마이그레이션 없음.

## 10. Definition of Done

1. 신규 약 20건 + 기존 346건 = 약 366/366 테스트 통과 (`./venv/bin/pytest plugins/token-tracker/tests -q`).
2. `plugin.json` / `marketplace.json` v0.9.0 반영.
3. 신규 `token-history-stop` skill 정상 등록 (Claude Code reload 후 인식).
4. 수동 검증 (사용자):
   - 첫 `/token-history` 호출 → daemon 시작 + 브라우저 열림 (http://...)
   - 두번째 호출 → daemon 재사용 (시작 안 함, 즉시 응답)
   - `/token-history-stop` 호출 → daemon 종료 + "stopped" 출력
   - `/token-history` 다시 호출 → daemon 재시작
5. PR 생성 → 사용자 리뷰 → 승인 후 머지 + v0.9.0 태그.

## 11. 리스크 / 고려사항

- **`lsof` 의존**: macOS / Linux 표준 도구지만 없을 가능성 매우 낮음. 없으면 stderr/error.log 안내 후 종료.
- **`start_new_session=True`**: subprocess 가 부모 세션 죽음에 영향받지 않게 detach. macOS / Linux 모두 동작.
- **stderr 누수**: daemon 의 stderr 가 부모 프로세스로 누수되면 hook 응답 (skill output) 깨짐. PIPE 로 받아 별도 스레드/파일로 redirect 또는 DEVNULL.
- **포트 충돌 (다른 프로세스)**: `_is_alive()` 가 false 반환 (헤더 mismatch) → start 도 실패 → 안내 출력 ("port 8765 occupied by other process, please free or stop conflict").
- **macOS firewall prompt**: 첫 bind 시 macOS 가 "외부 접근 허용?" 다이얼로그를 띄울 수 있음 (loopback only 라 보통 안 뜸). 뜨면 사용자가 거부해도 loopback bind 는 동작.
- **brew Python vs system Python**: `sys.executable` 사용 → 호출자와 동일한 인터프리터로 daemon 실행 (가상환경/시스템 mismatch 방지).
