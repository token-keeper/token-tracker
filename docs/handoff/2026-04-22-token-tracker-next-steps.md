# token-tracker 인수인계 — 2026-04-22

> 이 문서는 이 대화를 모르는 **다음 세션의 Claude가 바로 이어 작업할 수 있게** 정리된 핸드오프 문서다. 세션이 시작되면 이 파일을 먼저 읽고, 참조 파일들을 확인한 뒤 사용자의 다음 지시를 따르면 된다.

---

## 1. 한 줄 요약

token-tracker = Claude Code 플러그인. Stop hook이 발화할 때마다 방금 끝난 사용자 요청(UserPromptSubmit → Stop) 한 건의 토큰·비용을 한 줄로 출력한다. **Phase 1 MVP 완료 + 실전 검증 + 3건의 버그 픽스 반영됨.** 현재 태그 `v0.1.0-mvp`, 이후 추가 수정 3개 커밋.

---

## 2. 파일 구조 / 참조 순서

다음 세션에서는 아래 순서로 읽어라.

1. **이 문서 (`docs/handoff/2026-04-22-token-tracker-next-steps.md`)** — 현재 상황, 다음 작업 후보
2. **설계 스펙 (`docs/superpowers/specs/2026-04-22-token-tracker-plugin-design.md`)** — 전체 플러그인 설계 의도, Phase 1~3 구분, 후속 과제
3. **Phase 1 계획 (`docs/superpowers/plans/2026-04-22-token-tracker-phase1-mvp.md`)** — 이미 실행 완료된 11개 태스크
4. **구현 디렉터리 (`/Users/i_brody/Desktop/harness/token-tracker/`)** — git repo, 41 tests, v0.1.0-mvp 태그

사용자의 글로벌 CLAUDE.md 규칙(한글 응답, 숫자 선택지, 승인 기반 진행 등)은 여전히 유효하다.

---

## 3. 현재 작동 중인 기능

### 3.1 Stop hook 출력
매 응답 끝에 다음 한 줄이 `systemMessage`로 표시된다:
```
비용 $0.0180 · 1,546 toks · cache 85% · 12.3s
```
- **비용** = retail pay-per-token 기준 (Anthropic public 가격표). statusline의 내부 tracker 값과 다를 수 있음 — README에 명시됨.
- **toks** = `input + cache_creation + cache_read + output` 전체 (API 빌링 기준).
- **cache** = `cache_read / total_input` 적중률.
- **s** = UserPromptSubmit → Stop 경과 초.

### 3.2 설치 상태 (로컬 dev)
`/Users/i_brody/Desktop/harness/token-tracker/.claude/settings.local.json`에 직접 hook 등록되어 있음. **Claude Code를 `/Users/i_brody/Desktop/harness/token-tracker/`(또는 하위)에서 실행할 때만 발화한다.** 다른 디렉터리에서 실행하면 적용 안 됨.

정식 marketplace 경로는 **아직 적용 안 됨** (Phase 2 후보 A 참고).

### 3.3 테스트
41 passing. Python 3.10+ 표준 라이브러리만.
```bash
cd /Users/i_brody/Desktop/harness/token-tracker && pytest -q
```

---

## 4. v0.1.0-mvp 태그 이후 누적된 3건의 버그 픽스

이 섹션은 "똑같은 문제를 재발견하지 말라"는 용도다.

### 4.1 `fc2869b` Stop hook 플러시 폴링 (최대 500ms)
**증상**: 실전에서 Stop 출력이 `$0.0000 · 0 toks · cache 0%`로만 나옴.
**원인**: Claude Code가 Stop hook을 발화하는 시점에 마지막 assistant 라인이 아직 JSONL에 flush 안 돼 있을 수 있음. 우리 hook이 단일 read로 끝나서 0 turns로 해석.
**수정**: `hooks/on_stop.py`에서 0 turns 나오면 100ms 간격으로 최대 5회 재시도 (500ms 한도).
**관련 테스트**: `tests/test_hook_end_to_end.py::test_stop_polls_for_delayed_flush`.

### 4.2 `82acff9` 코드리뷰 피드백 (세 가지 서브 이슈)
- `import io` 미사용 제거.
- `state` 없이 `turns` 0이면 출력 skip (spurious Stop 노이즈 방지).
- `pricing.compute_cost`에 longest-prefix match 추가 — `claude-opus-4-7[1m]`, `claude-opus-4-7-20260101` 같은 suffix 변형 모델 ID 대응.

### 4.3 `8ea96a9` **중복 counting 버그 + cache_creation 표시**
**증상**: `$12.0125 · 432 toks · cache 0%` 같은 말이 안 되는 수치.
**원인 1**: Claude Code는 하나의 API 응답을 **content block별로 쪼개 JSONL 여러 라인에 쓴다** (thinking 블록, text 블록, tool_use 블록). 각 라인에 **같은 usage 필드가 복사**돼 있어서 우리가 N번 합산함.
  - 같은 `message.id` 공유 → dedupe 기준.
**원인 2**: 표시 토큰은 `input + cache_read + output`이었는데 비용 계산엔 `cache_creation`까지 포함. 그래서 작은 토큰수에 큰 비용이 붙어 모순돼 보임.
**수정**:
- `parser.py`: `TurnUsage`에 `message_id` 필드 추가.
- `aggregator.py`: `_dedupe_by_message_id`로 같은 msg_id 한 번만 반영.
- `aggregator.py`: `total_input_tokens = input + cache_creation + cache_read` (cache_creation 포함).
- `cache_hit_rate` 분모도 동일하게 업데이트.
**검증**: 실제 세션 데이터에서 문제 turn $12.01 → $6.01로 정상화.
**관련 테스트**: `tests/test_aggregator.py::test_dedupe_by_message_id` 등 3건 추가.

---

## 5. 확정된 다음 작업 후보 (우선순위 순)

> **다음 세션 권장**: B부터 시작 (`/token-detail` skill).

### A. 로컬 marketplace 패키징 ✅ 완료 (2026-04-22)

- `.claude-plugin/marketplace.json` 추가 (self-contained, `source: "."`).
- `.claude-plugin/plugin.json`에 `hooks: "./hooks/hooks.json"` 필드 명시.
- `/plugin marketplace add <repo>` + `/plugin install token-tracker@token-tracker-local`로 설치.
- 기존 `.claude/settings.local.json` 제거됨 — repo 밖에서 Claude Code를 띄워도 hook 발화.
- 관련 테스트: `tests/test_marketplace_manifest.py` (5건).
- 관련 plan: `docs/superpowers/plans/2026-04-22-token-tracker-local-marketplace.md`.

### B. Phase 2: `/token-detail` skill (3–4h 예상)
spec 섹션 3 참고. 직전 request의 turn별 상세 표를 출력.
- 각 turn: 순서, 모델, 사용 툴 목록, 토큰 breakdown, turn별 비용, turn별 소요시간
- skill 디렉터리: `token-tracker/skills/token-detail/`
- `disable-model-invocation: true`로 토큰 절약
- 데이터 소스: 이미 `aggregator.Summary.turns[]`에 turn별 정보 있음 → formatter에 detail 변형 추가하면 됨

**사용자가 명시적으로 요청한 기능**: "상세보기는 최대한 디테일하게, 차례대로 보고싶어. 그리고 각 turn에서 걸린 소요된 시간도 보고싶어."

### C. Phase 3: `/token-history` + `/token-verbose` skill (2–3h 예상)
- `/token-history`: 현재 세션 내 모든 request 요약 리스트
- `/token-verbose`: config.json의 `verbose: true` 토글 → 이후 Stop마다 자동으로 상세 출력

### D. 가격표 정확도 개선 / Team 플랜 대응 (조사 필요)
현재 `lib/pricing.py`는 public retail 요금표 5m 캐시 tier 기준. 실제 사용자는 Claude Team 플랜이라 statusline의 내부 값과 2~3배 이상 차이남. 조사할 것:
- Anthropic API가 응답 헤더에 실제 billing cost를 반환하는지
- 1h cache tier 가격 반영 (`ephemeral_1h_input_tokens` 활용)
- config에 "pricing_override" 필드로 사용자 할인율 주입

---

## 6. 사용자 성향 메모 (빠르게 협업하려면 알면 좋음)

- **한글 응답**, **숫자 선택지**, **선택지 + 추천안 + 이유** 제시 선호.
- 동작·설계 결정은 하나씩 나눠서 확인. 오타 같은 사소한 건 묶어도 됨.
- `git commit`은 사용자 명시 요청 전엔 하지 않음. 단, 서브에이전트 주도 TDD 흐름에서 plan에 commit 스텝이 들어있으면 그건 정상 흐름이라 수행.
- 서버 실행(`npm start` 등)은 직접 하지 말고 사용자에게 요청.
- 승인 없는 과잉 작업 금지. 루프/토큰 낭비 지양.
- Auto mode 전환 시: 적극적으로 진행하되 destructive 액션은 여전히 확인.

---

## 7. 다음 세션 시작 시 권장 워크플로

1. 사용자가 방향을 잡아주면 (위 A/B/C/D 중), 해당 작업에 대한 **plan 문서**를 `writing-plans` skill로 만든다 (`docs/superpowers/plans/YYYY-MM-DD-token-tracker-<topic>.md`).
2. plan 승인 후 `subagent-driven-development` skill로 실행.
3. Phase 1에서 발견된 엣지케이스(4번 섹션)를 참고해 같은 함정에 빠지지 않게 한다.

사용자가 "다음 작업 바로 진행"이라고 하면 **1순위 A**부터 제안하고 확인받아라.

---

## 8. 중요 경로·태그 참조

| 항목 | 값 |
|---|---|
| 플러그인 repo | `/Users/i_brody/Desktop/harness/token-tracker/` |
| 로컬 hook 설정 | `token-tracker/.claude/settings.local.json` (gitignored) |
| state 디렉터리 | `~/.claude/plugins/token-tracker/state/` |
| 에러 로그 | `~/.claude/plugins/token-tracker/log/error.log` |
| 최신 태그 | `v0.1.0-mvp` (779c7c0..82acff9) |
| 태그 후 커밋 | `fc2869b` (flush polling), `8d0eaba` (README), `8ea96a9` (dedupe + cc display), 기타 2건 chore |
| 테스트 수 | 41 passing |
