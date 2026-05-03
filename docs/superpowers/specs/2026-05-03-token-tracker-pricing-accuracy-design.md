# token-tracker pricing 정확도 v2 설계 문서

**작성일**: 2026-05-03
**대상 릴리스**: v0.7.0
**원 핸드오프 항목**: D — 가격표 정확도 개선 / Team 플랜 대응
**요약**: Opus 4.7 단가 회귀(3배 overbill) fix + prompt cache 1h tier 분리.
**리뷰 반영**: 7개 적대적 서브에이전트 리뷰 후 CRITICAL 2건 + MAJOR 8건 + MINOR 9건 반영. (거부 2건은 §15 명시.)

---

## 1. 목적과 범위

### 1.1 동기

사용자(Brody) statusline에 표시되는 비용과 token-tracker 한 줄 요약 비용이 **2~3배 차이**나는 문제를 해결한다.

### 1.2 진단 단계에서 확정된 두 가지 원인

**원인 A — Opus 단가 회귀 (영향 큼)**

`lib/pricing.py`에 박힌 Opus 4.7 단가가 옛 Opus 4 / 4.1 시대 단가($15/MT input)다. Anthropic은 Opus 4.5부터 단가를 1/3로 인하했고($5/MT), 우리는 미반영. 결과적으로 Opus 사용 turn마다 약 3배 overbill.

| 항목 (회귀 발생 항목 표시) | 현재 코드 | 공식 (2026-05-03 fetch) |
|---|---|---|
| Opus 4.7 input | $15.0/MT | **$5.0/MT** ⚠️ |
| Opus 4.7 output | $75.0/MT | **$25.0/MT** ⚠️ |
| Opus 4.7 5m write | $18.75/MT | **$6.25/MT** ⚠️ |
| Opus 4.7 1h write | (없음) | **$10.0/MT** (신규) |
| Opus 4.7 cache read | $1.5/MT | **$0.50/MT** ⚠️ |
| Sonnet 4.6 전체 | 일치 | 일치 |
| Haiku 4.5 전체 | 일치 | 일치 |

⚠️ 표시는 회귀 발생 항목 — 모두 회귀 가드 테스트 필수 (§9.1).

**원인 B — prompt cache 1h tier 미분리 (영향 작음~중간)**

transcript JSONL의 `usage.cache_creation`은 `ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens`로 분리되어 박혀 있다. 우리 parser는 legacy 합산 필드(`cache_creation_input_tokens`)만 읽고, pricing.py는 5m 단가만 적용. 1h tier가 우세한 세션은 underbill (1h 단가는 5m의 1.6배).

진단 캡처 데이터(이번 세션 첫 turn):
```
"cache_creation": {
  "ephemeral_1h_input_tokens": 42180,
  "ephemeral_5m_input_tokens": 0
}
```
즉 100% 1h tier — 시스템 프롬프트·CLAUDE.md 등 큰 컨텍스트가 1h로 캐시됨.

### 1.3 진단으로 봉쇄된 길 (= 외부 source 접근 불가)

다음은 진단 단계에서 "외부 데이터 접근 불가"로 확인되어 이번 spec에서 다룰 수 없는 것들 (§14 "의식적 YAGNI"와는 다른 범주):

- **Stop hook stdin에 cost 필드 없음** — 1줄 PR로 statusline 값을 그대로 가져오는 길 봉쇄.
- **transcript JSONL에도 cost 필드 없음** — Claude Code가 client-side 추정만 메모리에 보관.

따라서 우리 자체 retail 추정의 정확도를 끌어올리는 길만 남음 — 그게 원인 A + B를 동시에 fix하는 이번 작업.

---

## 2. 핵심 결정 사항

| 항목 | 결정 | 근거 |
|---|---|---|
| 단가 source | `https://platform.claude.com/docs/en/about-claude/pricing` (2026-05-03 fetch) | 공식 가격표 |
| 데이터 모델 | `cache_creation_tokens` 단일 필드 → `cache_creation_5m_tokens` + `cache_creation_1h_tokens` 두 필드 (제거 + 추가) | transcript shape과 1:1, 진실의 출처 단일화 |
| transcript 구버전 entry fallback | `cache_creation` 중첩 객체 없으면 합산값을 5m로 간주 | 1h tier 없던 시절 데이터 가정. **방향: underbill** (5m 단가가 더 낮으므로 비용을 낮게 추정) — §10 진단으로 fallback 실제 활성 여부 확인 필수 |
| cache_creation 객체 + legacy 동시 박힌 라인 처리 | 중첩 객체 우선 — legacy 합산 무시 | 신버전 transcript 표준 패턴 (둘 다 박힘). `if not cc:` 분기로 안전. 회귀 가드 테스트 §9.1에 명시 |
| schema_version bump | v2 → v3 | 직렬화 구조 변경 |
| backward compat (옛 last_summary) | v1/v2 파일은 load 시 None 반환 + stderr 1줄 로그, 옛 파일 호환 마이그레이션 코드 작성 안 함 | 사용자 명시 결정: "옛 메모리 삭제하고 처음부터 쌓자" — KISS |
| 옛 session 디렉터리 디스크 정리 | 이번 spec 범위 밖 (별도 GC task) | 새 코드가 안 읽으니 잔존해도 무해 |
| **detail_formatter cache 칼럼** | `cache_creation_5m_tokens + cache_creation_1h_tokens` 합산 표시 (단일 칼럼 유지) | dataclass 필드 제거 시 detail.py 즉시 크래시 방지 — 변경 범위에 detail_formatter 포함 (§8) |
| **detail.py schema gate** | `(1, 2)` → `(3,)` 동기 갱신 | v3 bump 후 detail.py가 v3 거부하지 않도록 — 변경 범위에 detail.py 포함 (§8) |
| **silent $0 모델 안전장치** | `_resolve_rates` None 시 stderr 1줄 emit | 미등록 모델 alias 진입 시 검증 단계에서 false-positive 방지 (§11) |
| **parser 헬퍼 추출** | spec에 명시 안 함 — 구현 detail로 plan/구현 단계에 위임 | KISS는 구현 단계에서 자연 적용. spec scope 폭증 방지 (DRY 위반은 reviewer가 코드리뷰에서 잡음) |
| 1h 단가 검증 | spec에 박힌 절대값 fix (계산식 아님) | 공식 페이지 fetch로 확정 |
| 다른 Opus 변형(4.5, 4.6) 단가 | 추가 안 함 (PRICING dict에 키만 없음) — silent $0 안전장치(§11)로 detection 가능 | YAGNI: 사용자가 4.7 외 안 씀 |
| Data residency 1.1x multiplier | 무시 | 사용자 default global inference |
| Fast mode 6x premium | 무시 | Opus 4.6 only, 사용자 미사용 |

---

## 3. 데이터 모델 변경

### 3.1 `lib/parser.py` — `TurnUsage`

```python
@dataclass
class TurnUsage:
    model: str
    input_tokens: int
    output_tokens: int
    # 제거: cache_creation_tokens
    cache_creation_5m_tokens: int = 0   # 신규 — default와 fallback 분기 동일 의미
    cache_creation_1h_tokens: int = 0   # 신규
    cache_read_tokens: int
    tools_used: list[dict] = field(default_factory=list)
    # ... (다른 필드 변경 없음)
```

dataclass `default=0`과 §4 fallback의 1h 값(=0)은 **동일**. 단 5m 값은 의미가 다르다 — default는 "값 없음/zero", fallback은 "legacy 합산값을 5m tier로 매핑"한 양수일 수 있음. default를 변경하는 순간(예: -1 sentinel) 1h 분기는 갈라지므로 한쪽만 바꾸면 안 된다는 점 코드 코멘트로 명시.

### 3.2 `lib/parser.py` — `SubagentUsage`

같은 패턴으로 `cache_creation_tokens` 제거 + `cache_creation_5m_tokens` / `cache_creation_1h_tokens` 두 필드 추가.

두 dataclass는 codebase 내부 전용이라 외부 backward-compat 부담 없음.

---

## 4. parser 변경

> **§10 진단 통과 전제** — 이번 brainstorming 진단은 메인 jsonl `message.usage.cache_creation` 중첩 객체 shape만 확인됨. `toolUseResult.usage` (foreground sub) 와 sidechain `message.usage` (async sub)는 미확인. plan 1단계 진단 결과에 따라 함수별 fallback이 갈라질 수 있음. spec §4 추출 로직은 "동일 shape" 가정 기반.

세 함수가 동일 패턴으로 변경:

- `parse_line` — 메인 jsonl assistant 라인의 `message.usage`
- `parse_tool_result_for_agent` — foreground sub의 `toolUseResult.usage`
- `parse_sidechain_assistant` — async sub의 sidechain `message.usage`

공통 추출 로직 (헬퍼 추출 여부는 구현 자유):
```python
cc = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
cache_5m = int(cc.get("ephemeral_5m_input_tokens", 0))
cache_1h = int(cc.get("ephemeral_1h_input_tokens", 0))
# fallback: cache_creation 중첩 객체가 없는 옛 entry는 합산값을 5m로 간주.
# 방향: underbill (1h tier가 섞여있다면 실제보다 낮게 표시) — §10 진단으로
# 옛 entry가 실재하는지 먼저 확인. 실재하지 않으면 fallback은 dead path가
# 되므로 향후 제거 가능.
if not cc:
    cache_5m = int(usage.get("cache_creation_input_tokens", 0))
    cache_1h = 0
```

`cache_read`는 5m/1h 단가 동일($0.50/$0.30/$0.10/MT)이라 분리 없이 `cache_read_input_tokens` 합산값 그대로 사용. **Anthropic이 향후 cache_read에 1h tier 별도 단가를 도입하면 silent underbill** — 코드 코멘트에 "단가 분리 시 재검토" 명시. 회귀 가드 테스트는 추가하지 않음 (공지 없으면 자동 detection 불가) — 단가 페이지 모니터링은 외부 활동으로 둠.

### 4.1 입력 검증 정책 (비범위 명시)

`int(cc.get(...))` 형태의 추출 로직은 기존 parser와 동일한 best-effort 수준. transcript가 손상/조작되어 비-int값이 박히면 `parse_line`이 통째 raise하지만, 이는 **기존 코드와 동일 동작**이라 신규 회귀 아님. 추가 입력 검증(`isinstance(v, int)` + `max(0, v)` 클램프 등)은 이번 spec 범위 밖.

---

## 5. pricing 변경

### 5.1 `lib/pricing.py` — `PRICING` dict 전면 갱신

```python
# Source: https://platform.claude.com/docs/en/about-claude/pricing
# Fetched: 2026-05-03
# 회귀 fix: Opus 4.7은 4.5부터 단가가 1/3로 인하됐는데 우리는 옛 단가($15)를 박아둠.
#
# 가정:
# - prompt cache write는 5m / 1h 두 tier만 존재 (Anthropic 2년간 두 tier 유지).
#   30m/4h 등 새 tier 추가 시 PRICING 키 + parser + summary_store v4 bump 필요.
# - cache_read는 모든 tier 단가 동일 (5m/1h 모두 동일 cache_read 단가).
#   향후 분리되면 spec/회귀 재검토.
# - 단가 변경 시 §9.1의 절대값 회귀 가드 테스트
#   (test_pricing_opus_4_7_all_rates_absolute, test_pricing_sonnet_4_6_1h_..., test_pricing_haiku_4_5_1h_...)
#   도 같이 갱신. 안 갱신하면 정당한 단가 변경이 회귀로 오인됨.
PRICING = {
    "claude-opus-4-7": {
        "input": 5.0,
        "output": 25.0,
        "cache_creation_5m": 6.25,
        "cache_creation_1h": 10.0,
        "cache_read": 0.50,
    },
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_creation_5m": 3.75,
        "cache_creation_1h": 6.0,
        "cache_read": 0.30,
    },
    "claude-haiku-4-5": {
        "input": 1.0,
        "output": 5.0,
        "cache_creation_5m": 1.25,
        "cache_creation_1h": 2.0,
        "cache_read": 0.10,
    },
}
```

### 5.2 `compute_cost`

```python
def compute_cost(model: str, usage) -> float:
    rates = _resolve_rates(model)
    if rates is None:
        return 0.0   # silent $0 — §11 안전장치로 stderr 경고 emit
    per = 1_000_000.0
    return (
        usage.input_tokens * rates["input"] / per
        + usage.output_tokens * rates["output"] / per
        + usage.cache_creation_5m_tokens * rates["cache_creation_5m"] / per
        + usage.cache_creation_1h_tokens * rates["cache_creation_1h"] / per
        + usage.cache_read_tokens * rates["cache_read"] / per
    )
```

`is_known_model` / `effective_billing_model` / `_resolve_rates`는 변경 없음 (단, §11 stderr 경고가 `_resolve_rates` 또는 호출 시점에 추가됨).

---

## 6. aggregator 변경

`aggregate()`의 단일 누적 패스에서 `total_input` 계산식만 두 필드 합산으로:

```python
total_input += (
    item.input_tokens
    + item.cache_creation_5m_tokens
    + item.cache_creation_1h_tokens
    + item.cache_read_tokens
)
```

다른 부분(`_dedupe_by_message_id`, `_attach_subagents`, `Summary` 시그니처)은 변경 없음 — **단, §10 진단 5번 결과가 "cache_creation 객체가 dedupe-keep 라인에 안 박혀있음"으로 나오면 `_dedupe_by_message_id`에 cache field merge 로직 추가 필요** (예상 +20~40 LOC). 그 경우 §6 spec 갱신 + 회귀 가드 테스트 1건 추가 (`test_dedupe_keeps_5m_1h_from_kept_line`은 §9.1에 이미 명시).

`Summary.total_input_tokens`는 여전히 4가지 (`input + cache_5m + cache_1h + cache_read`) 합산값.

`cache_hit_rate = cache_read / total_input` 의미: 수치는 동일하지만 **cache_creation tier 비중 변동 시 분모 노이즈 발생**(5m이 많으면 분모가 작고, 1h가 많으면 분모가 큼). 해석 의미는 이전과 동일하지만 엄밀한 isomorphic은 아님 — 후속 task에서 5m/1h 분리 hit rate 검토 가능.

`Summary` 자체에 5m/1h 분리 합산 필드 **추가 안 함** (YAGNI — 필요 시점에 추가).

---

## 7. summary_store 변경

### 7.1 SCHEMA_VERSION bump

```python
SCHEMA_VERSION = 3
SUPPORTED_SCHEMA_VERSIONS = (3,)   # v1, v2 제거
```

### 7.2 `_TURN_KEYS` / `_SUB_KEYS` 갱신

- 제거: `cache_creation_tokens`
- 추가: `cache_creation_5m_tokens`, `cache_creation_1h_tokens`

dataclass 신규 필드와 `_TURN_KEYS` 화이트리스트의 동기화는 수동 — 누락 시 silent drop. **§3.1 dataclass 변경과 §7.2 화이트리스트 갱신은 같은 PR에 반드시 동시 포함** (한쪽만 머지되면 직렬화/역직렬화 비대칭). 회귀 가드는 §15 follow-up (lint 테스트는 이번 spec 범위 밖).

### 7.3 v1/v2 파일 처리

`load_last_summary`가 `schema_version not in SUPPORTED_SCHEMA_VERSIONS` 분기에서 stderr에 한 줄 로그 + None 반환. 기존 코드와 동일 패턴이고 마이그레이션 헬퍼는 추가하지 않는다.

### 7.4 자연 정리 흐름

- 같은 session의 옛 파일은 다음 Stop hook 발화 시 v3 형식으로 새로 저장되어 자연 덮어쓰기 (path 동일 — §9.2 e2e에서 path 동일성 assert).
- 다른 옛 session 파일들은 디스크에 잔존하지만 v0.7.0 코드가 안 읽으니 무해. 디스크 정리는 별도 GC task로 분리.

### 7.5 사용자 영향

업그레이드 직후 첫 `/token-detail` 호출 결과:
- **같은 session에 직전 Stop hook이 v0.6.x로 저장한 파일이 있으면** → "데이터 없음" 응답. 다음 Stop hook 발화 1번이면 v3 파일이 생성되어 정상 동작.
- 새 session에서는 처음부터 v3 파일 생성, 이슈 없음.

§7.3의 stderr 한 줄 로그는 **통상 케이스에서 사용자에게 보이지 않음** — Claude Code skill output pipe는 stdout만 본문에 표시. stderr는 디버깅용이라 통상 UX에 영향 없음 (사용자가 직접 hook 디버깅 시 grep으로 v1/v2 load 빈도 추적 가능).

---

## 8. detail 표시 변경 (CRITICAL — 변경 범위 명시)

### 8.1 `lib/detail_formatter.py`

`detail_formatter.py:200,226`의 `turn.cache_creation_tokens` / `sub.cache_creation_tokens` 직접 참조를 합산 표현으로 교체:

```python
# 기존: f"{turn.cache_creation_tokens:,}"
# 신규:
f"{(turn.cache_creation_5m_tokens + turn.cache_creation_1h_tokens):,}"
```

`cache` 칼럼 의미 동일(legacy 합산값과 동일 결과). 5m/1h 분리 노출은 비범위 (§14).

### 8.2 `skills/token-detail/scripts/detail.py`

`detail.py:58`의 schema 화이트리스트 동기 갱신:

```python
# 기존: if data.get("schema_version") not in (1, 2):
# 신규: if data.get("schema_version") not in (3,):
```

이 두 변경(8.1, 8.2)이 누락되면 v0.7.0 출시 직후 `/token-detail` 호출 즉시 크래시 + 옛/새 schema 모두 거부. 반드시 같은 PR에 포함.

---

## 9. 테스트 전략

### 9.1 단위 테스트 (신규 ~17건)

**`tests/test_parser.py` 추가**
- `test_parse_line_extracts_5m_and_1h_separately`
- `test_parse_line_falls_back_to_legacy_when_no_cache_creation_obj`
- `test_parse_line_prefers_nested_cc_when_both_present` — 중첩 `{5m:1000,1h:2000}` + legacy `cache_creation_input_tokens:3000` 동시 박은 라인에서 결과가 5m=1000/1h=2000이고 legacy 3000은 무시됨 명시 assertion (이중 카운팅 회귀 가드)
- `test_parse_line_handles_5m_1h_matrix` — 4-매트릭스 parametrize (5m=0/1h=0, 5m>0/1h=0, 5m=0/1h>0, 둘 다 양수)
- `test_parse_tool_result_for_agent_extracts_5m_1h`
- `test_parse_sidechain_assistant_extracts_5m_1h`

**`tests/test_pricing.py` 추가**
- `test_pricing_opus_4_7_all_rates_absolute` — input=$5, output=$25, 5m=$6.25, 1h=$10, cache_read=$0.50 5개 절대값 가드 (단가 변경 시 같이 갱신 필요 코멘트)
- `test_pricing_sonnet_4_6_1h_is_6_dollars_per_mtok` — 1h 단가 절대값 가드
- `test_pricing_haiku_4_5_1h_is_2_dollars_per_mtok` — 1h 단가 절대값 가드
- `test_pricing_1h_more_expensive_than_5m_for_all_models` — 분리 누락 회귀 가드
- `test_compute_cost_combines_5m_and_1h_correctly`
- `test_compute_cost_emits_stderr_for_unknown_model` — silent $0 안전장치 (§11)

**`tests/test_aggregator.py` 추가**
- `test_total_input_includes_both_5m_and_1h`
- `test_aggregate_cost_uses_per_tier_rates`
- `test_aggregate_5m_1h_uses_sub_model_rates` — parent=opus + sub=haiku에 sub.cache_creation_1h_tokens=1000일 때 haiku 1h 단가($2.0/MT) 적용 검증
- `test_dedupe_keeps_5m_1h_from_kept_line` — dedupe가 cache 객체를 keep된 line에서 가져오는지 (§10 진단 결과 thinking 라인과 tool_use 라인의 위치에 따라 갈림)

**`tests/test_summary_store.py` 추가**
- `test_load_v3_roundtrip` — 5m/1h 양수 양쪽 직렬화/역직렬화 fixture에 명시
- `test_load_v1_returns_none`
- `test_load_v2_returns_none`
- `test_save_writes_v3`

### 9.2 e2e 테스트 (신규 ~3건)

- `test_e2e_pricing_with_real_transcript_shape` — 이번 진단에서 캡처한 실제 1h-heavy transcript fixture로 정확 비용 검증.
- `test_e2e_v2_summary_load_returns_none_then_next_stop_creates_v3_at_same_path` — 자연 마이그레이션. **path 동일성 assert** (`path_before == path_after` + `read(path).schema_version == 3`).
- `test_e2e_detail_renders_after_v3_save` — detail_formatter + detail.py가 v3 파일 정상 표시 (CRITICAL #1, #2 회귀 가드).

### 9.3 기존 테스트 영향 (정량)

`cache_creation_tokens` / `cache_creation_input_tokens` 인용 fixture/assertion이 **약 94곳**에 분포 (grep 기준 — fixture 헬퍼 포함 시 +α):
- `test_hook_end_to_end.py`: 25곳
- `test_sidechain.py`: 15곳
- `test_parser.py`: 13곳
- `test_aggregator.py`: 14곳
- `test_pricing.py`: 11곳
- `test_summary_store.py`: 9곳
- `test_detail_formatter.py`: 6곳
- `test_detail_script_e2e.py`: 1곳
- 기타 fixture 헬퍼 (`_mk`, `_turn`, `_sub`, hook stdin builders)

**갱신 작업은 본 v0.7.0 PR에 반드시 포함** (별도 commit으로 분리해도 OK, 별도 PR로는 분리 금지). 누락 시 v0.7.0 머지 직후 245개 기존 테스트가 빨갛게 깨진 채로 release되어 CI 게이트 fail. 같은 PR 안에 다음 task가 모두 들어가야 함:
1. fixture 헬퍼들에서 `cache_creation_tokens=N` → `cache_creation_5m_tokens=N` (보수적 가정 — fixture는 옛 시절 데이터 의도) 또는 명시적으로 5m/1h 분리.
2. cost 기댓값 하드코딩 갱신 — Opus 단가 1/3 인하로 모든 cost assert가 깨짐. 신단가 기반으로 재계산.
3. 일부 fixture는 **신규 1h-tier shape**로 마이그레이션해 e2e 1h tier 회귀 슈트 확보 (현재 fixture 모두 단일 필드 형식이라 1h tier 회귀 못 잡음).

**예상 카운트**: 245 → ~280 passing (신규 ~20건 + 기존 95+곳 갱신).

---

## 10. plan 1단계 사전 진단

본 코드 작업 진입 전 **추가 진단 1턴 필요**. 진단 코드는 **별도 disposable script**(`scripts/diagnose_v0_7_shapes.py`)로 작성하고 commit하지 않는다. parser/hook 본체에 임시 print를 삽입하지 않는다 (옛 진단 흐름의 commit 누출 위험 회피).

진단 항목:
1. **toolUseResult.usage shape** (foreground sub) — `cache_creation` 중첩 객체 동일하게 박혀있는지.
2. **sidechain message.usage shape** (async sub) — 동일.
3. **cache_creation 객체와 legacy `cache_creation_input_tokens`가 동시에 박힌 라인의 빈도** — 둘 다 박힌 케이스가 표준이면 §4 fallback `if not cc:`가 정상 동작 검증.
4. **`cache_creation == {}` (빈 dict) + `cache_creation_input_tokens > 0` 조합 존재 여부** — 현 §4 fallback `if not cc:`가 빈 dict도 falsy로 처리해 자연 cover하지만, 이 진단은 빈도 측정 + 보강 분기 필요 여부 판단용. 빈도가 무시 못 할 수준이면 fallback을 `if not cc or (cache_5m == 0 and cache_1h == 0)`로 보강.
5. **dedupe 대상 message_id 그룹 중 `cache_creation` 객체가 어느 라인(thinking/text/tool_use)에 박히는지** — 첫 라인(thinking)에 안 박혀 있으면 `_dedupe_by_message_id`가 5m/1h를 0으로 잡는 회귀 위험. 진단 결과에 따라 dedupe 로직 보강 또는 spec §6 변경.
6. **구버전(`cache_creation` 중첩 객체 없는) entry 실재 여부** — 실재 안 하면 §4 fallback path는 dead code → spec에서 제거 + raise/log 결정.

진단 결과에 따른 spec 수정 분기 기준:
- shape이 모든 함수에서 동일 + legacy 동시 박힘 표준 + cache 객체가 첫 라인에 박힘 → spec 그대로 진행.
- shape이 함수별로 다름 → §4 추출 로직을 함수별 fallback으로 갈라냄.
- 키 이름이 다름(예: `cache_writes`) → 별도 함수 또는 mapping 추가, spec 보강.
- dedupe 그룹의 첫 라인에 cache 객체 없음 → `_dedupe_by_message_id`가 cache 필드도 merge하도록 보강.

---

## 11. silent $0 안전장치

`_resolve_rates`가 미등록 모델 alias에 대해 None을 반환할 때 `compute_cost`가 0.0을 silent 반환. 검증 단계(§12)에서 사용자가 statusline과 비교 시 차이를 "1h tier 미반영"으로 오진할 위험.

### 11.1 변경

`_resolve_rates` 또는 `compute_cost` 안에서 첫 발견 시 1회 stderr 1줄 emit:

```python
sys.stderr.write(f"[token-tracker] unknown pricing model: {model}\n")
```

같은 model에 대한 중복 경고 방지를 위해 module-level set으로 once-emit (구현 detail). emit 위치는 구현 자유 — `_resolve_rates`가 None 반환 직전 또는 `compute_cost`가 0.0 반환 직전 어느 쪽이든 OK. `effective_billing_model`이 sub_model에서 parent로 fallback할 때 parent가 known model이면 emit 안 함 (이미 정상 처리).

### 11.2 회귀 가드

`test_compute_cost_emits_stderr_for_unknown_model` (§9.1).

---

## 12. 사용자 최종 검증

코드 머지 직전, 사용자 1턴 검증:

1. v0.7.0 코드 적용 (source + cache 동기화)
2. 사용자가 짧은 메시지 1턴
3. 응답 끝나면 두 값 비교:
   - statusline의 `💰 $X.XXX` 표시값
   - token-tracker 한 줄 요약 `비용 $Y.YYYY`
4. 결과:
   - **일치 (±5% 오차)** → D 작업 success → 머지 + v0.7.0 태그
   - **여전히 큰 차이** → 추가 원인 조사 (이번 spec 범위 밖, follow-up issue 발급)

### 12.1 ±5% 임계값 근거

±5%는 다음 노이즈 합산을 cover하는 마진:
- output token 모델 추정 오차 (±1~2%)
- statusline의 client-side 추정 알고리즘이 우리 retail 단가 적용과 미세 다를 가능성 (±1~2%)
- round-trip / 라인 분할 dedupe 누적 오차 (±1%)

±5% 초과 시 잔여 원인 (예: Team 플랜 할인율, 다른 모델 silent $0 등) 조사 필요. 측정 기준은 **한 turn 비용** (누적 세션 아님). 5%는 worst-case 합산이며 RSS로 보면 약 3% — 둘 중 어느 메트릭으로 봐도 통과면 일치 판단.

### 12.2 검증 시 silent $0 모델 확인

검증 1턴 동안 §11 stderr 경고가 발생하는지 확인. 발생하면 "일치 ±5%"가 가짜 일치(둘 다 부분 데이터)일 수 있으므로 해당 모델을 PRICING dict에 추가 후 재검증.

---

## 13. 릴리스 메모

- **버전**: v0.7.0 (minor bump — schema_version v2 → v3 호환성 깨짐, dataclass 필드 제거)
- **태그**: `v0.7.0`
- **CHANGELOG / handoff**:
  - 핸드오프 5.D 항목 ✅ 완료 표시
  - **Opus 4.7 단가 1/3 인하 반영** — 이전 버전 대비 Opus turn당 비용 표시가 약 1/3 수준으로 줄어듦. 이는 Anthropic의 공식 가격 인하(Opus 4.5부터)를 늦게 반영한 결과지 token-tracker 버그 아님. 핸드오프 + 릴리스 노트에 환산 가이드 명시 (예: "v0.6.x에서 $0.30 표시 → v0.7.0에서 약 $0.10 표시"). 또한 옛 누적 비용(메모리·핸드오프에 적힌 v0.6.x 비용)과 v0.7.0 비용 직접 비교는 의미 없음 — 비교 시 환산 적용 필요.
  - schema_version v3 breaking change — 옛 last_summary 파일은 자연 무시됨 (사용자 액션 불필요). 첫 응답 후 `/token-detail`이 일시적으로 빈 결과 가능 — 1턴 후 정상화.
- **새 핸드오프 문서** (`docs/handoff/2026-05-03-token-tracker-next-steps.md`) 생성, 다음 candidate task(C' `/token-history` 등) 갱신
- **첫 emit banner (선택)**: v0.7.0 첫 발화 1회에 한 줄 "Opus 단가 인하 반영 완료 (v0.7.0)" 노출 가능 — UX 시끄러우면 핸드오프 안내로 충분. **선택 여부는 사용자 결정** (구현자가 임의 결정하지 말 것). 핸드오프/CHANGELOG 안내로 충분하면 banner 생략.

---

## 14. 비범위 (의식적 YAGNI)

이번 spec scope에서 의식적으로 제외:

- Opus 4.5 / 4.6 / 4.1 등 Opus 변형 단가 추가 — silent $0 안전장치(§11)로 detection 가능. 등장 시 follow-up.
- Sonnet 4.5 / Sonnet 4 / Haiku 3.5 등 다른 모델 — 사용자 미사용 모델/할인 전부.
- Data residency 1.1x multiplier
- Fast mode 6x premium
- Batch API 50% discount
- Team 플랜 할인율 config override (사용자가 진단 결과 statusline과 일치하면 불필요. 차이 잔존 시 follow-up)
- detail 표에 5m/1h 분리 컬럼 노출
- 옛 session 디렉터리 디스크 GC
- last_summary v1/v2 파일 마이그레이션 헬퍼
- pricing 데이터/코드 분리 (`lib/pricing_data.json`) — 사용자 결정으로 follow-up
- 30m / 4h 등 **새 prompt cache tier 추가** — Anthropic 공지 시 별도 spec/PR로 처리 (parser/PRICING/summary_store 동시 갱신 필요)
- tier 표현 dict 구조 (`cache_creation: dict[tier, int]`) — 사용자 결정으로 두 필드 분리 유지
- parser 추출 로직 헬퍼 추출 — 구현 detail로 plan/구현 단계에 위임
- `_TURN_KEYS` ↔ dataclass 필드 lint 테스트 — follow-up

각 항목은 필요 시점에 별도 spec/plan으로 다룬다.

---

## 15. 적대적 리뷰 거부 항목 (의도적)

7개 적대적 리뷰에서 제기된 항목 중 의도적으로 거부:

- **MAJOR #8 — parser 헬퍼 추출 (DRY)**: KISS는 plan/구현 단계에서 자연 적용. spec scope 폭증 방지. 코드리뷰에서 reviewer가 잡으면 됨.
- **MINOR #28 — `_TURN_KEYS` ↔ dataclass lint 테스트**: 같은 이유 (구현 detail). silent drop 위험 작음 — `_TURN_KEYS` 갱신은 이번 PR diff에서 명시적 변경이라 누락 가능성 낮음.

다른 항목은 모두 본 spec에 반영됨 (CRITICAL 5건 → 등급 재평가 후 #1, #2 CRITICAL 유지 + #3 MAJOR 강등 + #4, #5 MINOR 강등; MAJOR 8건 반영; MINOR 9건 일괄 반영).
