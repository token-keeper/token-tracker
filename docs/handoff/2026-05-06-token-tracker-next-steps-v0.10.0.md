# token-tracker 인수인계 — 2026-05-06 (v0.10.0 pricing 분리)

> 다음 세션의 Claude 가 바로 이어 작업할 수 있게 정리된 핸드오프. 직전 핸드오프 (`2026-05-05-token-tracker-next-steps-v0.9.0.md`) 와 함께 읽는다.

---

## 1. 한 줄 요약

token-tracker = Claude Code 플러그인. **현재 v0.10.0** — v0.9.0 (HTTP daemon) 후 dev-mode 토글 (PR #6) + pricing 분리 (PR #7) 묶어서 minor bump.
- PR #7: `lib/pricing.py` 의 PRICING dict → `lib/pricing_data.json` 으로 분리 + legacy 모델 7종 단가 추가
- 등록 모델 3 → 10 (Opus 4.0/4.1/4.5/4.6/4.7, Sonnet 4.0/4.5/4.6, Haiku 3.5/4.5)
- **387 tests passing** (v0.9.0 baseline 370 + dev-mode PR 9 + 이번 PR 8)
- 단가 변경 시 사이클: 코드 PR + schema bump → 1줄 data diff

---

## 2. 이번 세션 작업 (PR #7)

### 2.1 작업 흐름
1. v0.9.0 핸드오프의 후보 C (pricing 분리) + D (다른 모델 단가) 묶음 선택
2. brainstorm 생략 + plan 짧게 → 구현 (사용자 합의: 단순 refactor + data 작업)
3. Anthropic 공식 pricing 페이지 fetch → 모든 모델 단가 확인 (`fetched=2026-05-06`)
4. 7-agent 병렬 코드리뷰 → CRITICAL 0 / MAJOR 3 / MINOR 13
5. MAJOR 3 모두 fix (parametrize 통합 + 손상 JSON 분기 가드 + isinstance + 메시지/docstring 정돈)
6. push + PR 생성

### 2.2 commit 2개
- **commit 1 — `refactor(pricing)`**: PRICING dict → `lib/pricing_data.json` 분리. import time 1회 `_load_pricing()` 호출. fail-fast 정책 (파일 없음/JSON 파싱은 자연 전파, top-level/models 형태 오류는 케이스별 RuntimeError).
- **commit 2 — `feat(pricing)`**: legacy 7종 추가 (Opus 4.0/4.1/4.5/4.6, Sonnet 4.0/4.5, Haiku 3.5). 테스트 — 모델별 단가 가드 5개 → `_RATE_TIERS` + `pytest.parametrize` 1개로 통합. 손상 JSON 6 분기 가드 (top-level/models 키/dict 아님/빈/파싱/파일 없음). Opus 4.0 prefix-match 회귀 가드 (4.x 가 4.0 단가로 잘못 매치 방지).

### 2.3 7-agent 코드리뷰 결과
| 영역 | CRITICAL | MAJOR | MINOR |
|---|---|---|---|
| 아키텍처 | 0 | 0 | 2 (lru_cache 검토 / 메타데이터 dead) |
| 원칙 | 0 | 1 | 3 |
| 중복/복잡도 | 0 | 1 | 3 |
| 사이드이펙트/에러 | 0 | 0 | 2 |
| 보안 | 0 | 0 | 1 |
| 성능 | 0 | 0 | 0 |
| 테스트 커버리지 | 0 | 1 | 3 |

MAJOR (실제 2개 = legacy 가드 DRY + 손상 JSON 분기 미커버) 모두 fix. MINOR 13건은 가치 낮아 스킵.

### 2.4 호환성
- `compute_cost` / `is_known_model` / `effective_billing_model` 시그니처 동일
- `PRICING` dict 형태 유지 (`dict[str, dict[str, float]]`) — aggregator / detail_formatter / history_renderer 영향 0
- `history.jsonl` schema 변경 없음. `SUPPORTED_SCHEMA_VERSIONS` bump 안 함
- deprecated 모델 (Sonnet 3.7 / Opus 3 / Haiku 3) 은 dispatch 가능성 매우 낮아 제외, 추후 row 1줄로 추가 가능

---

## 3. 파일 구조 (PR #7 추가/변경)

| 파일 | 역할 |
|---|---|
| `plugins/token-tracker/lib/pricing_data.json` (NEW) | 단가 표 + fetched 날짜 + source URL + notes |
| `plugins/token-tracker/lib/pricing.py` | `_load_pricing()` (import time) + 기존 함수 시그니처 유지 |
| `plugins/token-tracker/tests/test_pricing.py` | 36 테스트 (v0.9.0 의 19 → +17) |

`lib/pricing_data.json` 스키마:
```json
{
  "fetched": "2026-05-06",
  "source": "https://platform.claude.com/docs/en/about-claude/pricing",
  "notes": "...",
  "models": {
    "claude-opus-4-7": { "input": 5.0, "output": 25.0, "cache_creation_5m": 6.25, "cache_creation_1h": 10.0, "cache_read": 0.50 },
    ...
  }
}
```

`fetched` / `source` / `notes` 는 현재 코드에서 참조 안 함 (사람용 메타데이터). 향후 stale 가드 (fetched N개월 이상이면 startup 경고) 같은 활용 여지 있음.

---

## 4. 다음 작업 후보 (우선순위 순)

v0.9.0 핸드오프의 후보 갱신:

### A. cache 디렉터리 정리 — **해결됨**
- dev-mode 토글 (PR #6) 로 작업 폴더 → cache 자동 sync 흐름 확보
- 옛 cache 디렉터리 (`0.6.0/`, `0.1.0/`) 도 이미 정리됨, 현재 `0.9.0/` 만 남음

### C. pricing 데이터 분리 — **해결됨 (이번 PR)**

### D. 다른 모델 단가 추가 — **해결됨 (이번 PR)**
- Opus 4.0/4.1/4.5/4.6, Sonnet 4.0/4.5, Haiku 3.5 추가
- deprecated (Sonnet 3.7 / Opus 3 / Haiku 3) 만 잔여, 필요 시 row 1줄

### E. context bloat 분석 시각화 — **잔여, 큰 작업**
- 사용자 의도: turn N 의 input_tokens 가 N-1 보다 갑자기 큰 시점 + 그 직전 tool_result 크기 비교 = 어떤 도구 응답이 context 를 부풀렸는지 탐색
- 현재 데이터 (`summary.turns`, `transcript_entries`) 만으로 가능
- v0.10.0 후보. brainstorm → spec → plan 흐름 필수

### B. CHANGELOG.md 도입 — **낮음**
- 핸드오프 doc 으로 충분히 작동 중

### F. SQLite 도입 — **보류**
- 트리거 (세션 수천 개 / 통계 / 다중 머신 sync) 발생 후

### G. 200k+ tier 모니터링 — **가치 0**
- Opus 4.7 은 1M context 까지 standard pricing

### 새 후보
1. **모델 short alias 기능** — `Agent(model="sonnet")` 같은 short alias 가 silent $0 → 부모 단가 fallback 으로 흘러가는 현 동작 외에, `_resolve_rates` 가 alias 매핑 (sonnet → claude-sonnet-4-6 latest) 으로 정확한 단가 적용. pricing_data.json 에 `aliases: { "sonnet": "claude-sonnet-4-6", "haiku": "claude-haiku-4-5", "opus": "claude-opus-4-7" }` 추가만 하면 됨. 작은 작업.
2. **pricing_data.json fetched 날짜 stale 가드** — `fetched` 가 N개월 이상이면 startup stderr 경고. 7-agent 리뷰의 MINOR 항목. 매우 작은 작업.
3. **history viewer 검색·정렬·필터** — token-history skill 의 web UI 가 현재 단순 timeline. 세션 검색 / 도구별 필터 / 모델별 정렬. 중간 규모.

---

## 5. 사용자 성향 메모 (이번 세션 추가분)

기존 (v0.9.0 핸드오프 doc 그대로 유효):
- 한글 응답 / 숫자 선택지 / 선택지 + 추천 + 이유 제시
- 빠른 진행 — 7-agent 리뷰 결과 보고 후 추천 대로 빠르게 승인
- 작은 follow-up 묶기 선호 (이번 PR 에 doc 도 묶음)
- `git commit` / 머지는 명시 승인 후만
- 막히거나 디버깅 3회 이상 실패 시 즉시 도움 요청
- 시각적 디자인 빨간색 진단 (#FF0000) — `style.css` 임시 마커

이번 세션 추가:
- **brainstorm 생략 합의** — 단순 refactor + data 작업은 plan 짧게 → 구현 흐름. spec 까지 안 써도 됨.
- **묶기 결정 시 사이즈 명확히** — 이번에 1번+2번 묶기 결정할 때 "둘 다 합쳐 300줄 미만" 명시한 게 도움 됐음. 다음번에도 묶기 추천 시 사이즈 근거 같이 제시.
- **"4번 ㄱㄱ" 패턴** — 선택지 번호 + ㄱㄱ 으로 빠른 승인. 사용자가 같은 패턴 쓰면 즉시 진행.
- **PR 생성 후 자동 reinstall 검증** — PR 머지 전이라도 dev-mode OFF 상태에서 `/plugin uninstall` + `/plugin install` 하면 working tree (현재 feature 브랜치) 가 cache 로 복사됨. 사용자가 검증할 수 있게 안내.

---

## 6. 작업 흐름 메모

### 6.1 7-agent 병렬 코드리뷰 패턴
- 영역별 prompt 명확히 분리 + 결과 형식 통일 (`[CRITICAL] N건 | [MAJOR] N건 | [MINOR] N건`) → 통합 리포트가 깔끔
- `run_in_background: true` 로 7개 병렬 발화. 완료 알림 받으며 N/7 카운팅.
- 사용자에게 통합 리포트 보고 시 CRITICAL/MAJOR/MINOR 모두 상세 (위치 + 왜 + 수정 방향) — 사용자 룰 (`rules/code-review.md`)
- MINOR 중 fix 비용 작고 가치 있는 것 (이번엔 `isinstance(raw, dict)` 가드 / docstring 정돈) 은 묶어서 추천

### 6.2 두 commit 분리 패턴
하나의 PR 안에 관심사 둘 (refactor + feat) 일 때:
1. 작업 폴더에 두 변경 모두 적용 (이번엔 JSON 10 모델 + pricing.py + tests)
2. JSON 임시로 3 모델 버전으로 되돌림 → `git add lib/pricing.py lib/pricing_data.json` → commit 1
3. JSON 다시 10 모델 버전으로 복원 → `git add lib/pricing_data.json tests/test_pricing.py` → commit 2

`git add -p` (인터랙티브 금지 룰) 없이 두 commit 으로 나눌 수 있음.

### 6.3 dev-mode OFF 상태 reinstall 검증
- `/plugin uninstall token-tracker@token-tracker-local` → cache `0.9.0/` 디렉터리 제거
- `/plugin install token-tracker@token-tracker-local` → marketplace source (작업 폴더 = 현재 브랜치) 가 새 cache 로 복사
- `/reload-plugins` → hook 재등록
- 다음 prompt 한 번 → 토큰 line 정상 출력 확인 = 검증 완료

PR 머지 전에도 working tree 가 cache 의 source 이므로 같은 흐름.

---

## 7. 중요 경로·태그 참조

| 항목 | 값 |
|---|---|
| 플러그인 repo (로컬) | `/Users/brody/Desktop/token-tracker/` |
| 플러그인 repo (GitHub) | `https://github.com/brody424/TokenTracker` |
| marketplace manifest | `.claude-plugin/marketplace.json` (repo 루트) |
| plugin 디렉터리 | `plugins/token-tracker/` |
| pricing 데이터 (NEW) | `plugins/token-tracker/lib/pricing_data.json` |
| Claude Code 설치 경로 (cache, active) | `~/.claude/plugins/cache/token-tracker-local/token-tracker/0.10.0/` (PR #7 머지 + reinstall 후) |
| 옛 cache 디렉터리 | `0.9.0/` (이전 active, version bump 후 자가복구 흐름은 PR #6 의 manifest version bump fix 가 처리) |
| state 디렉터리 | `~/.claude/plugins/token-tracker/state/` |
| history JSONL | `~/.claude/plugins/token-tracker/state/{session_id}/history.jsonl` |
| 에러 로그 (hook) | `~/.claude/plugins/token-tracker/log/error.log` |
| daemon stderr 로그 | `<plugin_root>/log/server_daemon.stderr.log` (cache 위치) |
| dev-mode 토글 | `./scripts/dev-mode.sh on / off / status` |
| 최신 태그 | **v0.10.0** (pricing 분리 + legacy 모델 7종 + dev-mode 토글 묶음) |
| 주요 PR | #1 (v0.7.0 pricing v2), #2 (v0.8.0 /token-history), #4 (v0.8.1 parser fix), #5 (v0.9.0 HTTP daemon), #6 (dev-mode 토글), **#7 (v0.10.0 pricing 분리)** |
| 테스트 수 | **387 passing** (PR #7 머지 후) |
| 테스트 실행 | `./venv/bin/pytest plugins/token-tracker/tests -q` (repo 루트 기준) |
| Anthropic pricing 페이지 | https://platform.claude.com/docs/en/about-claude/pricing |
| Claude Design 프로젝트 | https://claude.ai/design/p/019df2f7-ddb2-7aab-a4db-82305082fbfc |

---

## 8. 다음 세션 시작 시 권장 워크플로

1. 이 핸드오프 + (선택) v0.9.0 핸드오프 읽어서 컨텍스트 정리
2. 사용자가 방향 잡아주면 (위 4절 후보 또는 새 아이디어), 작업 규모에 따라 흐름 분기:
   - **작은 작업** (refactor / data / 단일 분기 추가): plan 짧게 → 구현 → 7-agent 리뷰 → PR
   - **중간 작업**: brainstorm 1~2 옵션 정도 → spec 안 쓰고 plan → 구현 → 리뷰 → PR
   - **큰 작업** (E. context bloat 시각화 같은): brainstorm → spec → plan → subagent-driven-development → 리뷰 → PR
3. PR 생성 후 사용자에게 검증 안내: `/plugin uninstall` + `/plugin install` + 다음 prompt 토큰 line 확인
4. 머지 명시 승인 후 머지 → main pull → 다음 작업

사용자가 "다음 작업 바로 진행" 이라고 하면:
- **E (context bloat 시각화)** 가 가장 큰 가치 후보 — brainstorm 부터 시작
- 또는 **새 후보 1번 (모델 alias)** / **2번 (stale 가드)** — 작은 작업, 한 PR 안에 묶기 가능
- 정리 작업이 더 누적되었으면 그쪽 우선

기능 추가 vs 정리 작업 비율은 v0.9.0 핸드오프 시점보다 정리 쪽이 많이 줄었음 (이번 PR 로 핵심 정리 끝). 이제 기능 / UX 작업이 더 자연스러움.
