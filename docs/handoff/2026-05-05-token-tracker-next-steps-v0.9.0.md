# token-tracker 인수인계 — 2026-05-05 (v0.9.0 출시 후)

> 다음 세션의 Claude 가 바로 이어 작업할 수 있게 정리된 핸드오프. 이 파일을 먼저 읽고, 참조 파일 확인 후 사용자의 다음 지시를 따른다. 같은 날(2026-05-05) 의 v0.8.0 시점 핸드오프 (`2026-05-05-token-tracker-next-steps.md`) 도 함께 참조.

---

## 1. 한 줄 요약

token-tracker = Claude Code 플러그인. **현재 v0.9.0** — 머신당 1개의 idempotent HTTP daemon (포트 8765, `127.0.0.1` only) 도입.
- `/token-history` 가 `file://` 대신 `http://127.0.0.1:8765/{session_id}` 로 진입 → fetch / ES module / CORS 활용 가능
- HTML 파일 디스크 저장 폐지 (매 요청 동적 렌더)
- 신규 `/token-history-stop` skill (daemon 명시 종료)
- 다크모드 펼침 영역 elevation 토큰 추가 (`--surface-elev`)
- 370 tests passing (v0.8.1 baseline 346 + 신규 24)

---

## 2. 이번 세션의 두 출시 (v0.8.1 + v0.9.0)

같은 세션에서 두 PR 연속 머지.

### 2.1 v0.8.1 (PR #4, commit `c202a4b`)
- **핵심**: `lib/parser.py` 의 `parse_tool_result` 가 `text` 외 content block (MCP `tool_reference`, `image`) 을 빈 문자열로 떨어뜨리던 v0.8.0 회귀 수정
- 신규 helper `_normalize_tool_result_block(block) -> str` — 4종 분기 (text / tool_reference / image / unknown) + 미래 새 type 도 `[<type>]` placeholder 로 방어
- 추가 fix 두 건 (사용자가 "버전 분리 말고" 라며 같이 묶음):
  - `style.css`: turn 헤더의 도구 pill wrap 허용 (3개 이상이면 잘리던 문제)
  - `history_renderer.py` + `app.js`: multi-tool turn 의 첫 도구만 보이던 회귀 → `tool_pairs` list 데이터 모델로 (tool_use_id 매칭)
- 16 신규 테스트 (단위 12 parametrize + 통합 4)

### 2.2 v0.9.0 (PR #5, commit `b083007`)
- **핵심**: HTTP daemon 도입 — `lib/server_daemon.py` (handler) + `lib/http_server.py` (process 헬퍼)
- daemon 라이프사이클:
  - **안 죽음** (재부팅까지 살아있음, 명시 stop 으로만 종료)
  - 호출 시 살아있으면 재사용 (idempotent), 없으면 띄움
  - daemon 본인 식별: `/healthz` 응답에 `X-Token-Tracker: 1` 헤더
- 라우팅: `/healthz`, `/`, `/{session_id}`, `/favicon.ico` (path traversal 방어 `^[A-Za-z0-9_-]+$`)
- 신규 skill `/token-history-stop` (`lsof -t -i :8765` → SIGTERM → 0.5s 대기 → 살아있는 PID 만 SIGKILL)
- `/token-history` 의 HTML 파일 디스크 저장 / cap 정책 폐지 (매 요청 동적 렌더)
- CSS 다크모드 elevation 토큰 `--surface-elev` 추가 (펼친 row + panel 이 일반 row 와 명확히 구분되게)
- 24 신규 테스트 (server_daemon 8 + http_server 11 + stop_skill 3 + e2e 갱신 +2)

### 2.3 코드리뷰 결과 보강 (subagent-driven-development 흐름)
각 task 후 spec compliance + code quality 두 단계 review.

대표 발견 + fix:
- v0.8.1 Task 1 (helper): MAJOR 1 (Task 2 단독 머지 금지) — 4 commit 한 PR 으로 묶음, follow-up 없음
- v0.8.1 Task 2 (parse_tool_result): MAJOR (image 통합 테스트 누락) → 보강 commit 추가
- v0.9.0 Task 1 (server_daemon): MAJOR (do_GET 쿼리스트링 strip 순서) → fix
- v0.9.0 Task 2 (http_server): **CRITICAL** (`BadStatusLine` / `IncompleteRead` 미포착, `OSError` 서브클래스 아님) + MAJOR 3 (log_fp close, SIGKILL per-PID 체크, timeout 테스트 3초 실제 대기) → 한 commit 으로 묶어 fix

---

## 3. v0.8.x 와의 호환성

- `history.jsonl` schema **변경 없음**. `transcript_entries[*].content` 는 여전히 string. `SUPPORTED_SCHEMA_VERSIONS` bump 안 함.
- 옛 `state_dir/{sid}/history-*.html` 파일은 자동 정리 안 함. 사용자가 원하면 `rm`. 다음 prompt 부터 access 안 됨.
- `/token-history` 외부 호출 인터페이스 동일, 출력 URL 만 `file://` → `http://127.0.0.1:8765/{sid}`.
- Pricing dict / hook 동작 변경 없음.

---

## 4. 파일 구조 / 참조 순서

다음 세션에서는 아래 순서로 읽어라.

1. **이 문서** (`docs/handoff/2026-05-05-token-tracker-next-steps-v0.9.0.md`) — 현재 상황, 다음 작업 후보
2. **v0.8.0 핸드오프** (`docs/handoff/2026-05-05-token-tracker-next-steps.md`) — v0.7.0 ~ v0.8.0 컨텍스트, 사용자 성향 메모
3. **v0.7.0 / v0.8.0 spec / plan** (선택) — `docs/superpowers/specs/`, `docs/superpowers/plans/` 안의 2026-04 ~ 2026-05-03 문서
4. **v0.8.1 spec** (`docs/superpowers/specs/2026-05-05-parser-mcp-tool-result-fix-design.md`)
5. **v0.9.0 spec** (`docs/superpowers/specs/2026-05-05-localhost-http-server-design.md`)
6. **구현 디렉터리** (`/Users/brody/Desktop/token-tracker/`) — git repo, 370 tests, v0.9.0 태그

사용자의 글로벌 CLAUDE.md 규칙 (한글 응답, 숫자 선택지, 승인 기반 진행) 은 여전히 유효.

---

## 5. 다음 작업 후보 (우선순위 순)

### A. (NEW) cache 디렉터리 정리 / 자동 sync 흐름
- 현재 cache 디렉터리명이 첫 install 시점 버전으로 굳음 (이전엔 `0.6.0/` 디렉터리에 v0.7.0 plugin.json). 이번 reinstall 로 새 `0.9.0/` 디렉터리 생성됐지만 옛 `0.6.0/`, `0.1.0/` 도 그대로 남음.
- 또 코드 변경 후 검증 흐름이 아직 수동: cache 의 파일 수정 (cp) 또는 plugin 재설치.
- 후보 작업:
  - 옛 cache 디렉터리 정리 스크립트 또는 자동 마이그레이션
  - 작업 디렉터리 → cache 동기화 헬퍼 (`scripts/sync-cache.sh` 등)
  - 또는 development mode (cache 가 작업 디렉터리 symlink 가리키게)
- 우선순위: 중간. 사용자가 다른 plugin 변경할 때마다 같은 마찰 발생.

### B. CHANGELOG.md 도입 (선택)
- 현재 release 흐름이 핸드오프 doc 으로 갈음. CHANGELOG.md 표준 형식이 git tag 별 변경 추적에 더 깔끔.
- 우선순위: 낮음. 핸드오프 doc 으로 충분히 작동 중.

### C. pricing 데이터/코드 분리 (`lib/pricing_data.json`)
- v0.7.0 final review 때 follow-up 으로 미룬 항목 (spec §15).
- 단가 변경마다 코드 PR + schema bump 사이클 → 1줄 data diff.
- 우선순위: 중간. 단가 변경 빈도에 따라.

### D. 다른 모델 단가 추가 (Opus 4.5 / 4.6 / Sonnet 4.5 등)
- 현재 PRICING dict 에 Opus 4.7, Sonnet 4.6, Haiku 4.5 만 있음.
- 사용자가 다른 모델 dispatch 시 silent $0 → stderr 경고 (v0.7.0 안전장치).
- 우선순위: 사용자가 그 모델 사용 시점.

### E. context bloat 분석 시각화
- 사용자 의도: turn N 의 input_tokens 가 N-1 보다 갑자기 큰 시점 + 그 직전 tool_result 크기 비교 = 어떤 도구 응답이 context 를 부풀렸는지 탐색.
- 현재 데이터 (`summary.turns`, `transcript_entries`) 만으로 가능.
- 우선순위: 큰 작업, v0.10.0+ 후보.

### F. DB 도입 (history.jsonl → SQLite)
- v0.9.0 brainstorm 때 사용자 제안. 현재 jsonl 잘 작동 중이라 보류.
- 트리거: 세션 수천 개 누적, 통계 기능, 다중 머신 sync 필요.
- 우선순위: 낮음, 트리거 발생 후.

### G. 200k+ tier 모니터링 (v0.7.0 핸드오프 그대로)
- Opus 4.7 은 1M context 까지 standard pricing.
- 우선순위: 0 (현재 가치 없음).

---

## 6. 사용자 성향 메모 (v0.8.0 핸드오프 doc + 이번 세션 추가분)

기존 (v0.8.0 핸드오프 doc 그대로):
- **한글 응답**, **숫자 선택지**, **선택지 + 추천안 + 이유** 제시 선호.
- 동작·설계 결정은 하나씩 나눠서 확인. 오타 같은 사소한 건 묶어도 됨.
- `git commit`은 사용자 명시 요청 전엔 하지 않음.
- **PR 머지는 반드시 사용자 명시 승인 후만** 실행.
- 서버 실행은 직접 하지 말고 사용자에게 요청.
- 승인 없는 과잉 작업 금지. 루프/토큰 낭비 지양.
- 막히거나 디버깅이 3회 이상 실패하면 즉시 사용자에게 상황 공유 + 도움 요청.
- Auto mode 전환 시: 적극적으로 진행하되 destructive 액션은 여전히 확인.

이번 세션 추가:
- **빠른 진행 선호** — code review 결과 보고 후 추천 액션 명시하면 거의 그대로 "그래 진행" 식으로 빠르게 승인. 굳이 다단계 확인 안 해도 됨.
- **"버전 굳이 나누지 말고"** — 작은 fix (수십 줄 미만) 는 진행 중인 PR 에 끼워 넣기 선호. 단, 큰 관심사 변화는 분리.
- **시각적 디버깅 빨간색 진단** — UI 변경 시 색이 안 바뀐 것처럼 보이면 임시로 빨간색 (#FF0000) 찍어 어느 selector 가 적용되는지 확인. 사용자가 직접 제안한 패턴이라 효과적.
- **iOS 개발자 관점 설명 선호** — daemon 같은 서버 용어는 비유로 풀어 설명 (예: "iOS 백그라운드 앱 같은 거"). 짧게 핵심만.

---

## 7. v0.9.0 작업 흐름 메모 (다음 세션 학습용)

### 7.1 Plugin 재설치 흐름 (cache 갱신)

v0.8.0 출시 후 사용자가 plugin reinstall 한번도 안 했었음 → cache 가 v0.7.0 시점에 머물러 있었고 v0.8.0 의 token-history skill 도 cache 에 없었음. 다음 세션에서 코드 변경 후 동작 확인 흐름:

```
/plugin uninstall token-tracker
/plugin install token-tracker@token-tracker-local
/reload-plugins
```

→ 새 cache 디렉터리 (현재 active 버전명) 가 생성되며 옛 dir 은 그대로 남음.

### 7.2 CSS 만 변경 시 빠른 반영

- daemon 이 매 요청마다 `style.css` 를 inline 으로 HTML 에 박음 (`history_renderer.py:233` 의 `_read(_CSS_PATH)`)
- `style.css` 만 변경했으면:
  ```
  cp <작업 디렉터리>/style.css <cache 디렉터리>/style.css
  ```
  + 브라우저 cmd+R 새로고침 = 즉시 반영
- daemon 재시작 / plugin 재설치 불필요

### 7.3 lib `.py` 변경 시

- daemon code (server_daemon.py / http_server.py / history_renderer.py 등) 변경 시 **daemon 재시작 필요**:
  ```
  /token-tracker:token-history-stop
  ```
  그리고 cache 의 파일도 갱신. 가장 안전한 방법은 plugin reinstall + reload-plugins.

### 7.4 subagent-driven-development 흐름

- task 마다: implementer (sonnet) → spec reviewer (sonnet) → code quality reviewer (general-purpose, sonnet)
- review 결과 보고 → 사용자가 추천 따라 빠르게 승인 → fix → 다음 task
- 한 번도 BLOCKED / NEEDS_CONTEXT 없이 끝남
- v0.9.0 Task 2 에서 CRITICAL 1건 (HTTPException 미포착) 발견 — code quality review 가 catching 잘 동작

### 7.5 시각적 디자인 결정 시 playwright

- file:// 접근은 차단 → v0.9.0 daemon 띄우면 `http://127.0.0.1:8765/{sid}` 로 직접 navigate 가능 (v0.9.0 의 부수 효과)
- 또는 v0.8.x 에선 임시 HTTP 서버 (`python3 -m http.server 8765`) + cleanup
- 다크모드 토글 / row click 등 인터랙션 evaluate 로 처리

---

## 8. 중요 경로·태그 참조

| 항목 | 값 |
|---|---|
| 플러그인 repo (로컬) | `/Users/brody/Desktop/token-tracker/` |
| 플러그인 repo (GitHub) | `https://github.com/brody424/TokenTracker` |
| marketplace manifest | `.claude-plugin/marketplace.json` (repo 루트) |
| plugin 디렉터리 | `plugins/token-tracker/` |
| Claude Code 설치 경로 (cache, 현재 active) | `~/.claude/plugins/cache/token-tracker-local/token-tracker/0.9.0/` |
| 옛 cache 디렉터리 (정리 후보) | `~/.claude/plugins/cache/token-tracker-local/token-tracker/0.6.0/`, `0.1.0/` |
| state 디렉터리 | `~/.claude/plugins/token-tracker/state/` |
| history JSONL | `~/.claude/plugins/token-tracker/state/{session_id}/history.jsonl` |
| 에러 로그 (hook) | `~/.claude/plugins/token-tracker/log/error.log` |
| daemon stderr 로그 | `<plugin_root>/log/server_daemon.stderr.log` (cache 위치) |
| 최신 태그 | **v0.9.0** (HTTP daemon) |
| 주요 태그 | v0.6.x ~ v0.7.0 (pricing v2), v0.8.0 (/token-history), v0.8.1 (parser fix + UI 회귀), **v0.9.0** (HTTP daemon) |
| 테스트 수 | **370 passing** (v0.9.0 머지 후) |
| 테스트 실행 | `./venv/bin/pytest plugins/token-tracker/tests -q` (repo 루트 기준) |
| v0.9.0 PR | https://github.com/brody424/TokenTracker/pull/5 (MERGED 2026-05-05) |
| v0.8.1 PR | https://github.com/brody424/TokenTracker/pull/4 (MERGED 2026-05-05) |
| v0.8.0 PR | https://github.com/brody424/TokenTracker/pull/2 (MERGED 2026-05-05) |
| v0.7.0 PR | https://github.com/brody424/TokenTracker/pull/1 (MERGED 2026-05-03) |
| Claude Design 프로젝트 | https://claude.ai/design/p/019df2f7-ddb2-7aab-a4db-82305082fbfc |

---

## 9. 다음 세션 시작 시 권장 워크플로

1. 이 핸드오프 + (선택) v0.8.0 핸드오프 읽어서 컨텍스트 정리.
2. 사용자가 방향 잡아주면 (위 5절 A~G 중 또는 새 아이디어), 해당 작업에 대한 **brainstorm → spec → plan** 흐름:
   - `superpowers:brainstorming` skill — 옵션 제시 + 사용자 결정 받아 design 섹션별 승인
   - 결정 사항 → `docs/superpowers/specs/YYYY-MM-DD-...md` 에 spec 저장 + commit
   - `superpowers:writing-plans` skill — implementation plan (`docs/superpowers/plans/...`)
3. plan 승인 → `superpowers:subagent-driven-development` skill 로 실행 (task 마다 spec + code quality 두 단계 review).
4. v0.7.0 ~ v0.9.0 의 함정·교훈 (코드리뷰 fix 패턴, cache 동기화 흐름) 참고.

사용자가 "다음 작업 바로 진행" 이라고 하면 **A (cache 디렉터리 정리)** 또는 **C (pricing 분리)** 부터 추천하고 확인받아라. 기능 추가보다 정리 작업이 누적된 상태.
