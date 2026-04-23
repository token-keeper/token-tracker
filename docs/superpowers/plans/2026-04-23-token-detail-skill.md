# `/token-detail` Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 2-B — `/token-detail` 슬래시 skill을 구현해 직전 request의 turn별 상세표를 표시한다.

**Architecture:** Stop hook이 flush polling 완료 후 `Summary`를 `state/{session_id}/last_summary.json`에 원자 쓰기 → `/token-detail` 호출 시 skill의 `!`script`` 치환이 `scripts/detail.py`를 실행 → 스크립트가 `${CLAUDE_SESSION_ID}` argv로 state 읽어 포맷된 표를 stdout 출력 → LLM이 본문에 삽입된 텍스트를 그대로 사용자에게 전달.

**Tech Stack:** Python 3.10+ stdlib only, pytest, Claude Code plugin/skill system.

**Spec**: `docs/superpowers/specs/2026-04-22-token-detail-skill-design.md` (v2)

---

## 작업 원칙

- **테스트 실행 경로**: 반드시 repo 루트에서 `./venv/bin/pytest plugins/token-tracker/tests -q` (venv는 루트, pytest는 venv에 설치됨).
- **커밋 규칙**: 각 Task 말미에 한 번 커밋. Conventional Commits 포맷, 한국어 본문.
- **TDD 순서**: 테스트 먼저 작성 → 실패 확인 → 구현 → 통과 확인 → 커밋.
- **기존 테스트 깨짐 방지**: parser/aggregator/state 변경 Task는 기존 테스트도 함께 업데이트.

---

## Task 1: i18n 리소스 파일 생성

**Files:**
- Create: `plugins/token-tracker/lib/i18n/__init__.py`
- Create: `plugins/token-tracker/lib/i18n/ko.json`
- Create: `plugins/token-tracker/lib/i18n/en.json`
- Create: `plugins/token-tracker/lib/i18n_loader.py`
- Create: `plugins/token-tracker/tests/test_i18n_loader.py`

- [ ] **Step 1: ko.json 생성**

`plugins/token-tracker/lib/i18n/ko.json`:
```json
{
  "header_title": "직전 request 상세",
  "header_total": "총 비용 {cost} | {tokens} toks | cache {rate} | {elapsed}",
  "col_index": "#",
  "col_model": "모델",
  "col_tools": "툴",
  "col_input": "input",
  "col_cc": "cc",
  "col_cr": "cr",
  "col_output": "output",
  "col_cost": "비용",
  "col_time": "시간",
  "legend": "범례: cc=cache_creation, cr=cache_read",
  "err_no_state": "아직 기록된 request가 없습니다. 먼저 Claude에게 질문 후 다시 실행하세요.",
  "err_parse": "상세 정보를 읽지 못했습니다 (파일 손상).",
  "err_unsupported_schema": "이 state 파일은 현재 skill과 호환되지 않습니다 (삭제 후 다음 응답부터 재생성).",
  "err_empty_turns": "직전 request에 assistant 응답이 없습니다."
}
```

- [ ] **Step 2: en.json 생성**

`plugins/token-tracker/lib/i18n/en.json`:
```json
{
  "header_title": "Last request detail",
  "header_total": "total {cost} | {tokens} toks | cache {rate} | {elapsed}",
  "col_index": "#",
  "col_model": "model",
  "col_tools": "tools",
  "col_input": "input",
  "col_cc": "cc",
  "col_cr": "cr",
  "col_output": "output",
  "col_cost": "cost",
  "col_time": "time",
  "legend": "legend: cc=cache_creation, cr=cache_read",
  "err_no_state": "No recorded request yet. Ask Claude first, then retry.",
  "err_parse": "Could not read detail (file corrupted).",
  "err_unsupported_schema": "State file is not compatible with current skill (delete; will regenerate on next response).",
  "err_empty_turns": "The last request has no assistant response."
}
```

- [ ] **Step 3: 빈 `__init__.py` 생성 (패키지 인식용)**

`plugins/token-tracker/lib/i18n/__init__.py` — 빈 파일.

- [ ] **Step 4: 실패하는 loader 테스트 작성**

`plugins/token-tracker/tests/test_i18n_loader.py`:
```python
from lib.i18n_loader import load_strings


def test_load_ko_has_required_keys():
    s = load_strings("ko")
    assert s["header_title"] == "직전 request 상세"
    assert "col_model" in s
    assert "err_no_state" in s


def test_load_en_has_required_keys():
    s = load_strings("en")
    assert s["header_title"] == "Last request detail"


def test_unknown_language_falls_back_to_en():
    s = load_strings("zz")
    assert s["header_title"] == "Last request detail"


def test_all_expected_keys_present_both_languages():
    expected_keys = {
        "header_title", "header_total",
        "col_index", "col_model", "col_tools",
        "col_input", "col_cc", "col_cr",
        "col_output", "col_cost", "col_time",
        "legend",
        "err_no_state", "err_parse", "err_unsupported_schema", "err_empty_turns",
    }
    assert set(load_strings("ko").keys()) == expected_keys
    assert set(load_strings("en").keys()) == expected_keys
```

- [ ] **Step 5: 테스트 실행 → 실패 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_i18n_loader.py -v`
Expected: `ModuleNotFoundError: No module named 'lib.i18n_loader'`.

- [ ] **Step 6: loader 구현**

`plugins/token-tracker/lib/i18n_loader.py`:
```python
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


_I18N_DIR = Path(__file__).resolve().parent / "i18n"
_SUPPORTED = {"ko", "en"}


@lru_cache(maxsize=8)
def load_strings(lang: str) -> dict[str, str]:
    """Load translated strings for the given language.

    Falls back to 'en' when the language is unknown or the file is missing.
    Cached per language — loaded only once per process.
    """
    chosen = lang if lang in _SUPPORTED else "en"
    path = _I18N_DIR / f"{chosen}.json"
    return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 7: 테스트 실행 → 통과 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_i18n_loader.py -v`
Expected: 4 passed.

- [ ] **Step 8: 전체 테스트 회귀 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests -q`
Expected: 기존 46 + 신규 4 = **50 passed**.

- [ ] **Step 9: 커밋**

```bash
git add plugins/token-tracker/lib/i18n/ plugins/token-tracker/lib/i18n_loader.py plugins/token-tracker/tests/test_i18n_loader.py
git commit -m "feat(i18n): add ko/en resource files + loader

detail_formatter와 detail 스크립트가 사용할 번역 문자열을
lib/i18n/{ko,en}.json 리소스로 분리. lru_cache로 프로세스당 한 번 로드.
향후 언어 추가 시 formatter 코드 수정 없이 리소스만 추가하면 됨."
```

---

## Task 2: parser / aggregator — tools_used 구조 변경 + index 필드

**Files:**
- Modify: `plugins/token-tracker/lib/parser.py`
- Modify: `plugins/token-tracker/lib/aggregator.py`
- Modify: `plugins/token-tracker/tests/test_parser.py`
- Modify: `plugins/token-tracker/tests/test_aggregator.py`

**변경 요지**: `TurnUsage.tools_used`를 `list[str]` → `list[dict]` (`{"name": str, "count": int}`) 로. turn의 `index` 필드 추가 (aggregator에서 enumerate로 부여).

- [ ] **Step 1: 새 구조를 기대하는 parser 테스트 추가**

`plugins/token-tracker/tests/test_parser.py`에 기존 테스트 유지하되, `test_parse_assistant_line_with_tool_uses`를 다음으로 교체:

```python
def test_parse_assistant_line_aggregates_tool_use_counts():
    entry = {
        "type": "assistant",
        "timestamp": "2026-04-23T10:00:00Z",
        "message": {
            "id": "msg_1",
            "model": "claude-opus-4-7",
            "usage": {
                "input_tokens": 10, "output_tokens": 20,
                "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            },
            "content": [
                {"type": "text", "text": "ok"},
                {"type": "tool_use", "name": "Read"},
                {"type": "tool_use", "name": "Read"},
                {"type": "tool_use", "name": "Edit"},
            ],
        },
    }
    t = parser.parse_line(entry)
    assert t is not None
    assert t.tools_used == [{"name": "Read", "count": 2}, {"name": "Edit", "count": 1}]
```

`test_parse_simple_assistant_line`의 기존 `tools_used == []` 단언은 그대로 유지 (빈 리스트).

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_parser.py::test_parse_assistant_line_aggregates_tool_use_counts -v`
Expected: FAIL — 현재 구현은 `list[str]`을 반환.

- [ ] **Step 3: parser.py 수정**

`plugins/token-tracker/lib/parser.py` 전체 교체:
```python
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class TurnUsage:
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    tools_used: list[dict] = field(default_factory=list)  # [{"name": str, "count": int}]
    timestamp_iso: str = ""
    message_id: str = ""
    index: int = 0  # set by aggregator


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

    return TurnUsage(
        model=msg.get("model", ""),
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cache_creation_tokens=int(usage.get("cache_creation_input_tokens", 0)),
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
        tools_used=tools_used,
        timestamp_iso=entry.get("timestamp", ""),
        message_id=str(msg.get("id", "")),
    )
```

- [ ] **Step 4: parser 테스트 실행 → 통과**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_parser.py -v`
Expected: 전체 통과.

- [ ] **Step 5: aggregator에서 index 부여하는 테스트 추가**

`plugins/token-tracker/tests/test_aggregator.py` 끝에 추가:
```python
def test_aggregate_assigns_sequential_index():
    turns = [
        TurnUsage(model="claude-opus-4-7", input_tokens=1, output_tokens=1,
                  cache_creation_tokens=0, cache_read_tokens=0, message_id="a"),
        TurnUsage(model="claude-opus-4-7", input_tokens=1, output_tokens=1,
                  cache_creation_tokens=0, cache_read_tokens=0, message_id="b"),
        TurnUsage(model="claude-opus-4-7", input_tokens=1, output_tokens=1,
                  cache_creation_tokens=0, cache_read_tokens=0, message_id="c"),
    ]
    s = aggregate(turns, elapsed=1.0)
    assert [t.index for t in s.turns] == [0, 1, 2]


def test_aggregate_index_after_dedupe():
    dup = TurnUsage(model="claude-opus-4-7", input_tokens=1, output_tokens=1,
                    cache_creation_tokens=0, cache_read_tokens=0, message_id="a")
    turns = [
        dup, dup,  # same message_id, deduped
        TurnUsage(model="claude-opus-4-7", input_tokens=1, output_tokens=1,
                  cache_creation_tokens=0, cache_read_tokens=0, message_id="b"),
    ]
    s = aggregate(turns, elapsed=1.0)
    assert [t.index for t in s.turns] == [0, 1]
```

- [ ] **Step 6: 테스트 실행 → 실패 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_aggregator.py::test_aggregate_assigns_sequential_index -v`
Expected: FAIL — `TurnUsage`에 index 없거나 기본값 0만.

- [ ] **Step 7: aggregator.py 수정**

`plugins/token-tracker/lib/aggregator.py`, `aggregate` 끝부분:
```python
def aggregate(turns: list[TurnUsage], elapsed: float) -> Summary:
    unique = _dedupe_by_message_id(turns)
    for i, t in enumerate(unique):
        t.index = i
    total_cost = sum(compute_cost(t.model, t) for t in unique)
    total_input = sum(
        t.input_tokens + t.cache_creation_tokens + t.cache_read_tokens
        for t in unique
    )
    total_output = sum(t.output_tokens for t in unique)
    cache_read = sum(t.cache_read_tokens for t in unique)
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

(기존 코드에서 `for i, t in enumerate(unique): t.index = i` 단 두 줄 추가.)

- [ ] **Step 8: 전체 테스트 회귀 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests -q`
Expected: 50 passed (parser 1개 교체 + aggregator 2개 추가, 실제 숫자는 교체·추가 반영).

- [ ] **Step 9: 커밋**

```bash
git add plugins/token-tracker/lib/parser.py plugins/token-tracker/lib/aggregator.py plugins/token-tracker/tests/test_parser.py plugins/token-tracker/tests/test_aggregator.py
git commit -m "feat(parser/aggregator): tools_used count 구조 + turn index 필드

detail skill이 'Read×3,Edit×1' 형식으로 툴 호출 횟수를 표시할 수 있도록
parser에서 Counter로 집계. aggregator는 dedupe 후 enumerate로 index 부여해
turn 순서를 Summary에 영속화."
```

---

## Task 3: state.py 경로 변경 ({session_id}/offset.json)

**Files:**
- Modify: `plugins/token-tracker/lib/state.py`
- Modify: `plugins/token-tracker/tests/test_state.py`

**변경 요지**: 기존 `state/{session_id}.json` → `state/{session_id}/offset.json`. 세션별 서브디렉터리로 진입해 `last_summary.json`과 공존.

- [ ] **Step 1: 새 경로 기대하는 테스트 수정**

`plugins/token-tracker/tests/test_state.py` — 모든 테스트가 임시 디렉터리(`paths.state_dir()` monkeypatch)에서 `{session_id}/offset.json` 경로를 기대하도록. 기존 테스트 전체 교체:

```python
import json
import os
from pathlib import Path

from lib import paths, state


def _patch_state_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "_base_data_dir", lambda: tmp_path)


def test_save_and_load_roundtrip(monkeypatch, tmp_path):
    _patch_state_dir(monkeypatch, tmp_path)
    state.save_state("sess-1", {"offset": 123, "started_at": 456.0})
    loaded = state.load_state("sess-1")
    assert loaded == {"offset": 123, "started_at": 456.0}


def test_save_creates_session_subdirectory(monkeypatch, tmp_path):
    _patch_state_dir(monkeypatch, tmp_path)
    state.save_state("sess-2", {"offset": 0})
    expected = tmp_path / "state" / "sess-2" / "offset.json"
    assert expected.is_file()


def test_load_missing_returns_none(monkeypatch, tmp_path):
    _patch_state_dir(monkeypatch, tmp_path)
    assert state.load_state("nonexistent") is None


def test_load_corrupted_returns_none(monkeypatch, tmp_path):
    _patch_state_dir(monkeypatch, tmp_path)
    session_dir = tmp_path / "state" / "sess-3"
    session_dir.mkdir(parents=True)
    (session_dir / "offset.json").write_text("{not json", encoding="utf-8")
    assert state.load_state("sess-3") is None


def test_save_is_atomic_no_temp_leftover(monkeypatch, tmp_path):
    _patch_state_dir(monkeypatch, tmp_path)
    state.save_state("sess-4", {"offset": 1})
    session_dir = tmp_path / "state" / "sess-4"
    temps = [p for p in session_dir.iterdir() if p.name.startswith(".tmp-")]
    assert temps == []
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_state.py -v`
Expected: 대부분 FAIL — 현재 경로는 `state/{session_id}.json` (flat).

- [ ] **Step 3: state.py 수정**

`plugins/token-tracker/lib/state.py` 전체:
```python
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from lib import paths


def _session_dir(session_id: str) -> Path:
    d = paths.state_dir() / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _offset_path(session_id: str) -> Path:
    return _session_dir(session_id) / "offset.json"


def save_state(session_id: str, data: dict) -> None:
    target = _offset_path(session_id)
    fd, tmp = tempfile.mkstemp(
        prefix=".tmp-", suffix=".json", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, target)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_state(session_id: str) -> dict | None:
    target = _offset_path(session_id)
    if not target.exists():
        return None
    try:
        with target.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
```

- [ ] **Step 4: 테스트 실행 → 통과**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_state.py -v`
Expected: 5 passed.

- [ ] **Step 5: 기존 hook e2e 테스트 확인 (회귀 없음)**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_hook_end_to_end.py -v`
Expected: 전부 통과 (state 경로가 hook 내부에서 간접 사용됨).

- [ ] **Step 6: 전체 테스트 회귀 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests -q`
Expected: 50 passed.

- [ ] **Step 7: 커밋**

```bash
git add plugins/token-tracker/lib/state.py plugins/token-tracker/tests/test_state.py
git commit -m "refactor(state): state/{session_id}/offset.json 서브디렉터리 구조

last_summary.json과 한 세션의 state를 같은 폴더에 모으기 위해 flat 경로를
세션별 서브디렉터리로 이동. 구 구조의 기존 파일은 offset 없음으로
fallback되어 자연 소멸."
```

---

## Task 4: summary_store.py — Summary 저장·복원

**Files:**
- Create: `plugins/token-tracker/lib/summary_store.py`
- Create: `plugins/token-tracker/tests/test_summary_store.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`plugins/token-tracker/tests/test_summary_store.py`:
```python
import json
from pathlib import Path

from lib import paths, summary_store
from lib.aggregator import Summary
from lib.parser import TurnUsage


def _patch_state_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "_base_data_dir", lambda: tmp_path)


def _sample_summary() -> Summary:
    turns = [
        TurnUsage(
            model="claude-opus-4-7",
            input_tokens=10, output_tokens=20,
            cache_creation_tokens=0, cache_read_tokens=5,
            tools_used=[{"name": "Read", "count": 2}],
            timestamp_iso="2026-04-23T10:00:00Z",
            message_id="m1",
            index=0,
        )
    ]
    return Summary(
        total_cost=0.001, total_input_tokens=15,
        total_output_tokens=20, cache_hit_rate=0.33,
        total_elapsed=1.5, turns=turns,
    )


def test_save_load_roundtrip(monkeypatch, tmp_path):
    _patch_state_dir(monkeypatch, tmp_path)
    summary_store.save_last_summary("sess-1", _sample_summary())
    loaded = summary_store.load_last_summary("sess-1")
    assert loaded is not None
    assert loaded.total_cost == 0.001
    assert len(loaded.turns) == 1
    assert loaded.turns[0].tools_used == [{"name": "Read", "count": 2}]


def test_save_creates_directory(monkeypatch, tmp_path):
    _patch_state_dir(monkeypatch, tmp_path)
    summary_store.save_last_summary("sess-2", _sample_summary())
    assert (tmp_path / "state" / "sess-2" / "last_summary.json").is_file()


def test_load_missing_returns_none(monkeypatch, tmp_path):
    _patch_state_dir(monkeypatch, tmp_path)
    assert summary_store.load_last_summary("nonexistent") is None


def test_load_corrupted_json_returns_none(monkeypatch, tmp_path, capsys):
    _patch_state_dir(monkeypatch, tmp_path)
    d = tmp_path / "state" / "sess-3"
    d.mkdir(parents=True)
    (d / "last_summary.json").write_text("{not valid", encoding="utf-8")
    assert summary_store.load_last_summary("sess-3") is None


def test_load_unsupported_schema_version_returns_none(monkeypatch, tmp_path):
    _patch_state_dir(monkeypatch, tmp_path)
    d = tmp_path / "state" / "sess-4"
    d.mkdir(parents=True)
    (d / "last_summary.json").write_text(
        json.dumps({"schema_version": 99, "summary": {}}),
        encoding="utf-8",
    )
    assert summary_store.load_last_summary("sess-4") is None


def test_load_missing_summary_field_returns_none(monkeypatch, tmp_path):
    _patch_state_dir(monkeypatch, tmp_path)
    d = tmp_path / "state" / "sess-5"
    d.mkdir(parents=True)
    (d / "last_summary.json").write_text(
        json.dumps({"schema_version": 1}),
        encoding="utf-8",
    )
    assert summary_store.load_last_summary("sess-5") is None


def test_save_is_atomic_no_temp_leftover(monkeypatch, tmp_path):
    _patch_state_dir(monkeypatch, tmp_path)
    summary_store.save_last_summary("sess-6", _sample_summary())
    d = tmp_path / "state" / "sess-6"
    temps = [p for p in d.iterdir() if p.name.startswith(".tmp-")]
    assert temps == []
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_summary_store.py -v`
Expected: `ModuleNotFoundError: No module named 'lib.summary_store'`.

- [ ] **Step 3: summary_store.py 구현**

`plugins/token-tracker/lib/summary_store.py`:
```python
from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from dataclasses import asdict
from pathlib import Path

from lib import paths
from lib.aggregator import Summary
from lib.parser import TurnUsage


SCHEMA_VERSION = 1


def _summary_path(session_id: str) -> Path:
    d = paths.state_dir() / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d / "last_summary.json"


def save_last_summary(session_id: str, summary: Summary) -> None:
    target = _summary_path(session_id)
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "saved_at": __import__("time").time(),
        "summary": asdict(summary),
    }
    fd, tmp = tempfile.mkstemp(
        prefix=".tmp-", suffix=".json", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(envelope, f)
        os.replace(tmp, target)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_last_summary(session_id: str) -> Summary | None:
    target = _summary_path(session_id)
    if not target.exists():
        return None
    try:
        with target.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        print(traceback.format_exc(), file=sys.stderr)
        return None

    if data.get("schema_version") != SCHEMA_VERSION:
        print(
            f"[summary_store] unsupported schema_version={data.get('schema_version')} at {target}",
            file=sys.stderr,
        )
        return None

    sd = data.get("summary")
    if not isinstance(sd, dict):
        return None
    try:
        turns = [TurnUsage(**t) for t in sd.get("turns", [])]
        return Summary(
            total_cost=float(sd["total_cost"]),
            total_input_tokens=int(sd["total_input_tokens"]),
            total_output_tokens=int(sd["total_output_tokens"]),
            cache_hit_rate=float(sd["cache_hit_rate"]),
            total_elapsed=float(sd["total_elapsed"]),
            turns=turns,
        )
    except (KeyError, TypeError, ValueError):
        print(traceback.format_exc(), file=sys.stderr)
        return None
```

- [ ] **Step 4: 테스트 실행 → 통과**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_summary_store.py -v`
Expected: 7 passed.

- [ ] **Step 5: 전체 테스트 회귀 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests -q`
Expected: 57 passed (50 + 7).

- [ ] **Step 6: 커밋**

```bash
git add plugins/token-tracker/lib/summary_store.py plugins/token-tracker/tests/test_summary_store.py
git commit -m "feat(summary_store): Summary 영속화 모듈 + schema_version 검증

Stop hook이 집계한 Summary를 state/{session_id}/last_summary.json에
원자 쓰기 (tempfile+os.replace). load 시 schema_version 불일치나 필수 필드
결손은 None 반환 + stderr 진단 기록."
```

---

## Task 5: detail_formatter.py — Summary → 상세 표 문자열

**Files:**
- Create: `plugins/token-tracker/lib/detail_formatter.py`
- Create: `plugins/token-tracker/tests/test_detail_formatter.py`

- [ ] **Step 1: 실패하는 테스트 작성 (구조 기반 검증)**

`plugins/token-tracker/tests/test_detail_formatter.py`:
```python
from lib.detail_formatter import format_detail, visual_width
from lib.aggregator import Summary
from lib.parser import TurnUsage


def _turn(**overrides):
    base = dict(
        model="claude-opus-4-7", input_tokens=100, output_tokens=50,
        cache_creation_tokens=0, cache_read_tokens=0,
        tools_used=[], timestamp_iso="", message_id="m",
        index=0,
    )
    base.update(overrides)
    return TurnUsage(**base)


def _summary(turns):
    return Summary(
        total_cost=0.01, total_input_tokens=sum(t.input_tokens + t.cache_read_tokens + t.cache_creation_tokens for t in turns),
        total_output_tokens=sum(t.output_tokens for t in turns),
        cache_hit_rate=0.5, total_elapsed=10.0, turns=list(turns),
    )


def test_format_ko_contains_header_title():
    out = format_detail(_summary([_turn()]), "ko")
    assert "직전 request 상세" in out


def test_format_en_contains_header_title():
    out = format_detail(_summary([_turn()]), "en")
    assert "Last request detail" in out


def test_format_unknown_language_falls_back_to_en():
    out = format_detail(_summary([_turn()]), "zz")
    assert "Last request detail" in out


def test_empty_turns_shows_empty_turns_message():
    s = _summary([])
    out = format_detail(s, "ko")
    assert "응답이 없습니다" in out


def test_tool_with_counts_rendered():
    turn = _turn(tools_used=[{"name": "Read", "count": 3}, {"name": "Edit", "count": 1}])
    out = format_detail(_summary([turn]), "ko")
    assert "Read×3" in out
    assert "Edit×1" in out


def test_tools_empty_shows_dash():
    out = format_detail(_summary([_turn(tools_used=[])]), "ko")
    assert "—" in out


def test_tools_over_three_shows_ellipsis():
    turn = _turn(tools_used=[
        {"name": "A", "count": 1}, {"name": "B", "count": 1},
        {"name": "C", "count": 1}, {"name": "D", "count": 1},
        {"name": "E", "count": 1},
    ])
    out = format_detail(_summary([turn]), "ko")
    assert "...+2" in out


def test_long_model_name_truncated():
    long_name = "claude-opus-" + "x" * 30
    out = format_detail(_summary([_turn(model=long_name)]), "ko")
    assert "..." in out


def test_visual_width_hangul_counts_as_two():
    assert visual_width("abc") == 3
    assert visual_width("가나다") == 6
    assert visual_width("a가") == 3


def test_multi_turn_all_rows_present():
    turns = [
        _turn(index=0, model="opus"),
        _turn(index=1, model="sonnet"),
        _turn(index=2, model="haiku"),
    ]
    out = format_detail(_summary(turns), "ko")
    lines = out.splitlines()
    # find rows starting with " 1", " 2", " 3"
    row_starts = [l.strip().split()[0] for l in lines if l.strip() and l.strip()[0].isdigit()]
    assert row_starts == ["1", "2", "3"]


def test_header_total_contains_summary_values():
    s = _summary([_turn()])
    s.total_cost = 0.0180
    s.total_elapsed = 12.3
    out = format_detail(s, "ko")
    assert "$0.0180" in out
    assert "12.3" in out


def test_legend_included():
    out = format_detail(_summary([_turn()]), "ko")
    assert "cc=cache_creation" in out
    out_en = format_detail(_summary([_turn()]), "en")
    assert "cc=cache_creation" in out_en
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_detail_formatter.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: detail_formatter.py 구현**

`plugins/token-tracker/lib/detail_formatter.py`:
```python
from __future__ import annotations

from dataclasses import dataclass

from lib.aggregator import Summary
from lib.i18n_loader import load_strings
from lib.parser import TurnUsage


@dataclass
class Column:
    key: str         # i18n key for header label
    width: int       # character cells (visual)
    align: str       # "left" or "right"


_COLUMNS = [
    Column("col_index", 3, "right"),
    Column("col_model", 22, "left"),
    Column("col_tools", 20, "left"),
    Column("col_input", 8, "right"),
    Column("col_cc", 6, "right"),
    Column("col_cr", 7, "right"),
    Column("col_output", 8, "right"),
    Column("col_cost", 10, "right"),
    Column("col_time", 7, "right"),
]
_GAP = 2


def visual_width(s: str) -> int:
    """Return the visible width on a monospace terminal, counting CJK as 2."""
    return sum(2 if ord(c) > 0x2E80 else 1 for c in s)


def _pad(s: str, width: int, align: str) -> str:
    w = visual_width(s)
    if w >= width:
        return _truncate(s, width)
    pad = " " * (width - w)
    return pad + s if align == "right" else s + pad


def _truncate(s: str, width: int) -> str:
    out = ""
    used = 0
    for c in s:
        cw = 2 if ord(c) > 0x2E80 else 1
        if used + cw > width - 3:
            return out + "..."
        out += c
        used += cw
    return out


def _format_tools(tools: list[dict]) -> str:
    if not tools:
        return "—"
    rendered = [f"{t['name']}×{t['count']}" for t in tools]
    if len(rendered) <= 3:
        return ",".join(rendered)
    shown = rendered[:3]
    remainder = len(rendered) - 3
    return ",".join(shown) + f",...+{remainder}"


def _turn_time(turn: TurnUsage, next_turn: TurnUsage | None,
               prior_sum: float, total_elapsed: float) -> float | None:
    # try started/ended on the turn itself
    started = getattr(turn, "started_at", None)
    ended = getattr(turn, "ended_at", None)
    if started is not None and ended is not None:
        return max(0.0, ended - started)
    # fall back to next turn's start
    if started is not None and next_turn is not None:
        next_started = getattr(next_turn, "started_at", None)
        if next_started is not None:
            return max(0.0, next_started - started)
    # last turn without ended: total - prior
    if next_turn is None:
        remaining = total_elapsed - prior_sum
        return max(0.0, remaining)
    return None


def format_detail(summary: Summary, language: str) -> str:
    s = load_strings(language)

    if not summary.turns:
        return s["err_empty_turns"]

    # header
    cost_str = f"${summary.total_cost:.4f}"
    total_tokens = summary.total_input_tokens + summary.total_output_tokens
    cache_rate = f"{int(round(summary.cache_hit_rate * 100))}%"
    elapsed = f"{summary.total_elapsed:.1f}s"
    header_line = s["header_total"].format(
        cost=cost_str, tokens=f"{total_tokens:,}",
        rate=cache_rate, elapsed=elapsed,
    )

    # column header
    header_cells = [_pad(s[c.key], c.width, c.align) for c in _COLUMNS]
    col_header_row = (" " * _GAP).join(header_cells)

    row_width = visual_width(col_header_row)
    rule = "━" * max(row_width, visual_width(header_line), visual_width(s["header_title"]))

    # rows
    rows: list[str] = []
    prior_sum = 0.0
    for i, turn in enumerate(summary.turns):
        next_turn = summary.turns[i + 1] if i + 1 < len(summary.turns) else None
        t_sec = _turn_time(turn, next_turn, prior_sum, summary.total_elapsed)
        t_str = f"{t_sec:.1f}s" if t_sec is not None else "?"
        if t_sec is not None:
            prior_sum += t_sec

        cost = f"${__import__('lib.pricing', fromlist=['compute_cost']).compute_cost(turn.model, turn):.4f}"
        cells = [
            str(turn.index + 1),
            turn.model,
            _format_tools(turn.tools_used),
            f"{turn.input_tokens:,}",
            f"{turn.cache_creation_tokens:,}",
            f"{turn.cache_read_tokens:,}",
            f"{turn.output_tokens:,}",
            cost,
            t_str,
        ]
        padded = [_pad(c, col.width, col.align) for c, col in zip(cells, _COLUMNS)]
        rows.append((" " * _GAP).join(padded))

    parts = [
        rule,
        " " + s["header_title"],
        " " + header_line,
        "",
        " " + col_header_row,
        *[" " + r for r in rows],
        rule,
        " " + s["legend"],
    ]
    return "\n".join(parts)
```

- [ ] **Step 4: 테스트 실행 → 통과**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_detail_formatter.py -v`
Expected: 11 passed.

- [ ] **Step 5: 전체 테스트 회귀 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests -q`
Expected: 68 passed (57 + 11).

- [ ] **Step 6: 커밋**

```bash
git add plugins/token-tracker/lib/detail_formatter.py plugins/token-tracker/tests/test_detail_formatter.py
git commit -m "feat(detail_formatter): Summary → 표 문자열 렌더러

COLUMNS 리스트로 컬럼 정의를 데이터화 (향후 컬러/JSON export 확장 대비).
한글 2칸 폭을 visual_width로 정확히 계산. turn 시간은 started/ended/다음
turn/total_elapsed의 4단계 fallback. 모든 i18n 문자열은 lib/i18n 리소스에서
로드."
```

---

## Task 6: hooks/on_stop.py — save_last_summary 호출 추가

**Files:**
- Modify: `plugins/token-tracker/hooks/on_stop.py`
- Modify: `plugins/token-tracker/tests/test_hook_end_to_end.py`

- [ ] **Step 1: e2e 테스트 추가 (실패)**

`plugins/token-tracker/tests/test_hook_end_to_end.py`에 추가:
```python
def test_last_summary_saved_after_stop(monkeypatch, tmp_path):
    # Arrange: fake a completed request
    _patch_plugin_root(monkeypatch, tmp_path)  # 기존 helper 있을 것으로 가정. 없으면 PLUGIN_ROOT env 세팅.
    # ... realistic cycle helper 재사용
    result = _run_cycle_and_get_outputs(...)
    # Assert: last_summary.json exists for the session
    from lib import paths
    summary_file = paths.state_dir() / "sess-e2e" / "last_summary.json"
    assert summary_file.is_file()
    import json
    data = json.loads(summary_file.read_text())
    assert data["schema_version"] == 1
    assert "summary" in data
    assert len(data["summary"]["turns"]) >= 1


def test_last_summary_not_saved_when_no_turns(monkeypatch, tmp_path):
    _patch_plugin_root(monkeypatch, tmp_path)
    # Arrange: empty transcript, no state
    result = _run_cycle_empty(...)
    from lib import paths
    summary_file = paths.state_dir() / "sess-empty" / "last_summary.json"
    assert not summary_file.exists()
```

**주의**: 기존 `test_hook_end_to_end.py`가 어떤 helper를 제공하는지 파일을 먼저 읽고 패턴을 맞춰라. `_run_cycle_and_get_outputs`는 예시 이름. 실제 파일의 헬퍼·픽스처를 재사용하고 session_id="sess-e2e" 같은 fixed 값을 사용.

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_hook_end_to_end.py::test_last_summary_saved_after_stop -v`
Expected: FAIL — `last_summary.json` 미생성.

- [ ] **Step 3: on_stop.py 수정**

`plugins/token-tracker/hooks/on_stop.py`, `main()` 함수의 `summary = aggregate(turns, elapsed=elapsed)` **직후, format_summary 이전**에 save 호출 추가:

```python
        elapsed = max(0.0, time.time() - started_at)
        summary = aggregate(turns, elapsed=elapsed)

        # Persist the just-computed Summary so /token-detail can read it.
        # Only save when we actually produced turns (flush polling finished).
        if summary.turns:
            try:
                from lib.summary_store import save_last_summary
                save_last_summary(session_id, summary)
            except Exception:
                _log_error(f"[on_stop] save_last_summary: {traceback.format_exc()}")

        cfg = _load_config(plugin_root)
        lang = cfg.get("language", "en")
        msg = format_summary(summary, lang)
        _emit(msg)
```

**핵심**: `if summary.turns:` 가드. flush polling이 실패해 turns가 0이면 저장 skip (spec §4.3의 "불완전 스냅샷 영구화 방지").

- [ ] **Step 4: 테스트 실행 → 통과**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_hook_end_to_end.py -v`
Expected: 기존 6 + 신규 2 = 8 passed.

- [ ] **Step 5: 전체 테스트 회귀 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests -q`
Expected: 70 passed (68 + 2).

- [ ] **Step 6: 커밋**

```bash
git add plugins/token-tracker/hooks/on_stop.py plugins/token-tracker/tests/test_hook_end_to_end.py
git commit -m "feat(hook): flush polling 완료 후 last_summary 저장

turns>0 확인 후에만 summary_store.save_last_summary 호출. 이전 summary가
polling 미완료 상태로 덮어쓰여 불완전 스냅샷이 영구화되는 Phase 1 재발
방지. 저장 실패는 error.log 기록 후 기존 흐름 계속 (hook은 exit 0)."
```

---

## Task 7: skills/token-detail — SKILL.md + scripts/detail.py

**Files:**
- Create: `plugins/token-tracker/skills/token-detail/SKILL.md`
- Create: `plugins/token-tracker/skills/token-detail/scripts/detail.py`
- Create: `plugins/token-tracker/tests/test_detail_script_e2e.py`

- [ ] **Step 1: 실패하는 e2e 테스트 작성**

`plugins/token-tracker/tests/test_detail_script_e2e.py`:
```python
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "skills" / "token-detail" / "scripts" / "detail.py"


def _run_script(session_id: str, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(SCRIPT), session_id],
        capture_output=True, text=True, env=env,
    )


def _seed_last_summary(home: Path, session_id: str, payload: dict) -> None:
    d = home / ".claude" / "plugins" / "token-tracker" / "state" / session_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "last_summary.json").write_text(json.dumps(payload), encoding="utf-8")


def _valid_summary_payload(session_id: str) -> dict:
    return {
        "schema_version": 1,
        "session_id": session_id,
        "saved_at": 1745301234.5,
        "summary": {
            "total_cost": 0.01,
            "total_input_tokens": 100,
            "total_output_tokens": 50,
            "cache_hit_rate": 0.5,
            "total_elapsed": 1.2,
            "turns": [{
                "model": "claude-opus-4-7",
                "input_tokens": 100, "output_tokens": 50,
                "cache_creation_tokens": 0, "cache_read_tokens": 0,
                "tools_used": [{"name": "Read", "count": 1}],
                "timestamp_iso": "2026-04-23T10:00:00Z",
                "message_id": "m1", "index": 0,
            }],
        },
    }


def test_script_always_exits_zero_with_no_state(tmp_path):
    result = _run_script("sess-missing", env_overrides={"HOME": str(tmp_path)})
    assert result.returncode == 0


def test_script_outputs_err_no_state_when_missing(tmp_path):
    result = _run_script("sess-missing", env_overrides={"HOME": str(tmp_path)})
    assert "아직 기록된 request" in result.stdout or "No recorded request" in result.stdout


def test_script_outputs_formatted_detail_when_state_exists(tmp_path):
    _seed_last_summary(tmp_path, "sess-ok", _valid_summary_payload("sess-ok"))
    result = _run_script("sess-ok", env_overrides={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert "Read×1" in result.stdout


def test_script_outputs_err_parse_on_corrupted_state(tmp_path):
    d = tmp_path / ".claude" / "plugins" / "token-tracker" / "state" / "sess-bad"
    d.mkdir(parents=True)
    (d / "last_summary.json").write_text("{not valid", encoding="utf-8")
    result = _run_script("sess-bad", env_overrides={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert ("손상" in result.stdout) or ("corrupted" in result.stdout.lower())


def test_script_outputs_err_unsupported_schema(tmp_path):
    payload = {"schema_version": 99, "summary": {}}
    _seed_last_summary(tmp_path, "sess-future", payload)
    result = _run_script("sess-future", env_overrides={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert ("호환되지 않습니다" in result.stdout) or ("not compatible" in result.stdout)
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_detail_script_e2e.py -v`
Expected: 스크립트 파일이 없어서 `FileNotFoundError` 또는 exit code non-zero.

- [ ] **Step 3: scripts/detail.py 구현**

`plugins/token-tracker/skills/token-detail/scripts/detail.py`:
```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path


def _setup_sys_path() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        root = Path(env)
    else:
        # scripts/detail.py -> skills/token-detail/scripts -> plugin root 3 up
        root = Path(__file__).resolve().parent.parent.parent.parent
    sys.path.insert(0, str(root))
    return root


def _load_language(plugin_root: Path) -> str:
    cfg = plugin_root / "config.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text(encoding="utf-8")).get("language", "en")
        except Exception:
            pass
    return "en"


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
        from lib.i18n_loader import load_strings
        from lib.summary_store import load_last_summary
        from lib.detail_formatter import format_detail

        lang = _load_language(plugin_root)
        strings = load_strings(lang)

        if not session_id:
            print(strings["err_no_state"])
            return 0

        # schema_version==unsupported 는 load_last_summary가 None 반환하며 stderr로 version을 기록함.
        summary = load_last_summary(session_id)

        # determine which error to print by re-inspecting file when summary is None
        if summary is None:
            from lib import paths
            candidate = paths.state_dir() / session_id / "last_summary.json"
            if not candidate.exists():
                print(strings["err_no_state"])
                return 0
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if data.get("schema_version") != 1:
                    print(strings["err_unsupported_schema"])
                    return 0
            except Exception:
                pass
            print(strings["err_parse"])
            return 0

        if not summary.turns:
            print(strings["err_empty_turns"])
            return 0

        print(format_detail(summary, lang))
        return 0
    except Exception:
        tb = traceback.format_exc()
        _log_error(f"[detail.py] {tb}")
        print(tb, file=sys.stderr)
        # best-effort user message
        try:
            from lib.i18n_loader import load_strings
            print(load_strings("en")["err_parse"])
        except Exception:
            print("detail skill: unexpected error")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: SKILL.md 생성**

`plugins/token-tracker/skills/token-detail/SKILL.md`:
```markdown
---
name: token-detail
description: 직전 request의 turn별 토큰·비용·툴 사용 내역을 표로 출력
disable-model-invocation: true
---

!`python3 ${CLAUDE_SKILL_DIR}/scripts/detail.py "${CLAUDE_SESSION_ID}"`

위 출력 블록을 그대로 사용자에게 전달하세요. 숫자 해석·요약·추가 설명 금지.
```

- [ ] **Step 5: e2e 테스트 실행 → 통과**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_detail_script_e2e.py -v`
Expected: 5 passed.

- [ ] **Step 6: 전체 테스트 회귀 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests -q`
Expected: 75 passed (70 + 5).

- [ ] **Step 7: 커밋**

```bash
git add plugins/token-tracker/skills/ plugins/token-tracker/tests/test_detail_script_e2e.py
git commit -m "feat(skill): /token-detail skill + scripts/detail.py + e2e 테스트

SKILL.md는 !`cmd` 치환 한 줄로 스크립트 실행 → stdout이 본문에 삽입.
스크립트는 \${CLAUDE_SESSION_ID}를 argv로 받아 state/last_summary.json
로드 후 detail_formatter로 표 출력. 모든 에러 경로에서 exit 0 유지,
사용자에게 친절한 i18n 메시지 표시."
```

---

## Task 8: 수동 검증 + 문서 + 버전 범프 + 태그

**Files:**
- Modify: `README.md`
- Modify: `docs/handoff/2026-04-22-token-tracker-next-steps.md`
- Modify: `plugins/token-tracker/.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`

- [ ] **Step 1: 사용자 수동 검증 요청 (사용자 개입)**

사용자에게 다음을 안내:
1. Claude Code에서 `/reload-plugins` 실행 (새 skill 감지).
2. 아무 짧은 메시지 주고받아 Stop hook 발화시킴 (이때 last_summary.json 생성).
3. 바로 이어서 `/token-detail` 입력 → 표가 채팅창에 표시되는지 확인.
4. 새 세션 시작 직후 (응답 전) `/token-detail` 입력 → "아직 기록된 request가 없습니다." 메시지 확인.
5. state 파일 수동 손상 (`echo '{bad' > ~/.claude/plugins/token-tracker/state/<session>/last_summary.json`) 후 `/token-detail` → 손상 메시지 + error.log 확인.

사용자 보고 3건 모두 OK 확인 후 다음 Step 진행.

- [ ] **Step 2: README에 `/token-detail` 섹션 추가**

`README.md` — "## What it shows" 섹션 아래에 새 섹션 삽입:
```markdown
## Detail view: `/token-detail`

직전 request의 turn별 토큰·비용·툴 사용 내역을 한 번에 보고 싶다면:

```
/token-detail
```

출력 예시:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 직전 request 상세
 총 비용 $0.0180 | 1,546 toks | cache 85% | 12.3s

  #  모델                    툴                input    cc     cr      output   비용     시간
  1  opus-4-7[1m]            Read×3,Edit×1    120      400    800       450   $0.008   2.1s
  2  opus-4-7[1m]            —                 95        0  1,200       320   $0.006   3.5s
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 범례: cc=cache_creation, cr=cache_read
```

skill은 `disable-model-invocation: true`로 등록돼 있어 Claude가 자동으로 호출하지 않고, 사용자가 `/token-detail`을 직접 입력해야만 실행됩니다.
```

- [ ] **Step 3: handoff 문서 업데이트**

`docs/handoff/2026-04-22-token-tracker-next-steps.md`의 섹션 5-B 교체:
```markdown
### B. `/token-detail` skill ✅ 완료 (2026-04-23)

- `plugins/token-tracker/skills/token-detail/` 추가. SKILL.md + scripts/detail.py.
- Stop hook이 flush polling 완료 후 `state/{session}/last_summary.json`에 Summary 저장.
- detail_formatter가 COLUMNS 리스트 + i18n 리소스(`lib/i18n/{ko,en}.json`)로 표 렌더링.
- 관련 테스트: summary_store(7), detail_formatter(11), detail_script_e2e(5), hook_e2e 확장(2).
- 관련 plan: `docs/superpowers/plans/2026-04-23-token-detail-skill.md`.

> **다음 세션 권장**: C (`/token-history` + `/token-verbose`) 또는 D (가격표 정확도).
```

섹션 5 맨 위 "다음 세션 권장: B부터 시작" 문구를 "다음 세션 권장: C부터 시작"으로 변경.

- [ ] **Step 4: 버전 범프**

`plugins/token-tracker/.claude-plugin/plugin.json`에서 `"version": "0.2.0"` → `"version": "0.3.0"`.
`.claude-plugin/marketplace.json`의 plugins[0].version 동일 변경.

- [ ] **Step 5: 버전 일관성 테스트 통과 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_marketplace_manifest.py::test_marketplace_plugin_version_matches_plugin_json -v`
Expected: PASS.

- [ ] **Step 6: 전체 테스트 최종**

Run: `./venv/bin/pytest plugins/token-tracker/tests -q`
Expected: 75 passed.

- [ ] **Step 7: 커밋**

```bash
git add README.md docs/handoff/ plugins/token-tracker/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "chore(release): bump to 0.3.0 for /token-detail skill

README에 skill 사용법 + 출력 예시 추가. handoff 문서 후보 B 완료 표시.
plugin.json과 marketplace.json version을 0.3.0으로 동기화."
```

- [ ] **Step 8: 태그 생성**

```bash
git tag -a v0.3.0 -m "v0.3.0: /token-detail skill (Phase 2-B)"
git log --oneline v0.2.0..v0.3.0
```

- [ ] **Step 9: 최종 사용자 보고**

형식:
```
완료: /token-detail skill (Phase 2-B)
- 신규 파일: 10 (lib 4 + skills 2 + i18n 2 + tests 3 + resources 1 빼고 정확히 카운트)
- 수정 파일: 5 (parser, aggregator, state, hooks/on_stop, README)
- 신규 테스트: 25건 (i18n 4 + parser 변경 1 + aggregator 2 + state 재작성 5 + summary_store 7 + detail_formatter 11 + detail_script_e2e 5 + hook_e2e 2)
- 전체 테스트: 75 passed
- 태그: v0.3.0

다음 후보: C (/token-history + /token-verbose) 또는 D (가격표 정확도).
```

---

## Self-Review 결과

**1. Spec coverage**
- §2 Claude Code skill 메커니즘 → Task 7 SKILL.md로 구현. ✅
- §3 데이터 흐름 → Task 6(hook save) + Task 7(skill read). ✅
- §4.1 파일 구조 → Task 1~7 전부 커버. ✅
- §4.3 flush polling 선행 → Task 6 Step 3 `if summary.turns:` 가드로 반영. ✅
- §4.4 state 디렉터리 마이그레이션 → Task 3. ✅
- §4.5 schema_version 정책 → Task 4 load에서 버전 검증 + stderr. ✅
- §6 출력 포맷 → Task 5 detail_formatter. ✅
- §7 에러 처리 표 → Task 7 스크립트가 세 에러 경로 처리 (err_no_state, err_parse, err_unsupported_schema). ✅
- §8 테스트 전략 (단위 + integration + e2e + 체크포인트 매핑) → Task 1~7 각 TDD. ✅
- §9 후속 과제 → 범위 외, plan에 포함 안 함 (의도).

**2. Placeholder scan**
- "TBD/TODO/implement later" 없음.
- 각 Task의 코드는 완전. 한 곳 예외: Task 6 Step 1의 `_run_cycle_and_get_outputs(...)` 는 기존 파일의 helper 활용 지시 (실제 helper 이름은 파일 확인 후). 이는 구현자가 기존 패턴을 따라야 하는 정당한 이유.

**3. Type consistency**
- `TurnUsage.tools_used`: Task 2에서 `list[dict]`로 변경 → Task 4 summary_store dataclass asdict/`TurnUsage(**t)` 복원 → Task 5 formatter가 `{"name", "count"}` 읽음. ✅
- `TurnUsage.index`: Task 2에서 default 0 + aggregator가 enumerate로 부여 → Task 5 formatter가 `turn.index + 1` 표시. ✅
- `Summary` 필드: Task 4 save/load가 aggregator.Summary의 모든 필드 dump/restore. ✅
- state 파일 경로: Task 3 `offset.json` + Task 4 `last_summary.json` 같은 세션 서브디렉터리 공존. ✅

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-23-token-detail-skill.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Fresh subagent per task, two-stage review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session, batch execution with checkpoints for review.

**Which approach?**
