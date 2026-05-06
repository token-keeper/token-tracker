# token-tracker 인수인계 — 2026-05-06 (v0.11.0 alias + 자동 갱신)

> 다음 세션의 Claude 가 바로 이어 작업할 수 있게 정리된 핸드오프. 직전 핸드오프 (`2026-05-06-token-tracker-next-steps-v0.10.0.md`) 와 함께 읽는다.

---

## 1. 한 줄 요약

token-tracker = Claude Code 플러그인. **현재 v0.11.0** — short alias 자동 매핑 + SessionStart 7일 주기 자동 갱신 인프라 추가.
- alias 자동 탐지: `Agent(model="sonnet")` → `claude-sonnet-{latest}` 정확 단가 청구 (이전 v0.10.0: parent fallback)
- SessionStart hook 자동 fetch: Anthropic 페이지 7일 주기 → `~/.claude/plugins/token-tracker/state/pricing_data.json` 에 write
- 수동 헬퍼: `scripts/update-pricing.sh` 즉시 갱신
- verbose 표 short name fix (1줄 회귀)
- **431 tests passing** (v0.10.0 baseline 387 + 신규 44)

---

## 2. 이번 세션 작업 (PR #8)

### 2.1 작업 흐름
1. v0.10.0 핸드오프의 후보 1번 (모델 short alias) 묶음 선택
2. 사용자 통찰: "verbose on 하면 raw `claude-opus-4-7` 나옴" → display 단축은 이미 구현됨 (`_short_model_name`) 인데 verbose 표 만 누락된 버그 발견
3. "새 모델 출시 시 자동 업데이트" 요구로 SessionStart 자동 fetch 인프라 확장
4. trigger 결정: 매 hook → SessionStart hook 7일 주기 + unknown model 발견 시 안내
5. write 위치 결정: cache (reinstall 영향) / 작업 폴더 (git 더럽힘) 회피 → state override 채택
6. 자동 vs 수동 결정: SessionStart 자동 + scripts/update-pricing.sh 수동 헬퍼 둘 다 (옵션 2)
7. PR 사이즈 결정: 1080줄 (300줄 룰 위반) — 사용자가 한 사이클 묶기 선호로 옵션 2 선택
8. 7-agent 병렬 리뷰 → MAJOR 4건 → **비판적 재검토 후 모두 follow-up** 결정

### 2.2 commit 3개

**1. `feat(pricing)`: alias 자동 탐지 + state override + verbose fix**
- `lib/detail_formatter.py:232` — verbose 표 `turn.model` raw 출력 → `_short_model_name(turn.model)` (sub-row 만 변환되던 비대칭 fix)
- `lib/pricing.py`:
  - `_resolve_alias(short)` — family-prefix latest 자동 탐지. tuple 정렬 (`(4,6) > (4,5) > (4,)`) 으로 별도 매핑 dict 없이 PRICING 만 갱신하면 alias 자동 갱신
  - `_resolve_rates` 분기: exact → alias → prefix
  - `_load_pricing_from(path)` 분리 + state override merge 로직
  - unknown model stderr 메시지에 갱신 안내 추가
- `tests/test_pricing.py` — `_RATE_TIERS` parametrize 통합
- 의도된 동작 변경: alias 회귀 가드 5개 갱신 (parent fallback → latest family rate)
- `marketplace.json` 0.10.0 동기화 (PR #7 누락 fix)

**2. `feat(pricing_fetch)`: Anthropic 페이지 fetch + 단위 테스트**
- `lib/pricing_fetch.py` (NEW) — stdlib only (urllib + re)
- `parse_pricing_html` — markdown table row 정규식 (`(?:[^|]*?)` 로 deprecated link 흡수)
- `fetch_pricing_models` — 모든 예외 silent → None (fail-soft)
- 신규 테스트 22+12개

**3. `feat(hook,scripts)`: SessionStart 자동 갱신 + update-pricing.sh**
- `hooks/on_session_start.py` (NEW) — 7일 stale 검사 + fetch + state write + 새 모델 stderr 안내
- `hooks/hooks.json` — SessionStart event 등록
- `scripts/update-pricing.sh` (NEW) — 즉시 갱신 헬퍼 (timeout 10s, 7일 stale 무시)
- `.gitignore` 에 update-pricing.sh unignore 추가
- 신규 테스트 11개

### 2.3 호환성
- `compute_cost` / `is_known_model` / `effective_billing_model` 시그니처 동일
- `PRICING` dict 형태 그대로 — aggregator / detail_formatter / history_renderer 영향 0
- `history.jsonl` schema 변경 없음
- alias dispatch 시 기존 silent fallback → 정확 단가 (비용 표시 살짝 변할 수 있음, 대부분 감소)

### 2.4 7-agent 코드리뷰 결과 (모두 follow-up)

| 영역 | CRITICAL | MAJOR | MINOR |
|---|---|---|---|
| 아키텍처 | 0 | 2 | 3 |
| 원칙 | 0 | 1 | 2 |
| 중복/복잡도 | 0 | 0 | 1 |
| 사이드이펙트 | 0 | 1 | 3 |
| 보안 | 0 | 0 | 3 |
| 성능 | 0 | 0 | 2 |
| 테스트 커버리지 | 0 | 0 | 3 |

**MAJOR 4건 follow-up 정당성** (스킵 결정):

1. **hook ↔ update-pricing.sh payload 중복** — schema 변경 빈도 매우 낮음 + grep 한 번이면 발견. 다음 schema 변경 시 helper 추출 묶음
2. **state 경로 SSOT (`paths.state_dir()` 헬퍼와 분리)** — `_base_data_dir()` 변경 history 0회. 변경 시점에 grep 으로 잡힘
3. **private symbol cross-layer import (`_PRICING_DATA_PATH`/`_load_pricing_from`)** — 코드베이스 컨벤션 (모든 게 `_` prefix). 실용적 OK
4. **state JSON write 동시성 race** — 7일 stale gate + fail-soft fallback 안전망 → 실제 영향 0. 다중 세션 사용 늘어나서 실증 발견 시 atomic write 추가

---

## 3. 새 인프라 — pricing 자동 갱신 흐름

### 3.1 데이터 우선순위 (pricing.py `_load_pricing`)
```
1. lib/pricing_data.json (default — repo 의 baseline, 배포 시점 단가)
2. ~/.claude/plugins/token-tracker/state/pricing_data.json (override — 머신별)
   → merge: override 의 row 우선, default 만의 row 도 유지
```

### 3.2 SessionStart hook (자동, 7일 주기)
```
SessionStart 발화
  ↓
state/pricing_meta.json 의 last_fetch 검사
  ↓ (7일 이내면 silent skip)
  ↓ (7일 이상이면)
fetch_pricing_models() — 3초 timeout
  ↓ (None 이면 meta 갱신 안 함, 다음 SessionStart 재시도)
  ↓ (성공)
state/pricing_data.json 에 write + state/pricing_meta.json 갱신
  ↓
새 모델 발견 시 stderr 1회 안내
```

### 3.3 수동 헬퍼 (`scripts/update-pricing.sh`)
- 7일 stale 무시, 즉시 fetch + state write
- timeout 10초 (사용자 명시 실행이라 길게)
- 실패 시 exit 1 + stderr

### 3.4 fail-soft 안전망
- 네트워크 / HTTP / decode / 파싱 실패 모두 silent → None
- state JSON 손상 → default fallback + stderr 안내
- meta JSON 손상 → stale 로 간주 (강제 fetch)
- hook return code 0 보장 (SessionStart 가 세션 시작 자체 깨면 안 됨)

---

## 4. 다음 작업 후보 (우선순위 순)

### 잔여
- ~~A. cache 디렉터리 정리~~ (해결됨 — dev-mode 토글 + version bump 자가복구)
- ~~C. pricing 데이터 분리~~ (해결됨 — v0.10.0)
- ~~D. legacy 모델 단가~~ (해결됨 — v0.10.0)
- ~~새 후보 1번 (alias)~~ (해결됨 — v0.11.0)
- **E. context bloat 분석 시각화** — 큰 작업, v0.12.0+ 후보. 사용자 평소 원하던 핵심 기능
- B. CHANGELOG.md 도입 — 낮음 (핸드오프 doc 으로 충분)
- F. SQLite 도입 — 보류
- G. 200k+ tier 모니터링 — 가치 0
- H. **MAJOR 4건 follow-up 정리** — `lib/pricing_state.py` (atomic write + helper) + paths SSOT + public API. ~125줄. 우선순위 중하

### 새 후보 (v0.11.0 7-agent 리뷰 잔여 MINOR 중 가치 있는 것)
1. **`pricing_data.json` fetched 날짜 stale 가드** — N개월 이상이면 startup 경고 (자동 fetch 외 백업)
2. **혼합 row 가드 테스트** — `parse_pricing_html` 의 ValueError continue 분기 직접 검증
3. **`urlopen` 응답 크기 상한** — `MAX_BYTES = 2_000_000` (방어적)
4. **`_resolve_alias` `base_only` dead branch 제거** — 현재 `claude-haiku` 같은 base-only 키 없음

---

## 5. 사용자 성향 메모 (이번 세션 추가분)

기존 (v0.10.0 핸드오프 doc 그대로 유효):
- 한글 응답 / 숫자 선택지 / 선택지 + 추천 + 이유 제시
- 빠른 진행, 7-agent 결과 보고 후 추천대로 빠르게 승인
- 작은 follow-up 묶기 선호
- `git commit` / 머지는 명시 승인 후만
- 시각적 디자인 빨간색 진단 (#FF0000)

이번 세션 추가:
- **"곰곰히 생각해봤어?" 비판적 재검토 룰** — 7-agent 리뷰 결과 그대로 추천하지 말고 비판적 재평가. MAJOR 도 실제 위험도 따져 follow-up 가능. blind 따르기 안 됨. (이번 세션에서 4건 모두 follow-up 정당화)
- **trigger 분리 잘 인지** — 자동 fetch 시 매 hook vs SessionStart vs unknown model dispatch 등 적절한 trigger 명확히 구분. fetch 자체의 위험 (HTML 형식 / race / 권한) 짚기 좋아함
- **결정 옵션 명시 선호** — 옵션 A/B/C/D 형식 + 추천 + 근거. 사용자가 "2번 ㄱㄱ" 패턴으로 빠르게 승인
- **PR 사이즈 룰 위반 합의 가능** — 사이즈 명시 + 사용자 승인이면 한 PR 으로 묶기 OK (이번 1080줄)
- **자동화 적극적** — 자동 갱신 / hook 자동 발화 거부감 없음. 단 자동 디스크 쓰기 위치 (cache vs state vs source) 는 권한/git 영향 명확히 짚기

---

## 6. 작업 흐름 메모

### 6.1 Plan + brainstorm 생략 패턴
이번 작업도 v0.10.0 처럼 **brainstorm 생략 + plan 짧게 → 구현**. 단 중간에 사용자가 의문 제기하면 즉시 옵션 명시 제안 흐름 유효:
- "fetch 오래 안 걸리잖아?" → latency 외 위험 4가지 짚고 옵션 1/2/절충안 제시
- "Write 위치는?" → cache vs source vs state 권한/git 영향 짚고 추천
- "MAJOR 4건 다 fix?" → 비판적 재검토 후 옵션 A/B/C/D 제시

### 6.2 7-agent 병렬 리뷰 패턴 (재확인)
- 영역별 prompt 명확히 분리 + 결과 형식 통일 (`[CRITICAL] N건 | [MAJOR] N건 | [MINOR] N건`)
- `run_in_background: true` 로 7개 병렬 발화. 완료 알림 받으며 N/7 카운팅
- 결과 보고 후 **비판적 재평가** — MAJOR 등급도 trigger 빈도 / 잔여 위험 / fix 비용 trade-off
- fix vs follow-up 결정 시 사용자에게 옵션 제시 (모두 fix / 일부 fix / 모두 skip)

### 6.3 의도된 동작 변경 회귀 가드
이번 PR 의 alias 동작 변경 (silent fallback → 정확 단가) 처럼 **회귀 가드 의도가 바뀐 테스트** 는 갱신 시 새 의도 명시:
- 옛 가드: "silent $0 회귀 막음 (parent fallback)"
- 신 가드: "alias 자동 탐지로 정확 family rate 청구"
- 두 의도 모두 회귀 가능 — 하나만 박으면 다른 회귀 silent 통과

### 6.4 PR 분리 vs 묶기
- 룰: 300줄 / 한 관심사 / 한 PR
- 묶기 정당화: 사용자 명시 합의 + 사이즈 사전 보고 + 한 사이클 가치 명확
- 분리 추천: 다른 관심사 / 다음 세션 컨텍스트 유실 위험

### 6.5 SessionStart hook 패턴
- Claude Code 의 SessionStart event 사용 가능 — `hooks.json` 의 `"SessionStart"` 키
- `_setup_sys_path()` + `_log_error()` 패턴은 다른 hook 과 동일
- stdin drain 필수 (사용 안 해도)
- 어떤 예외도 propagate 안 하게 광범위 catch + log_dir 격리

---

## 7. 중요 경로·태그 참조

| 항목 | 값 |
|---|---|
| 플러그인 repo (로컬) | `/Users/brody/Desktop/token-tracker/` |
| 플러그인 repo (GitHub) | `https://github.com/brody424/TokenTracker` |
| marketplace manifest | `.claude-plugin/marketplace.json` (repo 루트) |
| plugin 디렉터리 | `plugins/token-tracker/` |
| pricing 데이터 (default) | `plugins/token-tracker/lib/pricing_data.json` |
| pricing 데이터 (state override) | `~/.claude/plugins/token-tracker/state/pricing_data.json` |
| pricing 갱신 meta | `~/.claude/plugins/token-tracker/state/pricing_meta.json` |
| pricing fetch 모듈 | `plugins/token-tracker/lib/pricing_fetch.py` |
| SessionStart hook | `plugins/token-tracker/hooks/on_session_start.py` |
| Claude Code 설치 경로 (cache, active) | `~/.claude/plugins/cache/token-tracker-local/token-tracker/0.11.0/` (PR #8 머지 + reinstall 후) |
| 옛 cache 디렉터리 | `0.10.0/`, `0.9.0/` (이전 active, version bump 자가복구로 정리됨) |
| state 디렉터리 | `~/.claude/plugins/token-tracker/state/` |
| history JSONL | `~/.claude/plugins/token-tracker/state/{session_id}/history.jsonl` |
| 에러 로그 (hook) | `~/.claude/plugins/token-tracker/log/error.log` |
| daemon stderr 로그 | `<plugin_root>/log/server_daemon.stderr.log` (cache 위치) |
| dev-mode 토글 | `./scripts/dev-mode.sh on / off / status` |
| pricing 수동 갱신 | `./scripts/update-pricing.sh` |
| 최신 태그 | **v0.11.0** (alias + 자동 갱신) |
| 주요 PR | #1 (v0.7.0 pricing v2), #2 (v0.8.0 /token-history), #4 (v0.8.1 parser fix), #5 (v0.9.0 HTTP daemon), #6 (dev-mode 토글), #7 (v0.10.0 pricing 분리), **#8 (v0.11.0 alias + 자동 갱신)** |
| 테스트 수 | **431 passing** (PR #8 머지 후) |
| 테스트 실행 | `./venv/bin/pytest plugins/token-tracker/tests -q` (repo 루트 기준) |
| Anthropic pricing 페이지 | https://platform.claude.com/docs/en/about-claude/pricing |
| Claude Design 프로젝트 | https://claude.ai/design/p/019df2f7-ddb2-7aab-a4db-82305082fbfc |

---

## 8. 다음 세션 시작 시 권장 워크플로

1. 이 핸드오프 + (선택) v0.10.0 핸드오프 읽어서 컨텍스트 정리
2. 사용자가 방향 잡아주면 (위 4절 후보 또는 새 아이디어), 작업 규모에 따라 흐름 분기:
   - **작은 작업** (refactor / data / 분기 추가): plan 짧게 → 구현 → 7-agent 리뷰 → PR
   - **중간 작업**: brainstorm 1~2 옵션 → 옵션 비교 → 사용자 결정 → spec 안 쓰고 plan → 구현 → 리뷰 → PR
   - **큰 작업** (E. context bloat 같은): brainstorm → spec → plan → subagent-driven-development → 리뷰 → PR
3. 7-agent 리뷰 결과는 **비판적 재검토** — MAJOR 도 trigger 빈도 / 잔여 위험 / fix 비용 trade-off 따져 follow-up 가능
4. PR 생성 후 검증 안내: `/plugin uninstall` + `/plugin install` + 다음 prompt 검증
5. 머지 명시 승인 후 → main pull → 다음 작업

사용자가 "다음 작업 바로 진행" 이라고 하면:
- **E (context bloat 시각화)** 가 가장 큰 가치 후보 — brainstorm 부터 시작 (사용자가 평소 원하던 핵심)
- 또는 **H (MAJOR 4건 follow-up 정리)** — 정리 작업, ~125줄. 후순위
- 새 후보 (stale 가드 / 응답 크기 상한 등) 는 작은 작업, 한 PR 안에 묶기 가능

기능 / UX 작업 비중이 정리 작업보다 커진 시점. v0.12.0 부터는 큰 기능 작업이 자연스러움.
