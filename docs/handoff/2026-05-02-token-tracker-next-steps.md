# token-tracker 인수인계 — 2026-05-02

> 이 문서는 이 대화를 모르는 **다음 세션의 Claude가 바로 이어 작업할 수 있게** 정리된 핸드오프 문서다. 세션이 시작되면 이 파일을 먼저 읽고, 참조 파일들을 확인한 뒤 사용자의 다음 지시를 따르면 된다.

---

## 1. 한 줄 요약

token-tracker = Claude Code 플러그인. Stop hook이 발화할 때마다 방금 끝난 사용자 요청의 토큰·비용을 한 줄 요약으로 출력한다. **현재 v0.6.4** — offset 갱신 정책 명문화: on_stop은 절대 offset을 갱신하지 않으며, on_user_prompt가 유일한 갱신점이다. 한 사용자 입력 = 한 누적 last_summary로 메인의 모든 응답 turn + 모든 sub 결과가 합산되어야 한다는 의도를 회귀 가드 + 코드 주석으로 codify. async background dispatch가 활성 중이면 매 Stop마다 끼어들지 않고 모두 끝난 시점 1번만 emit (윈도우 회귀 fix로 dispatch가 이전 turn에 있어도 정확 감지). detail 표 `툴` 칼럼이 thinking/tool_use 라인 dedupe 시 silent drop되던 버그 fix. `/token-detail` sub 행이 `└ sub: general-purpose [sonnet 4.6]`처럼 model까지 표시하고, sub의 model을 알 때는 그 단가로 정확히 비용 산정. unknown alias("sonnet" 등)도 부모 단가로 안전 fallback. **245 tests passing**. `config.json`의 `verbose: true`로 매 응답마다 turn별 상세 표를 자동 출력(결정론적, LLM 우회), `/token-detail`로 주문형 조회, `/token-verbose [on|off]`로 verbose 토글 — 모두 slash로 수동 호출 전용(`disable-model-invocation: true`).

**v0.6.2 (2026-05-02)**: sub 행이 model 정보까지 노출. async sub은 sidechain `message.model`, foreground sub은 dispatch 시 `input.model`. 둘 다 모르면 부모 단가 fallback + legend 안내. 모든 sub model이 알려지면 정확 비용이라 legend 생략. 188 → 205 tests.

**v0.6.2 보강 (T13, 2026-05-02 같은 날)**: 머지 차단 CRITICAL + UX 개선 D 옵션. 205 → 222 tests.

**v0.6.3 hot-fix (T15, 2026-04-23)**: 두 가지 회귀 fix — (A) `extract_async_launches`가 `_read_tail` window 밖의 dispatch를 못 봐 sub 0개로 출력되던 버그, (B) `_dedupe_by_message_id`가 thinking 라인 keep할 때 tool_use 라인의 `tools_used`까지 silent drop하던 버그. 222 → 233 tests.

**v0.6.3 추가 hot-fix (T16, 2026-04-23)**: T15 file-based active 카운트로 전환한 후 일부 sub의 task-notification이 메인 jsonl에 매칭 안 돼 (다른 jsonl로 흘러간 케이스) launches 27 / active 10으로 영원히 active 잔존하던 회귀 fix. `count_active_async_agents_from_file`이 sidechain `agent-{id}.jsonl`에 assistant 라인이 1개 이상 있으면(= sub가 응답 생성 = 끝남) 완료로 간주하도록 OR 신호 추가. path traversal·symlink 가드 유지. 233 → 238 tests.

---

## 2. 파일 구조 / 참조 순서

다음 세션에서는 아래 순서로 읽어라.

1. **이 문서 (`docs/handoff/2026-05-02-token-tracker-next-steps.md`)** — 현재 상황, 다음 작업 후보
2. **이전 핸드오프 (`docs/handoff/2026-04-22-token-tracker-next-steps.md`)** — Phase 1~2 누적 컨텍스트
3. **설계 스펙 (`docs/superpowers/specs/2026-04-22-token-tracker-plugin-design.md`)** — 전체 플러그인 설계 의도, Phase 1~3 구분, 후속 과제
4. **subagent 토큰 plan (`docs/superpowers/plans/2026-05-02-token-tracker-subagent-tokens.md`)** — v0.6.0에서 실행 완료된 task 분해
5. **구현 디렉터리 (`/Users/brody/Desktop/token-tracker/`)** — git repo, 176 tests, v0.6.0 태그

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
정식 marketplace 경로로 설치됨. `/plugin marketplace add <repo>` + `/plugin install token-tracker@token-tracker-local` + `/reload-plugins` 후 어디서든 발화.

### 3.3 테스트
176 passing. Python 3.10+ 표준 라이브러리만.
```bash
./venv/bin/pytest plugins/token-tracker/tests -q
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

> **다음 세션 권장**: C' (`/token-history`) 또는 D (가격표 정확도).

### A. 로컬 marketplace 패키징 ✅ 완료 (2026-04-22)

- 표준 marketplace 레이아웃으로 파일 재배치: `hooks/`, `lib/`, `tests/`, `config.json`, `.claude-plugin/plugin.json`을 모두 `plugins/token-tracker/` 하위로 이동. 루트 `.claude-plugin/marketplace.json`은 유지.
- `marketplace.json`의 `source`는 `"./plugins/token-tracker"` (Claude Code가 `source: "."` 자기참조는 schema 거부).
- `plugin.json`에 `hooks` 필드는 **선언하지 않음** — Claude Code가 `hooks/hooks.json`을 convention으로 자동 로드. 명시하면 "Duplicate hooks file" 에러.
- 설치: `/plugin marketplace add <repo>` + `/plugin install token-tracker@token-tracker-local` + `/reload-plugins`.
- 기존 `.claude/settings.local.json` 제거됨 — repo 밖에서 Claude Code를 띄워도 hook 발화.
- 관련 테스트: `plugins/token-tracker/tests/test_marketplace_manifest.py` (5건).
- 관련 plan: `docs/superpowers/plans/2026-04-22-token-tracker-local-marketplace.md`.
- 커밋 히스토리: `8dcb7f6` (초기 manifest) → `7857721` (파일 이동) → `3eb8e79` (hooks 중복 제거).

### B. `/token-detail` skill ✅ 완료 (2026-04-23)

- `plugins/token-tracker/skills/token-detail/` 추가 (`SKILL.md` + `scripts/detail.py`).
- Stop hook이 flush polling 완료 후 `state/{session}/last_summary.json`에 Summary 저장.
- `detail_formatter`가 COLUMNS 리스트 + `lib/i18n/{ko,en}.json` 리소스로 표 렌더링.
- `tools_used`를 `[{name, count}]` 구조로 확장. `TurnUsage.index` 필드 추가.
- SKILL.md는 `!`cmd`` 한 줄로 스크립트 실행 → stdout이 본문에 삽입 → LLM이 그대로 전달.
- `${CLAUDE_SESSION_ID}` 공식 env variable을 argv로 받아 session 스코프 확정.
- schema_version=1, 미지원 시 `None` 반환 + stderr 진단.
- v0.3.1 hotfix: parser가 timestamp_iso를 `started_at` epoch float로 변환해 turn별 시간 계산 정상화 + SKILL.md 지시문 강화(`<script-output>` XML 태그).
- v0.4.0: **verbose 모드 추가** — `config.json`의 `verbose: true` 또는 `TOKEN_TRACKER_VERBOSE=1` 환경변수로 매 Stop마다 자동 상세 표 출력. Hook이 직접 systemMessage에 덧붙여 LLM을 거치지 않아 **결정론적**. slash skill이 가끔 LLM 맥락에 끌려 표 대신 엉뚱한 응답을 내는 근본 한계를 우회.
- 관련 spec v2: `docs/superpowers/specs/2026-04-22-token-detail-skill-design.md`.
- 관련 plan: `docs/superpowers/plans/2026-04-23-token-detail-skill.md`.
- 신규 테스트 총 29건. 전체 46 → 85.

### C. `/token-verbose` toggle skill ✅ 완료 (2026-04-24, v0.5.0)

- `plugins/token-tracker/skills/token-verbose/` 추가 (`SKILL.md` + `scripts/verbose_toggle.py`).
- `/token-verbose` (인자 없음) → 현재 상태, `/token-verbose on|off` → 전환, 이미 같은 상태면 "변경 없음" 안내.
- alias 수용: `on/1/true/yes`, `off/0/false/no` — case-insensitive.
- `_write_config`는 tmp 파일 → `os.replace()` 패턴으로 **원자적 쓰기** (Stop hook과 race 방어, 디스크풀 시 손상 방지).
- `disable-model-invocation: true` + `$ARGUMENTS` 치환으로 사용자 수동 호출 전용.
- `hooks/on_stop.py` env 판정 로직 수정: whitelist(`1/true/yes/on`, `0/false/no/off`) 외 값은 env 무시하고 config으로 폴백 (이전: whitelist 외면 조용히 off로 떨어짐).
- 신규 테스트 20건 (`test_verbose_toggle_script.py` 12 + `test_verbose_integration.py` 8, 후자는 toggle→stop 연속 E2E + SKILL.md manifest 포함).
- 커밋: `9d7c3a4` (hook fix) + `dc0dc74` (skill).

### C'. Phase 3 잔여: `/token-history` skill (2~3h 예상)
- 현재 세션 내 **모든 request**의 요약 리스트 (turn#·비용·토큰·cache%·시간).
- `/token-detail`(직전 단건 상세)과 축이 다른 보완. 세션 중반에 누적 사용량 훑기용.
- `last_summary.json` 대신 전체 세션 aggregate가 필요 → hook에서 매번 append하거나 skill이 JSONL을 처음부터 파싱.
- 기존 i18n/formatter/aggregator 재활용 가능.

### D. 가격표 정확도 개선 / Team 플랜 대응 (조사 필요)
현재 `lib/pricing.py`는 public retail 요금표 5m 캐시 tier 기준. 실제 사용자는 Claude Team 플랜이라 statusline의 내부 값과 2~3배 이상 차이남. 조사할 것:
- Anthropic API가 응답 헤더에 실제 billing cost를 반환하는지
- 1h cache tier 가격 반영 (`ephemeral_1h_input_tokens` 활용)
- config에 "pricing_override" 필드로 사용자 할인율 주입

### E. v0.5.0 코드리뷰 MAJOR 회수 ✅ 완료 (2026-04-24, v0.5.1)

v0.5.0 병렬 리뷰에서 YAGNI/범위 이유로 보류된 MAJOR 3건을 3개 독립 PR로 회수. 각 PR은 7 에이전트 병렬 리뷰 + 사용자 승인 + local `--no-ff` 머지.

**E-1. `lib/config.py` 단일 owner ✅ (PR `766f670`)**
- 신규 `lib/config.py`에 `load_config` / `update_config` (atomic tmp+os.replace, OSError 전파) / `get_language` / `is_verbose` (env whitelist 폴백 포함) 4개 공개 API.
- `hooks/on_stop.py`, `skills/token-detail/scripts/detail.py`, `skills/token-verbose/scripts/verbose_toggle.py` 3곳이 모두 lib 경유로 일원화.
- `load_config`는 JSON이 non-dict(배열/스칼라) 시 DEFAULTS 복사본 반환 (downstream `AttributeError` 방지), `update_config`는 replace 실패 시 `.tmp` cleanup 후 raise.
- 테스트 +32건 (`test_config.py`). 103 → 135 passing.

**E-2. `$ARGUMENTS` env var passthrough ✅ (PR `bd33991`)**
- `SKILL.md` 호출을 `!`TOKEN_TRACKER_VERBOSE_ARG="$ARGUMENTS" python3 ...``로 변경. script는 `os.environ.get("TOKEN_TRACKER_VERBOSE_ARG", "")` 읽기.
- `_parse_arg(raw: str) -> str`로 signature 단순화. `main()`에서 argv 인자 제거.
- env var 네이밍은 기존 `TOKEN_TRACKER_VERBOSE` 프리픽스 규약 맞춤.
- **보안 경계는 defense-in-depth 한 겹 추가 수준** — bash `$(...)` expansion 자체는 여전히 Claude Code 런타임 책임. injection **차단**이 아닌 **argv 재해석 경로 축소**로 정확히 기술.
- injection-safety 테스트 2건 + config reset in loop. 135 → 137 passing.

**E-3. OSError split + exit 1 + i18n verbose_error_io ✅ (PR `ebdf622`)**
- `verbose_toggle.py`의 `update_config` 호출을 `try/except OSError`로 감쌈. `_log_error`로 tb를 `error.log`에 기록, `print`로 i18n 메시지를 **stdout**(stderr가 아니라 — Claude Code skill output pipe 가시성)에 보냄, `return 1`.
- i18n 2 locale에 `verbose_error_io` 추가 (`{reason}` placeholder에 `str(e)`로 `[Errno N] ...` 끼움).
- 테스트: `os.replace` 실패를 **dir trick**(`config.json` 위치에 디렉터리 생성 → parent writable 유지하되 replace만 POSIX 규칙으로 실패)으로 isolate. readonly dir + ko locale 케이스 포함. 각 테스트에 `[Errno` substring assertion으로 `{reason}` 포맷 회귀 방지.
- 137 → 140 passing. marketplace.json 동기화로 141.

**E-4. MINOR 미처리 (여전히 선택적)**
v0.5.0 원본 MINOR + v0.5.1 PR별 리뷰 MINOR 혼재. SKILL.md 공통 boilerplate(`_setup_sys_path`, `_log_error`)를 `lib/skill_runtime.py`로 추출, `_log_error`의 context manager 사용, alias 축소, `str(OSError)` 경로 노출 축약(`e.strerror`), CI root `skipif` 가드, ENOSPC 시나리오 테스트 등. 모두 선택적.

### F. `/token-detail` subagent 표시 ✅ 완료 (2026-05-02, v0.6.0)

- **foreground subagent**: 메인 jsonl의 `toolUseResult.totalTokens`/`usage` 필드에서 직접 추출 (parser).
- **async subagent**: 메인 jsonl의 `async_launched` 라인에서 `(tool_use_id, agent_id)` 매핑을 수집 → sidechain jsonl 디렉터리(`{transcript_dir}/{session_id}/subagents/agent-*.jsonl`) 파싱 (신규 `lib/sidechain.py`).
- aggregator가 `tool_use_id` 매칭으로 부모 turn에 attach. 부모를 못 찾은 sub는 silent drop (시끄럽게 실패시키지 않음).
- detail 표에서 부모 행 직후 `└ {agent_type}` 들여쓰기 행으로 표시. 비용은 부모 model 단가로 추정 (sidechain에 model 정보가 항상 있는 게 아니라서). 표 하단 legend에 `* subagent 비용은 부모 모델 단가로 추정` 한 줄 추가.
- `schema_version` 1 → 2 bump (Summary에 `subagents` 직렬화). v1 파일은 빈 리스트로 normalize 후 정상 로드 (forward-compat).
- Summary 합계(total_cost / total_tokens)에도 subagent 토큰·비용이 포함됨.
- 신규 테스트 ~35건 (parser/aggregator/sidechain/state/formatter/pricing 회귀). 141 → 176 passing.
- 관련 plan: `docs/superpowers/plans/2026-05-02-token-tracker-subagent-tokens.md`.
- 6 commits: `8bf5bc3` (parser) → `98cdeb4` (aggregator) → `7f5169d` (hook + sidechain.py) → `c48c76f` (state schema v2) → `4ca7569` (detail formatter) → `48e3079` (pricing 회귀).

### F-2. v0.6.0 리뷰 후속 정리 + timing 회귀 fix ✅ 완료 (2026-05-02, v0.6.1)

7개 병렬 코드리뷰(CRITICAL 0)에서 보고된 MAJOR 5건 + 시각 검증 중 발견된 timing 회귀 2건을 같은 브랜치에서 보강했다.

**리뷰 보강 5건:**
- `eb7a855` refactor(parser): `parse_agent_tool_uses` 헬퍼 추출 — sidechain의 책임 침범 해소 (DRY)
- `fe23fd9` refactor(parser): `SubagentUsage`의 dead 필드 3개(`agent_id`, `started_at`, `model`) 제거 (YAGNI). `summary_store`는 `**data` 대신 명시적 키 추출 패턴으로 전환해 forward-compat 보존
- `527e96c` refactor(aggregator): turn+sub 합산을 한 패스로 통합 (`(t, *t.subagents)` 시퀀스)
- `f1f0372` fix(sidechain): `agent_id` path traversal 가드 — 정규식 `^[A-Za-z0-9_-]+$` + `Path.is_symlink()` 거부 + `resolve().is_relative_to()` defense-in-depth
- `1b4838f` test: 빈 sidechain dir / 0바이트 jsonl / `subagents=[]` legacy 회귀 가드

**timing 회귀 fix 2건 (시각 검증으로만 발견됨, unit test 못 잡음):**
- `bff10a7` fix(hook): Stop hook의 flush polling 종료 조건을 `not turns or _missing_fg_match()`로 보강. Agent dispatch가 있는데 매칭 fg_sub이 없으면 100ms × 5회 더 polling. Agent 미호출 turn은 expected가 빈 셋이라 즉시 종료(성능 회귀 0)
- `f2781ee` fix(aggregator): `_dedupe_by_message_id`가 같은 message_id를 보면 두 번째부터 skip하던 동작이 **`agent_tool_use_ids`도 같이 drop**해서 sub 매칭이 silent fail하던 버그. Claude Code가 한 응답을 thinking/text/tool_use 라인으로 쪼개 같은 msg_id로 쓰는데, 첫 라인(thinking)이 살아남으면 tool_use 라인의 ids가 사라졌음. 이제 같은 msg_id를 만나면 ids만 kept turn에 merge

**follow-up 미처리 (별도 plan 권장):**
- M4 (orphan 가시화) — 부모 못 찾은 sub을 별도 행/섹션으로 노출 (현재 silent drop)
- M5 (sidechain offset 캐시) — 매 Stop마다 sidechain jsonl 전체를 재read. 장기 세션에서 측정 후 대응

**최종 신규 테스트 ~47건. 141 → 188 passing.**

### F-3. sub 행에 model 표시 + 정확 비용 ✅ 완료 (2026-05-02, v0.6.2)

v0.6.1까지는 sub 행이 `└ general-purpose`처럼 agent_type만 보였고, sub 비용은 항상 부모 model 단가로 추정했다. 실제로는 sub이 다른 model로 돌아도 (예: opus 부모 + haiku sub) 모두 opus 단가로 비용이 산출돼 부정확했다.

**모델 정보 source 우선순위 (높음 → 낮음):**
1. async sub — sidechain jsonl `assistant.message.model` (가장 정확)
2. foreground sub — 메인 jsonl `Agent` tool_use `input.model` (caller가 dispatch 시 명시한 경우만)
3. 모름 — 빈 문자열 → 부모 단가 fallback + footer legend 표시

**변경 사항:**
- `lib/parser.py`: `SubagentUsage.model` 필드 부활. `parse_agent_tool_uses`가 `(tool_use_id, subagent_type, model)` 트리플 반환. `parse_sidechain_assistant`가 `message.model`을 SubagentUsage에 채움.
- `lib/sidechain.py`: `extract_async_launches`가 `{agent_id: (tool_use_id, agent_type, model)}` 매핑 반환. `collect_sidechain_subagents`는 sidechain `message.model` 우선, 없을 때만 launch model로 fallback.
- `hooks/on_stop.py`: 메인 jsonl entries를 walk해 `{tool_use_id: model}` 룩업을 만들고 fg_subs 중 model이 빈 것을 채움.
- `lib/aggregator.py`: 비용 계산 시 `billing_model = sub.model or parent.model` — sub model이 알려지면 정확 단가로, 모르면 부모 단가로 fallback.
- `lib/detail_formatter.py`: sub 행 라벨 `└ sub: general-purpose [sonnet 4.6]` 형식. `_short_model_name` 헬퍼가 `claude-{family}-{major}-{minor}[-suffix]` 정규식으로 `opus 4.7`/`sonnet 4.6`/`haiku 4.5` 압축 표기. footer legend(`* subagent 비용은 부모 모델 단가로 추정`)는 model을 모르는 sub이 1개라도 있을 때만 출력 — 전부 알면 정확 비용이라 안내 생략.
- `lib/summary_store.py`: `_SUB_KEYS`에 `"model"` 추가해 v2 파일에 직렬화. schema_version은 2 유지 (v2 안의 minor 정리). 기존 v2 파일은 `model` 키가 없어도 default `""`로 정상 로드.

**신규 테스트 ~12건. 188 → 205 passing.**

**i18n:** `subagent_row_label`은 i18n 키로 두지 않고 `_SUB_LABEL = "sub:"` 모듈 상수로 처리 (ko/en 둘 다 동일이라 KISS). `subagent_row_prefix`(`└ `), `subagent_legend`는 그대로.

#### F-3 보강 (T13, 같은 v0.6.2): CRITICAL silent $0 회귀 + D 옵션

**CRITICAL fix (silent $0 회귀):** 사용자가 `Agent(model="sonnet")` 같은 short alias로 dispatch하면 parser가 `sub.model="sonnet"`을 채움. 기존 `billing_model = sub.model or parent.model` 패턴은 `"sonnet"` truthy라 부모 fallback이 안 되고 그대로 `compute_cost("sonnet", sub)`에 전달 → `_resolve_rates("sonnet")` None → **0.0 silent return**. 즉 v0.6.1의 부모 단가 추정보다 부정확한 회귀(sub 비용 무음 $0).

수정:
- `lib/pricing.py`에 `effective_billing_model(sub_model, parent_model)` 단일 헬퍼 추출. known pricing key prefix match만 통과시키고 그 외 truthy 값(unknown alias)은 부모 단가로 fallback.
- `lib/aggregator.py` + `lib/detail_formatter.py`가 같은 헬퍼 호출 (DRY).
- `lib/detail_formatter.py`의 legend 트리거 조건을 `not is_known_model(sub.model)`로 강화. 빈 문자열뿐 아니라 unknown alias도 "추정" 안내가 뜬다.
- 풀체인 e2e 회귀 가드 1건 (`test_e2e_sub_with_short_alias_falls_back_to_parent_model_rate`).

**D 옵션 (async background UX):** 사용자가 `run_in_background: true`로 N개 dispatch → 결과가 점차 도착하며 메인이 매번 응답 → 매 응답 끝 Stop hook이 token-tracker 한 줄 요약 emit → 사용자에게 매번 끼어드는 UX 문제.

수정:
- `lib/sidechain.py`에 `count_active_async_agents(entries) -> int` 추가. `extract_async_launches`로 launched agent_id 집합 + 메인 jsonl의 `<task-notification><status>completed</status>` XML(또는 `attachment.type=queued_command`)에서 완료 agent_id 집합. 차집합 크기.
- `hooks/on_stop.py`에서 active > 0이면 `_emit` 생략하고 `return 0`. last_summary는 그 직전에 이미 저장됐으므로 활성 중에도 누적치는 보존되고, 모두 끝난 시점 Stop에서 정상 emit.
- verbose 모드(config.verbose=true 또는 TOKEN_TRACKER_VERBOSE=1)는 debug 용도라 active 무시하고 매번 emit.
- 단위 테스트 6건 + e2e 4건 추가 (`tests/test_sidechain.py`, `tests/test_hook_end_to_end.py`).

**신규 테스트 +17. 205 → 222 passing.**

### F-4. v0.6.3 hot-fix: launches 윈도우 + tools_used merge (2026-04-23)

v0.6.2 출시 후 사용자 실측에서 발견된 두 가지 회귀를 같은 hot-fix 브랜치에서 처리.

**Bug A — `extract_async_launches`가 짧은 윈도우만 보다가 launches 누락:**
- 증상: turn 1에서 background dispatch → turn 2 Stop 시 token-tracker 한 줄 요약이 매번 끼어드는 회귀. 또한 detail 표에 sub 0개 표시.
- 원인: `_read_tail(transcript_path, offset)`이 offset 뒤만 읽음 → dispatch가 이전 turn에 있으면 launches 추출 0개 → `count_active_async_agents` 0 (silent guard 풀림) + `collect_sidechain_subagents` 빈 매핑 (sub drop).
- fix: `lib/sidechain.py`에 `extract_async_launches_from_file(transcript_path)` / `count_active_async_agents_from_file(transcript_path)` 추가. jsonl을 처음부터 stream parse해 offset 무시. 기존 in-memory 함수는 단위 테스트 호환을 위해 유지. `hooks/on_stop.py`가 두 헬퍼를 file-based 변형으로 교체.

**Bug B — `_dedupe_by_message_id`가 `tools_used` drop:**
- 증상: detail 표에서 메인 turn 6개 모두 `툴` 칼럼이 `—`. v0.6.0부터 잠재 회귀 (T10이 `agent_tool_use_ids`만 merge하고 `tools_used`는 누락).
- 원인: Claude Code가 한 응답을 thinking + tool_use + text 라인으로 쪼개 같은 message_id로 기록. parser는 라인별로 TurnUsage 생성 — thinking 라인 `tools_used=[]`, tool_use 라인만 채워짐. dedupe가 첫(thinking) 라인 keep + 이후 skip → tool_use 라인의 `tools_used` silent drop.
- fix: `lib/aggregator.py:_dedupe_by_message_id`가 같은 message_id 만나면 `tools_used`도 name 기준으로 merge (같은 이름 count 합산, 새 이름 stable append).

**테스트 +10건 (sidechain 7 + aggregator 2 + e2e 1). 222 → 233 passing.**

**커밋:**
- `fix(sidechain): extract_async_launches_from_file로 jsonl 전체 read (윈도우 누락 회귀)`
- `fix(hook): launches를 file-based로 추출해 dispatch 후 turn에서도 sub 매칭`
- `fix(aggregator): _dedupe_by_message_id가 tools_used도 merge (count 합산)`
- `chore(release): bump to 0.6.3 + handoff 갱신 (hot-fix)`

### F-5. v0.6.4: offset 갱신 정책 명문화 (2026-04-23)

**의도:** 사용자가 한 번 입력하면 token-tracker는 한 번만 출력하고, 그 출력에는 그 입력에 대한 메인의 모든 응답 turn + 모든 sub 결과가 누적되어야 한다.

**핵심 변경:**
- `hooks/on_stop.py`: offset 갱신 정책을 코드 주석으로 명문화 — `on_stop은 absolutely offset을 갱신하지 않는다. 유일한 갱신점은 on_user_prompt`. (실제 코드는 이미 정책대로지만 주석이 없어 미래 누군가 `state["offset"] = file_size`를 다시 추가할 위험이 있었음.)
- 회귀 가드 e2e 테스트 2건:
  - `test_offset_not_advanced_by_stop_so_summary_accumulates_across_turns`: turn 1만 있을 때 첫 Stop → turn 1 + turn 2 있을 때 두 번째 Stop. last_summary가 누적되어 turns≥2 + total_input_tokens 증가 검증.
  - `test_offset_resets_on_new_user_prompt`: 새 user_prompt가 들어오면 그 시점의 file_size로 offset 초기화. 두 번째 사용자 입력의 last_summary는 이전 입력의 turn을 포함하지 않음.

**왜 dedupe로 충분한가:** 매 Stop은 user_prompt 시점부터의 모든 entries를 반복 read한다. 비용 측면에서는 `_read_tail` + parse가 매번 실행되지만 turns/subs는 `_dedupe_by_message_id`(turn) + `tool_use_id` 매칭(sub)으로 정합성이 유지된다. 장기 turn(수십 응답)에서 read 비용이 문제되면 후속에서 incremental cache로 최적화 가능.

**테스트 +2건. 243 → 245 passing.**

**커밋:**
- `fix(hook): on_stop이 offset을 갱신하지 않음 — 한 사용자 입력에 대한 누적 last_summary 보존`
- `test(e2e): offset 누적 정책 회귀 가드`
- `chore(release): bump to 0.6.4 + handoff 갱신 (offset 정책)`

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

1. 사용자가 방향을 잡아주면 (위 C'/D 중), 해당 작업에 대한 **plan 문서**를 `writing-plans` skill로 만든다 (`docs/superpowers/plans/YYYY-MM-DD-token-tracker-<topic>.md`).
2. plan 승인 후 `subagent-driven-development` skill로 실행.
3. Phase 1에서 발견된 엣지케이스(4번 섹션)를 참고해 같은 함정에 빠지지 않게 한다.

사용자가 "다음 작업 바로 진행"이라고 하면 **C'(`/token-history`)** 부터 제안하고 확인받아라.

---

## 8. 중요 경로·태그 참조

| 항목 | 값 |
|---|---|
| 플러그인 repo | `/Users/brody/Desktop/token-tracker/` |
| marketplace manifest | `.claude-plugin/marketplace.json` (repo 루트) |
| plugin 디렉터리 | `plugins/token-tracker/` (plugin.json, hooks/, lib/, tests/, config.json) |
| Claude Code 설치 경로 | `~/.claude/plugins/cache/token-tracker-local/token-tracker/0.1.0/` |
| state 디렉터리 | `~/.claude/plugins/token-tracker/state/` |
| 에러 로그 | `~/.claude/plugins/token-tracker/log/error.log` |
| 최신 태그 | `v0.6.4` (offset 갱신 정책 명문화) |
| 주요 태그 | `v0.1.0-mvp`, `v0.2.0` (marketplace), `v0.3.0` (`/token-detail`), `v0.3.1` (hotfix), `v0.4.0` (verbose), `v0.5.0` (`/token-verbose`), `v0.5.1` (리뷰 MAJOR 회수), `v0.6.0` (subagent 토큰), `v0.6.1` (리뷰 보강 + timing 회귀 fix), `v0.6.2` (sub 모델 표시 + 정확 비용), `v0.6.3` (launches 윈도우 + tools_used 회귀 hot-fix), `v0.6.4` (offset 정책 명문화) |
| 테스트 수 | 245 passing (v0.6.4 offset 정책 회귀 가드 후) |
| 테스트 실행 | `./venv/bin/pytest plugins/token-tracker/tests -q` (repo 루트 기준) |
