# token-tracker pricing 정확도 v2 구현 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Opus 4.7 단가 회귀(3배 overbill) fix + prompt cache 1h tier 분리로 token-tracker 비용 표시를 statusline과 일치시킨다.

**Architecture:** parser가 transcript JSONL의 `cache_creation` 중첩 객체에서 5m/1h tier를 분리 추출 → pricing.py가 두 tier 별도 단가 적용 → aggregator가 단일 패스로 합산. summary_store schema v2 → v3 breaking. detail_formatter / detail.py 동기 갱신. 95곳 기존 fixture 일괄 마이그레이션.

**Tech Stack:** Python 3.10+ 표준 라이브러리. pytest. Claude Code plugin 인프라.

**Spec:** `docs/superpowers/specs/2026-05-03-token-tracker-pricing-accuracy-design.md`

**Baseline:** 248 tests passing (main, v0.6.4 머지 후).

---

## File Structure

**Modify (production):**
- `plugins/token-tracker/lib/parser.py` — TurnUsage/SubagentUsage 필드 분리, 3개 함수 5m/1h 추출
- `plugins/token-tracker/lib/pricing.py` — PRICING dict 단가 갱신, compute_cost 두 tier 합산, silent $0 stderr
- `plugins/token-tracker/lib/aggregator.py` — total_input 합산식
- `plugins/token-tracker/lib/summary_store.py` — SCHEMA_VERSION v3, 화이트리스트 갱신
- `plugins/token-tracker/lib/detail_formatter.py` — cache 칼럼 5m+1h 합산
- `plugins/token-tracker/skills/token-detail/scripts/detail.py` — schema gate (3,)
- `plugins/token-tracker/.claude-plugin/plugin.json` — version 0.6.4 → 0.7.0

**Modify (test, ~94곳):**
- `plugins/token-tracker/tests/test_hook_end_to_end.py` (25곳)
- `plugins/token-tracker/tests/test_sidechain.py` (15곳)
- `plugins/token-tracker/tests/test_parser.py` (13곳)
- `plugins/token-tracker/tests/test_aggregator.py` (14곳)
- `plugins/token-tracker/tests/test_pricing.py` (11곳)
- `plugins/token-tracker/tests/test_summary_store.py` (9곳)
- `plugins/token-tracker/tests/test_detail_formatter.py` (6곳)
- `plugins/token-tracker/tests/test_detail_script_e2e.py` (1곳)
- fixture 헬퍼들 (`_mk`, `_turn`, `_sub`, hook stdin builders)

**Create (test, 신규 ~20건 단위 + 3건 e2e):**
- 위 test 파일들에 신규 함수 추가 (별도 파일 신설 안 함 — 기존 파일에 응집)

**Create (disposable, 커밋 안 함):**
- `scripts/diagnose_v0_7_shapes.py` — Task 0 진단용

**Not modified:**
- `hooks/on_stop.py` — 변경 없음
- `lib/sidechain.py` — 변경 없음
- `skills/token-verbose/` — 변경 없음

---

## 진행 흐름 / 커밋 정책

- **브랜치**: `feature/v0.7.0-pricing-accuracy` 단일 — 모든 변경은 같은 브랜치 + 한 PR.
- **PR**: 단일 PR. spec §9.3 명시: fixture 갱신과 메인 변경은 같은 PR.
- **Commit**: phase별 분리(메인 변경 / fixture 갱신 / e2e / version bump). 각 task가 commit 단위 또는 task 묶음 단위.
- **TDD**: 모든 production code 변경은 red → green → commit. fixture 갱신은 별도(테스트 코드라 TDD 무관).

---

## Task 0: 브랜치 생성 + Plan 1단계 진단

**Files:**
- Create: `scripts/diagnose_v0_7_shapes.py` (커밋 안 함)

- [ ] **Step 0.1: feature 브랜치 생성**

```bash
cd /Users/brody/Desktop/token-tracker
git checkout main && git pull origin main
git checkout -b feature/v0.7.0-pricing-accuracy
```

Expected: switched to new branch.

- [ ] **Step 0.2: 진단 스크립트 작성 (disposable)**

Create `scripts/diagnose_v0_7_shapes.py`:

```python
#!/usr/bin/env python3
"""Disposable diagnostic — DO NOT COMMIT.

목표: spec §10 진단 6항목 확인.
1. toolUseResult.usage shape (foreground sub)
2. sidechain message.usage shape (async sub)
3. cache_creation 객체 + legacy 동시 박힌 라인 빈도
4. cache_creation == {} + legacy > 0 케이스 존재 여부
5. dedupe 그룹 첫 라인의 cache_creation 객체 박힘 여부
6. cache_creation 중첩 객체 없는 구버전 entry 실재 여부
"""
import json
from pathlib import Path
from collections import Counter

def find_transcripts():
    """현재 사용자의 모든 Claude Code transcript 디렉터리 스캔."""
    base = Path.home() / ".claude" / "projects"
    for project_dir in base.iterdir():
        for jsonl in project_dir.glob("*.jsonl"):
            yield jsonl

def analyze_one(jsonl_path):
    stats = Counter()
    msg_id_lines = {}  # msg_id -> [(idx, has_cc_obj, type_block)]
    sidechain_path = jsonl_path.parent / jsonl_path.stem / "subagents"
    sidechain_files = list(sidechain_path.glob("*.jsonl")) if sidechain_path.exists() else []

    with jsonl_path.open() as f:
        for i, line in enumerate(f):
            try:
                e = json.loads(line)
            except Exception:
                continue
            t = e.get("type")
            # foreground sub: toolUseResult.usage
            if t == "user":
                tur = e.get("toolUseResult")
                if isinstance(tur, dict) and tur.get("agentType"):
                    usage = tur.get("usage", {})
                    if isinstance(usage, dict):
                        cc = usage.get("cache_creation")
                        stats["fg_sub_total"] += 1
                        if isinstance(cc, dict):
                            stats["fg_sub_with_cc_obj"] += 1
                        if "cache_creation_input_tokens" in usage:
                            stats["fg_sub_with_legacy"] += 1
            # main assistant: message.usage
            elif t == "assistant":
                msg = e.get("message", {})
                usage = msg.get("usage")
                if isinstance(usage, dict):
                    cc = usage.get("cache_creation")
                    stats["main_assistant_total"] += 1
                    if isinstance(cc, dict):
                        stats["main_with_cc_obj"] += 1
                        if cc.get("ephemeral_5m_input_tokens", 0) == 0 and cc.get("ephemeral_1h_input_tokens", 0) == 0:
                            if usage.get("cache_creation_input_tokens", 0) > 0:
                                stats["main_empty_cc_obj_with_legacy"] += 1
                    if "cache_creation_input_tokens" in usage:
                        stats["main_with_legacy"] += 1
                    # dedupe 그룹: msg_id별로 라인 위치 + cc 객체 박힘 추적
                    mid = msg.get("id", "")
                    if mid:
                        content = msg.get("content") or []
                        block_types = [b.get("type", "") for b in content if isinstance(b, dict)]
                        block_type = block_types[0] if block_types else ""
                        msg_id_lines.setdefault(mid, []).append((i, isinstance(cc, dict), block_type))

    # async sub
    for scf in sidechain_files:
        with scf.open() as f:
            for line in f:
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("type") != "assistant":
                    continue
                msg = e.get("message", {})
                usage = msg.get("usage")
                if isinstance(usage, dict):
                    cc = usage.get("cache_creation")
                    stats["async_sub_total"] += 1
                    if isinstance(cc, dict):
                        stats["async_sub_with_cc_obj"] += 1

    # dedupe 첫 라인 분석
    for mid, lines in msg_id_lines.items():
        if len(lines) < 2:
            continue  # dedupe 대상 아님
        lines.sort()  # 라인 순
        first_idx, first_has_cc, first_block = lines[0]
        any_later_has_cc = any(has_cc for _, has_cc, _ in lines[1:])
        if not first_has_cc and any_later_has_cc:
            stats["dedupe_first_line_missing_cc"] += 1
        else:
            stats["dedupe_first_line_has_cc_or_no_later"] += 1

    return stats

def main():
    total = Counter()
    file_count = 0
    for jsonl in find_transcripts():
        try:
            s = analyze_one(jsonl)
            total.update(s)
            file_count += 1
        except Exception as e:
            print(f"skip {jsonl}: {e}")

    print(f"=== analyzed {file_count} transcripts ===")
    for k, v in sorted(total.items()):
        print(f"  {k}: {v}")

    print()
    print("=== verdict ===")
    if total["fg_sub_with_cc_obj"] == total["fg_sub_total"]:
        print("✅ foreground sub: cache_creation 객체 항상 박힘")
    else:
        print(f"⚠️ foreground sub: {total['fg_sub_total'] - total['fg_sub_with_cc_obj']}/{total['fg_sub_total']}는 cc 객체 없음 — fallback 필요")
    if total["async_sub_with_cc_obj"] == total["async_sub_total"]:
        print("✅ async sub: cache_creation 객체 항상 박힘")
    else:
        print(f"⚠️ async sub: {total['async_sub_total'] - total['async_sub_with_cc_obj']}는 cc 객체 없음")
    if total["main_empty_cc_obj_with_legacy"] > 0:
        print(f"⚠️ 빈 cc 객체 + legacy>0: {total['main_empty_cc_obj_with_legacy']} — fallback 보강 필요")
    else:
        print("✅ 빈 cc 객체 + legacy>0 없음 — 현 §4 fallback 충분")
    if total["dedupe_first_line_missing_cc"] > 0:
        print(f"⚠️ dedupe 첫 라인에 cc 없음: {total['dedupe_first_line_missing_cc']} — _dedupe_by_message_id 보강 필요")
    else:
        print("✅ dedupe 첫 라인에 cc 항상 박힘 — §6 'dedupe 변경 없음' 유지")

if __name__ == "__main__":
    main()
```

- [ ] **Step 0.3: 진단 실행 + 결과 보고**

```bash
python3 scripts/diagnose_v0_7_shapes.py
```

Expected output (한 가지 가능 케이스):
```
=== analyzed N transcripts ===
  fg_sub_total: X
  fg_sub_with_cc_obj: X
  ...
=== verdict ===
✅ foreground sub: cache_creation 객체 항상 박힘
✅ async sub: cache_creation 객체 항상 박힘
✅ 빈 cc 객체 + legacy>0 없음 — 현 §4 fallback 충분
✅ dedupe 첫 라인에 cc 항상 박힘 — §6 'dedupe 변경 없음' 유지
```

분기:
- 모두 ✅ → spec 그대로 진행 (Task 1로).
- ⚠️ 발생 → 사용자에게 보고, spec 보강 결정 후 진행.

- [ ] **Step 0.4: disposable script 정리 (커밋 X)**

```bash
# 진단 결과 확인 후
echo "scripts/" >> .gitignore  # 만약 .gitignore에 없으면
# 또는 scripts/diagnose_v0_7_shapes.py 만 무시
```

진단 스크립트는 commit하지 않음. 결과만 사용자에게 보고하고 spec/plan 분기 결정.

---

## Task 1: parser TurnUsage / SubagentUsage 필드 분리

**Files:**
- Modify: `plugins/token-tracker/lib/parser.py` (dataclass 정의)
- Test: `plugins/token-tracker/tests/test_parser.py`

- [ ] **Step 1.1: 실패 테스트 작성**

Add to `tests/test_parser.py`:

```python
def test_turn_usage_has_separate_5m_and_1h_fields():
    """TurnUsage가 cache_creation_5m_tokens / cache_creation_1h_tokens 두 필드를 가짐."""
    from lib.parser import TurnUsage
    t = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=10,
        output_tokens=20,
        cache_creation_5m_tokens=100,
        cache_creation_1h_tokens=200,
        cache_read_tokens=50,
    )
    assert t.cache_creation_5m_tokens == 100
    assert t.cache_creation_1h_tokens == 200
    assert not hasattr(t, "cache_creation_tokens")  # 옛 필드 제거 확인


def test_subagent_usage_has_separate_5m_and_1h_fields():
    from lib.parser import SubagentUsage
    s = SubagentUsage(
        agent_type="general-purpose",
        tool_use_id="x",
        input_tokens=1,
        output_tokens=2,
        cache_creation_5m_tokens=300,
        cache_creation_1h_tokens=400,
        cache_read_tokens=5,
    )
    assert s.cache_creation_5m_tokens == 300
    assert s.cache_creation_1h_tokens == 400
    assert not hasattr(s, "cache_creation_tokens")
```

- [ ] **Step 1.2: 실패 확인**

```bash
cd /Users/brody/Desktop/token-tracker
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py::test_turn_usage_has_separate_5m_and_1h_fields -xvs
```

Expected: FAIL — `TypeError: __init__() got unexpected keyword argument 'cache_creation_5m_tokens'`

- [ ] **Step 1.3: dataclass 변경 구현**

Modify `lib/parser.py` — `TurnUsage` dataclass:

```python
@dataclass
class TurnUsage:
    model: str
    input_tokens: int
    output_tokens: int
    # 제거: cache_creation_tokens
    # 신규 — default와 fallback의 1h 값(0)은 동일. 5m 값은 의미 다름:
    #   default=값 없음, fallback=legacy 합산값을 5m로 매핑한 양수일 수 있음.
    cache_creation_5m_tokens: int = 0
    cache_creation_1h_tokens: int = 0
    cache_read_tokens: int = 0
    tools_used: list[dict] = field(default_factory=list)
    timestamp_iso: str = ""
    message_id: str = ""
    index: int = 0
    started_at: float | None = None
    ended_at: float | None = None
    agent_tool_use_ids: list[str] = field(default_factory=list)
    subagents: list["SubagentUsage"] = field(default_factory=list)


@dataclass
class SubagentUsage:
    agent_type: str
    tool_use_id: str
    input_tokens: int
    output_tokens: int
    # 제거: cache_creation_tokens
    cache_creation_5m_tokens: int = 0
    cache_creation_1h_tokens: int = 0
    cache_read_tokens: int = 0
    total_duration_ms: int = 0
    model: str = ""
```

⚠️ **이 시점에 다른 테스트들이 모두 collection-time error로 깨진다** (cache_creation_tokens 인용 fixture가 95곳) — Task 13까지는 전체 테스트 슈트가 빨갛다. 정상이다. Task 1~12는 각자 *해당 task의 신규 테스트*만 통과 검증.

- [ ] **Step 1.4: 신규 테스트 통과 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py::test_turn_usage_has_separate_5m_and_1h_fields plugins/token-tracker/tests/test_parser.py::test_subagent_usage_has_separate_5m_and_1h_fields -xvs
```

Expected: PASS (2/2).

- [ ] **Step 1.5: commit**

```bash
git add plugins/token-tracker/lib/parser.py plugins/token-tracker/tests/test_parser.py
git commit -m "feat(parser): TurnUsage/SubagentUsage cache_creation 5m/1h 필드 분리"
```

---

## Task 2: parser parse_line 5m/1h 추출

**Files:**
- Modify: `plugins/token-tracker/lib/parser.py:parse_line`
- Test: `plugins/token-tracker/tests/test_parser.py`

- [ ] **Step 2.1: 실패 테스트 4건 작성 (parametrize 매트릭스 + legacy fallback + 둘 다 박힘)**

Add to `tests/test_parser.py`:

```python
import pytest


@pytest.mark.parametrize("c5m,c1h", [(0, 0), (100, 0), (0, 200), (100, 200)])
def test_parse_line_extracts_5m_and_1h_matrix(c5m, c1h):
    from lib.parser import parse_line
    entry = {
        "type": "assistant",
        "message": {
            "id": "msg_1",
            "model": "claude-opus-4-7",
            "usage": {
                "input_tokens": 5,
                "output_tokens": 10,
                "cache_read_input_tokens": 20,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": c5m,
                    "ephemeral_1h_input_tokens": c1h,
                },
            },
            "content": [],
        },
        "timestamp": "2026-05-03T10:00:00Z",
    }
    t = parse_line(entry)
    assert t is not None
    assert t.cache_creation_5m_tokens == c5m
    assert t.cache_creation_1h_tokens == c1h


def test_parse_line_falls_back_to_legacy_when_no_cache_creation_obj():
    """구버전 entry: cache_creation 중첩 객체 없으면 합산값을 5m로 간주."""
    from lib.parser import parse_line
    entry = {
        "type": "assistant",
        "message": {
            "id": "msg_2",
            "model": "claude-opus-4-7",
            "usage": {
                "input_tokens": 5,
                "output_tokens": 10,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 999,
                # cache_creation 중첩 객체 없음
            },
            "content": [],
        },
        "timestamp": "2026-05-03T10:00:00Z",
    }
    t = parse_line(entry)
    assert t is not None
    assert t.cache_creation_5m_tokens == 999  # fallback
    assert t.cache_creation_1h_tokens == 0


def test_parse_line_prefers_nested_cc_when_both_present():
    """이중 카운팅 회귀 가드: 중첩 객체와 legacy가 동시에 박혀도 중첩만 사용."""
    from lib.parser import parse_line
    entry = {
        "type": "assistant",
        "message": {
            "id": "msg_3",
            "model": "claude-opus-4-7",
            "usage": {
                "input_tokens": 5,
                "output_tokens": 10,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 3000,  # 무시되어야 함
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 1000,
                    "ephemeral_1h_input_tokens": 2000,
                },
            },
            "content": [],
        },
        "timestamp": "2026-05-03T10:00:00Z",
    }
    t = parse_line(entry)
    assert t is not None
    assert t.cache_creation_5m_tokens == 1000
    assert t.cache_creation_1h_tokens == 2000
    # legacy 3000은 무시되어야 함 — 합산이 3000(중복 안됨)
    assert (t.cache_creation_5m_tokens + t.cache_creation_1h_tokens) == 3000
```

- [ ] **Step 2.2: 실패 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py::test_parse_line_extracts_5m_and_1h_matrix plugins/token-tracker/tests/test_parser.py::test_parse_line_falls_back_to_legacy_when_no_cache_creation_obj plugins/token-tracker/tests/test_parser.py::test_parse_line_prefers_nested_cc_when_both_present -xvs
```

Expected: FAIL (parse_line 아직 옛 로직).

- [ ] **Step 2.3: parse_line 변경 구현**

Modify `lib/parser.py:parse_line` — usage 추출 부분:

```python
def parse_line(entry: dict) -> TurnUsage | None:
    if not isinstance(entry, dict):
        return None
    if entry.get("type") != "assistant":
        return None
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return None
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return None

    # cache_creation tier 분리 추출 (spec §4 공통 로직)
    cc = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    cache_5m = int(cc.get("ephemeral_5m_input_tokens", 0))
    cache_1h = int(cc.get("ephemeral_1h_input_tokens", 0))
    if not cc:
        # fallback: 옛 entry는 합산값을 5m로 간주 (방향: underbill)
        cache_5m = int(usage.get("cache_creation_input_tokens", 0))
        cache_1h = 0

    content = msg.get("content") or []
    raw_names = [
        blk.get("name", "")
        for blk in content
        if isinstance(blk, dict) and blk.get("type") == "tool_use"
    ]
    counter = Counter(name for name in raw_names if name)
    tools_used = [
        {"name": name, "count": count}
        for name, count in counter.items()
    ]
    agent_tool_use_ids = [tu_id for tu_id, _, _ in parse_agent_tool_uses(entry)]

    timestamp_iso = entry.get("timestamp", "")

    return TurnUsage(
        model=msg.get("model", ""),
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cache_creation_5m_tokens=cache_5m,
        cache_creation_1h_tokens=cache_1h,
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
        tools_used=tools_used,
        timestamp_iso=timestamp_iso,
        message_id=str(msg.get("id", "")),
        started_at=_iso_to_epoch(timestamp_iso),
        agent_tool_use_ids=agent_tool_use_ids,
    )
```

- [ ] **Step 2.4: 신규 테스트 통과 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py -k "5m_and_1h_matrix or falls_back_to_legacy or prefers_nested_cc" -xvs
```

Expected: PASS (6/6: parametrize 4 + fallback 1 + nested 1).

- [ ] **Step 2.5: commit**

```bash
git add plugins/token-tracker/lib/parser.py plugins/token-tracker/tests/test_parser.py
git commit -m "feat(parser): parse_line이 cache_creation 5m/1h tier 분리 추출"
```

---

## Task 3: parser parse_tool_result_for_agent 5m/1h 추출

**Files:**
- Modify: `plugins/token-tracker/lib/parser.py:parse_tool_result_for_agent`
- Test: `plugins/token-tracker/tests/test_parser.py`

- [ ] **Step 3.1: 실패 테스트 작성**

```python
def test_parse_tool_result_for_agent_extracts_5m_1h():
    from lib.parser import parse_tool_result_for_agent
    entry = {
        "type": "user",
        "toolUseResult": {
            "agentType": "general-purpose",
            "status": "completed",
            "totalDurationMs": 1234,
            "usage": {
                "input_tokens": 5,
                "output_tokens": 10,
                "cache_read_input_tokens": 20,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 100,
                    "ephemeral_1h_input_tokens": 200,
                },
            },
        },
        "message": {
            "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": "ok"}],
        },
    }
    s = parse_tool_result_for_agent(entry)
    assert s is not None
    assert s.cache_creation_5m_tokens == 100
    assert s.cache_creation_1h_tokens == 200
```

- [ ] **Step 3.2: 실패 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py::test_parse_tool_result_for_agent_extracts_5m_1h -xvs
```

Expected: FAIL.

- [ ] **Step 3.3: 구현**

Modify `lib/parser.py:parse_tool_result_for_agent` (같은 추출 패턴):

```python
def parse_tool_result_for_agent(entry: dict) -> SubagentUsage | None:
    if not isinstance(entry, dict):
        return None
    if entry.get("type") != "user":
        return None
    tur = entry.get("toolUseResult")
    if not isinstance(tur, dict):
        return None
    agent_type = tur.get("agentType")
    if not agent_type:
        return None
    if tur.get("status") != "completed":
        return None

    tool_use_id = _extract_tool_use_id(entry)
    usage = tur.get("usage") if isinstance(tur.get("usage"), dict) else {}

    cc = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    cache_5m = int(cc.get("ephemeral_5m_input_tokens", 0))
    cache_1h = int(cc.get("ephemeral_1h_input_tokens", 0))
    if not cc:
        cache_5m = int(usage.get("cache_creation_input_tokens", 0))
        cache_1h = 0

    return SubagentUsage(
        agent_type=str(agent_type),
        tool_use_id=tool_use_id,
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cache_creation_5m_tokens=cache_5m,
        cache_creation_1h_tokens=cache_1h,
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
        total_duration_ms=int(tur.get("totalDurationMs", 0) or 0),
    )
```

- [ ] **Step 3.4: 통과 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py::test_parse_tool_result_for_agent_extracts_5m_1h -xvs
```

Expected: PASS.

- [ ] **Step 3.5: commit**

```bash
git add plugins/token-tracker/lib/parser.py plugins/token-tracker/tests/test_parser.py
git commit -m "feat(parser): parse_tool_result_for_agent도 5m/1h 분리 추출"
```

---

## Task 4: parser parse_sidechain_assistant 5m/1h 추출

**Files:**
- Modify: `plugins/token-tracker/lib/parser.py:parse_sidechain_assistant`
- Test: `plugins/token-tracker/tests/test_parser.py`

- [ ] **Step 4.1: 실패 테스트**

```python
def test_parse_sidechain_assistant_extracts_5m_1h():
    from lib.parser import parse_sidechain_assistant
    entry = {
        "type": "assistant",
        "message": {
            "model": "claude-haiku-4-5",
            "usage": {
                "input_tokens": 5,
                "output_tokens": 10,
                "cache_read_input_tokens": 20,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": 100,
                    "ephemeral_1h_input_tokens": 200,
                },
            },
        },
    }
    s = parse_sidechain_assistant(entry, "general-purpose", "tu_1")
    assert s is not None
    assert s.cache_creation_5m_tokens == 100
    assert s.cache_creation_1h_tokens == 200
    assert s.model == "claude-haiku-4-5"
```

- [ ] **Step 4.2: 실패 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py::test_parse_sidechain_assistant_extracts_5m_1h -xvs
```

Expected: FAIL.

- [ ] **Step 4.3: 구현**

Modify `lib/parser.py:parse_sidechain_assistant`:

```python
def parse_sidechain_assistant(
    entry: dict, agent_type: str, tool_use_id: str,
) -> SubagentUsage | None:
    if not isinstance(entry, dict):
        return None
    if entry.get("type") != "assistant":
        return None
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return None
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return None

    cc = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    cache_5m = int(cc.get("ephemeral_5m_input_tokens", 0))
    cache_1h = int(cc.get("ephemeral_1h_input_tokens", 0))
    if not cc:
        cache_5m = int(usage.get("cache_creation_input_tokens", 0))
        cache_1h = 0

    return SubagentUsage(
        agent_type=agent_type,
        tool_use_id=tool_use_id,
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cache_creation_5m_tokens=cache_5m,
        cache_creation_1h_tokens=cache_1h,
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
        total_duration_ms=0,
        model=str(msg.get("model", "")),
    )
```

- [ ] **Step 4.4: 통과 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py::test_parse_sidechain_assistant_extracts_5m_1h -xvs
```

Expected: PASS.

- [ ] **Step 4.5: commit**

```bash
git add plugins/token-tracker/lib/parser.py plugins/token-tracker/tests/test_parser.py
git commit -m "feat(parser): parse_sidechain_assistant도 5m/1h 분리 추출"
```

---

## Task 5: pricing PRICING dict 갱신 + compute_cost 두 tier 합산

**Files:**
- Modify: `plugins/token-tracker/lib/pricing.py`
- Test: `plugins/token-tracker/tests/test_pricing.py`

- [ ] **Step 5.1: 회귀 가드 테스트 작성 (절대값 + 1h>5m + 합산)**

Add to `tests/test_pricing.py`:

```python
def test_pricing_opus_4_7_all_rates_absolute():
    """Opus 4.7 단가 5개 절대값 가드 — 옛 단가($15/$75/$18.75/$1.5) 회귀 방지.
    단가 변경 시 같이 갱신 필요."""
    from lib.pricing import PRICING
    p = PRICING["claude-opus-4-7"]
    assert p["input"] == 5.0
    assert p["output"] == 25.0
    assert p["cache_creation_5m"] == 6.25
    assert p["cache_creation_1h"] == 10.0
    assert p["cache_read"] == 0.50


def test_pricing_sonnet_4_6_1h_is_6_dollars_per_mtok():
    from lib.pricing import PRICING
    assert PRICING["claude-sonnet-4-6"]["cache_creation_1h"] == 6.0
    assert PRICING["claude-sonnet-4-6"]["cache_creation_5m"] == 3.75


def test_pricing_haiku_4_5_1h_is_2_dollars_per_mtok():
    from lib.pricing import PRICING
    assert PRICING["claude-haiku-4-5"]["cache_creation_1h"] == 2.0
    assert PRICING["claude-haiku-4-5"]["cache_creation_5m"] == 1.25


def test_pricing_1h_more_expensive_than_5m_for_all_models():
    """tier 분리 누락 회귀 가드 — 1h가 5m보다 비싸야 정상."""
    from lib.pricing import PRICING
    for model, rates in PRICING.items():
        assert rates["cache_creation_1h"] > rates["cache_creation_5m"], (
            f"{model}: 1h {rates['cache_creation_1h']} <= 5m {rates['cache_creation_5m']}"
        )


def test_compute_cost_combines_5m_and_1h_correctly():
    """5m + 1h 두 단가 정확 합산."""
    from lib.parser import TurnUsage
    from lib.pricing import compute_cost
    usage = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=1_000_000,    # = $5
        output_tokens=1_000_000,   # = $25
        cache_creation_5m_tokens=1_000_000,  # = $6.25
        cache_creation_1h_tokens=1_000_000,  # = $10
        cache_read_tokens=1_000_000,         # = $0.50
    )
    cost = compute_cost("claude-opus-4-7", usage)
    expected = 5.0 + 25.0 + 6.25 + 10.0 + 0.50
    assert abs(cost - expected) < 1e-6
```

- [ ] **Step 5.2: 실패 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_pricing.py -k "all_rates_absolute or 1h_is or 1h_more_expensive or combines_5m_and_1h" -xvs
```

Expected: FAIL — PRICING에 신규 키 없음, compute_cost 옛 로직.

- [ ] **Step 5.3: pricing.py 갱신**

Replace `lib/pricing.py` with:

```python
from __future__ import annotations

import sys
from lib.parser import TurnUsage


# Source: https://platform.claude.com/docs/en/about-claude/pricing
# Fetched: 2026-05-03
# 회귀 fix: Opus 4.7은 4.5부터 단가가 1/3로 인하됐는데 우리는 옛 단가($15)를 박아둠.
#
# 가정:
# - prompt cache write는 5m / 1h 두 tier만 존재 (Anthropic 2년간 두 tier 유지).
#   30m/4h 등 새 tier 추가 시 PRICING 키 + parser + summary_store v4 bump 필요.
# - cache_read는 모든 tier 단가 동일 (5m/1h 모두 동일 cache_read 단가).
#   향후 분리되면 spec/회귀 재검토.
# - 단가 변경 시 tests/test_pricing.py의 절대값 회귀 가드 테스트
#   (test_pricing_opus_4_7_all_rates_absolute, test_pricing_sonnet_4_6_1h_..., test_pricing_haiku_4_5_1h_...)
#   도 같이 갱신. 안 갱신하면 정당한 단가 변경이 회귀로 오인됨.
PRICING: dict[str, dict[str, float]] = {
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


_warned_unknown_models: set[str] = set()


def _resolve_rates(model: str) -> dict[str, float] | None:
    """Look up pricing for a model id (exact or longest-prefix match)."""
    if model in PRICING:
        return PRICING[model]
    best: tuple[int, str] | None = None
    for key in PRICING:
        if model.startswith(key) and (best is None or len(key) > best[0]):
            best = (len(key), key)
    return PRICING[best[1]] if best else None


def compute_cost(model: str, usage: TurnUsage) -> float:
    """Compute USD cost for a usage record (TurnUsage 또는 SubagentUsage)."""
    rates = _resolve_rates(model)
    if rates is None:
        # Silent $0 안전장치 — 미등록 모델 alias 발견 시 stderr 1회 경고
        if model not in _warned_unknown_models:
            _warned_unknown_models.add(model)
            sys.stderr.write(f"[token-tracker] unknown pricing model: {model}\n")
        return 0.0
    per_mtok = 1_000_000.0
    return (
        usage.input_tokens * rates["input"] / per_mtok
        + usage.output_tokens * rates["output"] / per_mtok
        + usage.cache_creation_5m_tokens * rates["cache_creation_5m"] / per_mtok
        + usage.cache_creation_1h_tokens * rates["cache_creation_1h"] / per_mtok
        + usage.cache_read_tokens * rates["cache_read"] / per_mtok
    )


def is_known_model(model: str) -> bool:
    return _resolve_rates(model) is not None


def effective_billing_model(sub_model: str, parent_model: str) -> str:
    """Pick the model id to bill a subagent's usage at."""
    if sub_model and is_known_model(sub_model):
        return sub_model
    return parent_model
```

- [ ] **Step 5.4: 통과 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_pricing.py -k "all_rates_absolute or 1h_is or 1h_more_expensive or combines_5m_and_1h" -xvs
```

Expected: PASS (5/5).

- [ ] **Step 5.5: commit**

```bash
git add plugins/token-tracker/lib/pricing.py plugins/token-tracker/tests/test_pricing.py
git commit -m "feat(pricing): Opus 4.7 단가 회귀 fix + 1h tier 추가 + silent \$0 안전장치"
```

---

## Task 6: pricing silent $0 stderr 안전장치 회귀 가드

**Files:**
- Test: `plugins/token-tracker/tests/test_pricing.py` (Task 5에서 이미 코드 구현됨)

- [ ] **Step 6.1: 실패 테스트**

```python
def test_compute_cost_emits_stderr_for_unknown_model(capsys, monkeypatch):
    """미등록 model에 대해 stderr 경고가 한 번 나오고 그 후엔 silent."""
    from lib import pricing
    from lib.parser import TurnUsage
    # state 초기화
    monkeypatch.setattr(pricing, "_warned_unknown_models", set())
    usage = TurnUsage(
        model="unknown-future-model-99",
        input_tokens=1000,
        output_tokens=500,
    )
    cost1 = pricing.compute_cost("unknown-future-model-99", usage)
    assert cost1 == 0.0
    captured = capsys.readouterr()
    assert "unknown pricing model" in captured.err
    assert "unknown-future-model-99" in captured.err

    # 같은 model 두 번째 호출은 silent
    cost2 = pricing.compute_cost("unknown-future-model-99", usage)
    assert cost2 == 0.0
    captured2 = capsys.readouterr()
    assert captured2.err == ""  # 두 번째는 emit 안 함
```

- [ ] **Step 6.2: 실패 확인 → 통과 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_pricing.py::test_compute_cost_emits_stderr_for_unknown_model -xvs
```

Task 5에서 이미 stderr emit + once-emit 구현했으므로 바로 PASS 예상. 실패하면 Task 5 코드 확인 후 수정.

- [ ] **Step 6.3: commit**

```bash
git add plugins/token-tracker/tests/test_pricing.py
git commit -m "test(pricing): silent \$0 stderr 안전장치 회귀 가드"
```

---

## Task 7: aggregator total_input 합산식 변경

**Files:**
- Modify: `plugins/token-tracker/lib/aggregator.py:aggregate`
- Test: `plugins/token-tracker/tests/test_aggregator.py`

- [ ] **Step 7.1: 실패 테스트**

Add to `tests/test_aggregator.py`:

```python
def test_total_input_includes_both_5m_and_1h():
    from lib.aggregator import aggregate
    from lib.parser import TurnUsage
    turns = [
        TurnUsage(
            model="claude-opus-4-7",
            input_tokens=100,
            output_tokens=10,
            cache_creation_5m_tokens=1000,
            cache_creation_1h_tokens=2000,
            cache_read_tokens=500,
            message_id="msg_a",
        )
    ]
    s = aggregate(turns, elapsed=1.0)
    assert s.total_input_tokens == 100 + 1000 + 2000 + 500


def test_aggregate_cost_uses_per_tier_rates():
    """5m + 1h 두 단가가 정확히 적용."""
    from lib.aggregator import aggregate
    from lib.parser import TurnUsage
    turns = [
        TurnUsage(
            model="claude-opus-4-7",
            input_tokens=0,
            output_tokens=0,
            cache_creation_5m_tokens=1_000_000,  # = $6.25
            cache_creation_1h_tokens=1_000_000,  # = $10.0
            cache_read_tokens=0,
            message_id="msg_b",
        )
    ]
    s = aggregate(turns, elapsed=1.0)
    assert abs(s.total_cost - (6.25 + 10.0)) < 1e-6


def test_aggregate_5m_1h_uses_sub_model_rates():
    """sub model이 parent와 다르면 sub 단가로 계산."""
    from lib.aggregator import aggregate
    from lib.parser import TurnUsage, SubagentUsage
    sub = SubagentUsage(
        agent_type="general-purpose",
        tool_use_id="tu_1",
        input_tokens=0,
        output_tokens=0,
        cache_creation_5m_tokens=0,
        cache_creation_1h_tokens=1_000_000,  # haiku 1h = $2.0
        cache_read_tokens=0,
        model="claude-haiku-4-5",
    )
    parent = TurnUsage(
        model="claude-opus-4-7",  # 부모는 opus
        input_tokens=0,
        output_tokens=0,
        cache_creation_5m_tokens=0,
        cache_creation_1h_tokens=0,
        cache_read_tokens=0,
        message_id="msg_c",
        agent_tool_use_ids=["tu_1"],
    )
    s = aggregate([parent], elapsed=1.0, subagents=[sub])
    # haiku 1h $2/MT × 1M tokens = $2.0 (opus $10이 아닌)
    assert abs(s.total_cost - 2.0) < 1e-6
```

- [ ] **Step 7.2: 실패 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_aggregator.py -k "total_input_includes_both or per_tier_rates or sub_model_rates" -xvs
```

Expected: FAIL.

- [ ] **Step 7.3: aggregator 변경**

Modify `lib/aggregator.py:aggregate` — total_input 합산만:

```python
def aggregate(
    turns: list[TurnUsage],
    elapsed: float,
    subagents: list[SubagentUsage] | None = None,
) -> Summary:
    unique = _dedupe_by_message_id(turns)
    for i, t in enumerate(unique):
        t.index = i

    if subagents:
        _attach_subagents(unique, subagents)

    # Single-pass accumulation across each turn and its attached subagents.
    # Subagents bill at their own model rate when known; otherwise fall back
    # to parent. Input total includes both 5m and 1h cache_creation tiers
    # (spec §6).
    total_cost = 0.0
    total_input = 0
    total_output = 0
    cache_read = 0
    for t in unique:
        for item in (t, *t.subagents):
            sub_model = getattr(item, "model", "")
            billing_model = effective_billing_model(sub_model, t.model)
            total_cost += compute_cost(billing_model, item)
            total_input += (
                item.input_tokens
                + item.cache_creation_5m_tokens
                + item.cache_creation_1h_tokens
                + item.cache_read_tokens
            )
            total_output += item.output_tokens
            cache_read += item.cache_read_tokens

    cache_hit_rate = (cache_read / total_input) if total_input > 0 else 0.0

    return Summary(
        total_cost=total_cost,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        cache_hit_rate=cache_hit_rate,
        total_elapsed=elapsed,
        turns=unique,
    )
```

- [ ] **Step 7.4: 통과 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_aggregator.py -k "total_input_includes_both or per_tier_rates or sub_model_rates" -xvs
```

Expected: PASS (3/3).

- [ ] **Step 7.5: dedupe 회귀 가드 (Task 0 진단 결과 반영)**

진단 결과에 따라 분기:
- Task 0에서 "✅ dedupe 첫 라인에 cc 항상 박힘" → 추가 작업 없음. 다음 step으로.
- Task 0에서 "⚠️ dedupe 첫 라인에 cc 없음" → `_dedupe_by_message_id`에 cache field merge 추가 필요. 그 경우 spec §6 보강 + 신규 테스트 + commit.

dedupe 보강이 필요할 경우 (Task 0 결과로만 발화):

```python
def test_dedupe_keeps_5m_1h_from_kept_line():
    from lib.aggregator import _dedupe_by_message_id
    from lib.parser import TurnUsage
    # 같은 msg_id, 첫 라인 cache 0 / 두 번째 라인 cache 양수
    t1 = TurnUsage(model="claude-opus-4-7", input_tokens=0, output_tokens=0,
                    cache_creation_5m_tokens=0, cache_creation_1h_tokens=0,
                    cache_read_tokens=0, message_id="m1")
    t2 = TurnUsage(model="claude-opus-4-7", input_tokens=0, output_tokens=0,
                    cache_creation_5m_tokens=100, cache_creation_1h_tokens=200,
                    cache_read_tokens=0, message_id="m1")
    out = _dedupe_by_message_id([t1, t2])
    assert len(out) == 1
    # 보강 결과: 두 번째 라인의 cache 값이 살아남음
    assert out[0].cache_creation_5m_tokens == 100
    assert out[0].cache_creation_1h_tokens == 200
```

이 테스트가 필요하면 `_dedupe_by_message_id`에 다음 merge 추가:

```python
# kept 객체에 cache 필드가 0인데 새 라인에 양수가 있으면 갱신
if kept.cache_creation_5m_tokens == 0 and t.cache_creation_5m_tokens > 0:
    kept.cache_creation_5m_tokens = t.cache_creation_5m_tokens
if kept.cache_creation_1h_tokens == 0 and t.cache_creation_1h_tokens > 0:
    kept.cache_creation_1h_tokens = t.cache_creation_1h_tokens
```

- [ ] **Step 7.6: commit**

```bash
git add plugins/token-tracker/lib/aggregator.py plugins/token-tracker/tests/test_aggregator.py
git commit -m "feat(aggregator): total_input에 5m+1h 합산 + sub model 단가 정확 적용"
```

---

## Task 8: summary_store SCHEMA_VERSION v3 + 화이트리스트 갱신

**Files:**
- Modify: `plugins/token-tracker/lib/summary_store.py`
- Test: `plugins/token-tracker/tests/test_summary_store.py`

- [ ] **Step 8.1: 실패 테스트**

```python
def test_save_writes_v3():
    import json
    from lib.aggregator import Summary
    from lib.parser import TurnUsage
    from lib.summary_store import save_last_summary, _summary_path
    summary = Summary(
        total_cost=1.0, total_input_tokens=100, total_output_tokens=50,
        cache_hit_rate=0.5, total_elapsed=1.0,
        turns=[TurnUsage(
            model="claude-opus-4-7", input_tokens=10, output_tokens=20,
            cache_creation_5m_tokens=30, cache_creation_1h_tokens=40,
            cache_read_tokens=5, message_id="m1",
        )],
    )
    save_last_summary("test_v3_session", summary)
    with _summary_path("test_v3_session").open() as f:
        data = json.load(f)
    assert data["schema_version"] == 3
    t = data["summary"]["turns"][0]
    assert t["cache_creation_5m_tokens"] == 30
    assert t["cache_creation_1h_tokens"] == 40
    assert "cache_creation_tokens" not in t


def test_load_v3_roundtrip():
    from lib.aggregator import Summary
    from lib.parser import TurnUsage
    from lib.summary_store import save_last_summary, load_last_summary
    summary = Summary(
        total_cost=1.0, total_input_tokens=100, total_output_tokens=50,
        cache_hit_rate=0.5, total_elapsed=1.0,
        turns=[TurnUsage(
            model="claude-opus-4-7", input_tokens=10, output_tokens=20,
            cache_creation_5m_tokens=30, cache_creation_1h_tokens=40,
            cache_read_tokens=5, message_id="m1",
        )],
    )
    save_last_summary("test_roundtrip", summary)
    loaded = load_last_summary("test_roundtrip")
    assert loaded is not None
    assert loaded.turns[0].cache_creation_5m_tokens == 30
    assert loaded.turns[0].cache_creation_1h_tokens == 40
```

- [ ] **Step 8.2: 실패 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_summary_store.py -k "writes_v3 or v3_roundtrip" -xvs
```

Expected: FAIL.

- [ ] **Step 8.3: 구현**

Modify `lib/summary_store.py`:

```python
SCHEMA_VERSION = 3
SUPPORTED_SCHEMA_VERSIONS = (3,)   # v1, v2 제거 — 옛 파일은 None 반환

# ... (기존 코드)

_TURN_KEYS = (
    "model",
    "input_tokens",
    "output_tokens",
    "cache_creation_5m_tokens",   # 신규
    "cache_creation_1h_tokens",   # 신규
    "cache_read_tokens",
    "tools_used",
    "timestamp_iso",
    "message_id",
    "index",
    "started_at",
    "ended_at",
    "agent_tool_use_ids",
)
_SUB_KEYS = (
    "agent_type",
    "tool_use_id",
    "input_tokens",
    "output_tokens",
    "cache_creation_5m_tokens",   # 신규
    "cache_creation_1h_tokens",   # 신규
    "cache_read_tokens",
    "total_duration_ms",
    "model",
)
```

- [ ] **Step 8.4: 통과 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_summary_store.py -k "writes_v3 or v3_roundtrip" -xvs
```

Expected: PASS.

- [ ] **Step 8.5: commit**

```bash
git add plugins/token-tracker/lib/summary_store.py plugins/token-tracker/tests/test_summary_store.py
git commit -m "feat(summary_store): SCHEMA_VERSION v3 + 5m/1h 화이트리스트"
```

---

## Task 9: summary_store v1/v2 None 반환 회귀 가드

**Files:**
- Test: `plugins/token-tracker/tests/test_summary_store.py` (코드는 Task 8에서 이미 처리)

- [ ] **Step 9.1: 회귀 가드 테스트 작성**

```python
def test_load_v1_returns_none(tmp_path, monkeypatch):
    """v1 schema 파일은 load 시 None 반환 + stderr 경고."""
    import json
    from lib import summary_store, paths
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    sid = "test_v1"
    sdir = tmp_path / sid
    sdir.mkdir()
    (sdir / "last_summary.json").write_text(json.dumps({
        "schema_version": 1,
        "session_id": sid,
        "saved_at": 0,
        "summary": {"total_cost": 0.5, "total_input_tokens": 100,
                     "total_output_tokens": 50, "cache_hit_rate": 0.0,
                     "total_elapsed": 1.0, "turns": []},
    }))
    assert summary_store.load_last_summary(sid) is None


def test_load_v2_returns_none(tmp_path, monkeypatch):
    import json
    from lib import summary_store, paths
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    sid = "test_v2"
    sdir = tmp_path / sid
    sdir.mkdir()
    (sdir / "last_summary.json").write_text(json.dumps({
        "schema_version": 2,
        "session_id": sid,
        "saved_at": 0,
        "summary": {"total_cost": 0.5, "total_input_tokens": 100,
                     "total_output_tokens": 50, "cache_hit_rate": 0.0,
                     "total_elapsed": 1.0, "turns": []},
    }))
    assert summary_store.load_last_summary(sid) is None
```

- [ ] **Step 9.2: 통과 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_summary_store.py -k "v1_returns_none or v2_returns_none" -xvs
```

Expected: PASS (Task 8에서 SUPPORTED_SCHEMA_VERSIONS=(3,)로 변경했으므로).

- [ ] **Step 9.3: commit**

```bash
git add plugins/token-tracker/tests/test_summary_store.py
git commit -m "test(summary_store): v1/v2 파일 None 반환 회귀 가드"
```

---

## Task 10: detail_formatter cache 칼럼 5m+1h 합산

**Files:**
- Modify: `plugins/token-tracker/lib/detail_formatter.py:200,226`
- Test: `plugins/token-tracker/tests/test_detail_formatter.py`

- [ ] **Step 10.1: 실패 테스트 (AttributeError 회귀 가드)**

```python
def test_detail_formatter_renders_with_5m_1h_fields():
    """detail_formatter가 신규 5m/1h 필드를 합산해 cache 칼럼에 표시."""
    from lib.detail_formatter import format_detail
    from lib.aggregator import Summary
    from lib.parser import TurnUsage
    summary = Summary(
        total_cost=1.0, total_input_tokens=1000, total_output_tokens=100,
        cache_hit_rate=0.5, total_elapsed=2.0,
        turns=[TurnUsage(
            model="claude-opus-4-7", input_tokens=10, output_tokens=20,
            cache_creation_5m_tokens=300, cache_creation_1h_tokens=200,
            cache_read_tokens=50, message_id="m1",
        )],
    )
    text = format_detail(summary, lang="ko")
    # cache 칼럼이 합산 500을 표시 (5m 300 + 1h 200)
    assert "500" in text
```

- [ ] **Step 10.2: 실패 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_detail_formatter.py::test_detail_formatter_renders_with_5m_1h_fields -xvs
```

Expected: FAIL — `AttributeError: 'TurnUsage' object has no attribute 'cache_creation_tokens'`.

- [ ] **Step 10.3: detail_formatter 변경**

Modify `lib/detail_formatter.py:200,226` (정확한 line은 read 후 확인):

```python
# 기존: f"{turn.cache_creation_tokens:,}"
# 신규:
f"{(turn.cache_creation_5m_tokens + turn.cache_creation_1h_tokens):,}"
```

같은 패턴으로 sub 행(line 226):
```python
f"{(sub.cache_creation_5m_tokens + sub.cache_creation_1h_tokens):,}"
```

- [ ] **Step 10.4: 통과 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_detail_formatter.py::test_detail_formatter_renders_with_5m_1h_fields -xvs
```

Expected: PASS.

- [ ] **Step 10.5: commit**

```bash
git add plugins/token-tracker/lib/detail_formatter.py plugins/token-tracker/tests/test_detail_formatter.py
git commit -m "feat(detail): cache 칼럼이 5m+1h 합산 표시 (AttributeError 회귀 fix)"
```

---

## Task 11: detail.py schema gate (3,) 갱신

**Files:**
- Modify: `plugins/token-tracker/skills/token-detail/scripts/detail.py:58`
- Test: `plugins/token-tracker/tests/test_detail_script_e2e.py`

- [ ] **Step 11.1: 실패 테스트**

```python
def test_detail_script_accepts_v3_schema(tmp_path, monkeypatch):
    """detail.py가 v3 schema 파일을 정상 read."""
    import json, subprocess, sys
    from pathlib import Path
    from lib import paths
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    sid = "test_v3_detail"
    sdir = tmp_path / sid
    sdir.mkdir()
    (sdir / "last_summary.json").write_text(json.dumps({
        "schema_version": 3,
        "session_id": sid,
        "saved_at": 0,
        "summary": {
            "total_cost": 0.1, "total_input_tokens": 100,
            "total_output_tokens": 50, "cache_hit_rate": 0.0,
            "total_elapsed": 1.0,
            "turns": [{
                "model": "claude-opus-4-7", "input_tokens": 10,
                "output_tokens": 20, "cache_creation_5m_tokens": 30,
                "cache_creation_1h_tokens": 40, "cache_read_tokens": 5,
                "tools_used": [], "timestamp_iso": "", "message_id": "m1",
                "index": 0, "started_at": None, "ended_at": None,
                "agent_tool_use_ids": [], "subagents": [],
            }],
        },
    }))
    # detail.py 스크립트 직접 실행
    script = Path(__file__).parent.parent / "skills/token-detail/scripts/detail.py"
    result = subprocess.run(
        [sys.executable, str(script), sid],
        env={**__import__("os").environ, "TOKEN_TRACKER_LANG": "ko"},
        capture_output=True, text=True,
    )
    # "지원하지 않는 schema_version" 에러 없어야 함
    assert "지원하지 않는" not in result.stdout
    assert "지원하지 않는" not in result.stderr
    assert result.returncode == 0
```

(이 테스트는 통합형이라 실제로는 monkeypatch로 state_dir 못 바꿈 — subprocess라서. 대안: detail.py가 자기 스스로 schema gate 검사 후 조용히 거부하는지 unit test.)

대안 단순 테스트:

```python
def test_detail_script_v3_in_supported_versions():
    """detail.py 안의 schema_version 화이트리스트에 3이 포함됨."""
    from pathlib import Path
    src = (Path(__file__).parent.parent /
           "skills/token-detail/scripts/detail.py").read_text()
    # (3,) 패턴 또는 (1, 2, 3) 같은 것이라도 3이 포함되어야 함
    assert "(3,)" in src or "3 in" in src or "3, " in src or ", 3)" in src or ", 3," in src
```

- [ ] **Step 11.2: 실패 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_detail_script_e2e.py::test_detail_script_v3_in_supported_versions -xvs
```

Expected: FAIL — 현재는 `(1, 2)`.

- [ ] **Step 11.3: detail.py 변경**

Modify `skills/token-detail/scripts/detail.py:58`:

```python
# 기존: if data.get("schema_version") not in (1, 2):
# 신규:
if data.get("schema_version") not in (3,):
```

- [ ] **Step 11.4: 통과 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_detail_script_e2e.py::test_detail_script_v3_in_supported_versions -xvs
```

Expected: PASS.

- [ ] **Step 11.5: commit**

```bash
git add plugins/token-tracker/skills/token-detail/scripts/detail.py plugins/token-tracker/tests/test_detail_script_e2e.py
git commit -m "feat(detail): detail.py schema gate v3 동기 갱신"
```

---

## Task 12: 신규 e2e 테스트 3건

**Files:**
- Test: `plugins/token-tracker/tests/test_hook_end_to_end.py` (또는 신규 e2e 파일)

- [ ] **Step 12.1: e2e #1 — 실제 1h-heavy transcript fixture로 정확 비용 검증**

Add to `tests/test_hook_end_to_end.py`:

```python
def test_e2e_pricing_with_real_transcript_shape(tmp_path, monkeypatch):
    """진단에서 캡처한 1h-heavy 실제 shape으로 cost 정확 계산."""
    import json
    from lib.parser import parse_line
    from lib.aggregator import aggregate
    # 진단에서 본 실제 shape (cache_creation 100% 1h)
    entry = {
        "type": "assistant",
        "message": {
            "id": "msg_real",
            "model": "claude-opus-4-7",
            "usage": {
                "input_tokens": 6,
                "output_tokens": 1058,
                "cache_read_input_tokens": 15433,
                "cache_creation_input_tokens": 42180,  # legacy
                "cache_creation": {
                    "ephemeral_1h_input_tokens": 42180,
                    "ephemeral_5m_input_tokens": 0,
                },
            },
            "content": [],
        },
        "timestamp": "2026-05-03T10:00:00Z",
    }
    t = parse_line(entry)
    s = aggregate([t], elapsed=1.0)
    # 정확 비용:
    # input 6 × $5/MT = $0.00003
    # output 1058 × $25/MT = $0.026450
    # cache_1h 42180 × $10/MT = $0.421800
    # cache_read 15433 × $0.50/MT = $0.0077165
    # total ≈ $0.4560
    expected = (
        6 * 5.0 / 1_000_000
        + 1058 * 25.0 / 1_000_000
        + 42180 * 10.0 / 1_000_000
        + 15433 * 0.50 / 1_000_000
    )
    assert abs(s.total_cost - expected) < 1e-6
```

- [ ] **Step 12.2: e2e #2 — 자연 마이그레이션 path 동일성**

```python
def test_e2e_v2_summary_load_returns_none_then_next_save_creates_v3_at_same_path(tmp_path, monkeypatch):
    """v2 파일 → load None → 같은 path에 v3 새로 저장됨."""
    import json
    from lib import summary_store, paths
    from lib.aggregator import Summary
    from lib.parser import TurnUsage
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    sid = "test_natural_migration"
    sdir = tmp_path / sid
    sdir.mkdir()
    target = sdir / "last_summary.json"
    target.write_text(json.dumps({
        "schema_version": 2,
        "session_id": sid,
        "saved_at": 0,
        "summary": {"total_cost": 0.5, "total_input_tokens": 100,
                     "total_output_tokens": 50, "cache_hit_rate": 0.0,
                     "total_elapsed": 1.0, "turns": []},
    }))

    # 1) v2 파일 load → None
    assert summary_store.load_last_summary(sid) is None

    # 2) 새 Summary save → 같은 path에 v3 생성
    new_summary = Summary(
        total_cost=0.1, total_input_tokens=10, total_output_tokens=5,
        cache_hit_rate=0.0, total_elapsed=0.5,
        turns=[TurnUsage(model="claude-opus-4-7", input_tokens=1, output_tokens=1,
                          cache_creation_5m_tokens=0, cache_creation_1h_tokens=0,
                          cache_read_tokens=0, message_id="m_new")],
    )
    summary_store.save_last_summary(sid, new_summary)

    # 3) path 동일성 + v3 schema 확인
    assert target.exists()
    with target.open() as f:
        data = json.load(f)
    assert data["schema_version"] == 3
```

- [ ] **Step 12.3: e2e #3 — detail v3 표시 (CRITICAL #1, #2 회귀 가드)**

```python
def test_e2e_detail_renders_after_v3_save(tmp_path, monkeypatch):
    """v3 파일 저장 → detail_formatter가 cache 칼럼 정상 표시 (AttributeError 없음)."""
    from lib import summary_store, paths
    from lib.aggregator import Summary
    from lib.parser import TurnUsage
    from lib.detail_formatter import format_detail
    monkeypatch.setattr(paths, "state_dir", lambda: tmp_path)
    sid = "test_detail_e2e"
    summary = Summary(
        total_cost=0.1, total_input_tokens=550, total_output_tokens=20,
        cache_hit_rate=0.5, total_elapsed=1.0,
        turns=[TurnUsage(
            model="claude-opus-4-7", input_tokens=10, output_tokens=20,
            cache_creation_5m_tokens=300, cache_creation_1h_tokens=200,
            cache_read_tokens=50, message_id="m_e2e",
        )],
    )
    summary_store.save_last_summary(sid, summary)
    loaded = summary_store.load_last_summary(sid)
    assert loaded is not None
    text = format_detail(loaded, lang="ko")
    assert "500" in text  # 5m 300 + 1h 200
```

- [ ] **Step 12.4: 3건 모두 통과 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_hook_end_to_end.py -k "real_transcript_shape or natural_migration or detail_renders_after_v3" -xvs
```

Expected: PASS (3/3).

- [ ] **Step 12.5: commit**

```bash
git add plugins/token-tracker/tests/test_hook_end_to_end.py
git commit -m "test(e2e): 1h-heavy 정확 비용 + 자연 마이그레이션 + detail v3 회귀 가드"
```

---

## Task 13: 기존 ~94곳 fixture/cost 기댓값 일괄 갱신

**Files:** (모두 수정)
- `plugins/token-tracker/tests/test_hook_end_to_end.py` (25곳)
- `plugins/token-tracker/tests/test_sidechain.py` (15곳)
- `plugins/token-tracker/tests/test_parser.py` (13곳)
- `plugins/token-tracker/tests/test_aggregator.py` (14곳)
- `plugins/token-tracker/tests/test_pricing.py` (11곳)
- `plugins/token-tracker/tests/test_summary_store.py` (9곳)
- `plugins/token-tracker/tests/test_detail_formatter.py` (6곳)
- `plugins/token-tracker/tests/test_detail_script_e2e.py` (1곳)

**전략**: 같은 commit으로 처리하면 큰 commit. 파일별로 commit 분리.

- [ ] **Step 13.1: 옛 → 신 변환 패턴 (모든 파일 공통)**

`grep -rn "cache_creation_tokens" plugins/token-tracker/tests/`로 모든 인용 위치 확인.

각 fixture/assertion 패턴:

| 옛 | 신 |
|---|---|
| `cache_creation_tokens=N` | `cache_creation_5m_tokens=N` (보수적: legacy 시절 데이터를 5m로 매핑) |
| `cache_creation_tokens: N` (dict) | `cache_creation_5m_tokens: N` |
| `t.cache_creation_tokens` (assertion) | `(t.cache_creation_5m_tokens + t.cache_creation_1h_tokens)` (합산값으로) |
| `usage.cache_creation_input_tokens=N` (transcript fixture) | `usage.cache_creation_input_tokens=N` 그대로 + `cache_creation: {ephemeral_5m_input_tokens: N, ephemeral_1h_input_tokens: 0}` 추가 — 또는 fixture가 fallback 검증용이면 cc 객체 없는 채로 둠 |

**cost 기댓값 갱신**: Opus 단가 1/3 인하라 모든 Opus 비용 assert가 깨짐.
- 옛 input $15/MT × N → 신 $5/MT × N (3배 작음)
- 옛 output $75/MT × N → 신 $25/MT × N
- 옛 cache_creation $18.75/MT × N → 신 5m $6.25/MT 또는 1h $10/MT × N
- 옛 cache_read $1.5/MT × N → 신 $0.50/MT × N

각 파일별로 작업.

- [ ] **Step 13.2: test_parser.py 갱신**

```bash
grep -n "cache_creation_tokens\|cache_creation_input_tokens" plugins/token-tracker/tests/test_parser.py
```

각 인용을 위 패턴으로 수정. 통과 확인:

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py -xvs
```

Expected: 모든 기존 + Task 1~4 신규 테스트 PASS.

```bash
git add plugins/token-tracker/tests/test_parser.py
git commit -m "test(parser): fixture를 5m/1h 분리 형식으로 갱신"
```

- [ ] **Step 13.3: test_pricing.py 갱신**

같은 패턴. cost 기댓값 신단가로 재계산. 통과 확인 + commit:

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_pricing.py -xvs
git add plugins/token-tracker/tests/test_pricing.py
git commit -m "test(pricing): fixture를 5m/1h 분리 + 신 단가 cost 재계산"
```

- [ ] **Step 13.4: test_aggregator.py 갱신**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_aggregator.py -xvs
git add plugins/token-tracker/tests/test_aggregator.py
git commit -m "test(aggregator): fixture 5m/1h 분리 + 신 단가 cost 재계산"
```

- [ ] **Step 13.5: test_summary_store.py 갱신**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_summary_store.py -xvs
git add plugins/token-tracker/tests/test_summary_store.py
git commit -m "test(summary_store): fixture를 v3 schema + 5m/1h 형식으로 갱신"
```

- [ ] **Step 13.6: test_detail_formatter.py 갱신**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_detail_formatter.py -xvs
git add plugins/token-tracker/tests/test_detail_formatter.py
git commit -m "test(detail_formatter): fixture를 5m/1h 분리 형식으로 갱신"
```

- [ ] **Step 13.7: test_sidechain.py 갱신**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_sidechain.py -xvs
git add plugins/token-tracker/tests/test_sidechain.py
git commit -m "test(sidechain): fixture를 5m/1h 분리 형식으로 갱신"
```

- [ ] **Step 13.8: test_hook_end_to_end.py 갱신**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_hook_end_to_end.py -xvs
git add plugins/token-tracker/tests/test_hook_end_to_end.py
git commit -m "test(hook_e2e): fixture를 5m/1h 분리 + 신 단가 형식으로 갱신"
```

- [ ] **Step 13.9: test_detail_script_e2e.py 갱신**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_detail_script_e2e.py -xvs
git add plugins/token-tracker/tests/test_detail_script_e2e.py
git commit -m "test(detail_script_e2e): fixture를 v3 schema 형식으로 갱신"
```

---

## Task 14: 전체 테스트 통과 확인 + plugin.json version bump

**Files:**
- Modify: `plugins/token-tracker/.claude-plugin/plugin.json`

- [ ] **Step 14.1: 전체 테스트 통과 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests -q
```

Expected: ~268 passed (248 baseline + 신규 약 20건).

실패하면 해당 파일 다시 수정 후 재실행. 모두 통과까지.

- [ ] **Step 14.2: version bump**

Modify `plugins/token-tracker/.claude-plugin/plugin.json`:

```json
{
  "name": "token-tracker",
  "description": "한 번의 프롬프트가 소비한 토큰·비용을 Stop hook 응답 블록에 한 줄로 표시",
  "version": "0.7.0",
  "author": { "name": "brody" }
}
```

- [ ] **Step 14.3: marketplace.json 동기화 (만약 version 인용이 있다면)**

```bash
grep -n "0.6.4\|version" .claude-plugin/marketplace.json
```

version 인용 있으면 0.7.0으로 갱신.

- [ ] **Step 14.4: commit**

```bash
git add plugins/token-tracker/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "chore(release): bump to 0.7.0"
```

---

## Task 15: 사용자 1턴 검증 + cache 동기화 + v0.7.0 태그 + 핸드오프 갱신

**Files:**
- Modify: `~/.claude/plugins/cache/token-tracker-local/token-tracker/0.6.0/...` (cache 동기화)
- Create: `docs/handoff/2026-05-03-token-tracker-next-steps.md`

- [ ] **Step 15.1: cache 디렉터리 동기화**

Claude Code는 cache 사본을 발화하므로 source → cache 복사:

```bash
SRC=/Users/brody/Desktop/token-tracker/plugins/token-tracker
DST=$HOME/.claude/plugins/cache/token-tracker-local/token-tracker/0.6.0
cp $SRC/lib/parser.py $DST/lib/
cp $SRC/lib/pricing.py $DST/lib/
cp $SRC/lib/aggregator.py $DST/lib/
cp $SRC/lib/summary_store.py $DST/lib/
cp $SRC/lib/detail_formatter.py $DST/lib/
cp $SRC/skills/token-detail/scripts/detail.py $DST/skills/token-detail/scripts/
cp $SRC/.claude-plugin/plugin.json $DST/.claude-plugin/
```

또는 `/reload-plugins` 명령으로 한 번에 재로드 (사용자가 직접 실행).

- [ ] **Step 15.2: 사용자에게 1턴 trigger 요청**

사용자에게:
- "v0.7.0 코드 적용 완료. 짧은 메시지 한 번 보내줘. 응답 끝나면 statusline 비용과 token-tracker 한 줄 요약 비용을 비교해서 알려줘. ±5% 일치 = 검증 통과."

- [ ] **Step 15.3: 검증 결과 분기**

- **±5% 일치** → success → Step 15.4로
- **여전히 큰 차이** → 추가 진단 필요. spec §10 진단 다시 + silent $0 stderr 로그 확인 + follow-up issue 발급. v0.7.0 태그 보류.

- [ ] **Step 15.4: 핸드오프 문서 작성**

Create `docs/handoff/2026-05-03-token-tracker-next-steps.md`:

```markdown
# token-tracker 인수인계 — 2026-05-03

## 1. 한 줄 요약

token-tracker = Claude Code 플러그인. Stop hook이 발화할 때마다 토큰·비용 한 줄 요약 출력. **현재 v0.7.0** — pricing 정확도 v2 적용:
- Opus 4.7 단가 회귀 fix ($15→$5, 3배 overbill 해소)
- prompt cache 1h tier 분리 (5m $6.25 vs 1h $10 별도 단가)
- summary_store schema v2 → v3 breaking (옛 파일 자연 무시)
- detail_formatter / detail.py 동기 갱신
- ~268 tests passing

## 2. v0.6.x → v0.7.0 환산
- v0.6.x에서 Opus turn당 $0.30 표시 → v0.7.0에서 약 $0.10 표시 (3배 작음, 정상)
- 옛 누적 비용 직접 비교 의미 없음

## 3. 다음 작업 후보
- C': /token-history skill (세션 내 모든 request 요약 리스트)
- pricing 데이터/코드 분리 (lib/pricing_data.json)
- 옛 session 디렉터리 GC

## 4. 진행 흐름 메모
- v0.7.0 spec/plan: docs/superpowers/specs/2026-05-03-...md, docs/superpowers/plans/2026-05-03-...md
- 7개 적대적 리뷰 + 3명 팀메이트 리뷰 모두 반영
```

- [ ] **Step 15.5: v0.7.0 태그 + handoff commit**

```bash
git add docs/handoff/2026-05-03-token-tracker-next-steps.md
git commit -m "docs(handoff): v0.7.0 출시 핸드오프"

# main 브랜치로 머지 (사용자 승인 후)
# git checkout main
# git merge --no-ff feature/v0.7.0-pricing-accuracy -m "Merge: feature/v0.7.0-pricing-accuracy — pricing 정확도 v2"
# git tag -a v0.7.0 -m "v0.7.0: Opus 단가 회귀 fix + 1h tier 분리"
# git push origin main --tags  # 사용자 명시 승인 후
```

---

## Self-Review (작성 후)

- **Spec coverage**: spec §3~§13 모두 task로 매핑됨. §10 진단 = Task 0. §11 silent $0 = Task 5+6. §12 검증 = Task 15. §13 핸드오프 = Task 15.4. ✅
- **Placeholder scan**: TBD/TODO 없음. 모든 step에 구체적 명령/코드. ✅
- **Type consistency**: TurnUsage / SubagentUsage 시그니처 모든 task에서 동일. ✅
- **사용자 룰 준수**: feature 브랜치, TDD red-green-commit, 한글 메시지, fixture와 메인 변경 같은 PR. ✅
- **PR 사이즈**: production code <300줄 (parser/pricing/aggregator/summary_store/detail_formatter/detail.py 합산 ~150줄). fixture는 별도 카운트. ✅

---

## 실행 방식 선택

Plan complete and saved to `docs/superpowers/plans/2026-05-03-token-tracker-pricing-accuracy.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration. 15개 task를 사용자 승인 사이사이에 두고 진행. 각 task가 독립적이라 병렬화 가능 영역도 있음.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints. 한 세션에 끝까지 진행, 체크포인트 between phases.

어느 방식?
