# Parser MCP `tool_result.content` 누락 fix — implementation plan (v0.8.1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/token-history` 의 turn 카드에서 일부 도구의 TOOL RESULT 섹션이 비어 보이는 v0.8.0 회귀를 수정한다 (MCP `tool_reference`, `image` 등 비-text content block 미처리).

**Architecture:** `lib/parser.py` 의 `parse_tool_result` 안 inline 분기를 신규 helper `_normalize_tool_result_block(block: dict) -> str` 로 추출한다. helper 는 `text` / `tool_reference` / `image` / unknown 4종 분기로 placeholder string 을 반환한다. 미래의 새 block type 도 `[<type>]` 로 방어적 placeholder 를 출력해 동일 회귀를 막는다.

**Tech Stack:** Python 3 (stdlib only) · pytest · pytest.mark.parametrize

**Spec:** `docs/superpowers/specs/2026-05-05-parser-mcp-tool-result-fix-design.md`

---

## File Structure

| 파일 | 작업 | 책임 |
|---|---|---|
| `plugins/token-tracker/lib/parser.py` | Modify | 신규 `_normalize_tool_result_block` helper 추가, `parse_tool_result` 의 list 분기를 helper 호출로 교체 |
| `plugins/token-tracker/tests/test_parser.py` | Modify | helper 단위 테스트 12 + 통합 테스트 3 = 신규 15 |
| `plugins/token-tracker/.claude-plugin/plugin.json` | Modify | version `0.8.0` → `0.8.1` |
| `.claude-plugin/marketplace.json` | Modify | version `0.8.0` → `0.8.1` |

테스트 카운트: 327 → 342 통과.

---

## Task 0: feature 브랜치 생성 + 기존 spec 파일 commit

**Files:**
- Modify: git branch state
- Add: `docs/superpowers/specs/2026-05-05-parser-mcp-tool-result-fix-design.md` (이미 작성됨, untracked)

- [ ] **Step 1: main 최신화 + feature 브랜치 생성**

```bash
git checkout main
git pull origin main
git checkout -b feature/v0.8.1-parser-mcp-tool-result-fix
```

- [ ] **Step 2: spec 파일 commit**

```bash
git add docs/superpowers/specs/2026-05-05-parser-mcp-tool-result-fix-design.md
git commit -m "$(cat <<'EOF'
docs(spec): v0.8.1 parser MCP tool_result.content fix 디자인

/token-history 의 turn 카드에서 일부 도구의 TOOL RESULT 섹션이
비어 보이는 회귀(parse_tool_result 가 text 외 block 무시) 수정 디자인.
EOF
)"
```

---

## Task 1: helper `_normalize_tool_result_block` 추가 + 단위 테스트 (TDD)

**Files:**
- Modify: `plugins/token-tracker/lib/parser.py` (helper 추가, 기존 코드 그대로)
- Modify: `plugins/token-tracker/tests/test_parser.py` (parametrize 단위 테스트 1개 추가)

- [ ] **Step 1: 단위 테스트 작성 (실패 테스트)**

`plugins/token-tracker/tests/test_parser.py` 의 `# parse_tool_call / parse_tool_result` 섹션 (line 755 근처) 직전에 다음 추가:

```python
# ---------------------------------------------------------------------------
# _normalize_tool_result_block
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("block,expected", [
    # text
    ({"type": "text", "text": "hello"}, "hello"),
    ({"type": "text", "text": ""}, ""),
    ({"type": "text"}, ""),
    # tool_reference (MCP ToolSearch 결과)
    ({"type": "tool_reference", "tool_name": "TaskCreate"}, "[tool_reference] TaskCreate"),
    ({"type": "tool_reference"}, "[tool_reference]"),
    # image (Playwright screenshot 등)
    (
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "A" * 1024}},
        "[image: image/png, 768 bytes]",
    ),
    ({"type": "image", "source": {"media_type": "image/png"}}, "[image: image/png]"),
    ({"type": "image", "source": {"data": "A" * 1024}}, "[image: 768 bytes]"),
    ({"type": "image", "source": {}}, "[image]"),
    ({"type": "image"}, "[image]"),
    # unknown type 방어 placeholder
    ({"type": "some_new_block", "x": 1}, "[some_new_block]"),
    # type 키 누락 → skip
    ({}, ""),
])
def test_normalize_tool_result_block(block, expected):
    assert parser._normalize_tool_result_block(block) == expected
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

```bash
cd /Users/brody/Desktop/token-tracker
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py::test_normalize_tool_result_block -v
```

Expected: 모든 12 case `AttributeError: module 'lib.parser' has no attribute '_normalize_tool_result_block'`

- [ ] **Step 3: helper 구현**

`plugins/token-tracker/lib/parser.py` 의 `parse_tool_result` 함수 정의 (line 324 근처) **직전에** 다음 추가:

```python
def _normalize_tool_result_block(block: dict) -> str:
    """tool_result.content 안의 단일 block 을 사람이 읽을 수 있는 string 으로 정규화.

    알려진 type: text, tool_reference, image. 그 외에는 [<type>] placeholder 를
    반환해 미래에 새 block type 이 등장해도 조용히 빈 문자열로 떨어지지 않게 한다.
    type 키 자체가 없으면 빈 문자열 (caller 가 join 단계에서 skip)."""
    t = block.get("type")
    if not t:
        return ""
    if t == "text":
        text = block.get("text")
        return text if isinstance(text, str) else ""
    if t == "tool_reference":
        name = block.get("tool_name")
        if isinstance(name, str) and name:
            return f"[tool_reference] {name}"
        return "[tool_reference]"
    if t == "image":
        source = block.get("source")
        if not isinstance(source, dict):
            source = {}
        mt = source.get("media_type")
        media_type = mt if isinstance(mt, str) and mt else None
        data = source.get("data")
        size_bytes = (len(data) * 3 // 4) if isinstance(data, str) and data else None
        if media_type and size_bytes is not None:
            return f"[image: {media_type}, {size_bytes} bytes]"
        if media_type:
            return f"[image: {media_type}]"
        if size_bytes is not None:
            return f"[image: {size_bytes} bytes]"
        return "[image]"
    return f"[{t}]"
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py::test_normalize_tool_result_block -v
```

Expected: 12 passed

- [ ] **Step 5: commit**

```bash
git add plugins/token-tracker/lib/parser.py plugins/token-tracker/tests/test_parser.py
git commit -m "$(cat <<'EOF'
feat(parser): tool_result content block normalize helper 추가

text 외에 tool_reference / image / unknown 4종 block 을 사람이 읽을 수 있는
placeholder string 으로 정규화하는 _normalize_tool_result_block 신규 추가.
parametrize 단위 테스트 12 케이스로 모든 분기 cover.

이번 commit 은 helper 추가만, parse_tool_result 의 list 분기 호출 교체는
다음 commit 에서.
EOF
)"
```

---

## Task 2: `parse_tool_result` 리팩토링 + 통합 테스트

**Files:**
- Modify: `plugins/token-tracker/lib/parser.py` (line 342~349 의 inline 분기를 helper 호출로 교체)
- Modify: `plugins/token-tracker/tests/test_parser.py` (통합 테스트 3개 추가)

- [ ] **Step 1: 통합 테스트 작성 (실패 테스트)**

`plugins/token-tracker/tests/test_parser.py` 의 `test_parse_tool_result_list_content` (line 809) **다음에** 추가:

```python
def test_parse_tool_result_list_with_tool_reference():
    """MCP ToolSearch 같은 도구가 tool_reference block 을 반환할 때
    placeholder 줄바꿈 리스트로 정규화된다 (v0.8.1 회귀 가드)."""
    from lib.parser import parse_tool_result
    entry = {
        "type": "user",
        "timestamp": "2026-05-03T14:23:01Z",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_search_1",
                    "content": [
                        {"type": "tool_reference", "tool_name": "TaskCreate"},
                        {"type": "tool_reference", "tool_name": "TaskUpdate"},
                    ],
                }
            ]
        },
    }
    out = parse_tool_result(entry)
    assert len(out) == 1
    assert out[0]["content"] == "[tool_reference] TaskCreate\n[tool_reference] TaskUpdate"


def test_parse_tool_result_list_mixed_text_and_tool_reference():
    """text + tool_reference 혼합 block 도 줄바꿈으로 join 된다."""
    from lib.parser import parse_tool_result
    entry = {
        "type": "user",
        "timestamp": "2026-05-03T14:23:01Z",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_mixed_1",
                    "content": [
                        {"type": "text", "text": "intro"},
                        {"type": "tool_reference", "tool_name": "Read"},
                    ],
                }
            ]
        },
    }
    out = parse_tool_result(entry)
    assert out[0]["content"] == "intro\n[tool_reference] Read"


def test_parse_tool_result_list_skips_blocks_without_type():
    """type 키가 없는 block 은 join 결과에서 빠진다 (빈 줄 안 생김)."""
    from lib.parser import parse_tool_result
    entry = {
        "type": "user",
        "timestamp": "2026-05-03T14:23:01Z",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_x",
                    "content": [
                        {"type": "text", "text": "a"},
                        {},
                        {"type": "text", "text": "b"},
                    ],
                }
            ]
        },
    }
    out = parse_tool_result(entry)
    assert out[0]["content"] == "a\nb"
```

- [ ] **Step 2: 테스트 실행해서 fail 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py -k "tool_reference or skips_blocks_without_type" -v
```

Expected:
- `test_parse_tool_result_list_with_tool_reference`: FAIL (`assert '' == '[tool_reference]...'`)
- `test_parse_tool_result_list_mixed_text_and_tool_reference`: FAIL (`assert 'intro' == 'intro\n[tool_reference] Read'`)
- `test_parse_tool_result_list_skips_blocks_without_type`: PASS (이미 통과 — 회귀 가드 역할)

- [ ] **Step 3: `parse_tool_result` 의 list 분기를 helper 호출로 교체**

`plugins/token-tracker/lib/parser.py` 의 line 342~349 (현재 코드):

```python
            elif isinstance(raw, list):
                parts: list[str] = []
                for sub in raw:
                    if isinstance(sub, dict) and sub.get("type") == "text":
                        t = sub.get("text")
                        if isinstance(t, str):
                            parts.append(t)
                text = "\n".join(parts)
```

를 다음으로 교체:

```python
            elif isinstance(raw, list):
                parts = [
                    _normalize_tool_result_block(b)
                    for b in raw
                    if isinstance(b, dict)
                ]
                text = "\n".join(p for p in parts if p)
```

- [ ] **Step 4: parser 전체 테스트 통과 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py -v
```

Expected: 모든 테스트 통과 (기존 `test_parse_tool_result_list_content` 도 그대로 통과 — text-only list 는 기존 결과와 동일).

- [ ] **Step 5: commit**

```bash
git add plugins/token-tracker/lib/parser.py plugins/token-tracker/tests/test_parser.py
git commit -m "$(cat <<'EOF'
fix(parser): tool_result list 분기를 _normalize_tool_result_block 호출로 교체

기존에 text block 만 추출하던 inline 루프를 helper 호출로 교체.
MCP tool_reference, image, unknown block 도 placeholder string 으로 정규화.

회귀 가드 통합 테스트 3개 추가:
- list_with_tool_reference (실측 케이스)
- list_mixed_text_and_tool_reference
- list_skips_blocks_without_type
EOF
)"
```

---

## Task 3: v0.8.1 버전 bump + 전체 회귀 테스트

**Files:**
- Modify: `plugins/token-tracker/.claude-plugin/plugin.json` (line 4)
- Modify: `.claude-plugin/marketplace.json` (line 12)

- [ ] **Step 1: plugin.json 버전 bump**

`plugins/token-tracker/.claude-plugin/plugin.json` 의 line 4:

기존:
```json
  "version": "0.8.0",
```

변경:
```json
  "version": "0.8.1",
```

- [ ] **Step 2: marketplace.json 버전 bump**

`.claude-plugin/marketplace.json` 의 line 12 (`"version": "0.8.0"`) 를 `"version": "0.8.1"` 로 변경.

- [ ] **Step 3: 전체 테스트 회귀 확인**

```bash
cd /Users/brody/Desktop/token-tracker
./venv/bin/pytest plugins/token-tracker/tests -q
```

Expected: `342 passed` (v0.8.0 baseline 327 + 신규 15 = 342)

만약 327 baseline 이 다른 숫자로 바뀌어 있으면 그 baseline + 15 가 expected.

- [ ] **Step 4: commit**

```bash
git add plugins/token-tracker/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "$(cat <<'EOF'
chore(release): v0.8.1 — parser MCP tool_result.content fix

plugin.json + marketplace.json 버전 0.8.0 → 0.8.1.
변경 내용: lib/parser.py 의 tool_result content normalize 가
text 외 block (tool_reference, image, unknown) 도 placeholder
로 정규화하도록 수정. /token-history 의 TOOL RESULT 빈 섹션
회귀 해소.
EOF
)"
```

---

## Task 4: PR 생성 + 사용자 리뷰 요청

**Files:** (코드 변경 없음, git 작업만)

- [ ] **Step 1: feature 브랜치 push**

```bash
git push -u origin feature/v0.8.1-parser-mcp-tool-result-fix
```

- [ ] **Step 2: PR 생성**

```bash
gh pr create --title "v0.8.1: parser MCP tool_result.content fix" --body "$(cat <<'EOF'
## Summary
- v0.8.0 회귀 수정: `/token-history` 의 turn 카드에서 일부 도구의 TOOL RESULT 섹션이 비어 보이던 문제
- 원인: `lib/parser.py` 의 `parse_tool_result` 가 list-of-blocks content 에서 `type == "text"` block 만 추출, MCP `tool_reference` / `image` 등 비-text block 은 빈 문자열로 떨어짐
- fix: 신규 helper `_normalize_tool_result_block(block) -> str` 로 4종 분기 (text / tool_reference / image / unknown) 처리. 미래 새 block type 도 `[<type>]` placeholder 로 방어
- history.jsonl schema 변경 없음, 기존 entry migration 안 함 (transcript 가 source of truth)

## Test plan
- [x] `_normalize_tool_result_block` 단위 12 case (parametrize) — text 빈/누락, tool_reference 이름 유무, image 4가지 source 조합, unknown type 방어, type 키 누락
- [x] `parse_tool_result` 통합 3 case — tool_reference 리스트, text+tool_reference 혼합, type 누락 block skip
- [x] 회귀 가드: 기존 `test_parse_tool_result_list_content` (text-only list) 그대로 통과
- [x] 전체 회귀: 342/342 passing (v0.8.0 baseline 327 + 신규 15)

## Spec / Plan
- spec: `docs/superpowers/specs/2026-05-05-parser-mcp-tool-result-fix-design.md`
- plan: `docs/superpowers/plans/2026-05-05-parser-mcp-tool-result-fix.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: PR URL 사용자에게 보고 + 리뷰 요청**

PR URL 을 사용자에게 출력하고, **머지는 사용자 명시 승인 후에만** 실행한다고 안내. 사용자 룰: "PR 생성까지만 자동, 머지는 사용자가 '머지해' 라고 명시한 뒤에만".

---

## Self-Review

- **Spec coverage**:
  - §4.1 helper 신규 → Task 1 ✓
  - §4.2 parse_tool_result 수정 → Task 2 ✓
  - §4.3 버전 bump → Task 3 ✓
  - §5 변환 규칙 (12 input → output) → Task 1 Step 1 (parametrize 12 case) ✓
  - §6 테스트 → Task 1 (12) + Task 2 (3) = 15 ✓ (spec 표기 14 와 1 차이: image 케이스 표 보강분 반영)
  - §7 호환성 → schema bump 없음, history_renderer 무수정 (Task 1~3 어디서도 안 건드림) ✓
  - §8 DoD → Task 3 (전체 테스트) + Task 4 (PR) ✓
- **Placeholder scan**: TBD/TODO 없음. 모든 step 에 실제 코드/명령어 첨부.
- **Type consistency**: helper signature `_normalize_tool_result_block(block: dict) -> str` 가 Task 1 정의 / Task 2 호출 모두 동일. 반환 타입(str) → caller 의 list join 에 직접 사용.
- **신규 테스트 카운트**: spec 14 vs plan 15 — 차이는 spec §5 표 self-review 시 보강한 image edge case (`media_type 누락 + data 있음`) 에서 발생. 사실 정합. spec 다시 손대지 않고 plan 에서 보강된 숫자로 진행.
