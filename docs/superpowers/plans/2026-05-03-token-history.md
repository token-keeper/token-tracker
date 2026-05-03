# /token-history Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code 세션의 모든 user prompt(현재 세션 + 전체 세션)에 대한 token/cost 요약 + transcript 전체를 로컬 web 브라우저에서 표시하는 `/token-history` skill을 구현한다.

**Architecture:** `on_user_prompt` hook이 `prompt_id`를 발급해 state에 저장 → `on_stop` hook이 매 Stop마다 그 prompt_id로 `history.jsonl` 마지막 행을 in-place rewrite 또는 append (transcript_entries 포함). `/token-history` skill은 `state/{current}/history.jsonl` + `state/*/history.jsonl` glob을 read해서 self-contained static HTML 한 파일을 생성하고 macOS `open file://...`으로 브라우저 자동 open.

**Tech Stack:** Python stdlib only (json, secrets, glob, subprocess, tempfile). Vanilla JS + 단일 HTML (라이브러리 0). pytest. 기존 token-tracker 패턴(i18n, summary_store schema versioning, atomic write, error.log) 그대로 따름.

**Spec:** `docs/superpowers/specs/2026-05-03-token-history-design.md`

**Target version:** v0.8.0

---

## File Structure

### Create

| 파일 | 역할 |
|---|---|
| `plugins/token-tracker/lib/history_store.py` | history.jsonl append/in-place rewrite, schema versioning, atomic write, multi-session glob load |
| `plugins/token-tracker/lib/history_renderer.py` | per-session + cross-session 데이터 → self-contained HTML 생성 (i18n inline, css/js inline, two `<script type="application/json">` blocks) |
| `plugins/token-tracker/skills/token-history/SKILL.md` | slash command entry, `disable-model-invocation: true` |
| `plugins/token-tracker/skills/token-history/scripts/history.py` | renderer 호출 + `open file://` 실행 + URL chat 출력 |
| `plugins/token-tracker/skills/token-history/templates/history.html.tmpl` | HTML 템플릿 (placeholder 토큰 방식) |
| `plugins/token-tracker/skills/token-history/static/style.css` | UI 스타일 (renderer가 inline으로 합침) |
| `plugins/token-tracker/skills/token-history/static/app.js` | sortable / search / filter / expand-collapse JS (renderer가 inline으로 합침) |
| `plugins/token-tracker/tests/test_history_store.py` | history_store unit tests |
| `plugins/token-tracker/tests/test_history_renderer.py` | renderer unit tests (HTML 출력에 data JSON inline 검증, escaping 검증) |
| `plugins/token-tracker/tests/test_history_skill_e2e.py` | skill 호출 → html 파일 생성 + URL 출력 e2e (subprocess.run mock) |

### Modify

| 파일 | 변경 |
|---|---|
| `plugins/token-tracker/hooks/on_user_prompt.py` | synthetic 분기 그대로, **real user prompt에서만** state에 `prompt_id` + `prompt_text` 추가 저장 |
| `plugins/token-tracker/hooks/on_stop.py` | line 187 `if count_active_async_agents > 0: return 0` 직전, `if summary.turns:` 가드 시점에 `history_store.append_or_update_history(...)` 호출 (try/except 격리) |
| `plugins/token-tracker/lib/parser.py` | `parse_user_prompt_text` / `parse_thinking` / `parse_assistant_text` / `parse_tool_call` / `parse_tool_result` / `parse_transcript_for_history` 헬퍼 추가 (기존 함수·dataclass 변경 없음) |
| `plugins/token-tracker/lib/i18n/ko.json`, `en.json` | web UI 문자열 키 22개 추가 |
| `plugins/token-tracker/tests/test_parser.py` | 신규 헬퍼 테스트 추가 |
| `plugins/token-tracker/tests/test_on_user_prompt.py` (없으면 신규) | prompt_id 발급 검증 |
| `plugins/token-tracker/tests/test_hook_end_to_end.py` | hook 변경에 의한 회귀 가드 추가 |
| `.claude-plugin/marketplace.json` (repo 루트) | version `0.8.0` |
| `plugins/token-tracker/.claude-plugin/plugin.json` 등 plugin metadata | v0.8.0 |

---

## Task 0: 진단 (Prerequisite)

구현 시작 전 spec 가정 3건을 실제 환경에서 확인. 결과를 plan에 인라인 메모하고 가정이 깨지면 task 보강.

**Files:**
- Read: `~/.claude/projects/*/` (transcript JSONL 실 샘플)
- Read: `plugins/token-tracker/hooks/on_user_prompt.py:74,83`
- Write: 진단 결과를 본 plan Task 0 끝에 메모로 추가

- [ ] **Step 0.1: on_user_prompt payload `prompt` 필드 확인**

```bash
# 한 번이라도 사용한 transcript 파일 찾기
ls ~/.claude/projects/ | head -3
# 임의 세션의 첫 user_prompt entry 확인
head -5 ~/.claude/projects/<some-session>/<transcript>.jsonl | python3 -c '
import json, sys
for line in sys.stdin:
    e = json.loads(line)
    if e.get("type") == "user":
        print(json.dumps(e, indent=2, ensure_ascii=False)[:500])
        break
'
```

Expected: user entry에 `message.content` (string 또는 list of content blocks)가 있음. `text` 필드 또는 `[{"type":"text","text":"..."}]` 형식. 이 결과를 토대로 `parse_user_prompt_text` 구현 (Task 1).

- [ ] **Step 0.2: thinking block 존재 확인**

```bash
# assistant entry 중 thinking 있는 것 찾기
grep -l '"type":"thinking"' ~/.claude/projects/*/*.jsonl | head -1
# 있으면 sample read
grep '"type":"thinking"' ~/.claude/projects/<found>/<transcript>.jsonl | head -1 | python3 -m json.tool
```

Expected: `assistant.message.content[]`에 `{"type":"thinking", "thinking":"...", "signature":"..."}` block이 있을 수 있음. `parse_thinking` 구현 시 이 구조 따름. 없으면 `parse_thinking`은 빈 list 반환 default.

- [ ] **Step 0.3: on_user_prompt가 받는 payload 실제 키 확인**

```bash
# error.log나 stderr 출력 활용. on_user_prompt.py 임시 수정 없이도 확인 가능:
python3 -c "
import json
sample = {
    'session_id': 'test',
    'transcript_path': '/tmp/x',
    'prompt': 'hello world'
}
print(json.dumps(sample, indent=2))
"
```

핵심 확인: `hook_input.get('prompt')`가 실제로 user 입력 문자열이어야 함. `on_user_prompt.py:83`이 이미 그 가정으로 구현되어 있으므로 참 (회귀 가드).

- [ ] **Step 0.4: 진단 메모를 본 plan Task 0 끝에 추가**

이 Task는 정상 진행을 확인하는 게 목적. 가정이 모두 검증되면 다음 Task로. 어긋나면 해당 Task 수정 + 새 Task 추가.

- [ ] **Step 0.5: 진단 commit (선택)**

```bash
# 진단 결과만 메모로 plan에 추가됐다면
git add docs/superpowers/plans/2026-05-03-token-history.md
git commit -m "chore(plan): Task 0 진단 결과 메모"
```

---

## Task 1: Parser 신규 헬퍼

transcript JSONL entry에서 user prompt text / assistant text / thinking / tool call / tool result를 추출하는 헬퍼 5개 + 한 entries list를 spec §4.1 transcript_entries 포맷으로 변환하는 합성 헬퍼 1개.

**Files:**
- Modify: `plugins/token-tracker/lib/parser.py` (기존 dataclass·함수 변경 없음, 추가만)
- Modify: `plugins/token-tracker/tests/test_parser.py` (테스트 추가)

- [ ] **Step 1.1: 실패하는 테스트 작성 (parse_user_prompt_text)**

`tests/test_parser.py` 끝에 추가:

```python
# --- /token-history 헬퍼 테스트 ---

def test_parse_user_prompt_text_string_content():
    entry = {
        "type": "user",
        "message": {"role": "user", "content": "hello world"},
    }
    from lib.parser import parse_user_prompt_text
    assert parse_user_prompt_text(entry) == "hello world"


def test_parse_user_prompt_text_list_content():
    entry = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": "hi"}],
        },
    }
    from lib.parser import parse_user_prompt_text
    assert parse_user_prompt_text(entry) == "hi"


def test_parse_user_prompt_text_returns_none_for_non_user():
    entry = {"type": "assistant", "message": {"content": [{"type": "text", "text": "x"}]}}
    from lib.parser import parse_user_prompt_text
    assert parse_user_prompt_text(entry) is None


def test_parse_user_prompt_text_returns_none_for_malformed():
    from lib.parser import parse_user_prompt_text
    assert parse_user_prompt_text({}) is None
    assert parse_user_prompt_text({"type": "user"}) is None
    assert parse_user_prompt_text({"type": "user", "message": {}}) is None
```

- [ ] **Step 1.2: 테스트 실행 → FAIL 확인**

```bash
cd /Users/brody/Desktop/token-tracker
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py::test_parse_user_prompt_text_string_content -v
```
Expected: `ImportError: cannot import name 'parse_user_prompt_text' from 'lib.parser'`

- [ ] **Step 1.3: parse_user_prompt_text 구현**

`plugins/token-tracker/lib/parser.py` 끝에 추가:

```python
def parse_user_prompt_text(entry: dict) -> str | None:
    """Extract user prompt text from a 'user' entry.

    Handles both `content: "string"` and `content: [{"type":"text","text":"..."}]`
    formats. Returns None when entry shape doesn't match.
    """
    if not isinstance(entry, dict) or entry.get("type") != "user":
        return None
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return None
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text")
                if isinstance(t, str):
                    return t
    return None
```

- [ ] **Step 1.4: 테스트 실행 → PASS 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py -k parse_user_prompt_text -v
```
Expected: 4 tests pass.

- [ ] **Step 1.5: parse_thinking / parse_assistant_text 테스트 작성**

`tests/test_parser.py`에 추가:

```python
def test_parse_assistant_text_basic():
    entry = {
        "type": "assistant",
        "timestamp": "2026-05-03T14:23:00Z",
        "message": {"content": [{"type": "text", "text": "hello"}]},
    }
    from lib.parser import parse_assistant_text
    out = parse_assistant_text(entry)
    assert out == [{"type": "assistant_text", "ts": out[0]["ts"], "text": "hello"}]
    assert isinstance(out[0]["ts"], float)


def test_parse_assistant_text_skips_other_blocks():
    entry = {
        "type": "assistant",
        "timestamp": "2026-05-03T14:23:00Z",
        "message": {
            "content": [
                {"type": "thinking", "thinking": "..."},
                {"type": "text", "text": "answer"},
                {"type": "tool_use", "id": "x", "name": "Bash", "input": {}},
            ]
        },
    }
    from lib.parser import parse_assistant_text
    out = parse_assistant_text(entry)
    assert len(out) == 1 and out[0]["text"] == "answer"


def test_parse_thinking_basic():
    entry = {
        "type": "assistant",
        "timestamp": "2026-05-03T14:23:00Z",
        "message": {"content": [{"type": "thinking", "thinking": "let me think"}]},
    }
    from lib.parser import parse_thinking
    out = parse_thinking(entry)
    assert out == [{"type": "thinking", "ts": out[0]["ts"], "text": "let me think"}]


def test_parse_thinking_returns_empty_when_none():
    from lib.parser import parse_thinking
    assert parse_thinking({"type": "assistant", "message": {"content": []}}) == []
    assert parse_thinking({"type": "user"}) == []
```

- [ ] **Step 1.6: parse_thinking / parse_assistant_text 구현**

`lib/parser.py`에 추가:

```python
def _entry_ts(entry: dict) -> float:
    return _iso_to_epoch(entry.get("timestamp", "")) or 0.0


def parse_assistant_text(entry: dict) -> list[dict]:
    """Extract assistant text blocks (excluding thinking, tool_use). Returns
    list of {"type":"assistant_text", "ts": float, "text": str}."""
    if not isinstance(entry, dict) or entry.get("type") != "assistant":
        return []
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content") or []
    if not isinstance(content, list):
        return []
    ts = _entry_ts(entry)
    out: list[dict] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                out.append({"type": "assistant_text", "ts": ts, "text": text})
    return out


def parse_thinking(entry: dict) -> list[dict]:
    """Extract thinking blocks. Returns list of
    {"type":"thinking", "ts": float, "text": str}."""
    if not isinstance(entry, dict) or entry.get("type") != "assistant":
        return []
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content") or []
    if not isinstance(content, list):
        return []
    ts = _entry_ts(entry)
    out: list[dict] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "thinking":
            t = block.get("thinking")
            if isinstance(t, str):
                out.append({"type": "thinking", "ts": ts, "text": t})
    return out
```

- [ ] **Step 1.7: 테스트 실행 → PASS 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py -k "parse_assistant_text or parse_thinking" -v
```
Expected: 4 tests pass.

- [ ] **Step 1.8: parse_tool_call / parse_tool_result 테스트 작성**

```python
def test_parse_tool_call_basic():
    entry = {
        "type": "assistant",
        "timestamp": "2026-05-03T14:23:00Z",
        "message": {
            "content": [
                {"type": "tool_use", "id": "tu_1", "name": "Bash",
                 "input": {"command": "ls"}},
            ]
        },
    }
    from lib.parser import parse_tool_call
    out = parse_tool_call(entry)
    assert len(out) == 1
    assert out[0]["type"] == "tool_call"
    assert out[0]["name"] == "Bash"
    assert out[0]["input"] == {"command": "ls"}
    assert out[0]["id"] == "tu_1"


def test_parse_tool_result_basic():
    entry = {
        "type": "user",
        "timestamp": "2026-05-03T14:23:01Z",
        "message": {
            "content": [
                {"type": "tool_result", "tool_use_id": "tu_1",
                 "content": "ok", "is_error": False},
            ]
        },
    }
    from lib.parser import parse_tool_result
    out = parse_tool_result(entry)
    assert len(out) == 1
    assert out[0]["type"] == "tool_result"
    assert out[0]["tool_use_id"] == "tu_1"
    assert out[0]["content"] == "ok"
    assert out[0]["is_error"] is False


def test_parse_tool_result_with_list_content():
    entry = {
        "type": "user",
        "timestamp": "2026-05-03T14:23:01Z",
        "message": {
            "content": [
                {"type": "tool_result", "tool_use_id": "tu_2",
                 "content": [{"type": "text", "text": "out1"}, {"type": "text", "text": "out2"}]},
            ]
        },
    }
    from lib.parser import parse_tool_result
    out = parse_tool_result(entry)
    assert out[0]["content"] == "out1\nout2"
```

- [ ] **Step 1.9: parse_tool_call / parse_tool_result 구현**

```python
def parse_tool_call(entry: dict) -> list[dict]:
    """Extract tool_use blocks from assistant entry. Returns list of
    {"type":"tool_call", "ts": float, "id": str, "name": str, "input": dict}."""
    if not isinstance(entry, dict) or entry.get("type") != "assistant":
        return []
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content") or []
    if not isinstance(content, list):
        return []
    ts = _entry_ts(entry)
    out: list[dict] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            out.append({
                "type": "tool_call",
                "ts": ts,
                "id": block.get("id", ""),
                "name": block.get("name", ""),
                "input": block.get("input", {}),
            })
    return out


def parse_tool_result(entry: dict) -> list[dict]:
    """Extract tool_result blocks from user entry (Claude Code injects results
    as user messages). Normalizes content to a single string."""
    if not isinstance(entry, dict) or entry.get("type") != "user":
        return []
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content") or []
    if not isinstance(content, list):
        return []
    ts = _entry_ts(entry)
    out: list[dict] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            raw = block.get("content")
            if isinstance(raw, str):
                text = raw
            elif isinstance(raw, list):
                parts: list[str] = []
                for sub in raw:
                    if isinstance(sub, dict) and sub.get("type") == "text":
                        t = sub.get("text")
                        if isinstance(t, str):
                            parts.append(t)
                text = "\n".join(parts)
            else:
                text = ""
            out.append({
                "type": "tool_result",
                "ts": ts,
                "tool_use_id": block.get("tool_use_id", ""),
                "content": text,
                "is_error": bool(block.get("is_error", False)),
            })
    return out
```

- [ ] **Step 1.10: 테스트 실행 → PASS 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py -k "parse_tool_call or parse_tool_result" -v
```
Expected: 3 tests pass.

- [ ] **Step 1.11: parse_transcript_for_history 합성 헬퍼 테스트 + 구현**

테스트:

```python
def test_parse_transcript_for_history_orders_by_ts():
    entries = [
        {"type": "assistant", "timestamp": "2026-05-03T14:23:00Z",
         "message": {"content": [{"type": "text", "text": "hi"}]}},
        {"type": "user", "timestamp": "2026-05-03T14:23:01Z",
         "message": {"content": [{"type": "tool_result", "tool_use_id": "x",
                                  "content": "out"}]}},
        {"type": "assistant", "timestamp": "2026-05-03T14:23:02Z",
         "message": {"content": [{"type": "thinking", "thinking": "th"}]}},
    ]
    from lib.parser import parse_transcript_for_history
    out = parse_transcript_for_history(entries)
    assert [e["type"] for e in out] == ["assistant_text", "tool_result", "thinking"]
```

구현:

```python
def parse_transcript_for_history(entries: list[dict]) -> list[dict]:
    """Aggregate transcript entries into the spec §4.1 transcript_entries
    format. Excludes user prompt text (that's stored separately as
    user_prompt.text). Sort by ts ascending; entries with ts=0.0 (missing
    timestamp) keep insertion order via Python's stable sort."""
    out: list[dict] = []
    for e in entries:
        out.extend(parse_thinking(e))
        out.extend(parse_assistant_text(e))
        out.extend(parse_tool_call(e))
        out.extend(parse_tool_result(e))
    out.sort(key=lambda x: x["ts"])
    return out
```

- [ ] **Step 1.12: 전체 parser 테스트 + 회귀 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_parser.py -v
```
Expected: 기존 테스트 + 신규 테스트 모두 PASS.

- [ ] **Step 1.13: 전체 회귀 가드**

```bash
./venv/bin/pytest plugins/token-tracker/tests -q
```
Expected: 277 + 신규 (~12) all pass.

- [ ] **Step 1.14: Commit**

```bash
git add plugins/token-tracker/lib/parser.py plugins/token-tracker/tests/test_parser.py
git commit -m "feat(parser): /token-history용 transcript 추출 헬퍼 6종 추가"
```

---

## Task 2: history_store — schema + atomic write 기본

dataclass + JSONL atomic write (tmp+replace) + schema_version 검증. `append_or_update_history`는 Task 3에서 in-place rewrite 추가.

**Files:**
- Create: `plugins/token-tracker/lib/history_store.py`
- Create: `plugins/token-tracker/tests/test_history_store.py`

- [ ] **Step 2.1: 실패하는 테스트 (basic append + schema)**

`tests/test_history_store.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _build_summary_dict():
    return {
        "total_cost": 0.01,
        "total_input_tokens": 100,
        "total_output_tokens": 200,
        "cache_hit_rate": 0.5,
        "total_elapsed": 2.0,
        "turns": [],
    }


def test_append_creates_file_and_writes_one_line(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.history_store import (
        SCHEMA_VERSION,
        append_or_update_history,
        load_session_history,
    )

    sess = "sess_a"
    append_or_update_history(
        session_id=sess,
        prompt_id="p_001",
        user_prompt_text="hello",
        started_at=1.0,
        ended_at=2.0,
        summary_dict=_build_summary_dict(),
        models_used=["claude-opus-4-7"],
        has_subagent_other_model=False,
        transcript_entries=[],
    )

    path = tmp_path / ".claude/plugins/token-tracker/state" / sess / "history.jsonl"
    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["schema_version"] == SCHEMA_VERSION
    assert entry["prompt_id"] == "p_001"
    assert entry["user_prompt"] == {"text": "hello", "ts": 1.0}
    assert entry["models_used"] == ["claude-opus-4-7"]


def test_load_session_history_returns_entries(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.history_store import append_or_update_history, load_session_history

    append_or_update_history(
        session_id="s", prompt_id="p_1", user_prompt_text="a",
        started_at=1.0, ended_at=2.0, summary_dict=_build_summary_dict(),
        models_used=[], has_subagent_other_model=False, transcript_entries=[],
    )
    out = load_session_history("s")
    assert len(out) == 1 and out[0]["prompt_id"] == "p_1"


def test_load_session_history_empty_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.history_store import load_session_history
    assert load_session_history("nonexistent") == []
```

- [ ] **Step 2.2: 테스트 실행 → FAIL**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_history_store.py -v
```
Expected: ImportError on `lib.history_store`.

- [ ] **Step 2.3: history_store 최소 구현 (append-only, in-place는 Task 3)**

`plugins/token-tracker/lib/history_store.py`:

```python
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

from lib import paths


SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = (1,)


def _history_path(session_id: str) -> Path:
    d = paths.state_dir() / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d / "history.jsonl"


def _build_envelope(
    *,
    prompt_id: str,
    session_id: str,
    user_prompt_text: str,
    started_at: float,
    ended_at: float,
    summary_dict: dict,
    models_used: list[str],
    has_subagent_other_model: bool,
    transcript_entries: list[dict],
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_id": prompt_id,
        "session_id": session_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "user_prompt": {"text": user_prompt_text, "ts": started_at},
        "summary": summary_dict,
        "models_used": list(models_used),
        "has_subagent_other_model": bool(has_subagent_other_model),
        "transcript_entries": list(transcript_entries),
    }


def _atomic_write_lines(path: Path, lines: list[str]) -> None:
    """Write all lines atomically via tmp+replace."""
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".jsonl", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line)
                if not line.endswith("\n"):
                    f.write("\n")
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def append_or_update_history(
    *,
    session_id: str,
    prompt_id: str,
    user_prompt_text: str,
    started_at: float,
    ended_at: float,
    summary_dict: dict,
    models_used: list[str],
    has_subagent_other_model: bool,
    transcript_entries: list[dict],
) -> None:
    """Append a new entry (Task 3 will add in-place rewrite for same prompt_id)."""
    path = _history_path(session_id)
    envelope = _build_envelope(
        prompt_id=prompt_id, session_id=session_id,
        user_prompt_text=user_prompt_text, started_at=started_at,
        ended_at=ended_at, summary_dict=summary_dict,
        models_used=models_used,
        has_subagent_other_model=has_subagent_other_model,
        transcript_entries=transcript_entries,
    )
    new_line = json.dumps(envelope, ensure_ascii=False)
    existing: list[str] = []
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            existing = []
    _atomic_write_lines(path, existing + [new_line])


def load_session_history(session_id: str) -> list[dict]:
    """Load entries for a single session. Skips corrupted/unsupported lines."""
    path = paths.state_dir() / session_id / "history.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            print(f"[history_store] skip corrupted line in {path}", file=sys.stderr)
            continue
        if data.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
            print(f"[history_store] unsupported schema_version={data.get('schema_version')} in {path}", file=sys.stderr)
            continue
        out.append(data)
    return out
```

- [ ] **Step 2.4: 테스트 실행 → PASS**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_history_store.py -v
```
Expected: 3 tests pass.

- [ ] **Step 2.5: schema 검증 + 손상 행 skip 테스트**

`tests/test_history_store.py` 추가:

```python
def test_load_skips_corrupted_lines(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.history_store import load_session_history
    from lib import paths
    p = paths.state_dir() / "s" / "history.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        '{"schema_version":1,"prompt_id":"p_1","session_id":"s","started_at":1,"ended_at":2,"user_prompt":{"text":"","ts":1},"summary":{},"models_used":[],"has_subagent_other_model":false,"transcript_entries":[]}\n'
        '{not json}\n'
        '{"schema_version":1,"prompt_id":"p_2","session_id":"s","started_at":3,"ended_at":4,"user_prompt":{"text":"","ts":3},"summary":{},"models_used":[],"has_subagent_other_model":false,"transcript_entries":[]}\n',
        encoding="utf-8",
    )
    out = load_session_history("s")
    assert len(out) == 2
    assert [e["prompt_id"] for e in out] == ["p_1", "p_2"]
    err = capsys.readouterr().err
    assert "corrupted" in err


def test_load_skips_unsupported_schema(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.history_store import load_session_history
    from lib import paths
    p = paths.state_dir() / "s" / "history.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        '{"schema_version":99,"prompt_id":"p_x"}\n', encoding="utf-8"
    )
    out = load_session_history("s")
    assert out == []
    assert "unsupported schema_version" in capsys.readouterr().err
```

- [ ] **Step 2.6: 테스트 실행 → PASS**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_history_store.py -v
```
Expected: 5 tests pass.

- [ ] **Step 2.7: Commit**

```bash
git add plugins/token-tracker/lib/history_store.py plugins/token-tracker/tests/test_history_store.py
git commit -m "feat(history_store): JSONL append + schema versioning + atomic write 기본"
```

---

## Task 3: history_store — in-place rewrite (같은 prompt_id)

`append_or_update_history`가 마지막 행의 prompt_id를 비교해 같으면 마지막 행만 새 entry로 atomic rewrite, 다르면 append. spec §4.4 정책.

**Files:**
- Modify: `plugins/token-tracker/lib/history_store.py`
- Modify: `plugins/token-tracker/tests/test_history_store.py`

- [ ] **Step 3.1: 실패하는 테스트**

`tests/test_history_store.py`에 추가:

```python
def test_same_prompt_id_rewrites_last_line(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.history_store import append_or_update_history, load_session_history

    common = dict(
        session_id="s", prompt_id="p_1", user_prompt_text="hello",
        started_at=1.0, models_used=["claude-opus-4-7"],
        has_subagent_other_model=False, transcript_entries=[],
        summary_dict=_build_summary_dict(),
    )
    append_or_update_history(**{**common, "ended_at": 2.0})
    append_or_update_history(**{**common, "ended_at": 5.0,
                                 "transcript_entries": [{"type": "assistant_text", "ts": 3.0, "text": "x"}]})

    out = load_session_history("s")
    assert len(out) == 1
    assert out[0]["ended_at"] == 5.0
    assert out[0]["transcript_entries"] == [{"type": "assistant_text", "ts": 3.0, "text": "x"}]


def test_different_prompt_id_appends_new_line(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.history_store import append_or_update_history, load_session_history

    common = dict(
        session_id="s", user_prompt_text="x",
        started_at=1.0, ended_at=2.0, summary_dict=_build_summary_dict(),
        models_used=[], has_subagent_other_model=False, transcript_entries=[],
    )
    append_or_update_history(**{**common, "prompt_id": "p_1"})
    append_or_update_history(**{**common, "prompt_id": "p_2"})
    out = load_session_history("s")
    assert [e["prompt_id"] for e in out] == ["p_1", "p_2"]
```

- [ ] **Step 3.2: 테스트 실행 → FAIL**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_history_store.py::test_same_prompt_id_rewrites_last_line -v
```
Expected: FAIL — len(out) == 2 (append-only가 두 번 append).

- [ ] **Step 3.3: in-place rewrite 구현**

`lib/history_store.py`의 `append_or_update_history` 교체:

```python
def append_or_update_history(
    *,
    session_id: str,
    prompt_id: str,
    user_prompt_text: str,
    started_at: float,
    ended_at: float,
    summary_dict: dict,
    models_used: list[str],
    has_subagent_other_model: bool,
    transcript_entries: list[dict],
) -> None:
    """Append a new entry, OR rewrite the last line in-place when the last
    line's prompt_id matches `prompt_id` (spec §4.4 dedupe policy: one
    user prompt = one row, even when multiple Stops fire)."""
    path = _history_path(session_id)
    envelope = _build_envelope(
        prompt_id=prompt_id, session_id=session_id,
        user_prompt_text=user_prompt_text, started_at=started_at,
        ended_at=ended_at, summary_dict=summary_dict,
        models_used=models_used,
        has_subagent_other_model=has_subagent_other_model,
        transcript_entries=transcript_entries,
    )
    new_line = json.dumps(envelope, ensure_ascii=False)

    existing: list[str] = []
    if path.exists():
        try:
            existing = [
                ln for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
        except OSError:
            existing = []

    if existing:
        try:
            last = json.loads(existing[-1])
            if last.get("prompt_id") == prompt_id:
                existing[-1] = new_line
                _atomic_write_lines(path, existing)
                return
        except json.JSONDecodeError:
            pass

    _atomic_write_lines(path, existing + [new_line])
```

- [ ] **Step 3.4: 테스트 실행 → PASS**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_history_store.py -v
```
Expected: 7 tests pass.

- [ ] **Step 3.5: Commit**

```bash
git add plugins/token-tracker/lib/history_store.py plugins/token-tracker/tests/test_history_store.py
git commit -m "feat(history_store): 같은 prompt_id면 마지막 행 in-place rewrite (dedupe)"
```

---

## Task 4: history_store — multi-session glob load

`load_all_sessions_history` — `state/*/history.jsonl` 전부 read해서 한 list로. 손상된 세션은 skip.

**Files:**
- Modify: `plugins/token-tracker/lib/history_store.py`
- Modify: `plugins/token-tracker/tests/test_history_store.py`

- [ ] **Step 4.1: 실패하는 테스트**

```python
def test_load_all_sessions_aggregates(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.history_store import append_or_update_history, load_all_sessions_history

    for sess in ("alpha", "beta", "gamma"):
        append_or_update_history(
            session_id=sess, prompt_id=f"p_{sess}", user_prompt_text=sess,
            started_at=1.0, ended_at=2.0, summary_dict=_build_summary_dict(),
            models_used=[], has_subagent_other_model=False, transcript_entries=[],
        )

    out = load_all_sessions_history()
    assert len(out) == 3
    assert {e["session_id"] for e in out} == {"alpha", "beta", "gamma"}


def test_load_all_sessions_skips_session_without_history(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib import paths
    from lib.history_store import append_or_update_history, load_all_sessions_history

    # 1 session with history
    append_or_update_history(
        session_id="has_history", prompt_id="p", user_prompt_text="",
        started_at=1.0, ended_at=2.0, summary_dict=_build_summary_dict(),
        models_used=[], has_subagent_other_model=False, transcript_entries=[],
    )
    # 1 session with only last_summary, no history.jsonl
    (paths.state_dir() / "no_history").mkdir(parents=True, exist_ok=True)
    (paths.state_dir() / "no_history" / "last_summary.json").write_text("{}")

    out = load_all_sessions_history()
    assert {e["session_id"] for e in out} == {"has_history"}
```

- [ ] **Step 4.2: FAIL 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_history_store.py::test_load_all_sessions_aggregates -v
```
Expected: ImportError.

- [ ] **Step 4.3: load_all_sessions_history 구현**

`lib/history_store.py` 끝에 추가:

```python
def load_all_sessions_history() -> list[dict]:
    """Glob `state/*/history.jsonl` and merge all entries into one list.
    Each entry already carries `session_id`. Order: file glob order then
    line order within each file. Caller can sort by started_at if needed."""
    root = paths.state_dir()
    out: list[dict] = []
    for hist in sorted(root.glob("*/history.jsonl")):
        sess = hist.parent.name
        out.extend(load_session_history(sess))
    return out
```

- [ ] **Step 4.4: 테스트 PASS**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_history_store.py -v
```
Expected: 9 tests pass.

- [ ] **Step 4.5: Commit**

```bash
git add plugins/token-tracker/lib/history_store.py plugins/token-tracker/tests/test_history_store.py
git commit -m "feat(history_store): load_all_sessions_history (multi-session glob)"
```

---

## Task 5: on_user_prompt — prompt_id 발급

기존 synthetic prompt early return 분기 그대로 유지. real user prompt에서만 state에 `prompt_id` + `prompt_text` 추가 저장.

**Files:**
- Modify: `plugins/token-tracker/hooks/on_user_prompt.py`
- Create or modify: `plugins/token-tracker/tests/test_on_user_prompt.py`

- [ ] **Step 5.1: 실패하는 테스트 작성**

`tests/test_on_user_prompt.py` 신규 (이미 있으면 보강):

```python
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest


def _run_hook(monkeypatch, tmp_path, payload: dict, transcript_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps(payload))
    )
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text("", encoding="utf-8")

    from importlib import reload
    import hooks.on_user_prompt as h
    reload(h)
    return h.main()


def test_real_prompt_assigns_prompt_id_and_saves_state(tmp_path, monkeypatch):
    transcript = tmp_path / "transcript.jsonl"
    rc = _run_hook(monkeypatch, tmp_path, {
        "session_id": "s1", "transcript_path": str(transcript),
        "prompt": "hello world",
    }, transcript)
    assert rc == 0

    from lib.state import load_state
    st = load_state("s1")
    assert st is not None
    assert "prompt_id" in st and st["prompt_id"].startswith("p_")
    assert st.get("prompt_text") == "hello world"
    assert "started_at" in st


def test_synthetic_prompt_does_not_assign_prompt_id(tmp_path, monkeypatch):
    transcript = tmp_path / "transcript.jsonl"
    # First, real prompt
    _run_hook(monkeypatch, tmp_path, {
        "session_id": "s2", "transcript_path": str(transcript),
        "prompt": "real input",
    }, transcript)
    from lib.state import load_state
    real = load_state("s2")
    real_pid = real["prompt_id"]

    # Now, synthetic — should NOT change prompt_id
    _run_hook(monkeypatch, tmp_path, {
        "session_id": "s2", "transcript_path": str(transcript),
        "prompt": "<system-reminder>\n...stuff...",
    }, transcript)
    after = load_state("s2")
    assert after["prompt_id"] == real_pid
```

- [ ] **Step 5.2: FAIL 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_on_user_prompt.py -v
```
Expected: KeyError "prompt_id" (현 hook에서 저장 안 함).

- [ ] **Step 5.3: on_user_prompt.py 수정**

`hooks/on_user_prompt.py`의 `main()` 내 `save_state` 호출 부분 교체. **synthetic prompt는 위쪽 `_is_synthetic_prompt` early return으로 이미 걸러진 상태이므로 여기 도달한 입력은 real user prompt만** (spec §4.4.1) — 따라서 prompt_id 발급은 자연스럽게 real prompt에만 적용된다.

```python
        # ... existing _is_synthetic_prompt early return preserved (line 83) ...

        from lib.state import save_state
        import secrets

        size = os.path.getsize(transcript_path) if os.path.exists(transcript_path) else 0
        # spec §4.4.1: real user prompt에만 prompt_id 발급. synthetic은 위에서
        # early return되므로 여기 도달하지 않음. 결과적으로 synthetic event 후
        # 발생하는 Stop은 직전 real prompt의 prompt_id로 누적된다 (의도된 동작).
        prompt_text = hook_input.get("prompt") if isinstance(hook_input.get("prompt"), str) else ""
        save_state(
            session_id,
            {
                "offset": size,
                "started_at": time.time(),
                "prompt_id": f"p_{secrets.token_hex(3)}",
                "prompt_text": prompt_text,
            },
        )
```

- [ ] **Step 5.4: 테스트 PASS**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_on_user_prompt.py -v
```
Expected: 2 tests pass.

- [ ] **Step 5.5: 회귀 가드**

```bash
./venv/bin/pytest plugins/token-tracker/tests -q
```
Expected: 기존 + 신규 모두 PASS.

- [ ] **Step 5.6: Commit**

```bash
git add plugins/token-tracker/hooks/on_user_prompt.py plugins/token-tracker/tests/test_on_user_prompt.py
git commit -m "feat(on_user_prompt): real prompt에 prompt_id + prompt_text state 추가"
```

---

## Task 6: on_stop — history_store 호출 추가

spec §3.2 / §5.2 — line 187 `if count_active_async_agents > 0: return 0` 직전, line 163 `if summary.turns:` 가드 시점에 호출. try/except 격리. prompt_id 없으면 skip.

**Files:**
- Modify: `plugins/token-tracker/hooks/on_stop.py`
- Modify: `plugins/token-tracker/tests/test_hook_end_to_end.py`

- [ ] **Step 6.1: 통합 테스트 작성**

`tests/test_hook_end_to_end.py`에 추가 (기존 fixture 패턴 재활용 — 기존 file의 helper 함수 read해서 따라 쓸 것):

```python
def test_on_stop_appends_history_when_prompt_id_present(tmp_path, monkeypatch):
    """A complete flow: on_user_prompt → on_stop → history.jsonl has 1 row."""
    monkeypatch.setenv("HOME", str(tmp_path))

    # Setup: minimal transcript with one assistant turn
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps({
            "type": "assistant",
            "timestamp": "2026-05-03T14:23:00Z",
            "message": {
                "id": "msg_1",
                "model": "claude-opus-4-7",
                "content": [{"type": "text", "text": "hi"}],
                "usage": {"input_tokens": 10, "output_tokens": 5,
                          "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            },
        }) + "\n",
        encoding="utf-8",
    )

    # Run on_user_prompt first (assigns prompt_id)
    import io, sys, json as j, importlib
    monkeypatch.setattr(sys, "stdin", io.StringIO(j.dumps({
        "session_id": "s_e2e", "transcript_path": str(transcript),
        "prompt": "hi",
    })))
    import hooks.on_user_prompt as up
    importlib.reload(up)
    up.main()

    # Run on_stop
    monkeypatch.setattr(sys, "stdin", io.StringIO(j.dumps({
        "session_id": "s_e2e", "transcript_path": str(transcript),
    })))
    import hooks.on_stop as os_hook
    importlib.reload(os_hook)
    os_hook.main()

    # Verify
    from lib.history_store import load_session_history
    out = load_session_history("s_e2e")
    assert len(out) == 1
    assert out[0]["user_prompt"]["text"] == "hi"
    assert out[0]["models_used"] == ["claude-opus-4-7"]


def test_on_stop_skips_history_when_no_prompt_id(tmp_path, monkeypatch):
    """If prompt_id is missing in state (e.g., hook never ran), skip history."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.state import save_state
    save_state("s_skip", {"offset": 0, "started_at": 1.0})  # no prompt_id

    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        json.dumps({
            "type": "assistant", "timestamp": "2026-05-03T14:23:00Z",
            "message": {"id": "m", "model": "claude-opus-4-7",
                        "content": [{"type": "text", "text": "x"}],
                        "usage": {"input_tokens": 1, "output_tokens": 1,
                                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}},
        }) + "\n",
        encoding="utf-8",
    )

    import io, sys, json as j, importlib
    monkeypatch.setattr(sys, "stdin", io.StringIO(j.dumps({
        "session_id": "s_skip", "transcript_path": str(transcript),
    })))
    import hooks.on_stop as os_hook
    importlib.reload(os_hook)
    os_hook.main()

    from lib.history_store import load_session_history
    assert load_session_history("s_skip") == []  # skipped


def test_on_stop_history_failure_does_not_break_last_summary(tmp_path, monkeypatch):
    """history_store throwing must not break last_summary save."""
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.state import save_state
    save_state("s_fail", {"offset": 0, "started_at": 1.0,
                           "prompt_id": "p_x", "prompt_text": "x"})

    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        json.dumps({
            "type": "assistant", "timestamp": "2026-05-03T14:23:00Z",
            "message": {"id": "m", "model": "claude-opus-4-7",
                        "content": [{"type": "text", "text": "x"}],
                        "usage": {"input_tokens": 1, "output_tokens": 1,
                                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}},
        }) + "\n",
        encoding="utf-8",
    )

    # Sabotage history_store
    import lib.history_store as hs
    monkeypatch.setattr(hs, "append_or_update_history",
                        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    import io, sys, json as j, importlib
    monkeypatch.setattr(sys, "stdin", io.StringIO(j.dumps({
        "session_id": "s_fail", "transcript_path": str(transcript),
    })))
    import hooks.on_stop as os_hook
    importlib.reload(os_hook)
    rc = os_hook.main()
    assert rc == 0  # hook still returns OK

    # last_summary still saved
    from lib.summary_store import load_last_summary
    summ = load_last_summary("s_fail")
    assert summ is not None
```

- [ ] **Step 6.2: FAIL 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_hook_end_to_end.py -k history -v
```
Expected: FAIL.

- [ ] **Step 6.3: on_stop.py 수정**

`hooks/on_stop.py`의 line 168 직후 `save_last_summary` 부분 다음, line 187 `if count_active_async_agents` 직전에 history_store 호출 추가. 위치 정확히:

```python
        # Persist the just-computed Summary so /token-detail can read it.
        # Only save when we actually produced turns (flush polling finished).
        if summary.turns:
            try:
                from lib.summary_store import save_last_summary
                save_last_summary(session_id, summary)
            except Exception:
                _log_error(f"[on_stop] save_last_summary: {traceback.format_exc()}")

            # /token-history (v0.8.0): persist history.jsonl entry. Same gate
            # as last_summary (only when turns exist). Failure here must NOT
            # break the existing emit / async early-return flow.
            try:
                pid = state.get("prompt_id") if isinstance(state, dict) else None
                if pid:
                    from lib.history_store import append_or_update_history
                    from lib.parser import parse_transcript_for_history
                    transcript_entries_for_hist = parse_transcript_for_history(entries)

                    # Compute models_used + has_subagent_other_model
                    models_seen: list[str] = []
                    has_other = False
                    for t in summary.turns:
                        if t.model and t.model not in models_seen:
                            models_seen.append(t.model)
                        for s in t.subagents:
                            sm = getattr(s, "model", "")
                            if sm and sm != t.model:
                                has_other = True

                    from dataclasses import asdict
                    append_or_update_history(
                        session_id=session_id,
                        prompt_id=pid,
                        user_prompt_text=state.get("prompt_text", "") if isinstance(state, dict) else "",
                        started_at=started_at,
                        ended_at=time.time(),
                        summary_dict=asdict(summary),
                        models_used=models_seen,
                        has_subagent_other_model=has_other,
                        transcript_entries=transcript_entries_for_hist,
                    )
            except Exception:
                _log_error(f"[on_stop] history_store: {traceback.format_exc()}")
```

(들여쓰기는 기존 `if summary.turns:` 안쪽으로. async early return은 line 187 그대로 — 위 코드는 그 이전.)

- [ ] **Step 6.4: 테스트 PASS**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_hook_end_to_end.py -v
```
Expected: 3 신규 테스트 + 기존 모두 PASS.

- [ ] **Step 6.5: 전체 회귀 가드**

```bash
./venv/bin/pytest plugins/token-tracker/tests -q
```
Expected: All pass (277 + ~14 new).

- [ ] **Step 6.6: Commit**

```bash
git add plugins/token-tracker/hooks/on_stop.py plugins/token-tracker/tests/test_hook_end_to_end.py
git commit -m "feat(on_stop): history.jsonl entry 갱신 호출 추가 (try/except 격리)"
```

---

## Task 7: i18n 신규 키 추가 (ko/en)

spec §8 22개 키. ko + en 동시 추가.

**Files:**
- Modify: `plugins/token-tracker/lib/i18n/ko.json`
- Modify: `plugins/token-tracker/lib/i18n/en.json`
- Modify: `plugins/token-tracker/tests/test_i18n_loader.py` (신규 키 존재 검증)

- [ ] **Step 7.1: 실패하는 테스트**

`tests/test_i18n_loader.py`에 추가:

```python
def test_ko_has_history_keys():
    from lib.i18n_loader import load_strings
    s = load_strings("ko")
    for key in [
        "html_title", "html_generated_at", "html_version_label",
        "tab_current", "tab_all",
        "col_history_index", "col_history_time", "col_history_prompt",
        "col_history_model", "col_history_cost", "col_history_in",
        "col_history_out", "col_history_cc", "col_history_elapsed",
        "col_history_session",
        "search_placeholder", "filter_model_all", "filter_session_all",
        "expand_user_prompt", "expand_ai_response", "expand_thinking",
        "expand_tool_calls", "expand_show_full", "expand_collapse",
        "total_label", "no_data_message",
        "opened_url",
    ]:
        assert key in s, f"missing ko key: {key}"


def test_en_has_history_keys():
    from lib.i18n_loader import load_strings
    s = load_strings("en")
    for key in [
        "html_title", "tab_current", "tab_all",
        "col_history_prompt", "search_placeholder", "no_data_message",
        "opened_url",
    ]:
        assert key in s
```

- [ ] **Step 7.2: FAIL 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_i18n_loader.py -k history -v
```
Expected: AssertionError missing key.

- [ ] **Step 7.3: ko.json 추가**

`lib/i18n/ko.json`의 `}` 직전에 추가 (마지막 entry에 콤마 추가):

```json
  "html_title": "token-tracker history",
  "html_generated_at": "생성: {ts}",
  "html_version_label": "token-tracker {version}",
  "tab_current": "현재 세션 ({n})",
  "tab_all": "전체 세션 ({n})",
  "col_history_index": "#",
  "col_history_time": "시각",
  "col_history_prompt": "prompt",
  "col_history_model": "model",
  "col_history_cost": "cost",
  "col_history_in": "in",
  "col_history_out": "out",
  "col_history_cc": "cc%",
  "col_history_elapsed": "elapsed",
  "col_history_session": "session",
  "search_placeholder": "prompt 검색...",
  "filter_model_all": "all models",
  "filter_session_all": "all sessions",
  "expand_user_prompt": "user prompt",
  "expand_ai_response": "AI response",
  "expand_thinking": "thinking",
  "expand_tool_calls": "tool calls ({n})",
  "expand_show_full": "전체 보기 ▾",
  "expand_collapse": "접기 ▴",
  "total_label": "total",
  "no_data_message": "데이터 없음 — 첫 user prompt 응답 후 다시 호출하세요.",
  "opened_url": "opened: {url}"
```

- [ ] **Step 7.4: en.json 추가**

`lib/i18n/en.json`에 동일 키, 영어 번역:

```json
  "html_title": "token-tracker history",
  "html_generated_at": "generated: {ts}",
  "html_version_label": "token-tracker {version}",
  "tab_current": "current session ({n})",
  "tab_all": "all sessions ({n})",
  "col_history_index": "#",
  "col_history_time": "time",
  "col_history_prompt": "prompt",
  "col_history_model": "model",
  "col_history_cost": "cost",
  "col_history_in": "in",
  "col_history_out": "out",
  "col_history_cc": "cc%",
  "col_history_elapsed": "elapsed",
  "col_history_session": "session",
  "search_placeholder": "search prompts...",
  "filter_model_all": "all models",
  "filter_session_all": "all sessions",
  "expand_user_prompt": "user prompt",
  "expand_ai_response": "AI response",
  "expand_thinking": "thinking",
  "expand_tool_calls": "tool calls ({n})",
  "expand_show_full": "show full ▾",
  "expand_collapse": "collapse ▴",
  "total_label": "total",
  "no_data_message": "No data yet — make a request and try again.",
  "opened_url": "opened: {url}"
```

- [ ] **Step 7.5: 테스트 PASS**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_i18n_loader.py -v
```
Expected: All pass.

- [ ] **Step 7.6: Commit**

```bash
git add plugins/token-tracker/lib/i18n/ko.json plugins/token-tracker/lib/i18n/en.json plugins/token-tracker/tests/test_i18n_loader.py
git commit -m "feat(i18n): /token-history web UI strings 추가 (ko + en)"
```

---

## Task 8: history_renderer — 빈 데이터 + 기본 구조

renderer가 self-contained HTML을 만들어 반환. 첫 iteration: 빈 데이터 / 한 entry / 두 데이터 set이 모두 inline됨을 검증.

**Files:**
- Create: `plugins/token-tracker/lib/history_renderer.py`
- Create: `plugins/token-tracker/skills/token-history/templates/history.html.tmpl`
- Create: `plugins/token-tracker/skills/token-history/static/style.css`
- Create: `plugins/token-tracker/skills/token-history/static/app.js`
- Create: `plugins/token-tracker/tests/test_history_renderer.py`

- [ ] **Step 8.1: 템플릿 + static 파일 stubs 생성**

`plugins/token-tracker/skills/token-history/templates/history.html.tmpl`:

```html
<!DOCTYPE html>
<html lang="__LANG__">
<head>
  <meta charset="utf-8">
  <meta http-equiv="cache-control" content="no-store">
  <title>__HTML_TITLE__</title>
  <style>__CSS__</style>
</head>
<body>
  <header>
    <h1>__HTML_TITLE__</h1>
    <div class="meta">__GENERATED_AT__ · __VERSION_LABEL__</div>
  </header>
  <nav class="tabs">
    <button data-tab="current" class="active">__TAB_CURRENT__</button>
    <button data-tab="all">__TAB_ALL__</button>
  </nav>
  <section class="filters">
    <input type="search" id="search" placeholder="__SEARCH_PLACEHOLDER__">
    <select id="filter-model"><option value="">__FILTER_MODEL_ALL__</option></select>
    <select id="filter-session"><option value="">__FILTER_SESSION_ALL__</option></select>
  </section>
  <section id="totals" class="totals"></section>
  <main id="table-host"></main>
  <section id="empty" class="empty" hidden>__NO_DATA_MESSAGE__</section>
  <script id="data-current" type="application/json">__DATA_CURRENT__</script>
  <script id="data-all" type="application/json">__DATA_ALL__</script>
  <script id="i18n" type="application/json">__I18N_JSON__</script>
  <script>__JS__</script>
</body>
</html>
```

`plugins/token-tracker/skills/token-history/static/style.css` (최소):

```css
:root { color-scheme: light dark; }
body { font: 14px/1.5 system-ui, -apple-system, sans-serif; margin: 0; padding: 1rem; }
header h1 { margin: 0 0 0.25rem; font-size: 1.2rem; }
header .meta { color: #888; font-size: 0.85rem; }
nav.tabs { margin: 1rem 0 0.5rem; display: flex; gap: 0.5rem; }
nav.tabs button { padding: 0.4rem 0.8rem; border: 1px solid #ccc; background: transparent; cursor: pointer; }
nav.tabs button.active { background: #eef; border-color: #88f; }
.filters { display: flex; gap: 0.5rem; margin-bottom: 0.5rem; }
.filters input, .filters select { padding: 0.3rem; }
.totals { margin: 0.5rem 0; padding: 0.4rem; background: #f4f4f4; }
table { border-collapse: collapse; width: 100%; }
th, td { padding: 0.3rem 0.5rem; border-bottom: 1px solid #eee; text-align: left; }
th { cursor: pointer; user-select: none; }
.row-expand { background: #fafafa; padding: 0.5rem; }
.row-expand section { margin: 0.5rem 0; }
.row-expand h4 { margin: 0 0 0.25rem; font-size: 0.9rem; }
pre { white-space: pre-wrap; word-break: break-word; margin: 0; font-family: ui-monospace, monospace; font-size: 0.85rem; }
.collapsed pre.long { max-height: 4lh; overflow: hidden; }
.collapsed pre.long::after { content: ' …'; }
.empty { padding: 2rem; text-align: center; color: #888; }
```

`plugins/token-tracker/skills/token-history/static/app.js` (최소 stub — Task 12에서 풀):

```javascript
(function () {
  const dataCurrent = JSON.parse(document.getElementById('data-current').textContent);
  const dataAll = JSON.parse(document.getElementById('data-all').textContent);
  const i18n = JSON.parse(document.getElementById('i18n').textContent);
  const state = { tab: 'current', sortKey: 'started_at', sortDir: 1, search: '', model: '', session: '', expanded: new Set() };

  // Task 12 will implement render. Stub only mounts a placeholder.
  document.getElementById('table-host').textContent = '(rendering pending)';
})();
```

- [ ] **Step 8.2: 실패하는 테스트**

`tests/test_history_renderer.py`:

```python
from __future__ import annotations
import json


def test_render_empty_data_includes_empty_message():
    from lib.history_renderer import render_history_html
    html = render_history_html(current=[], all_sessions=[], lang="ko")
    assert "데이터 없음" in html


def test_render_inlines_data_current_and_data_all():
    from lib.history_renderer import render_history_html
    sample = [{"prompt_id": "p_1", "session_id": "s",
               "user_prompt": {"text": "hi", "ts": 1.0},
               "started_at": 1.0, "ended_at": 2.0,
               "summary": {"total_cost": 0.01, "total_input_tokens": 1,
                           "total_output_tokens": 1, "cache_hit_rate": 0.0,
                           "total_elapsed": 1.0, "turns": []},
               "models_used": ["claude-opus-4-7"],
               "has_subagent_other_model": False,
               "transcript_entries": []}]
    html = render_history_html(current=sample, all_sessions=sample, lang="ko")
    # Two script blocks, both contain p_1
    assert html.count('id="data-current"') == 1
    assert html.count('id="data-all"') == 1
    assert html.count('"p_1"') >= 2


def test_render_escapes_script_tag_in_user_prompt():
    """JSON inlined in <script> must not break out via </script>."""
    from lib.history_renderer import render_history_html
    payload = [{"prompt_id": "p", "session_id": "s",
                "user_prompt": {"text": "</script><script>alert(1)</script>", "ts": 1.0},
                "started_at": 1.0, "ended_at": 2.0,
                "summary": {"total_cost": 0, "total_input_tokens": 0,
                            "total_output_tokens": 0, "cache_hit_rate": 0,
                            "total_elapsed": 0, "turns": []},
                "models_used": [], "has_subagent_other_model": False,
                "transcript_entries": []}]
    html = render_history_html(current=payload, all_sessions=[], lang="ko")
    # Raw </script> must be escaped inside JSON
    assert "</script><script>alert(1)</script>" not in html


def test_render_uses_lang_attr():
    from lib.history_renderer import render_history_html
    html = render_history_html(current=[], all_sessions=[], lang="en")
    assert 'lang="en"' in html
    html_ko = render_history_html(current=[], all_sessions=[], lang="ko")
    assert 'lang="ko"' in html_ko
```

- [ ] **Step 8.3: FAIL 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_history_renderer.py -v
```
Expected: ImportError.

- [ ] **Step 8.4: history_renderer 구현**

`plugins/token-tracker/lib/history_renderer.py`:

```python
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from lib.i18n_loader import load_strings


_TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills" / "token-history" / "templates" / "history.html.tmpl"
)
_CSS_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills" / "token-history" / "static" / "style.css"
)
_JS_PATH = (
    Path(__file__).resolve().parent.parent
    / "skills" / "token-history" / "static" / "app.js"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _safe_json_for_script(obj) -> str:
    """JSON-encode for inline <script> block — escape `</` to neutralize
    `</script>` injection in any string field."""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def _read_plugin_version() -> str:
    """Read version from plugin.json. Falls back to 'unknown'."""
    try:
        manifest = (
            Path(__file__).resolve().parent.parent
            / ".claude-plugin" / "plugin.json"
        )
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return data.get("version", "unknown")
    except Exception:
        return "unknown"


def render_history_html(
    *, current: list[dict], all_sessions: list[dict], lang: str
) -> str:
    s = load_strings(lang)
    template = _read(_TEMPLATE_PATH)
    css = _read(_CSS_PATH)
    js = _read(_JS_PATH)

    generated_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    version = _read_plugin_version()

    i18n_subset = {k: s[k] for k in s if k.startswith((
        "tab_", "col_history_", "search_", "filter_", "expand_",
        "total_label", "no_data_message", "opened_url",
        "html_title", "html_generated_at", "html_version_label",
    ))}

    replacements = {
        "__LANG__": lang if lang in ("ko", "en") else "en",
        "__HTML_TITLE__": s["html_title"],
        "__GENERATED_AT__": s["html_generated_at"].format(ts=generated_at),
        "__VERSION_LABEL__": s["html_version_label"].format(version=version),
        "__TAB_CURRENT__": s["tab_current"].format(n=len(current)),
        "__TAB_ALL__": s["tab_all"].format(n=len(all_sessions)),
        "__SEARCH_PLACEHOLDER__": s["search_placeholder"],
        "__FILTER_MODEL_ALL__": s["filter_model_all"],
        "__FILTER_SESSION_ALL__": s["filter_session_all"],
        "__NO_DATA_MESSAGE__": s["no_data_message"],
        "__DATA_CURRENT__": _safe_json_for_script(current),
        "__DATA_ALL__": _safe_json_for_script(all_sessions),
        "__I18N_JSON__": _safe_json_for_script(i18n_subset),
        "__CSS__": css,
        "__JS__": js,
    }

    out = template
    for k, v in replacements.items():
        out = out.replace(k, v)
    return out
```

- [ ] **Step 8.5: 테스트 PASS**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_history_renderer.py -v
```
Expected: 4 tests pass.

- [ ] **Step 8.6: Commit**

```bash
git add plugins/token-tracker/lib/history_renderer.py plugins/token-tracker/skills/token-history/ plugins/token-tracker/tests/test_history_renderer.py
git commit -m "feat(history_renderer): self-contained HTML 생성 (i18n + data inline + script escape)"
```

---

## Task 9: skills/token-history/SKILL.md + scripts/history.py

skill entry 정의 + history.py가 history_renderer 호출 → 파일 write → `open file://` 실행 → URL chat 출력.

**Files:**
- Create: `plugins/token-tracker/skills/token-history/SKILL.md`
- Create: `plugins/token-tracker/skills/token-history/scripts/history.py`
- Create: `plugins/token-tracker/tests/test_history_skill_e2e.py`

- [ ] **Step 9.1: SKILL.md 작성**

`plugins/token-tracker/skills/token-history/SKILL.md`:

```markdown
---
name: token-history
description: 세션 누적 token/cost + transcript를 web 브라우저 (file://)로 표시
disable-model-invocation: true
---

<script-output>
!`python3 ${CLAUDE_SKILL_DIR}/scripts/history.py "${CLAUDE_SESSION_ID}"`
</script-output>

**필수 규칙 — 반드시 준수:**
- 당신의 응답은 오직 위 `<script-output>` 태그 내부 텍스트를 **한 글자도 바꾸지 말고 그대로** 출력하는 것이다.
- 해석·요약·생략·추가 설명·맥락 언급·이전 대화 참조 절대 금지.
- 이 skill이 실행된 순간 이전 대화는 무시하라. 오직 위 블록만 출력한다.
- `<script-output>` 태그 자체는 출력에 포함하지 마라 (내부 텍스트만).
- 출력 전후에 어떤 문장도 추가하지 마라.
```

- [ ] **Step 9.2: 실패하는 e2e 테스트**

skill 디렉터리명에 `-`가 들어있어 표준 Python import 불가. 따라서 file path 기반 import helper를 처음부터 사용한다.

`tests/test_history_skill_e2e.py`:

```python
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def _import_history_main():
    """Import skills/token-history/scripts/history.py by file path
    (디렉터리명에 `-` 포함되어 일반 import 불가)."""
    plugin_root = Path(__file__).resolve().parents[1]  # plugins/token-tracker/
    spec = importlib.util.spec_from_file_location(
        "history_skill_main",
        plugin_root / "skills" / "token-history" / "scripts" / "history.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main


def _seed_history(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib.history_store import append_or_update_history
    append_or_update_history(
        session_id="s_skill", prompt_id="p_1", user_prompt_text="hello",
        started_at=1.0, ended_at=2.0,
        summary_dict={"total_cost": 0.01, "total_input_tokens": 1,
                       "total_output_tokens": 1, "cache_hit_rate": 0.0,
                       "total_elapsed": 1.0, "turns": []},
        models_used=["claude-opus-4-7"],
        has_subagent_other_model=False,
        transcript_entries=[],
    )


def test_history_script_writes_html_and_prints_url(tmp_path, monkeypatch, capsys):
    _seed_history(monkeypatch, tmp_path)
    run_history = _import_history_main()
    with patch("subprocess.run") as mocked:
        run_history(["history.py", "s_skill"])
        assert mocked.called

    out = capsys.readouterr().out
    assert "opened:" in out

    from lib import paths
    candidates = list((paths.state_dir() / "s_skill").glob("history-*.html"))
    assert len(candidates) == 1
    assert "p_1" in candidates[0].read_text(encoding="utf-8")


def test_history_script_prints_url_even_when_open_fails(tmp_path, monkeypatch, capsys):
    _seed_history(monkeypatch, tmp_path)
    run_history = _import_history_main()
    with patch("subprocess.run", side_effect=FileNotFoundError("no open")):
        run_history(["history.py", "s_skill"])
    out = capsys.readouterr().out
    assert "opened:" in out  # URL still printed
```

- [ ] **Step 9.3: history.py 구현**

`plugins/token-tracker/skills/token-history/scripts/history.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import time
import traceback
from pathlib import Path


def _setup_sys_path() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        root = Path(env)
    else:
        # scripts/history.py -> scripts -> token-history -> skills -> plugin root
        root = Path(__file__).resolve().parent.parent.parent.parent
    sys.path.insert(0, str(root))
    return root


def _log_error(msg: str) -> None:
    try:
        from lib.paths import log_dir
        (log_dir() / "error.log").open("a", encoding="utf-8").write(msg + "\n")
    except Exception:
        print(msg, file=sys.stderr)


def main(argv: list[str]) -> int:
    plugin_root = _setup_sys_path()
    session_id = argv[1] if len(argv) > 1 else ""

    try:
        from lib.config import get_language, load_config
        from lib import paths
        from lib.history_store import (
            load_all_sessions_history,
            load_session_history,
        )
        from lib.history_renderer import render_history_html
        from lib.i18n_loader import load_strings

        lang = get_language(load_config(plugin_root))
        strings = load_strings(lang)

        if not session_id:
            print(strings["no_data_message"])
            return 0

        current = load_session_history(session_id)
        all_sessions = load_all_sessions_history()

        html = render_history_html(current=current, all_sessions=all_sessions, lang=lang)

        out_dir = paths.state_dir() / session_id
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = int(time.time())
        out_path = out_dir / f"history-{ts}.html"
        out_path.write_text(html, encoding="utf-8")

        url = f"file://{out_path}"
        try:
            subprocess.run(["open", url], check=False)
        except FileNotFoundError:
            pass

        print(strings["opened_url"].format(url=url))
        return 0
    except Exception:
        tb = traceback.format_exc()
        _log_error(f"[history.py] {tb}")
        print(tb, file=sys.stderr)
        try:
            from lib.i18n_loader import load_strings
            print(load_strings("en")["no_data_message"])
        except Exception:
            print("token-history: unexpected error")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 9.4: 추가 packaging 불필요 — 테스트 helper가 file path로 import**

Step 9.2의 `_import_history_main()` helper가 `importlib.util.spec_from_file_location`로 `history.py`를 직접 load하므로 `__init__.py` 추가나 디렉터리 rename 불필요. 그대로 다음 step.

- [ ] **Step 9.5: 테스트 PASS**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_history_skill_e2e.py -v
```
Expected: 2 tests pass.

- [ ] **Step 9.6: Commit**

```bash
git add plugins/token-tracker/skills/token-history plugins/token-tracker/tests/test_history_skill_e2e.py
git commit -m "feat(skill): /token-history SKILL.md + scripts/history.py (browser open + URL)"
```

---

## Task 10: app.js — 표 렌더링 + 정렬 + 탭 전환

vanilla JS로 표를 그린다. 컬럼 9개 (전체 세션 탭은 +session). 헤더 클릭 정렬. 탭 전환 시 데이터 set 변경 + 정렬/필터/expand 상태 리셋.

**Files:**
- Modify: `plugins/token-tracker/skills/token-history/static/app.js`
- Modify: `plugins/token-tracker/skills/token-history/static/style.css` (추가 스타일)

- [ ] **Step 10.1: app.js 풀 구현 (정렬 + 탭)**

`plugins/token-tracker/skills/token-history/static/app.js`:

```javascript
(function () {
  const dataCurrent = JSON.parse(document.getElementById('data-current').textContent);
  const dataAll = JSON.parse(document.getElementById('data-all').textContent);
  const i18n = JSON.parse(document.getElementById('i18n').textContent);

  const COLUMNS = [
    { key: 'index',    label: i18n.col_history_index,    sortable: true },
    { key: 'time',     label: i18n.col_history_time,     sortable: true },
    { key: 'prompt',   label: i18n.col_history_prompt,   sortable: false },
    { key: 'model',    label: i18n.col_history_model,    sortable: true },
    { key: 'cost',     label: i18n.col_history_cost,     sortable: true },
    { key: 'in',       label: i18n.col_history_in,       sortable: true },
    { key: 'out',      label: i18n.col_history_out,      sortable: true },
    { key: 'cc',       label: i18n.col_history_cc,       sortable: true },
    { key: 'elapsed',  label: i18n.col_history_elapsed,  sortable: true },
  ];
  const SESSION_COL = { key: 'session', label: i18n.col_history_session, sortable: true };

  const state = {
    tab: 'current',
    sortKey: 'time',
    sortDir: 1,
    search: '',
    model: '',
    session: '',
    expanded: new Set(),
  };

  const escapeHtml = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
  }[c]));

  function shortModel(rawId) {
    if (!rawId) return '';
    const m = /^claude-([a-z]+)-(\d+)-(\d+)/.exec(rawId);
    return m ? `${m[1]} ${m[2]}.${m[3]}` : rawId;
  }

  function modelDisplay(entry) {
    const primary = entry.models_used && entry.models_used[0]
      ? shortModel(entry.models_used[0]) : '';
    return entry.has_subagent_other_model ? primary + '+ⓢ' : primary;
  }

  function dataset() {
    return state.tab === 'current' ? dataCurrent : dataAll;
  }

  function filtered() {
    const q = state.search.toLowerCase();
    return dataset().filter(e => {
      if (q && !(e.user_prompt && (e.user_prompt.text || '').toLowerCase().includes(q))) return false;
      if (state.model && (!e.models_used || e.models_used[0] !== state.model)) return false;
      if (state.tab === 'all' && state.session && e.session_id !== state.session) return false;
      return true;
    });
  }

  function rowValue(e, key) {
    switch (key) {
      case 'time': return e.started_at || 0;
      case 'model': return modelDisplay(e);
      case 'cost': return e.summary?.total_cost ?? 0;
      case 'in': return e.summary?.total_input_tokens ?? 0;
      case 'out': return e.summary?.total_output_tokens ?? 0;
      case 'cc': return e.summary?.cache_hit_rate ?? 0;
      case 'elapsed': return e.summary?.total_elapsed ?? 0;
      case 'session': return e.session_id || '';
      case 'index':
      default: return 0;
    }
  }

  function sorted(rows) {
    if (state.sortKey === 'index') return rows;
    const dir = state.sortDir;
    return [...rows].sort((a, b) => {
      const av = rowValue(a, state.sortKey);
      const bv = rowValue(b, state.sortKey);
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
  }

  function fmtTime(ts) {
    return new Date(ts * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  }

  function fmtCost(c) { return '$' + (c || 0).toFixed(4); }
  function fmtNum(n) { return Number(n || 0).toLocaleString(); }
  function fmtPct(p) { return Math.round((p || 0) * 100) + '%'; }
  function fmtElapsed(s) { return (s || 0).toFixed(1) + 's'; }

  function renderTotals(rows) {
    const t = rows.reduce((acc, e) => {
      const s = e.summary || {};
      acc.cost += s.total_cost || 0;
      acc.in += s.total_input_tokens || 0;
      acc.out += s.total_output_tokens || 0;
      acc.elapsed += s.total_elapsed || 0;
      const inp = (s.total_input_tokens || 0);
      acc.cacheNum += (s.cache_hit_rate || 0) * inp;
      acc.cacheDen += inp;
      return acc;
    }, {cost:0, in:0, out:0, elapsed:0, cacheNum:0, cacheDen:0});
    const cachePct = t.cacheDen > 0 ? (t.cacheNum / t.cacheDen) : 0;
    document.getElementById('totals').textContent =
      `${i18n.total_label}  ${fmtCost(t.cost)} · ${fmtNum(t.in + t.out)} toks · ${fmtPct(cachePct)} cache · ${fmtElapsed(t.elapsed)}`;
  }

  function renderTable(rows) {
    const cols = state.tab === 'all' ? [...COLUMNS, SESSION_COL] : COLUMNS;
    const host = document.getElementById('table-host');
    host.innerHTML = '';
    if (!rows.length) {
      document.getElementById('empty').hidden = false;
      return;
    }
    document.getElementById('empty').hidden = true;
    const table = document.createElement('table');
    const thead = document.createElement('thead');
    const tr = document.createElement('tr');
    cols.forEach(c => {
      const th = document.createElement('th');
      th.textContent = c.label + (state.sortKey === c.key ? (state.sortDir > 0 ? ' ▲' : ' ▼') : '');
      if (c.sortable) {
        th.style.cursor = 'pointer';
        th.onclick = () => {
          if (state.sortKey === c.key) state.sortDir *= -1;
          else { state.sortKey = c.key; state.sortDir = c.key === 'time' ? -1 : 1; }
          render();
        };
      }
      tr.appendChild(th);
    });
    thead.appendChild(tr);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    rows.forEach((e, i) => {
      const row = document.createElement('tr');
      row.dataset.promptId = e.prompt_id;
      const cells = {
        index: i + 1,
        time: fmtTime(e.started_at || 0),
        prompt: (e.user_prompt && e.user_prompt.text) || '',
        model: modelDisplay(e),
        cost: fmtCost(e.summary?.total_cost),
        in: fmtNum(e.summary?.total_input_tokens),
        out: fmtNum(e.summary?.total_output_tokens),
        cc: fmtPct(e.summary?.cache_hit_rate),
        elapsed: fmtElapsed(e.summary?.total_elapsed),
        session: (e.session_id || '').slice(0, 8),
      };
      cols.forEach(c => {
        const td = document.createElement('td');
        const val = cells[c.key];
        if (c.key === 'prompt') {
          td.title = val;
          td.style.maxWidth = '40ch';
          td.style.overflow = 'hidden';
          td.style.textOverflow = 'ellipsis';
          td.style.whiteSpace = 'nowrap';
        }
        td.textContent = val;
        row.appendChild(td);
      });
      row.style.cursor = 'pointer';
      row.onclick = () => toggleExpand(e.prompt_id);
      tbody.appendChild(row);

      if (state.expanded.has(e.prompt_id)) {
        const expandRow = document.createElement('tr');
        const expandCell = document.createElement('td');
        expandCell.colSpan = cols.length;
        expandCell.className = 'row-expand';
        expandCell.appendChild(renderExpand(e));
        expandRow.appendChild(expandCell);
        tbody.appendChild(expandRow);
      }
    });
    table.appendChild(tbody);
    host.appendChild(table);
  }

  function isLong(text) {
    if (!text) return false;
    return text.length > 500 || text.split('\n').length > 5;
  }

  function makePre(text) {
    const wrap = document.createElement('div');
    const pre = document.createElement('pre');
    if (isLong(text)) {
      pre.classList.add('long');
      wrap.classList.add('collapsed');
      const toggle = document.createElement('button');
      toggle.textContent = i18n.expand_show_full;
      toggle.onclick = (ev) => {
        ev.stopPropagation();
        const collapsed = wrap.classList.toggle('collapsed');
        toggle.textContent = collapsed ? i18n.expand_show_full : i18n.expand_collapse;
      };
      wrap.appendChild(pre);
      wrap.appendChild(toggle);
    } else {
      wrap.appendChild(pre);
    }
    pre.textContent = text;
    return wrap;
  }

  function renderExpand(e) {
    const root = document.createElement('div');
    const userSection = document.createElement('section');
    const userH = document.createElement('h4');
    userH.textContent = i18n.expand_user_prompt;
    userSection.appendChild(userH);
    userSection.appendChild(makePre((e.user_prompt && e.user_prompt.text) || ''));
    root.appendChild(userSection);

    const ai = (e.transcript_entries || []).filter(x => x.type === 'assistant_text').map(x => x.text).join('\n\n');
    if (ai) {
      const sec = document.createElement('section');
      const h = document.createElement('h4'); h.textContent = i18n.expand_ai_response;
      sec.appendChild(h); sec.appendChild(makePre(ai));
      root.appendChild(sec);
    }

    const thinking = (e.transcript_entries || []).filter(x => x.type === 'thinking').map(x => x.text).join('\n\n');
    if (thinking) {
      const sec = document.createElement('section');
      const h = document.createElement('h4'); h.textContent = i18n.expand_thinking;
      sec.appendChild(h); sec.appendChild(makePre(thinking));
      root.appendChild(sec);
    }

    const tools = (e.transcript_entries || []).filter(x => x.type === 'tool_call' || x.type === 'tool_result');
    if (tools.length) {
      const sec = document.createElement('section');
      const h = document.createElement('h4');
      h.textContent = i18n.expand_tool_calls.replace('{n}', tools.length);
      sec.appendChild(h);
      tools.forEach(t => {
        const li = document.createElement('div');
        if (t.type === 'tool_call') {
          li.textContent = `▸ ${t.name}: ${JSON.stringify(t.input).slice(0, 200)}`;
        } else {
          li.textContent = `  ↳ result${t.is_error ? ' (error)' : ''}: ${(t.content || '').slice(0, 200)}`;
        }
        sec.appendChild(li);
      });
      root.appendChild(sec);
    }

    return root;
  }

  function toggleExpand(pid) {
    if (state.expanded.has(pid)) state.expanded.delete(pid);
    else state.expanded.add(pid);
    render();
  }

  function rebuildFilters() {
    const ds = dataset();
    const models = new Set();
    const sessions = new Set();
    ds.forEach(e => {
      if (e.models_used && e.models_used[0]) models.add(e.models_used[0]);
      if (e.session_id) sessions.add(e.session_id);
    });

    const modelSel = document.getElementById('filter-model');
    modelSel.innerHTML = `<option value="">${i18n.filter_model_all}</option>`;
    [...models].sort().forEach(m => {
      const o = document.createElement('option');
      o.value = m; o.textContent = shortModel(m);
      modelSel.appendChild(o);
    });
    modelSel.value = state.model;

    const sessionSel = document.getElementById('filter-session');
    sessionSel.style.display = state.tab === 'all' ? '' : 'none';
    sessionSel.innerHTML = `<option value="">${i18n.filter_session_all}</option>`;
    [...sessions].sort().forEach(s => {
      const o = document.createElement('option');
      o.value = s; o.textContent = s.slice(0, 8);
      sessionSel.appendChild(o);
    });
    sessionSel.value = state.session;
  }

  function render() {
    rebuildFilters();
    const rows = sorted(filtered());
    renderTotals(rows);
    renderTable(rows);
  }

  // Wire events
  document.querySelectorAll('nav.tabs button').forEach(b => {
    b.onclick = () => {
      state.tab = b.dataset.tab;
      state.sortKey = 'time'; state.sortDir = -1;
      state.search = ''; state.model = ''; state.session = '';
      state.expanded.clear();
      document.getElementById('search').value = '';
      document.querySelectorAll('nav.tabs button').forEach(x => x.classList.toggle('active', x === b));
      render();
    };
  });
  document.getElementById('search').addEventListener('input', (ev) => {
    state.search = ev.target.value;
    render();
  });
  document.getElementById('filter-model').addEventListener('change', (ev) => {
    state.model = ev.target.value;
    render();
  });
  document.getElementById('filter-session').addEventListener('change', (ev) => {
    state.session = ev.target.value;
    render();
  });

  // Initial sort: most recent first
  state.sortDir = -1;
  render();
})();
```

- [ ] **Step 10.2: 회귀 가드 — renderer 테스트가 큰 JS 포함된 출력에서도 동작 확인**

```bash
./venv/bin/pytest plugins/token-tracker/tests/test_history_renderer.py plugins/token-tracker/tests/test_history_skill_e2e.py -v
```
Expected: 모두 PASS.

- [ ] **Step 10.3: Commit**

```bash
git add plugins/token-tracker/skills/token-history/static/
git commit -m "feat(history-ui): vanilla JS — 정렬·검색·필터·expand·탭 전환"
```

---

## Task 11: 사용자 수동 검증 (브라우저 실측)

자동화 테스트로 잡지 못하는 시각/UX 검증.

**Files:** none (사용자 직접 동작)

- [ ] **Step 11.1: 실제 환경에서 동작 시나리오 작성**

다음을 사용자가 실측하도록 안내. 자동화 X, 결과 메모는 plan 끝 메모 섹션에 추가:

1. 새 Claude Code 세션에서 prompt 1~3개 입력 + 응답 받기
2. `/token-history` 입력 → 브라우저 자동 open
3. 페이지에서 다음 확인:
   - 헤더에 token-tracker 버전, 생성 시각 표시
   - 탭 두 개 (현재 세션 N, 전체 세션 N) — N 정확
   - 표에 prompt 발췌, 시각, 모델, 비용, 토큰, cache%, elapsed 표시
   - 헤더 클릭 → 정렬 동작 (오름/내림 토글)
   - search box에 prompt 일부 입력 → 필터링
   - model dropdown 변경 → 필터링
   - 행 클릭 → 아래 expand 영역 펼침 (user prompt / AI response / thinking / tool calls)
   - 큰 텍스트는 default 접힘 + "전체 보기" 버튼
   - 탭 전환 시 정렬/필터/expand 상태 리셋
   - 빈 데이터일 때 "데이터 없음" 메시지
4. URL chat에 출력됐는지 확인 (`opened: file://...`)

- [ ] **Step 11.2: 발견 이슈 plan 끝에 메모 + 재실행 기준**

이슈 발견 시 spec 또는 plan 후속 task 추가. CRITICAL 이슈는 다음 task로 진행 전 fix.

- [ ] **Step 11.3: Commit (메모 추가가 있다면)**

```bash
git add docs/superpowers/plans/2026-05-03-token-history.md
git commit -m "chore(plan): Task 11 사용자 검증 결과 메모"
```

---

## Task 12: version bump + final 회귀 가드 + 최종 commit

v0.8.0 출시. 277 + 신규 테스트 전체 통과 확인.

**Files:**
- Modify: `.claude-plugin/marketplace.json` (repo 루트)
- Modify: `plugins/token-tracker/.claude-plugin/plugin.json` (있다면)

- [ ] **Step 12.1: version 파일 위치 확인**

```bash
ls /Users/brody/Desktop/token-tracker/.claude-plugin/
ls /Users/brody/Desktop/token-tracker/plugins/token-tracker/.claude-plugin/ 2>/dev/null
grep -r '"version"' /Users/brody/Desktop/token-tracker/.claude-plugin /Users/brody/Desktop/token-tracker/plugins/token-tracker/.claude-plugin 2>/dev/null
```

확인 후 모든 version 필드 `0.8.0`으로 교체.

- [ ] **Step 12.2: version bump**

(Step 12.1 결과에 따라 정확한 path 사용)

```bash
# 예시 — 실제 경로는 12.1 결과로 정확화
sed -i '' 's/"version": "0.7.0"/"version": "0.8.0"/g' .claude-plugin/marketplace.json
```

- [ ] **Step 12.3: 전체 테스트 회귀 가드**

```bash
cd /Users/brody/Desktop/token-tracker
./venv/bin/pytest plugins/token-tracker/tests -q
```
Expected: 277 + ~30 신규 = ~307 all PASS.

- [ ] **Step 12.4: 코드리뷰 (CLAUDE.md 룰: 7개 병렬 에이전트)**

이 단계는 plan 외부에서 사용자/오케스트레이터가 코드리뷰 에이전트 dispatch. 결과 CRITICAL 0건이면 다음 step.

- [ ] **Step 12.5: Final commit (version + plan 메모)**

```bash
git add .claude-plugin/marketplace.json plugins/token-tracker/.claude-plugin/plugin.json 2>/dev/null
git commit -m "chore(release): v0.8.0 — /token-history web UI"
```

- [ ] **Step 12.6: 사용자 push 승인 요청**

CLAUDE.md 룰: PR 머지/push는 사용자 명시 승인 후. plan은 여기서 종료. 사용자에게:
- "v0.8.0 ready. 277+30 tests pass. push & PR 만들까요?"

---

## 메모 (Task 0/11 결과 기록용)

(Task 0 진단 결과)

(Task 11 사용자 검증 결과)
