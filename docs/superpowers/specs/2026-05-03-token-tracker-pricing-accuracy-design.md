# token-tracker pricing 정확도 v2 설계 문서

**작성일**: 2026-05-03
**대상 릴리스**: v0.7.0
**원 핸드오프 항목**: D — 가격표 정확도 개선 / Team 플랜 대응
**요약**: Opus 4.7 단가 회귀(3배 overbill) fix + prompt cache 1h tier 분리.

---

## 1. 목적과 범위

### 1.1 동기

사용자(Brody) statusline에 표시되는 비용과 token-tracker 한 줄 요약 비용이 **2~3배 차이**나는 문제를 해결한다.

### 1.2 진단 단계에서 확정된 두 가지 원인

**원인 A — Opus 단가 회귀 (영향 큼)**

`lib/pricing.py`에 박힌 Opus 4.7 단가가 옛 Opus 4 / 4.1 시대 단가($15/MT input)다. Anthropic은 Opus 4.5부터 단가를 1/3로 인하했고($5/MT), 우리는 미반영. 결과적으로 Opus 사용 turn마다 약 3배 overbill.

| 항목 | 현재 코드 | 공식 (2026-05-03 fetch) |
|---|---|---|
| Opus 4.7 input | $15.0/MT | **$5.0/MT** |
| Opus 4.7 output | $75.0/MT | **$25.0/MT** |
| Opus 4.7 5m write | $18.75/MT | **$6.25/MT** |
| Opus 4.7 1h write | (없음) | **$10.0/MT** |
| Opus 4.7 cache read | $1.5/MT | **$0.50/MT** |
| Sonnet 4.6 전체 | 일치 | 일치 |
| Haiku 4.5 전체 | 일치 | 일치 |

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

### 1.3 검증된 비범위

진단 단계에서 다음이 확인되어 이번 spec에서 다루지 않는다:

- **Stop hook stdin에는 cost 필드 없음** — 1줄 PR로 statusline 값을 그대로 가져오는 길은 봉쇄됨. (statusline의 `cost.total_cost_usd`는 statusLine hook 전용 payload.)
- **transcript JSONL에도 cost 필드 없음** — Claude Code가 client-side 추정만 메모리에 보관.
- 따라서 우리 자체 retail 추정의 정확도를 끌어올리는 길만 남음 — 그게 원인 A + B를 동시에 fix하는 이번 작업.

---

## 2. 핵심 결정 사항

| 항목 | 결정 | 근거 |
|---|---|---|
| 단가 source | `https://platform.claude.com/docs/en/about-claude/pricing` (2026-05-03 fetch) | 공식 가격표 |
| 데이터 모델 | `cache_creation_tokens` 단일 필드 → `cache_creation_5m_tokens` + `cache_creation_1h_tokens` 두 필드 (제거 + 추가) | transcript shape과 1:1, 진실의 출처 단일화 |
| transcript 구버전 entry fallback | `cache_creation` 중첩 객체 없으면 합산값을 5m로 간주 | 1h tier 없던 시절 데이터 가정 (보수적 — 단가 낮은 쪽) |
| schema_version bump | v2 → v3 | 직렬화 구조 변경 |
| backward compat (옛 last_summary) | v1/v2 파일은 load 시 None 반환, 옛 파일 호환 마이그레이션 코드 작성 안 함 | 사용자 명시 결정: "옛 메모리 삭제하고 처음부터 쌓자" — KISS |
| 옛 session 디렉터리 디스크 정리 | 이번 spec 범위 밖 (별도 GC task) | 새 코드가 안 읽으니 잔존해도 무해 |
| detail 표 컬럼 분리 표시 | 안 함 — `cache` 단일 칼럼 유지 | YAGNI: statusline 비교가 D 작업의 목표, 표 컬럼 추가는 별개 task |
| 1h 단가 검증 | spec에 박힌 절대값 fix (계산식 아님) | 공식 페이지 fetch로 확정 |
| 다른 Opus 변형(4.5, 4.6) 단가 | 추가 안 함 (PRICING dict에 키만 없음) | YAGNI: 사용자가 4.7 외 안 씀. 다른 모델 transcript 등장 시 silent $0 → 별도 follow-up task |
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
    cache_creation_5m_tokens: int = 0   # 신규
    cache_creation_1h_tokens: int = 0   # 신규
    cache_read_tokens: int
    tools_used: list[dict] = field(default_factory=list)
    # ... (다른 필드 변경 없음)
```

### 3.2 `lib/parser.py` — `SubagentUsage`

같은 패턴으로 `cache_creation_tokens` 제거 + `cache_creation_5m_tokens` / `cache_creation_1h_tokens` 두 필드 추가.

두 dataclass는 codebase 내부 전용이라 외부 backward-compat 부담 없음.

---

## 4. parser 변경

세 함수가 동일 패턴으로 변경:

- `parse_line` — 메인 jsonl assistant 라인의 `message.usage`
- `parse_tool_result_for_agent` — foreground sub의 `toolUseResult.usage`
- `parse_sidechain_assistant` — async sub의 sidechain `message.usage`

공통 추출 로직:
```python
cc = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
cache_5m = int(cc.get("ephemeral_5m_input_tokens", 0))
cache_1h = int(cc.get("ephemeral_1h_input_tokens", 0))
# fallback: cache_creation 중첩 객체 없는 구버전 entry는 합산값을 5m로 간주
if not cc:
    cache_5m = int(usage.get("cache_creation_input_tokens", 0))
    cache_1h = 0
```

`cache_read`는 5m/1h 단가 동일($0.50/$0.30/$0.10/MT)이라 분리 없이 `cache_read_input_tokens` 합산값 그대로 사용.

---

## 5. pricing 변경

### 5.1 `lib/pricing.py` — `PRICING` dict 전면 갱신

```python
# Source: https://platform.claude.com/docs/en/about-claude/pricing
# Fetched: 2026-05-03
# 회귀 fix: Opus 4.7은 4.5부터 단가가 1/3로 인하됐는데 우리는 옛 단가($15)를 박아둠.
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
        return 0.0
    per = 1_000_000.0
    return (
        usage.input_tokens * rates["input"] / per
        + usage.output_tokens * rates["output"] / per
        + usage.cache_creation_5m_tokens * rates["cache_creation_5m"] / per
        + usage.cache_creation_1h_tokens * rates["cache_creation_1h"] / per
        + usage.cache_read_tokens * rates["cache_read"] / per
    )
```

`is_known_model` / `effective_billing_model` / `_resolve_rates`는 변경 없음.

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

다른 부분(`_dedupe_by_message_id`, `_attach_subagents`, `Summary` 시그니처)은 변경 없음. `Summary.total_input_tokens`는 여전히 4가지 합산값으로, `cache_hit_rate = cache_read / total_input` 의미 유지.

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

### 7.3 v1/v2 파일 처리

`load_last_summary`가 `schema_version not in SUPPORTED_SCHEMA_VERSIONS` 분기에서 stderr에 한 줄 로그 + None 반환. 기존 코드와 동일 패턴이고 마이그레이션 헬퍼는 추가하지 않는다.

### 7.4 자연 정리 흐름

- 같은 session의 옛 파일은 다음 Stop hook 발화 시 v3 형식으로 새로 저장되어 자연 덮어쓰기 (path 동일).
- 다른 옛 session 파일들은 디스크에 잔존하지만 v0.7.0 코드가 안 읽으니 무해. 디스크 정리는 별도 GC task로 분리.

### 7.5 사용자 영향

업그레이드 직후 첫 `/token-detail` 호출 결과:
- **같은 session에 직전 Stop hook이 v0.6.x로 저장한 파일이 있으면** → "데이터 없음" 응답. 다음 Stop hook 발화 1번이면 v3 파일이 생성되어 정상 동작.
- 새 session에서는 처음부터 v3 파일 생성, 이슈 없음.

---

## 8. 테스트 전략

### 8.1 단위 테스트 (신규 ~12건)

**`tests/test_parser.py` 추가**
- `test_parse_line_extracts_5m_and_1h_separately`
- `test_parse_line_falls_back_to_legacy_when_no_cache_creation_obj`
- `test_parse_tool_result_for_agent_extracts_5m_1h`
- `test_parse_sidechain_assistant_extracts_5m_1h`

**`tests/test_pricing.py` 추가**
- `test_pricing_opus_4_7_input_is_5_dollars_per_mtok` — **3배 overbill 회귀 가드** (assertion에 `5.0` 절대값 명시)
- `test_pricing_1h_more_expensive_than_5m_for_all_models` — 분리 누락 회귀 가드
- `test_compute_cost_combines_5m_and_1h_correctly`

**`tests/test_aggregator.py` 추가**
- `test_total_input_includes_both_5m_and_1h`
- `test_aggregate_cost_uses_per_tier_rates`

**`tests/test_summary_store.py` 추가**
- `test_load_v3_roundtrip`
- `test_load_v1_returns_none`
- `test_load_v2_returns_none`
- `test_save_writes_v3`

### 8.2 e2e 테스트 (신규 ~2건)

- `test_e2e_pricing_with_real_transcript_shape` — 이번 진단에서 캡처한 실제 1h-heavy transcript fixture로 정확 비용 검증.
- `test_e2e_v2_summary_load_returns_none_then_next_stop_creates_v3` — 자연 마이그레이션 흐름.

### 8.3 기존 테스트 영향

`cache_creation_tokens` 필드를 직접 참조하는 기존 테스트가 있다면 `cache_creation_5m_tokens` (호환 fallback과 동일) 또는 명시적 5m/1h 분리로 갱신. 회귀 가드 1h tier 추가 단가가 우연히 깨는 케이스 없는지 확인.

**예상 카운트**: 245 → ~260 passing.

---

## 9. plan 1단계 사전 진단

본 코드 작업 진입 전 **추가 진단 1턴 필요**:

이번 brainstorming 진단에서 확인된 건 **메인 jsonl `message.usage.cache_creation` 중첩 객체**의 shape뿐이다. 다음 두 곳도 같은 shape인지 미확인:

- `toolUseResult.usage` (foreground sub의 결과 라인)
- sidechain jsonl `message.usage` (async sub)

진단 방법: 같은 stdin/transcript dump 패턴으로 1턴 trigger 후 shape 비교. 같으면 spec의 공통 추출 로직 그대로 진행. 다르면 parser 함수별로 다른 fallback 적용 (plan 1단계에서 spec 보강).

---

## 10. 사용자 최종 검증

코드 머지 직전, 사용자 1턴 검증:

1. v0.7.0 코드 적용 (source + cache 동기화)
2. 사용자가 짧은 메시지 1턴
3. 응답 끝나면 두 값 비교:
   - statusline의 `💰 $X.XXX` 표시값
   - token-tracker 한 줄 요약 `비용 $Y.YYYY`
4. 결과:
   - **일치 (±5% 오차)** → D 작업 success → 머지 + v0.7.0 태그
   - **여전히 큰 차이** → 추가 원인 조사 (이번 spec 범위 밖, follow-up issue 발급)

---

## 11. 릴리스 메모

- **버전**: v0.7.0 (minor bump — pricing 단가 회귀 fix는 사실상 동작 큰 변경, schema_version v2 → v3 호환성 깨짐)
- **태그**: `v0.7.0`
- **CHANGELOG / handoff**:
  - 핸드오프 5.D 항목 ✅ 완료 표시
  - Opus 4.7 단가 회귀 fix 명시 (사용자가 옛 비용 표시 vs 신 비용 표시 차이 인지)
  - schema_version v3 breaking change — 옛 last_summary 파일은 자연 무시됨 (사용자 액션 불필요)
- **새 핸드오프 문서** (`docs/handoff/2026-05-03-token-tracker-next-steps.md`) 생성, 다음 candidate task(C' `/token-history` 등) 갱신

---

## 12. 비범위 (YAGNI)

- Opus 4.5 / 4.6 / 4.1 등 Opus 변형 단가 추가
- Sonnet 4.5 / Sonnet 4 / Haiku 3.5 등 다른 모델
- Data residency 1.1x multiplier
- Fast mode 6x premium
- Batch API 50% discount
- Team 플랜 할인율 config override (사용자가 진단 결과 statusline과 일치하면 불필요. 차이 잔존 시 follow-up)
- detail 표에 5m/1h 분리 컬럼 노출
- 옛 session 디렉터리 디스크 GC
- last_summary v1/v2 파일 마이그레이션 헬퍼

각 항목은 필요 시점에 별도 spec/plan으로 다룬다.
