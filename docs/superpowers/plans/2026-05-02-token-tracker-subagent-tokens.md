₩# `/token-detail` Subagent 토큰 표시 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/token-detail` 표에 Agent tool로 호출된 subagent의 토큰·비용·시간을 부모 turn의 자식 행(`└ ...`)으로 표시한다. 현재 누락 구간을 transcript의 `toolUseResult` 데이터로 메운다.

**Architecture:**
- transcript JSONL의 `type=="user"` 라인에는 `toolUseResult.agentType`/`totalTokens`/`usage`가 이미 기록돼 있음 (검증 완료)
- parser가 이를 `SubagentUsage` 데이터클래스로 추출 → aggregator가 부모 turn에 `tool_use_id` 매칭으로 attach → formatter가 부모 행 다음에 들여쓰기 행으로 렌더 → Stop 한 줄 요약은 메인+subagent 합산값을 그대로 사용 (자연스럽게 통합)

**Tech Stack:** Python 3.10+ stdlib only, pytest, Claude Code plugin/skill system. 기존 `lib/aggregator`, `lib/pricing`, `lib/detail_formatter`, `lib/i18n` 재사용.

---

## 결정 사항 (브리핑)

| ID | 결정 |
|---|---|
| D1 | 부모 turn 매칭 — assistant `tool_use.id` ↔ user `tool_result.tool_use_id` 일치 (검증 완료, 1/1) |
| D2 | async agent 결과 라인 형식 — Phase 0에서 실측 후 처리. 누락 시 future-work로 명시 |
| D3 | 데이터 모델 — `TurnUsage.subagents: list[SubagentUsage]` 부모에 attach (별도 turn 리스트 X) |
| D4 | detail 표 표시 — 부모 행 직후 `└ {agentType}` 들여쓰기 자식 행 |
| D5 | Stop 한 줄 요약 — 메인+subagent 합산만 (분리표기 없음) |
| D6 | subagent 비용 산정 — 부모 turn의 model 단가로 계산 + footer 주석 1줄 ("subagent 비용은 부모 모델 단가로 추정") |
| D7 | async agent 처리 — foreground + async 둘 다 처리 (Phase 0에서 sidechain jsonl 발견됨) |
| D8 | async subagent 행 표시 — launch한 부모 turn 아래 들여쓰기 (foreground와 동일) |

---

## 작업 원칙

- **테스트 실행 경로**: 반드시 repo 루트에서 `./venv/bin/pytest plugins/token-tracker/tests -q`
- **커밋 규칙**: 각 Task 말미에 한 번 커밋. Conventional Commits 포맷, 한국어 본문
- **TDD 순서**: 테스트 먼저 작성 → 실패 확인 → 구현 → 통과 확인 → 커밋
- **기존 테스트 깨짐 방지**: parser/aggregator 변경 Task는 기존 테스트도 함께 업데이트
- **하위 호환성**: 기존 `Summary` schema_version=1을 유지 가능한지 검토. subagent 필드 추가가 schema 변경이면 v2로 bump하고 `summary_store.load_last_summary`가 v1도 읽되 subagents 빈 배열로 normalize

---

## Phase 0: async agent 결과 라인 형식 조사 ✅ 완료 (2026-05-02)

**조사 결과 (코드 변경 X, 데이터 검증만):**

### foreground agent (동기)
- 메인 jsonl의 `type=="user"` 라인에서 `toolUseResult.status == "completed"` + `agentType` + `totalTokens` + `usage` 한 라인으로 통합 기록
- 매칭 키: 메인 turn의 `tool_use.id` ↔ 결과 라인의 `tool_result.tool_use_id` (1/1 검증됨)

### async/background agent (비동기)
- 메인 jsonl에는 `status: async_launched` + `outputFile` 라인만 들어옴 (완료 라인 X)
- 완료 결과는 **별도 sidechain jsonl 파일**에 저장:
  - 경로: `{transcript_dir}/{session_id}/subagents/agent-{agentId}.jsonl`
  - 또는 symlink: `/private/tmp/claude-501/{project}/{session_id}/tasks/{agentId}.output → 위 jsonl`
  - 형식: 메인 jsonl과 **완전히 동일** (`type==assistant`, `usage` 필드, `model` 필드). 차이는 `isSidechain: true` + `agentId` 필드
  - 토큰 정보가 sidechain jsonl의 assistant 라인 `message.usage`에 정상 기록됨 (검증됨)
- 한 세션에 다수 sidechain 파일 (background agent당 1개)

### 결론 (D7=2, D8=1 반영)
- foreground: `parse_tool_result_for_agent`로 메인 jsonl에서 한 라인씩 추출
- async: 메인 jsonl의 `async_launched` 라인에서 `(tool_use_id, agentId)` 쌍 수집 → sidechain jsonl 디렉터리 스캔 → `agent-{agentId}.jsonl` 파일을 기존 `parse_line`으로 파싱 → 같은 `tool_use_id`로 launch한 부모 turn에 attach
- async sidechain 파일이 누락(아직 안 끝났거나 디스크에서 사라짐)된 경우: 그 호출만 skip하고 계속 진행 (graceful degradation)

---

## Task 1: parser 확장 — `SubagentUsage` + foreground/async 양쪽 추출

**Files:**
- Modify: `plugins/token-tracker/lib/parser.py`
- Modify: `plugins/token-tracker/tests/test_parser.py`

**범위 (Phase 0 결론 반영):**
1. `SubagentUsage` dataclass: `agent_type`, `usage 4필드`, `total_duration_ms`, `tool_use_id`, `agent_id` (async 매핑용)
2. `parse_tool_result_for_agent(entry)`: 메인 jsonl의 user 라인에서 **foreground** subagent 추출 (status=="completed" + totalTokens)
3. `parse_async_launch(entry)`: 메인 jsonl의 user 라인에서 `(tool_use_id, agent_id)` 쌍 추출 (status=="async_launched")
4. `parse_sidechain_assistant(entry, agent_type)`: sidechain jsonl의 assistant 라인을 `SubagentUsage`로 변환 (기존 `parse_line` 로직 재사용 가능, 단 agent_type/agent_id 주입)

- [ ] **Step 1.1: 테스트 추가 (TDD red)**

`test_parser.py`:
- `test_parse_tool_result_returns_none_for_non_user_lines`: assistant 라인은 None
- `test_parse_tool_result_returns_none_when_no_agent_type`: 일반 tool_result는 None
- `test_parse_tool_result_extracts_agent_usage`: `toolUseResult.agentType` + `usage` 4필드 추출 확인
- `test_parse_tool_result_extracts_tool_use_id`: 매칭용 `tool_use_id` 추출 확인 (`message.content[].tool_use_id`)
- `test_parse_tool_result_skips_async_launched`: Phase 0 결론에 따라 분기 (async는 일단 None 또는 별도 처리)

- [ ] **Step 1.2: 구현**

```python
@dataclass
class SubagentUsage:
    agent_type: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    total_duration_ms: int = 0
    tool_use_id: str = ""  # for matching to parent turn
    # tools_used: optional, derive from toolStats if needed

def parse_tool_result_for_agent(entry: dict) -> SubagentUsage | None:
    if not isinstance(entry, dict) or entry.get("type") != "user":
        return None
    tur = entry.get("toolUseResult")
    if not isinstance(tur, dict) or "agentType" not in tur:
        return None
    if tur.get("status") != "completed":
        return None  # skip async_launched + 진행 중
    usage = tur.get("usage") or {}
    if not isinstance(usage, dict):
        return None
    # tool_use_id from inner tool_result block
    msg = entry.get("message") or {}
    content = msg.get("content") or []
    tool_use_id = ""
    for blk in content:
        if isinstance(blk, dict) and blk.get("type") == "tool_result":
            tool_use_id = blk.get("tool_use_id", "")
            break
    return SubagentUsage(
        agent_type=str(tur.get("agentType", "")),
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cache_creation_tokens=int(usage.get("cache_creation_input_tokens", 0)),
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
        total_duration_ms=int(tur.get("totalDurationMs", 0)),
        tool_use_id=tool_use_id,
    )
```

- [ ] **Step 1.3: 기존 `parse_line`은 변경 없음** (assistant 라인만 처리하는 책임 그대로)

- [ ] **Step 1.4: 테스트 통과 확인**

- [ ] **Step 1.5: 커밋** — `feat(parser): SubagentUsage + parse_tool_result_for_agent 추가`

---

## Task 2: TurnUsage에 subagents 필드 + aggregator 매칭

**Files:**
- Modify: `plugins/token-tracker/lib/parser.py` (`TurnUsage` dataclass)
- Modify: `plugins/token-tracker/lib/aggregator.py`
- Modify: `plugins/token-tracker/tests/test_aggregator.py`

- [ ] **Step 2.1: TurnUsage에 `subagents: list[SubagentUsage]` 필드 추가**

`field(default_factory=list)`로 기본값. 부모 turn의 tool_use 블록에서 Agent 이름 호출이 있을 때 매칭된 SubagentUsage가 들어감.

- [ ] **Step 2.2: aggregator 진입점 시그니처 검토**

현재 `aggregate(turns: list[TurnUsage], elapsed: float)`만 받음. 이제 `subagents: list[SubagentUsage]`도 같이 받게 변경:

```python
def aggregate(
    turns: list[TurnUsage],
    elapsed: float,
    subagents: list[SubagentUsage] | None = None,
) -> Summary:
```

부모 매칭 로직: `subagents`를 순회하며, `turn.tool_use_id_set`(아래 참조)에 포함된 sub만 turn.subagents에 append. 부모 못 찾은 sub는 로그 후 drop (또는 unattached 리스트로 보관 — Phase 0 결론에 따라 결정).

- [ ] **Step 2.3: parser에 부모 turn의 tool_use_id 수집 추가**

`parse_line`이 반환하는 `TurnUsage`에 `agent_tool_use_ids: list[str]` 필드 추가 (assistant 라인의 `tool_use` 블록 중 `name=="Agent"`의 `id` 모음). aggregator가 이걸로 매칭.

- [ ] **Step 2.4: Summary에 합계 갱신**

`Summary.total_input_tokens`, `total_output_tokens`, `cache_hit_rate`, `total_cost`가 **메인 turn + 모든 subagent**를 포함해야 함. dedup은 메시지 ID 기준으로 메인 turn 한 번만 — subagent는 별도 record라 dedup 무관.

- [ ] **Step 2.5: 테스트 추가**
- `test_aggregate_attaches_subagent_to_parent_by_tool_use_id`
- `test_aggregate_unmatched_subagent_is_dropped` (또는 unattached 분리 — D2 결과 따라)
- `test_aggregate_total_tokens_includes_subagent_usage`
- `test_aggregate_cache_hit_rate_includes_subagent_cache`

- [ ] **Step 2.6: 기존 테스트 업데이트** — `aggregate()` 호출부에서 subagents 파라미터 누락분 보강 (default None이면 기존과 동일 동작)

- [ ] **Step 2.7: 커밋** — `feat(aggregator): subagent를 부모 turn에 attach + 합계 포함`

---

## Task 3: hook의 데이터 흐름 통합 (foreground + async)

**Files:**
- Modify: `plugins/token-tracker/hooks/on_stop.py`
- Create: `plugins/token-tracker/lib/sidechain.py` (sidechain 디렉터리 발견 + 파싱)
- Modify: `plugins/token-tracker/tests/test_hook_end_to_end.py`

**sidechain 디렉터리 derivation:**
- `transcript_path = ~/.claude/projects/{project}/{session_id}.jsonl`
- 부모 디렉터리에 `{session_id}/subagents/agent-*.jsonl` 가 있을 수 있음
- **존재하지 않으면 graceful skip** (디스크에서 청소된 경우 + 첫 호출 직후 케이스)

- [ ] **Step 3.1: on_stop.py가 entries에서 두 종류 추출**

```python
turns = [t for t in (parse_line(e) for e in entries) if t is not None]
subagents = [s for s in (parse_tool_result_for_agent(e) for e in entries) if s is not None]
summary = aggregate(turns, elapsed=elapsed, subagents=subagents)
```

- [ ] **Step 3.2: flush polling 조건도 turn 기준 그대로 유지** (subagent 라인이 늦게 들어와도 turn이 있으면 진행)

- [ ] **Step 3.3: e2e 테스트 추가**

`tests/fixtures/sample_session_with_subagent.jsonl` 신규 — Agent 호출 + 결과 라인 포함된 미니 세션.

테스트:
- `test_stop_includes_subagent_in_total`: 메인 1 turn + sub 1개 → systemMessage 합계가 두 합 일치
- `test_last_summary_persists_subagents`: state/.../last_summary.json에 subagents가 직렬화됨

- [ ] **Step 3.4: 커밋** — `feat(hook): Stop hook이 transcript의 subagent usage도 집계`

---

## Task 4: summary_store schema bump

**Files:**
- Modify: `plugins/token-tracker/lib/summary_store.py`
- Modify: `plugins/token-tracker/tests/test_summary_store.py`

- [ ] **Step 4.1: schema_version 결정**
- 옵션 A: schema_version=2로 bump, v1 파일은 `subagents=[]` normalize 후 로드
- 옵션 B: schema_version=1 유지, 단순 누적 호환 (subagents 없을 때 [] default)
- 🤖 추천: **A** — 새 필드가 추가되면 명시적 bump가 바람직 (이전 v0.3.x도 동일 패턴). `/token-detail` 스크립트의 schema_version 체크에서 v1과 v2 둘 다 허용

- [ ] **Step 4.2: 직렬화/역직렬화 — subagents 리스트도 dict로 dump/load**

- [ ] **Step 4.3: 테스트** — v1 file → v2 normalize, v2 file → 그대로 load

- [ ] **Step 4.4: 커밋** — `feat(state): schema_version=2 + subagents 직렬화`

---

## Task 5: detail_formatter 계층 행

**Files:**
- Modify: `plugins/token-tracker/lib/detail_formatter.py`
- Modify: `plugins/token-tracker/lib/i18n/ko.json`
- Modify: `plugins/token-tracker/lib/i18n/en.json`
- Modify: `plugins/token-tracker/tests/test_detail_formatter.py`
- Modify: `plugins/token-tracker/tests/test_i18n_loader.py` (expected_keys 갱신)

- [ ] **Step 5.1: i18n 키 추가**
- `subagent_row_prefix` (예: `└` ko/en 동일)
- `subagent_legend` (`* subagent 비용은 부모 모델 단가로 추정` / `* subagent cost is estimated using parent model rate`)

- [ ] **Step 5.2: format_detail 변경**

각 turn 행을 출력한 직후, `turn.subagents`를 순회하며 자식 행을 추가:
- `#` 칼럼: 빈 칸
- `모델` 칼럼: `└ {agent_type}`
- `input/cc/cr/output`: subagent 자체 값
- `비용`: 부모 turn의 model 단가로 pricing.compute_cost 호출
- `시간`: `total_duration_ms / 1000` 표시
- `툴`: 빈 칸 또는 toolStats 요약 (선택)

부모 model이 없으면 (drop된 unmatched sub) 행 끝에 `?` 표시 — D2 결정에 따름.

- [ ] **Step 5.3: footer에 legend 추가**

기존 `legend` 라인 아래 `subagent_legend` 한 줄. subagent가 0건일 때는 출력 생략.

- [ ] **Step 5.4: 테스트**
- `test_detail_renders_subagent_row_under_parent`
- `test_detail_subagent_legend_appears_only_when_subagents_present`
- `test_detail_subagent_cost_uses_parent_model_rate`

- [ ] **Step 5.5: i18n loader 테스트의 expected_keys에 새 키 2개 추가**

- [ ] **Step 5.6: 커밋** — `feat(detail): subagent 행을 계층(└)으로 표시 + legend`

---

## Task 6: pricing 재사용 검증 + 엣지 케이스

**Files:**
- Modify: `plugins/token-tracker/tests/test_pricing.py` (필요 시)

- [ ] **Step 6.1: 기존 `compute_cost(model, usage_dict)` 그대로 재사용 가능한지 검증**

subagent의 `cache_creation_input_tokens`에 `ephemeral_5m`/`ephemeral_1h` tier 분리가 있어야 정확. 현재 pricing이 어느 tier로 계산하는지 확인 후 차이 발견 시 별도 Task로 분리.

- [ ] **Step 6.2: subagent의 모델 단가 대안 케이스**
- 부모 turn이 못 찾은 unmatched subagent → 비용 0 표시 + 행은 그대로 출력 (옵션) 또는 skip

- [ ] **Step 6.3: 커밋 (변경이 있으면)**

---

## Task 7: handoff 문서 + 버전 bump + 종합 테스트

**Files:**
- Create: `docs/handoff/2026-05-02-token-tracker-next-steps.md` (이전 문서 갱신본)
- Modify: `plugins/token-tracker/.claude-plugin/plugin.json` (버전 bump)
- Modify: `.claude-plugin/marketplace.json` (버전 동기화)

- [ ] **Step 7.1: 전체 테스트 실행 후 N/N passing 확인**

- [ ] **Step 7.2: handoff 문서 갱신**
- 섹션 5에 새 항목 F. `/token-detail` subagent 표시 ✅ 추가
- 다음 작업 후보를 C' (`/token-history`) 또는 D (가격표) 그대로 유지
- v0.5.1 → v0.6.0 bump 명시 (minor — 기능 추가)

- [ ] **Step 7.3: 버전 bump (0.6.0)**

- [ ] **Step 7.4: 커밋** — `chore(release): bump to 0.6.0 + handoff 업데이트`

---

## Task 8: 병렬 코드리뷰 + 머지

- [ ] **Step 8.1: PR 생성** (또는 단일 브랜치라면 push 후 작업 일시정지)

- [ ] **Step 8.2: 7개 병렬 리뷰 에이전트 spawn**
- 아키텍처, 원칙, 중복/복잡도, 사이드이펙트/에러, 보안, 성능, 테스트 커버리지

- [ ] **Step 8.3: CRITICAL 0건 확인** (글로벌 룰)

- [ ] **Step 8.4: MAJOR/MINOR 사용자 보고 + 수정 결정**

- [ ] **Step 8.5: 사용자 승인 후 머지 + 태그 (v0.6.0)**

---

## 위험·미해결 사항

1. **async agent 추적 불가능 시**: D2 Phase 0 결과에 따름. 누락된 8개 호출을 어떻게 다룰지는 future-work로 명시 (별도 plan).
2. **부모 모델 단가 가정**: D6에 명시. legend로 사용자에게 알림. 정확성보다 일관성 우선.
3. **schema_version=2 마이그레이션**: 기존 사용자의 last_summary.json은 다음 Stop에 자동 갱신되므로 영향 없음.
4. **subagent의 tools_used**: toolStats가 있지만 메인 turn의 tools_used와 형식이 다름. v0.6.0에서는 표시 생략하고 v0.6.x에서 추가 검토.

---

## 완료 정의

- [ ] N/N tests passing (현재 141 + 새 테스트 ~15 → 156+ 예상)
- [ ] `/token-detail` 표에 subagent 행이 부모 turn 아래 들여쓰기로 표시됨
- [ ] Stop 한 줄 요약의 합계가 메인+subagent 통합값
- [ ] CRITICAL 0건 코드리뷰 통과
- [ ] handoff 문서 + 버전 v0.6.0
