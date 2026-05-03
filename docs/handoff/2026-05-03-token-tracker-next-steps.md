# token-tracker 인수인계 — 2026-05-03

> 이 문서는 이 대화를 모르는 **다음 세션의 Claude가 바로 이어 작업할 수 있게** 정리된 핸드오프 문서다. 세션이 시작되면 이 파일을 먼저 읽고, 참조 파일들을 확인한 뒤 사용자의 다음 지시를 따르면 된다.

---

## 1. 한 줄 요약

token-tracker = Claude Code 플러그인. Stop hook이 발화할 때마다 토큰·비용 한 줄 요약 출력. **현재 v0.7.0** — pricing 정확도 v2 적용:
- **Opus 4.7 단가 회귀 fix** ($15→$5 input, $75→$25 output 등 — 3배 overbill 해소). v0.x 어디서 누락된 회귀.
- **prompt cache 1h tier 분리**: parser가 transcript의 `cache_creation.ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens` 두 필드 분리 추출, pricing이 5m($6.25) / 1h($10) 별도 단가 적용.
- **summary_store schema v2 → v3 breaking** + `detail_formatter` / `detail.py` 동기 갱신 (CRITICAL fix — dataclass 필드 제거 시 즉시 AttributeError 회귀 가드).
- **silent $0 stderr 안전장치**: 미등록 모델 alias 발견 시 `[token-tracker] unknown pricing model: ...` stderr 1회 emit.
- **277 tests passing** (baseline 248 + 신규 29건 회귀 가드).

**v0.7.0 사용자 검증 결과 (2026-05-03)**:
- 새 세션 1턴 trigger → statusline `$0.162` vs token-tracker `$0.2549` (1.57배 차이)
- 진단: cache_creation 24,651 토큰이 100% 1h tier에 박혀있음 (transcript 직접 확인). statusline은 5m 단가로 underbill, tt는 1h 단가로 정확.
- **결론: tt v0.7.0이 statusline / ccusage 대비 가장 정확** (Opus 4.x + 1h cache 시나리오)

---

## 2. v0.6.x → v0.7.0 환산 가이드

Opus 4.7 turn당 비용 표시가 약 **1/3 수준으로 줄어듦**. 이는 Anthropic 공식 가격 인하(Opus 4.5부터)를 늦게 반영한 결과지 token-tracker 버그가 아님.

| 항목 | v0.6.x 표시 | v0.7.0 표시 (예시) |
|---|---|---|
| Opus 4.7 input 1MTok | $15 | **$5** |
| Opus 4.7 output 1MTok | $75 | **$25** |
| Opus 4.7 5m write 1MTok | $18.75 | **$6.25** |
| Opus 4.7 1h write 1MTok | (5m 단가로 처리) | **$10** (별도 단가) |
| Opus 4.7 cache read 1MTok | $1.5 | **$0.50** |

**옛 누적 비용(메모리·핸드오프에 적힌 v0.6.x 비용)과 v0.7.0 비용 직접 비교는 의미 없음** — 같은 작업 시간 기준으로도 단가 차이가 있어 비교 시 환산 적용 필요.

---

## 3. 다른 도구와의 차이 (왜 statusline / ccusage와 다른가)

| 도구 | 토큰 source | 단가 source | **1h tier 인식** | Opus 4.x 정확도 |
|---|---|---|---|---|
| **token-tracker v0.7.0** | transcript JSONL | Anthropic 공식 (수동, 2026-05-03 fetch) | ✅ | **가장 정확** |
| Claude Code statusline (`cost.total_cost_usd`) | Claude Code 내부 메모리 | 비공개 (retail 추정) | ❌ underbill | 낮음 |
| ccusage (npm) | transcript JSONL (같음) | LiteLLM DB (자동 갱신) | ❌ underbill | 낮음 |
| 실제 Anthropic 청구 (pay-per-token) | 서버 정확 | 정확 | ✅ | 정답 (정의상) |

**Claude Max / Pro 같은 정액 구독자**: tt 값은 "이 요청을 pay-per-token API로 했다면 들었을 비용"의 가상 가격. 실제 결제액은 매월 정액. 사용량 추적·rate limit 관리용으로만 의미.

**pay-per-token API 사용자**: tt 값 ≈ 다음 결제일 청구액 (거의 정확).

---

## 4. 파일 구조 / 참조 순서

다음 세션에서는 아래 순서로 읽어라.

1. **이 문서 (`docs/handoff/2026-05-03-token-tracker-next-steps.md`)** — 현재 상황, 다음 작업 후보
2. **이전 핸드오프 (`docs/handoff/2026-05-02-token-tracker-next-steps.md`)** — v0.6.4까지 누적 컨텍스트
3. **v0.7.0 spec (`docs/superpowers/specs/2026-05-03-token-tracker-pricing-accuracy-design.md`)** — 460줄, 15 섹션, 결정 흐름
4. **v0.7.0 plan (`docs/superpowers/plans/2026-05-03-token-tracker-pricing-accuracy.md`)** — 1898줄, 15 task, subagent-driven 실행됨
5. **구현 디렉터리 (`/Users/brody/Desktop/token-tracker/`)** — git repo, 277 tests, v0.7.0 태그

사용자의 글로벌 CLAUDE.md 규칙(한글 응답, 숫자 선택지, 승인 기반 진행 등)은 여전히 유효하다.

---

## 5. 다음 작업 후보 (우선순위 순)

### A. `/token-history` skill (Phase 3 잔여, 2~3h 예상) ⭐ 권장
- 현재 세션 내 **모든 request**의 요약 리스트 (turn#·비용·토큰·cache%·시간).
- `/token-detail`(직전 단건 상세)과 축이 다른 보완. 세션 중반에 누적 사용량 훑기용.
- `last_summary.json` 대신 전체 세션 aggregate가 필요 → hook에서 매번 append하거나 skill이 JSONL을 처음부터 파싱.
- 기존 i18n/formatter/aggregator 재활용 가능.

### B. pricing 데이터/코드 분리 (`lib/pricing_data.json`)
- 현재 PRICING dict가 `pricing.py`에 hardcoded. 단가 변경마다 코드 PR + schema bump 사이클.
- 분리하면 가격 PR이 1줄 data diff로 끝남. `last_updated` 필드로 stale 감지도 쉬워짐.
- v0.7.0 final review에서 follow-up으로 미룬 항목 (spec §15).

### C. 다른 모델 단가 추가 (Opus 4.5 / 4.6 / Sonnet 4.5 등)
- 현재 PRICING dict에 Opus 4.7, Sonnet 4.6, Haiku 4.5만 있음.
- 사용자가 다른 모델로 dispatch하면 silent $0 → stderr 경고 emit (v0.7.0 안전장치). 그때 추가.

### D. v0.7.0 직후 첫 `/token-detail` UX 개선
- 옛 v2 last_summary 파일 무시 → "데이터 없음" 응답. 1턴 후 자연 갱신.
- 안내 메시지 정정 ("삭제 후" 부정확 — 자동 덮어써짐): "다음 응답부터 자동 갱신됩니다"로 i18n 단순화.

### E. 200k+ tier 모니터링
- Opus 4.7은 **1M context까지 standard pricing** (200k+ tier 단가 차이 없음 — 공식 페이지 명시).
- 만약 Anthropic이 향후 4.x 모델에 200k+ tier 도입하면 PRICING 키 + parser + summary_store v4 bump 필요.
- 현재는 follow-up 가치 0.

### F. `_warned_unknown_models` LRU/reset
- module-level set으로 process-lifetime 누적. short-lived hook script라 무해.
- 향후 daemon화 시 LRU/주기 reset 고려.

---

## 6. 사용자 성향 메모 (빠르게 협업하려면 알면 좋음)

- **한글 응답**, **숫자 선택지**, **선택지 + 추천안 + 이유** 제시 선호.
- 동작·설계 결정은 하나씩 나눠서 확인. 오타 같은 사소한 건 묶어도 됨.
- `git commit`은 사용자 명시 요청 전엔 하지 않음. 단, 서브에이전트 주도 TDD 흐름에서 plan에 commit 스텝이 들어있으면 그건 정상 흐름이라 수행.
- **PR 머지는 반드시 사용자 명시 승인 후만** 실행 (사용자 룰).
- 서버 실행(`npm start` 등)은 직접 하지 말고 사용자에게 요청.
- 승인 없는 과잉 작업 금지. 루프/토큰 낭비 지양.
- 적대적 리뷰 결과를 **무비판적으로 수용하지 말 것** — 사용자가 "왜 모두 수용?"으로 짚었음. 발견의 정당성을 비판적으로 재평가 후 사용자에게 옵션 제시.
- Auto mode 전환 시: 적극적으로 진행하되 destructive 액션은 여전히 확인.

---

## 7. v0.7.0 작업 흐름 메모 (다음 세션 학습용)

### 7.1 brainstorming 단계 (사용자가 좋게 봄)
- 진단을 plan 1단계 prerequisite로 박음 — Stop hook stdin / transcript에 cost 필드 유무 확인.
- 7개 적대적 리뷰 후 사용자가 "모두 수용?" 비판 → 비판적 재평가 후 19건 반영, 2건 거부 (parser 헬퍼, lint 테스트).
- 3명 팀메이트 리뷰 (적대적/긍정적/중립적) 한 번 더 — CRITICAL 0건 종료 조건 충족 후 16건 추가 보강.

### 7.2 구현 단계 (subagent-driven)
- 6 phase로 plan 15 task 묶어서 진행. 각 phase 종료마다 spec compliance + code quality reviewer.
- Phase B 시점에 reviewer가 "같은 파일 안 기존 fixture는 같은 phase에서 fix"가 깨끗하다고 지적 → 패턴 확립.
- Phase A 진단 결과로 Plan Task 7 Step 7.5 (dedupe 보강) skip 결정 — 진단 기반 spec 자기 수정 흐름.

### 7.3 검증 단계 (사용자 직접)
- 새 세션 1턴 trigger → statusline vs tt 비교.
- "동일하지 않다 — 너무 다르다" 보고 → 진단 결과 우리가 정확하고 statusline이 underbill 확정.
- 사용자 의도가 "statusline과 일치"였지만 실제로는 "정확한 비용 표시"가 더 가치 — spec 의도 정정.

### 7.4 final review (7 병렬 + 5 lens 코드리뷰 skill)
- 7 병렬: CRITICAL 0, MAJOR 4 (1건 반영 — detail.py schema gate import), MINOR 16 (무시)
- code-review skill (5 lens): 발견 2건 모두 confidence 80 미만 → "No issues found" PR comment

---

## 8. 중요 경로·태그 참조

| 항목 | 값 |
|---|---|
| 플러그인 repo (로컬) | `/Users/brody/Desktop/token-tracker/` |
| 플러그인 repo (GitHub) | `https://github.com/brody424/TokenTracker` |
| marketplace manifest | `.claude-plugin/marketplace.json` (repo 루트) |
| plugin 디렉터리 | `plugins/token-tracker/` |
| Claude Code 설치 경로 (cache) | `~/.claude/plugins/cache/token-tracker-local/token-tracker/0.6.0/` (디렉터리명은 0.6.0이지만 plugin.json은 v0.7.0으로 동기화됨) |
| state 디렉터리 | `~/.claude/plugins/token-tracker/state/` |
| 에러 로그 | `~/.claude/plugins/token-tracker/log/error.log` |
| 최신 태그 | **v0.7.0** (pricing 정확도 v2) |
| 주요 태그 | v0.1.0-mvp, v0.2.0~v0.6.4 (상세는 이전 핸드오프), **v0.7.0** (Opus 회귀 fix + 1h tier 분리) |
| 테스트 수 | **277 passing** (v0.7.0 머지 후) |
| 테스트 실행 | `./venv/bin/pytest plugins/token-tracker/tests -q` (repo 루트 기준) |
| PR | https://github.com/brody424/TokenTracker/pull/1 (MERGED 2026-05-03) |
| 진단 disposable script | `scripts/diagnose_v0_7_shapes.py` (.gitignore에 `/scripts/` — 미커밋, 로컬 보존) |

---

## 9. 다음 세션 시작 시 권장 워크플로

1. 이 핸드오프 + 이전 핸드오프 (`2026-05-02-...md`) 읽어서 컨텍스트 정리.
2. 사용자가 방향 잡아주면 (위 5절 A~F 중), 해당 작업에 대한 **plan 문서**를 `superpowers:writing-plans` skill로 만든다.
3. plan 승인 후 `subagent-driven-development` skill로 실행.
4. v0.7.0 작업의 함정·교훈(7절)을 참고해 같은 함정에 빠지지 않게 한다.

사용자가 "다음 작업 바로 진행"이라고 하면 **A (`/token-history`)** 부터 제안하고 확인받아라.
