# token-tracker 인수인계 — 2026-05-05

> 다음 세션의 Claude 가 바로 이어 작업할 수 있게 정리된 핸드오프 문서. 이 파일을 먼저 읽고, 참조 파일 확인 후 사용자의 다음 지시를 따른다.

---

## 1. 한 줄 요약

token-tracker = Claude Code 플러그인. **현재 v0.8.0** — `/token-history` skill 출시:
- 세션별 prompt 히스토리를 다크 우선 web dashboard 로 시각화
- 한 prompt 안의 N개 model 호출(turn) 을 모두 카드 리스트로 표시 (사용자 `/token-detail` 표 컬럼과 1:1 매칭)
- 다크/라이트/auto 3-way 테마 토글, oklch 토큰 + cost bar + cache hit dot
- 327 tests passing (v0.7.0 baseline 277 + 신규 50건)

---

## 2. v0.8.0 변경점

### 2.1 신규 skill `/token-history`
- 호출 시 세션 HTML 생성 → 브라우저 자동 오픈. URL 출력
- 데이터 source: `~/.claude/plugins/token-tracker/state/{session_id}/history.jsonl`
- skill 디렉터리: `plugins/token-tracker/skills/token-history/`
  - `SKILL.md`, `scripts/history.py`, `templates/history.html.tmpl`, `static/style.css`, `static/app.js`

### 2.2 hooks 갱신
- `on_user_prompt`: real prompt 에 `prompt_id` + `prompt_text` state 추가
- `on_stop`: history.jsonl entry append/update (try/except 격리)

### 2.3 history_store (신규 모듈)
- JSONL append + schema versioning + atomic write
- 같은 `prompt_id` 면 마지막 행 in-place rewrite (Stop 여러 번 발화해도 한 row)
- `load_session_history` / `load_all_sessions_history` (multi-session glob)

### 2.4 transcript parser 확장
- `parse_transcript_for_history`: thinking / assistant_text / tool_call / tool_result 4종 추출, ts 기준 정렬

### 2.5 web UI 디자인 (Claude Design 으로 받음)
- 다크 우선 (oklch + light/auto/dark 토글)
- 정렬·검색·필터·탭 전환·expand 모두 vanilla JS
- expand 영역: turn-by-turn 카드 리스트
  - 카드 헤더: # / model / tools / request 미리보기 / cost / input / cc / cr / output / elapsed
  - 카드 펼침 4섹션: THINKING / ASSISTANT / TOOL CALL / TOOL RESULT (없는 섹션 자동 생략)
  - 모두 펼치기/접기 단축 버튼
  - request 미리보기: tool_call 의 첫 input key/value 또는 tool 없는 turn 의 assistant_text 첫 줄

### 2.6 통합 시 잡은 회귀 가드 (이번 사이클에서 발견·수정)
- **JSON.parse 깨짐**: `<!--` → `<\!--` 옛 escape 가 invalid JSON escape 생성. fix: `<` 전체를 `<` unicode-escape.
- **placeholder collision**: chained `str.replace` 가 직전 페이로드 안의 placeholder 토큰을 재치환. fix: 단일 `re.sub` 단일 패스.
- 회귀 가드 테스트 모두 영구 보존 (test_history_renderer.py).

---

## 3. v0.7.x 와의 호환성

- 가격 데이터(`PRICING` dict) **변경 없음**. v0.7.0 핸드오프의 단가표 그대로 유효.
- 다른 도구(statusline / ccusage) 와의 차이도 동일 (token-tracker 가 1h tier 인식해서 가장 정확).

---

## 4. 파일 구조 / 참조 순서

다음 세션에서는 아래 순서로 읽어라.

1. **이 문서** (`docs/handoff/2026-05-05-token-tracker-next-steps.md`) — 현재 상황, 다음 작업 후보
2. **이전 핸드오프** (`docs/handoff/2026-05-03-token-tracker-next-steps.md`) — v0.7.0 까지 컨텍스트
3. **v0.8.0 spec** (`docs/superpowers/specs/2026-05-03-token-history-design.md`)
4. **v0.8.0 plan** (`docs/superpowers/plans/2026-05-03-token-history.md`)
5. **구현 디렉터리** (`/Users/brody/Desktop/token-tracker/`) — git repo, 327 tests, v0.8.0 태그

사용자의 글로벌 CLAUDE.md 규칙(한글 응답, 숫자 선택지, 승인 기반 진행) 은 여전히 유효.

---

## 5. 다음 작업 후보 (우선순위 순)

### A. parser 의 MCP `tool_result.content` 누락 fix ⭐ 권장
- 일부 MCP 도구 (예: ToolSearch) 의 `tool_result.content` 가 raw 데이터 단계에서 빈 문자열로 저장됨.
- `/token-history` 의 turn 카드 expand 시 TOOL RESULT 섹션이 비어 보이는 원인.
- `parser.py` 의 `parse_tool_result` 가 `content` 추출하는 로직 점검 필요. content block 이 list-of-blocks 인 경우 (text/image 혼합) 처리 누락 가능성.
- 이번 PR 범위 밖이라 v0.8.x 핫픽스로 빼둔 항목.

### B. localhost HTTP 서버 도입
- 현재 `/token-history` 는 `file://` 로 브라우저 오픈 → fetch / module import / CORS 의존 기능 사용 못 함.
- 작업 전 사용자와 합의된 lifecycle: **idempotent daemon** (호출 시 살아있으면 재사용, 없으면 띄움) + 고정 포트 8765 + `127.0.0.1` 만 bind.
- `tt-stop` 같은 보조 명령 또는 별도 stop skill 필요.
- v0.8.0 출시 직전 합의했으나 시간 관계로 별도 PR 로 미룬 항목.

### C. pricing 데이터/코드 분리 (`lib/pricing_data.json`)
- v0.7.0 final review 때 follow-up 으로 미룬 항목 (spec §15).
- 단가 변경마다 코드 PR + schema bump 사이클 → 1줄 data diff.

### D. 다른 모델 단가 추가 (Opus 4.5 / 4.6 / Sonnet 4.5 등)
- 현재 PRICING dict 에 Opus 4.7, Sonnet 4.6, Haiku 4.5 만 있음.
- 사용자가 다른 모델 dispatch 시 silent $0 → stderr 경고 emit (v0.7.0 안전장치). 그때 추가.

### E. context bloat 분석 시각화
- 사용자 의도: turn N 의 input_tokens 가 N-1 보다 갑자기 큰 시점 + 그 직전 tool_result 크기 비교 = 어떤 도구 응답이 context 를 부풀렸는지 탐색.
- 현재 데이터(`summary.turns`, `transcript_entries`) 만으로 가능. raw HTTP payload 는 못 받음 (사용자 합의: ROI 낮아서 mitmproxy 경로 안 감).
- v0.9.0 또는 그 이후 후보.

### F. 200k+ tier 모니터링 (v0.7.0 핸드오프 그대로 유효)
- Opus 4.7 은 1M context 까지 standard pricing. 향후 4.x 모델에 200k+ tier 도입되면 PRICING 키 + parser + summary_store v4 bump 필요. 현재 follow-up 가치 0.

---

## 6. 사용자 성향 메모

- **한글 응답**, **숫자 선택지**, **선택지 + 추천안 + 이유** 제시 선호.
- 동작·설계 결정은 하나씩 나눠서 확인. 오타 같은 사소한 건 묶어도 됨.
- `git commit`은 사용자 명시 요청 전엔 하지 않음.
- **PR 머지는 반드시 사용자 명시 승인 후만** 실행.
- 서버 실행(`npm start` 등) 은 직접 하지 말고 사용자에게 요청.
- 승인 없는 과잉 작업 금지. 루프/토큰 낭비 지양.
- 막히거나 디버깅이 3회 이상 실패하면 즉시 사용자에게 상황 공유 + 도움 요청.
- Auto mode 전환 시: 적극적으로 진행하되 destructive 액션은 여전히 확인.

---

## 7. v0.8.0 작업 흐름 메모 (다음 세션 학습용)

### 7.1 Claude Design 으로 디자인 외주
- 사용자가 디자인 시안을 Claude Design 에서 직접 만들기로 선택 (claude.ai/design).
- token-tracker 프로젝트(`019df2f7-ddb2-7aab-a4db-82305082fbfc`) 안에 `token-history.html` (v1) + `token-history v2.html` (turn 카드 expand) 두 파일.
- Playwright 로 디자인 페이지 자동화 — prompt 입력 + Send + Download 카드 click 으로 standalone HTML 받아옴.
- standalone 은 Claude Design 의 wrapper 포맷. 내부의 `<script type="__bundler/template">` 안 JSON-stringified 콘텐츠가 진짜 HTML. wrapper 빼고 template 만 우리 templates/static 에 통합.

### 7.2 검증
- 자동화: `./venv/bin/pytest plugins/token-tracker/tests -q` (327 통과)
- 수동: localhost 임시 서버 (`python3 -m http.server 8765`) + Playwright 로 인터랙션 (정렬·검색·필터·expand·테마 토글·turn 카드 토글·모두 펼치기/접기)
- file:// 로는 Playwright 가 차단 → 임시 HTTP 서버 필수

### 7.3 디자인 i18n 처리
- 사용자 결정 (옵션 1): 디자인 i18n 블록을 우리 `strings.*.json` 와 분리해서 `templates/history.html.tmpl` 에 그대로 인라인. 디자인 새로 받을 때 i18n 블록도 함께 옴 → 마찰 적음.

---

## 8. 중요 경로·태그 참조

| 항목 | 값 |
|---|---|
| 플러그인 repo (로컬) | `/Users/brody/Desktop/token-tracker/` |
| 플러그인 repo (GitHub) | `https://github.com/brody424/TokenTracker` |
| marketplace manifest | `.claude-plugin/marketplace.json` (repo 루트) |
| plugin 디렉터리 | `plugins/token-tracker/` |
| Claude Code 설치 경로 (cache) | `~/.claude/plugins/cache/token-tracker-local/token-tracker/0.6.0/` (디렉터리명 0.6.0 이지만 plugin.json 은 v0.8.0) |
| state 디렉터리 | `~/.claude/plugins/token-tracker/state/` |
| history JSONL | `~/.claude/plugins/token-tracker/state/{session_id}/history.jsonl` |
| 에러 로그 | `~/.claude/plugins/token-tracker/log/error.log` |
| 최신 태그 | **v0.8.0** (/token-history skill 출시) |
| 주요 태그 | v0.1.0-mvp ~ v0.6.4, v0.7.0 (pricing 정확도 v2), **v0.8.0** (/token-history) |
| 테스트 수 | **327 passing** (v0.8.0 머지 후) |
| 테스트 실행 | `./venv/bin/pytest plugins/token-tracker/tests -q` (repo 루트 기준) |
| v0.8.0 PR | https://github.com/brody424/TokenTracker/pull/2 (MERGED 2026-05-05) |
| v0.7.0 PR | https://github.com/brody424/TokenTracker/pull/1 (MERGED 2026-05-03) |
| Claude Design 프로젝트 | https://claude.ai/design/p/019df2f7-ddb2-7aab-a4db-82305082fbfc |

---

## 9. 다음 세션 시작 시 권장 워크플로

1. 이 핸드오프 + 이전 핸드오프 (`2026-05-03-...md`) 읽어서 컨텍스트 정리.
2. 사용자가 방향 잡아주면 (위 5절 A~F 중), 해당 작업에 대한 **plan 문서**를 `superpowers:writing-plans` skill 로 만든다.
3. plan 승인 후 `subagent-driven-development` skill 로 실행.
4. v0.7.0 / v0.8.0 의 함정·교훈을 참고해 같은 함정에 빠지지 않게 한다.

사용자가 "다음 작업 바로 진행" 이라고 하면 **A (`parser MCP tool_result fix`)** 부터 제안하고 확인받아라.
