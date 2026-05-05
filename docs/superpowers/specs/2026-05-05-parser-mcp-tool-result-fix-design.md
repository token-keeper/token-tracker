# Parser MCP `tool_result.content` 누락 fix — design (v0.8.1)

> 핫픽스: `/token-history` 의 turn 카드를 펼쳤을 때 일부 도구의 TOOL RESULT 섹션이 비어 보이는 회귀를 수정한다.

---

## 1. 배경

`/token-history` (v0.8.0) 출시 후, 일부 turn 의 TOOL RESULT 섹션이 비어 보이는 현상이 보고됨. 원인 조사 결과:

`lib/parser.py` 의 `parse_tool_result` 가 `block.content` (list 형태) 를 normalize 할 때 `type == "text"` block 만 추출하고 나머지 block 은 무시한다. transcript jsonl 에 실제 등장하는 block type 통계 (token-tracker repo 기준 최근 3개 세션):

| content block type | 빈도 | 현재 처리 |
|---|---|---|
| `__str__` (raw string) | 342 | OK |
| `text` (list 안) | 146 | OK |
| `tool_reference` (MCP `ToolSearch` 결과 등) | 20 | **빈 문자열로 떨어짐** |
| `image` (Playwright `browser_take_screenshot` 등) | 7 | **빈 문자열로 떨어짐** |

이로 인해 `transcript_entries[*].content` 가 `""` 가 되고, history web UI 가 빈 섹션을 자동 생략하면서 사용자에게는 "TOOL RESULT 가 없는 turn" 으로 보임.

## 2. 목표

1. 알려진 4종 block (`text`, `tool_reference`, `image`, raw string) 을 모두 사람이 읽을 수 있는 placeholder string 으로 정규화.
2. 미래에 새 block type 이 등장해도 조용히 빈 문자열로 떨어지지 않도록 방어 placeholder (`[<type>]`) 출력.
3. history.jsonl schema 변경 없음 — `content` 필드는 여전히 string.

## 3. 비목표 (out-of-scope)

- 이미 저장된 history.jsonl entry 의 backfill / migration.
- image base64 raw 데이터의 history.jsonl 보존 (context bloat 분석은 별도 follow-up).
- history_renderer / web UI (templates, css, js) 변경.
- localhost HTTP 서버 (B), pricing data/code 분리 (C) 등 다른 follow-up.

## 4. 변경 범위

### 4.1 신규 helper

`lib/parser.py` 에 신규 private 함수 추가:

```python
def _normalize_tool_result_block(block: dict) -> str:
    """Normalize a single content block inside tool_result.content into
    a human-readable string. Returns "" for unparseable blocks (skipped
    by caller)."""
```

### 4.2 `parse_tool_result` 수정

기존 `for sub in raw:` 루프를 helper 호출로 대체:

```python
elif isinstance(raw, list):
    parts = [_normalize_tool_result_block(b) for b in raw if isinstance(b, dict)]
    text = "\n".join(p for p in parts if p)
```

(string / 기타 케이스는 기존 동작 그대로 유지)

### 4.3 버전 bump

- `plugins/token-tracker/plugin.json` : `0.8.0` → `0.8.1`
- `.claude-plugin/marketplace.json` : 동일

## 5. 변환 규칙

| input block | output |
|---|---|
| `{"type":"text","text":"hello"}` | `"hello"` |
| `{"type":"text","text":""}` | `""` (skip) |
| `{"type":"text"}` (text 누락) | `""` (skip) |
| `{"type":"tool_reference","tool_name":"TaskCreate"}` | `"[tool_reference] TaskCreate"` |
| `{"type":"tool_reference"}` (tool_name 누락) | `"[tool_reference]"` |
| `{"type":"image","source":{"type":"base64","media_type":"image/png","data":"<b64>"}}` | `"[image: image/png, <N> bytes]"` |
| `{"type":"image","source":{"media_type":"image/png"}}` (data 누락) | `"[image: image/png]"` |
| `{"type":"image","source":{"data":"<b64>"}}` (media_type 누락) | `"[image: <N> bytes]"` |
| `{"type":"image","source":{}}` (둘 다 누락) | `"[image]"` |
| `{"type":"image"}` (source 누락) | `"[image]"` |
| `{"type":"foo_block","x":1}` (unknown) | `"[foo_block]"` |
| `{}` (type 누락) | `""` (skip) |

### Image size 계산

`size = len(data) * 3 // 4` — base64 padding 무시한 근사. 정확한 값(padding 보정)을 원할 정도의 정밀도가 필요하지 않으므로 단순화. data 가 string 이 아니거나 비어 있으면 size 생략.

### `\n.join` 시 빈 문자열 skip

helper 가 `""` 를 반환한 block 은 join 결과에서 제외 (`p for p in parts if p`). 이로 인해 빈 줄이 생기지 않음.

## 6. 테스트

`tests/test_parser.py` 에 신규 케이스 14개 추가.

### 6.1 `_normalize_tool_result_block` 단위 (10개)

| # | input | expected |
|---|---|---|
| 1 | `{"type":"text","text":"hello"}` | `"hello"` |
| 2 | `{"type":"text","text":""}` | `""` |
| 3 | `{"type":"tool_reference","tool_name":"TaskCreate"}` | `"[tool_reference] TaskCreate"` |
| 4 | `{"type":"tool_reference"}` | `"[tool_reference]"` |
| 5 | `{"type":"image","source":{"type":"base64","media_type":"image/png","data":"A"*1024}}` | `"[image: image/png, 768 bytes]"` |
| 6 | `{"type":"image","source":{"media_type":"image/png"}}` | `"[image: image/png]"` |
| 7 | `{"type":"image"}` | `"[image]"` |
| 8 | `{"type":"some_new_block","x":1}` | `"[some_new_block]"` |
| 9 | `{}` | `""` |
| 10 | `{"type":"text"}` | `""` |

### 6.2 `parse_tool_result` 통합 (4개)

| # | scenario | expected |
|---|---|---|
| 11 | content = string (regression guard) | 기존 동작 그대로 |
| 12 | content = mixed `[text, tool_reference]` | `"a\n[tool_reference] X"` |
| 13 | content = `[tool_reference, tool_reference]` (실측 케이스) | `"[tool_reference] TaskCreate\n[tool_reference] TaskUpdate"` |
| 14 | content = `[{}]` (타입 누락 block) | `""` |

전체 테스트 카운트: 327 → 341.

## 7. 호환성

- **history.jsonl schema**: 변경 없음. `transcript_entries[*].content` 는 여전히 string.
- **`SUPPORTED_SCHEMA_VERSIONS`**: bump 안 함.
- **이미 저장된 빈 string entry**: 그대로 둔다 (transcript 가 source of truth, 다음 prompt 부터 새 데이터로 채워짐).
- **history_renderer**: 손 안 댐. 현재 `if content:` 로 빈 섹션 자동 생략하던 로직은 placeholder 가 채워지면 자연스럽게 표시 모드로 전환됨.

## 8. Definition of Done

1. 신규 14개 + 기존 327개 = 341/341 테스트 통과 (`./venv/bin/pytest plugins/token-tracker/tests -q`).
2. `plugin.json` / `marketplace.json` 버전 v0.8.1 반영.
3. PR 생성 → 사용자 리뷰 → 승인 후 머지.

## 9. 리스크 / 고려사항

- **`\n.join` 단일 패스 유지**: v0.8.0 의 placeholder collision 회귀 (chained replace 로 인한 토큰 재치환) 와는 무관한 함수지만, 단순 join 으로 처리해서 동일 함정 없음.
- **새 MCP 서버가 등장**: `ListMcpResourcesTool` 등 향후 다른 MCP 도구가 새 block type 을 반환하면 `[<type>]` placeholder 가 web UI 에 노출됨. 이게 인지 신호로 작동 → 그때 helper 에 처리 추가하면 됨.
- **size 단위**: byte 만 표시. KB/MB 환산은 의도적으로 안 함 (정확한 byte 가 디버깅 시 더 유용).
