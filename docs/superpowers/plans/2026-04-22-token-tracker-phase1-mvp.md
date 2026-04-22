# token-tracker Phase 1 MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code Stop hook이 발화할 때마다 방금 끝난 사용자 요청(UserPromptSubmit → Stop)의 `비용 $X · 토큰수 · 캐시 적중률 · 소요시간`을 한 줄로 표시하는 플러그인을 구축한다.

**Architecture:** UserPromptSubmit hook에서 session JSONL의 byte offset을 state file에 저장 → Stop hook에서 저장된 offset부터 EOF까지 파싱 → 정적 가격표로 비용 산출 → systemMessage JSON으로 출력. Python 표준 라이브러리만 사용, claude-code marketplace plugin 포맷.

**Tech Stack:** Python 3.10+ (표준 라이브러리만), pytest, Claude Code plugin/hook 스펙(2026.04), JSON/JSONL.

**Spec:** `docs/superpowers/specs/2026-04-22-token-tracker-plugin-design.md`

**Scope:** 이 계획은 **Phase 1 MVP만** 다룬다. skills(`/token-detail`, `/token-history`, `/token-verbose`)는 Phase 2/3의 별도 계획으로 처리한다.

---

## File Structure

```
token-tracker/
├── .claude-plugin/plugin.json           # Task 1
├── hooks/
│   ├── hooks.json                        # Task 1
│   ├── on_user_prompt.py                 # Task 8
│   └── on_stop.py                        # Task 9
├── lib/
│   ├── __init__.py                       # Task 1
│   ├── paths.py                          # Task 2
│   ├── state.py                          # Task 3
│   ├── parser.py                         # Task 4
│   ├── pricing.py                        # Task 5
│   ├── aggregator.py                     # Task 6
│   └── formatter.py                      # Task 7
├── config.json                           # Task 1
└── tests/
    ├── __init__.py                       # Task 1
    ├── conftest.py                       # Task 1
    ├── fixtures/
    │   └── sample_session.jsonl          # Task 4
    ├── test_paths.py                     # Task 2
    ├── test_state.py                     # Task 3
    ├── test_parser.py                    # Task 4
    ├── test_pricing.py                   # Task 5
    ├── test_aggregator.py                # Task 6
    ├── test_formatter.py                 # Task 7
    └── test_hook_end_to_end.py           # Task 10
```

**Working directory for all tasks:** `/Users/i_brody/Desktop/harness/token-tracker/`

**Responsibility per file:**
- `paths.py` — 플러그인 루트/데이터 디렉터리 resolve
- `state.py` — atomic state 저장·복원
- `parser.py` — JSONL 라인 → `TurnUsage` (순수 함수)
- `pricing.py` — 정적 가격표 + `compute_cost`
- `aggregator.py` — `TurnUsage[]` + elapsed → `Summary`
- `formatter.py` — `Summary` + lang → 한 줄 문자열
- `hooks/on_user_prompt.py` — offset 기록만
- `hooks/on_stop.py` — 위 lib들 조립해 한 줄 출력

---

## Task 1: 프로젝트 스캐폴딩 & 플러그인 메타데이터

**Files:**
- Create: `token-tracker/.claude-plugin/plugin.json`
- Create: `token-tracker/hooks/hooks.json`
- Create: `token-tracker/config.json`
- Create: `token-tracker/lib/__init__.py`
- Create: `token-tracker/tests/__init__.py`
- Create: `token-tracker/tests/conftest.py`
- Create: `token-tracker/.gitignore`
- Create: `token-tracker/README.md`

- [ ] **Step 1: 작업 디렉터리 생성**

```bash
mkdir -p /Users/i_brody/Desktop/harness/token-tracker/{.claude-plugin,hooks,lib,tests/fixtures}
cd /Users/i_brody/Desktop/harness/token-tracker
git init
```

Expected: `.git`, 하위 디렉터리들 생성.

- [ ] **Step 2: `.claude-plugin/plugin.json` 작성**

```json
{
  "name": "token-tracker",
  "description": "한 번의 프롬프트가 소비한 토큰·비용을 Stop hook 응답 블록에 한 줄로 표시",
  "version": "0.1.0",
  "author": { "name": "brody" }
}
```

- [ ] **Step 3: `hooks/hooks.json` 작성**

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/on_user_prompt.py\""
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/on_stop.py\""
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 4: `config.json` 작성 (기본 설정)**

```json
{
  "language": "ko",
  "verbose": false
}
```

- [ ] **Step 5: 빈 `__init__.py` 2개와 `conftest.py` 작성**

`lib/__init__.py` (빈 파일):

```python
```

`tests/__init__.py` (빈 파일):

```python
```

`tests/conftest.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

- [ ] **Step 6: `.gitignore` 작성**

```
__pycache__/
*.pyc
.pytest_cache/
.venv/
.DS_Store
```

- [ ] **Step 7: `README.md` 최소본**

```markdown
# token-tracker

Claude Code plugin: display per-request token cost on every Stop.

See `docs/superpowers/specs/2026-04-22-token-tracker-plugin-design.md`.
```

- [ ] **Step 8: 구조 확인**

Run: `find . -type f | sort`
Expected: 위 8개 파일과 `.git/` 내부 파일들이 보임.

- [ ] **Step 9: Python 3.10+ 버전 확인**

Run: `python3 --version`
Expected: `Python 3.10.x` 이상.

- [ ] **Step 10: pytest 설치 가능 확인**

Run: `pytest --version`
Expected: pytest 버전 출력. macOS Homebrew 환경이면 `pipx install pytest`로 설치.

- [ ] **Step 11: Commit**

```bash
git add .
git commit -m "chore: scaffold token-tracker plugin skeleton"
```

---

## Task 2: `lib/paths.py` — 디렉터리 해결

**Files:**
- Create: `token-tracker/lib/paths.py`
- Create: `token-tracker/tests/test_paths.py`

목적: 플러그인 루트와 런타임 데이터 디렉터리를 어떤 실행 환경에서도 일관되게 resolve한다. `CLAUDE_PLUGIN_ROOT` env가 설정돼 있으면 그것을, 없으면 `__file__` 기반 fallback.

- [ ] **Step 1: Failing test 작성**

`tests/test_paths.py`:

```python
import os
from pathlib import Path

from lib import paths


def test_plugin_root_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    assert paths.plugin_root() == tmp_path


def test_plugin_root_fallback_to_file(monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    root = paths.plugin_root()
    assert (root / "lib" / "paths.py").exists()


def test_state_dir_creates_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    d = paths.state_dir()
    assert d.exists()
    assert d.is_dir()
    assert d == tmp_path / ".claude" / "plugins" / "token-tracker" / "state"


def test_log_dir_creates_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    d = paths.log_dir()
    assert d.exists()
    assert d == tmp_path / ".claude" / "plugins" / "token-tracker" / "log"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/i_brody/Desktop/harness/token-tracker && pytest tests/test_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.paths'`.

- [ ] **Step 3: Minimal implementation**

`lib/paths.py`:

```python
from __future__ import annotations

import os
from pathlib import Path


def plugin_root() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent


def _base_data_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".claude" / "plugins" / "token-tracker"


def state_dir() -> Path:
    d = _base_data_dir() / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir() -> Path:
    d = _base_data_dir() / "log"
    d.mkdir(parents=True, exist_ok=True)
    return d
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_paths.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/paths.py tests/test_paths.py
git commit -m "feat(lib): add paths module for plugin root/state/log dir resolution"
```

---

## Task 3: `lib/state.py` — Atomic 상태 저장·복원

**Files:**
- Create: `token-tracker/lib/state.py`
- Create: `token-tracker/tests/test_state.py`

목적: session_id별로 `{offset, started_at}`을 저장·복원. 손상 파일은 None 반환. atomic: tempfile + rename.

- [ ] **Step 1: Failing test 작성**

`tests/test_state.py`:

```python
import json
from pathlib import Path

from lib import state


def test_save_and_load_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    state.save_state("sess-1", {"offset": 1024, "started_at": 1700.5})
    assert state.load_state("sess-1") == {"offset": 1024, "started_at": 1700.5}


def test_load_missing_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert state.load_state("never-saved") is None


def test_load_corrupted_returns_none(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    from lib import paths
    p = paths.state_dir() / "corrupt.json"
    p.write_text("not json {{{")
    assert state.load_state("corrupt") is None


def test_save_is_atomic_no_temp_leftover(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    state.save_state("sess-atomic", {"offset": 0, "started_at": 0.0})
    from lib import paths
    files = list(paths.state_dir().iterdir())
    tempfiles = [f for f in files if f.name.startswith(".tmp")]
    assert tempfiles == []
```

- [ ] **Step 2: Run test — verify fail**

Run: `pytest tests/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.state'`.

- [ ] **Step 3: Minimal implementation**

`lib/state.py`:

```python
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from lib import paths


def _state_path(session_id: str) -> Path:
    return paths.state_dir() / f"{session_id}.json"


def save_state(session_id: str, data: dict) -> None:
    target = _state_path(session_id)
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
    target = _state_path(session_id)
    if not target.exists():
        return None
    try:
        with target.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_state.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/state.py tests/test_state.py
git commit -m "feat(lib): add atomic state save/load for per-session offset tracking"
```

---

## Task 4: `lib/parser.py` — JSONL 라인 파싱

**Files:**
- Create: `token-tracker/lib/parser.py`
- Create: `token-tracker/tests/fixtures/sample_session.jsonl`
- Create: `token-tracker/tests/test_parser.py`

목적: JSONL 라인(dict) → `TurnUsage` 또는 None. assistant 라인만 처리. 결정론적 순수 함수.

- [ ] **Step 1: Fixture 준비**

`tests/fixtures/sample_session.jsonl` (4줄 — user, assistant1, tool_result, assistant2):

```
{"type":"user","message":{"role":"user","content":"hi"},"uuid":"u1","timestamp":"2026-04-22T10:00:00.000Z"}
{"type":"assistant","message":{"id":"msg_1","role":"assistant","model":"claude-opus-4-7","content":[{"type":"text","text":"hello"}],"usage":{"input_tokens":10,"output_tokens":5,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}},"uuid":"a1","timestamp":"2026-04-22T10:00:01.000Z"}
{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu1","content":"ok"}]},"uuid":"tr1","timestamp":"2026-04-22T10:00:02.000Z"}
{"type":"assistant","message":{"id":"msg_2","role":"assistant","model":"claude-opus-4-7","content":[{"type":"tool_use","id":"tu2","name":"Read","input":{}},{"type":"tool_use","id":"tu3","name":"Grep","input":{}}],"usage":{"input_tokens":100,"output_tokens":20,"cache_creation_input_tokens":500,"cache_read_input_tokens":2000}},"uuid":"a2","timestamp":"2026-04-22T10:00:05.000Z"}
```

- [ ] **Step 2: Failing test 작성**

`tests/test_parser.py`:

```python
import json
from pathlib import Path

from lib import parser


FIXTURE = Path(__file__).parent / "fixtures" / "sample_session.jsonl"


def _load_lines():
    return [json.loads(l) for l in FIXTURE.read_text().splitlines() if l.strip()]


def test_parse_user_line_returns_none():
    lines = _load_lines()
    assert parser.parse_line(lines[0]) is None


def test_parse_tool_result_user_line_returns_none():
    lines = _load_lines()
    assert parser.parse_line(lines[2]) is None


def test_parse_simple_assistant_line():
    lines = _load_lines()
    t = parser.parse_line(lines[1])
    assert t is not None
    assert t.model == "claude-opus-4-7"
    assert t.input_tokens == 10
    assert t.output_tokens == 5
    assert t.cache_creation_tokens == 0
    assert t.cache_read_tokens == 0
    assert t.tools_used == []


def test_parse_assistant_line_with_tool_uses():
    lines = _load_lines()
    t = parser.parse_line(lines[3])
    assert t.tools_used == ["Read", "Grep"]
    assert t.cache_read_tokens == 2000


def test_parse_assistant_line_exposes_timestamp():
    lines = _load_lines()
    t = parser.parse_line(lines[1])
    assert t.timestamp_iso == "2026-04-22T10:00:01.000Z"


def test_parse_malformed_line_returns_none():
    assert parser.parse_line({"type": "assistant"}) is None
    assert parser.parse_line({}) is None
```

- [ ] **Step 3: Run test — verify fail**

Run: `pytest tests/test_parser.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 4: Minimal implementation**

`lib/parser.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TurnUsage:
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    tools_used: list[str] = field(default_factory=list)
    timestamp_iso: str = ""


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
    tools = [
        blk.get("name", "")
        for blk in content
        if isinstance(blk, dict) and blk.get("type") == "tool_use"
    ]

    return TurnUsage(
        model=msg.get("model", ""),
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
        cache_creation_tokens=int(usage.get("cache_creation_input_tokens", 0)),
        cache_read_tokens=int(usage.get("cache_read_input_tokens", 0)),
        tools_used=tools,
        timestamp_iso=entry.get("timestamp", ""),
    )
```

- [ ] **Step 5: Run test to verify pass**

Run: `pytest tests/test_parser.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add lib/parser.py tests/fixtures/sample_session.jsonl tests/test_parser.py
git commit -m "feat(lib): add pure-function JSONL parser for assistant turns"
```

---

## Task 5: `lib/pricing.py` — 정적 가격표 + 비용 계산

**Files:**
- Create: `token-tracker/lib/pricing.py`
- Create: `token-tracker/tests/test_pricing.py`

목적: 모델 ID + `TurnUsage` → USD 비용. 미등록 모델은 0.0 + 진단. 가격은 $/1M tokens.

**가격 출처 주석:** 각 엔트리 옆에 공식 문서 URL 또는 `retrieved: 2026-04-22` 주석을 단다. 플러그인 버전 bump로 갱신.

- [ ] **Step 1: Failing test 작성**

`tests/test_pricing.py`:

```python
import math

from lib import pricing
from lib.parser import TurnUsage


def test_known_model_cost_opus():
    u = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    cost = pricing.compute_cost("claude-opus-4-7", u)
    assert math.isclose(cost, 15.0, rel_tol=1e-6)


def test_cache_read_is_cheaper_than_input():
    u_cache = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=1_000_000,
    )
    u_input = TurnUsage(
        model="claude-opus-4-7",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    assert pricing.compute_cost("claude-opus-4-7", u_cache) < pricing.compute_cost(
        "claude-opus-4-7", u_input
    )


def test_unknown_model_returns_zero():
    u = TurnUsage(
        model="claude-ghost-1",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    assert pricing.compute_cost("claude-ghost-1", u) == 0.0


def test_sonnet_known():
    u = TurnUsage(
        model="claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    assert pricing.compute_cost("claude-sonnet-4-6", u) == 3.0


def test_haiku_known():
    u = TurnUsage(
        model="claude-haiku-4-5",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    assert pricing.compute_cost("claude-haiku-4-5", u) > 0.0
```

- [ ] **Step 2: Run test — verify fail**

Run: `pytest tests/test_pricing.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Minimal implementation**

`lib/pricing.py`:

```python
from __future__ import annotations

from lib.parser import TurnUsage


# Prices in USD per 1,000,000 tokens.
# Sources: Anthropic pricing page (retrieved 2026-04-22).
# Keys must match the "model" field observed in Claude Code JSONL transcripts.
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-7": {
        "input": 15.0,
        "output": 75.0,
        "cache_creation": 18.75,
        "cache_read": 1.5,
    },
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_creation": 3.75,
        "cache_read": 0.3,
    },
    "claude-haiku-4-5": {
        "input": 1.0,
        "output": 5.0,
        "cache_creation": 1.25,
        "cache_read": 0.1,
    },
}


def compute_cost(model: str, usage: TurnUsage) -> float:
    rates = PRICING.get(model)
    if rates is None:
        return 0.0
    per_mtok = 1_000_000.0
    return (
        usage.input_tokens * rates["input"] / per_mtok
        + usage.output_tokens * rates["output"] / per_mtok
        + usage.cache_creation_tokens * rates["cache_creation"] / per_mtok
        + usage.cache_read_tokens * rates["cache_read"] / per_mtok
    )


def is_known_model(model: str) -> bool:
    return model in PRICING
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_pricing.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/pricing.py tests/test_pricing.py
git commit -m "feat(lib): add static pricing table and cost computation"
```

---

## Task 6: `lib/aggregator.py` — Turn 집계 → Summary

**Files:**
- Create: `token-tracker/lib/aggregator.py`
- Create: `token-tracker/tests/test_aggregator.py`

목적: `TurnUsage[]` + elapsed초 → `Summary`. 캐시 적중률 = `cache_read / 전체 input`. 입력이 0이면 0.0 반환.

- [ ] **Step 1: Failing test 작성**

`tests/test_aggregator.py`:

```python
import math

from lib import aggregator
from lib.parser import TurnUsage


def _mk(model="claude-opus-4-7", **kw) -> TurnUsage:
    defaults = dict(
        model=model,
        input_tokens=0,
        output_tokens=0,
        cache_creation_tokens=0,
        cache_read_tokens=0,
    )
    defaults.update(kw)
    return TurnUsage(**defaults)


def test_empty_returns_zero_summary():
    s = aggregator.aggregate([], elapsed=0.0)
    assert s.total_cost == 0.0
    assert s.total_input_tokens == 0
    assert s.total_output_tokens == 0
    assert s.cache_hit_rate == 0.0
    assert s.total_elapsed == 0.0
    assert s.turns == []


def test_single_turn():
    t = _mk(input_tokens=100, output_tokens=50, cache_read_tokens=200)
    s = aggregator.aggregate([t], elapsed=1.5)
    assert s.total_input_tokens == 300  # 100 input + 200 cache_read
    assert s.total_output_tokens == 50
    assert math.isclose(s.cache_hit_rate, 200 / 300)
    assert s.total_elapsed == 1.5


def test_multiple_turns_sum():
    ts = [
        _mk(input_tokens=100, cache_read_tokens=0),
        _mk(input_tokens=100, cache_read_tokens=900),
    ]
    s = aggregator.aggregate(ts, elapsed=2.0)
    assert s.total_input_tokens == 1100
    assert math.isclose(s.cache_hit_rate, 900 / 1100)


def test_cache_hit_rate_with_zero_input():
    s = aggregator.aggregate([_mk()], elapsed=0.0)
    assert s.cache_hit_rate == 0.0


def test_total_cost_sums_per_turn():
    ts = [
        _mk(model="claude-opus-4-7", input_tokens=1_000_000),
        _mk(model="claude-sonnet-4-6", input_tokens=1_000_000),
    ]
    s = aggregator.aggregate(ts, elapsed=0.0)
    assert math.isclose(s.total_cost, 15.0 + 3.0, rel_tol=1e-6)
```

- [ ] **Step 2: Run test — verify fail**

Run: `pytest tests/test_aggregator.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Minimal implementation**

`lib/aggregator.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

from lib.parser import TurnUsage
from lib.pricing import compute_cost


@dataclass
class Summary:
    total_cost: float
    total_input_tokens: int
    total_output_tokens: int
    cache_hit_rate: float
    total_elapsed: float
    turns: list[TurnUsage] = field(default_factory=list)


def aggregate(turns: list[TurnUsage], elapsed: float) -> Summary:
    total_cost = sum(compute_cost(t.model, t) for t in turns)
    total_input = sum(t.input_tokens + t.cache_read_tokens for t in turns)
    total_output = sum(t.output_tokens for t in turns)
    cache_read = sum(t.cache_read_tokens for t in turns)
    cache_hit_rate = (cache_read / total_input) if total_input > 0 else 0.0

    return Summary(
        total_cost=total_cost,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        cache_hit_rate=cache_hit_rate,
        total_elapsed=elapsed,
        turns=list(turns),
    )
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_aggregator.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/aggregator.py tests/test_aggregator.py
git commit -m "feat(lib): aggregate turns into Summary with cost, cache hit rate, elapsed"
```

---

## Task 7: `lib/formatter.py` — i18n 한 줄 포맷

**Files:**
- Create: `token-tracker/lib/formatter.py`
- Create: `token-tracker/tests/test_formatter.py`

목적: `Summary` + language → 평범한 한 줄 텍스트. ko/en 지원. 숫자 단위 포맷팅 (천 단위 콤마, %).

출력 형식:
- ko: `비용 $0.0180 · 1,546 toks · cache 85% · 12.3s`
- en: `cost $0.0180 · 1,546 toks · cache 85% · 12.3s`

- [ ] **Step 1: Failing test 작성**

`tests/test_formatter.py`:

```python
from lib import formatter
from lib.aggregator import Summary


def _sum(**kw) -> Summary:
    base = dict(
        total_cost=0.018,
        total_input_tokens=1046,
        total_output_tokens=500,
        cache_hit_rate=0.85,
        total_elapsed=12.3,
        turns=[],
    )
    base.update(kw)
    return Summary(**base)


def test_ko_one_liner():
    s = _sum()
    out = formatter.format_summary(s, "ko")
    assert "비용 $0.0180" in out
    assert "1,546 toks" in out  # total = input + output
    assert "cache 85%" in out
    assert "12.3s" in out


def test_en_one_liner():
    s = _sum()
    out = formatter.format_summary(s, "en")
    assert out.startswith("cost $0.0180")
    assert "1,546 toks" in out


def test_unknown_language_falls_back_to_en():
    s = _sum()
    out = formatter.format_summary(s, "fr")
    assert out.startswith("cost $")


def test_zero_cost_and_cache():
    s = _sum(total_cost=0.0, cache_hit_rate=0.0, total_input_tokens=0, total_output_tokens=0)
    out = formatter.format_summary(s, "ko")
    assert "비용 $0.0000" in out
    assert "0 toks" in out
    assert "cache 0%" in out
```

- [ ] **Step 2: Run test — verify fail**

Run: `pytest tests/test_formatter.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Minimal implementation**

`lib/formatter.py`:

```python
from __future__ import annotations

from lib.aggregator import Summary


_MESSAGES = {
    "ko": {
        "summary": "비용 ${cost:.4f} · {tokens:,} toks · cache {cache}% · {elapsed:.1f}s",
    },
    "en": {
        "summary": "cost ${cost:.4f} · {tokens:,} toks · cache {cache}% · {elapsed:.1f}s",
    },
}


def _select_lang(lang: str) -> str:
    return lang if lang in _MESSAGES else "en"


def format_summary(summary: Summary, lang: str) -> str:
    total_tokens = summary.total_input_tokens + summary.total_output_tokens
    cache_pct = int(round(summary.cache_hit_rate * 100))
    tpl = _MESSAGES[_select_lang(lang)]["summary"]
    return tpl.format(
        cost=summary.total_cost,
        tokens=total_tokens,
        cache=cache_pct,
        elapsed=summary.total_elapsed,
    )
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/test_formatter.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add lib/formatter.py tests/test_formatter.py
git commit -m "feat(lib): format Summary into ko/en one-line text"
```

---

## Task 8: `hooks/on_user_prompt.py` — Offset 기록

**Files:**
- Create: `token-tracker/hooks/on_user_prompt.py`

목적: stdin JSON을 받아 `transcript_path`의 현재 byte 크기와 timestamp를 state에 기록. 실패해도 exit 0.

- [ ] **Step 1: stdin 처리 규약을 테스트로 못박기 — test 추가**

기존 `tests/test_state.py`에 hook 통합 경로를 간접 검증할 테스트는 Task 10(end-to-end)에서 수행. 이 태스크는 짧아서 TDD가 과함 → 구현 후 subprocess 기반 smoke check로 대체.

- [ ] **Step 2: 구현**

`hooks/on_user_prompt.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path


def _setup_sys_path() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        root = Path(env)
    else:
        root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    return root


def _log_error(msg: str) -> None:
    try:
        from lib.paths import log_dir
        log_file = log_dir() / "error.log"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def main() -> int:
    _setup_sys_path()
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
        session_id = hook_input.get("session_id")
        transcript_path = hook_input.get("transcript_path")
        if not session_id or not transcript_path:
            return 0

        from lib.state import save_state

        size = os.path.getsize(transcript_path) if os.path.exists(transcript_path) else 0
        save_state(
            session_id,
            {"offset": size, "started_at": time.time()},
        )
    except Exception:
        _log_error(f"[on_user_prompt] {traceback.format_exc()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Smoke-check 수동 실행**

```bash
cd /Users/i_brody/Desktop/harness/token-tracker
mkdir -p /tmp/tt-smoke
printf '{"type":"user"}\n' > /tmp/tt-smoke/session.jsonl
echo '{"session_id":"smoke-1","transcript_path":"/tmp/tt-smoke/session.jsonl","cwd":"/tmp","hook_event_name":"UserPromptSubmit"}' \
  | python3 hooks/on_user_prompt.py
echo "exit=$?"
cat ~/.claude/plugins/token-tracker/state/smoke-1.json
```

Expected:
- `exit=0`
- `state/smoke-1.json` 내용: `{"offset": 16, "started_at": <timestamp>}` (offset은 JSONL 파일 크기)

- [ ] **Step 4: Cleanup smoke artifacts (옵션)**

```bash
rm -f ~/.claude/plugins/token-tracker/state/smoke-1.json /tmp/tt-smoke/session.jsonl
```

- [ ] **Step 5: Commit**

```bash
git add hooks/on_user_prompt.py
git commit -m "feat(hooks): UserPromptSubmit hook records JSONL byte offset + start time"
```

---

## Task 9: `hooks/on_stop.py` — 집계 + systemMessage 출력

**Files:**
- Create: `token-tracker/hooks/on_stop.py`

목적: stdin JSON → state 로드 → transcript offset~EOF 파싱 → 집계 → i18n 한 줄 포맷 → stdout에 `{"systemMessage": "...", "continue": true}` JSON 출력. 실패 시 systemMessage는 최소한의 진단 메시지.

- [ ] **Step 1: 구현**

`hooks/on_stop.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import os
import sys
import time
import traceback
from pathlib import Path


def _setup_sys_path() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        root = Path(env)
    else:
        root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    return root


def _load_config(plugin_root: Path) -> dict:
    cfg_file = plugin_root / "config.json"
    if cfg_file.exists():
        try:
            return json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"language": "en", "verbose": False}


def _emit(system_message: str) -> None:
    json.dump(
        {"systemMessage": system_message, "continue": True}, sys.stdout
    )
    sys.stdout.flush()


def _log_error(msg: str) -> None:
    try:
        from lib.paths import log_dir
        log_file = log_dir() / "error.log"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


def _read_tail(transcript_path: str, offset: int) -> list[dict]:
    entries: list[dict] = []
    try:
        file_size = os.path.getsize(transcript_path)
        start = offset if 0 <= offset <= file_size else 0
        with open(transcript_path, "rb") as f:
            f.seek(start)
            data = f.read()
    except OSError:
        return []

    for raw in data.splitlines():
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def main() -> int:
    plugin_root = _setup_sys_path()
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
        session_id = hook_input.get("session_id")
        transcript_path = hook_input.get("transcript_path")
        if not session_id or not transcript_path:
            return 0

        from lib.state import load_state
        from lib.parser import parse_line
        from lib.aggregator import aggregate
        from lib.formatter import format_summary

        state = load_state(session_id) or {}
        offset = int(state.get("offset", 0))
        started_at = float(state.get("started_at", time.time()))

        entries = _read_tail(transcript_path, offset)
        turns = [t for t in (parse_line(e) for e in entries) if t is not None]

        elapsed = max(0.0, time.time() - started_at)
        summary = aggregate(turns, elapsed=elapsed)

        cfg = _load_config(plugin_root)
        lang = cfg.get("language", "en")
        msg = format_summary(summary, lang)
        _emit(msg)
    except Exception:
        _log_error(f"[on_stop] {traceback.format_exc()}")
        try:
            _emit("[token-tracker] error — see ~/.claude/plugins/token-tracker/log/error.log")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-check 수동 실행**

```bash
cd /Users/i_brody/Desktop/harness/token-tracker

# 1. fake session JSONL 준비
cp tests/fixtures/sample_session.jsonl /tmp/tt-stop.jsonl

# 2. UserPromptSubmit 시뮬레이션 (offset=0 기록)
echo '{"session_id":"stop-smoke","transcript_path":"/tmp/tt-stop.jsonl","cwd":"/tmp","hook_event_name":"UserPromptSubmit"}' \
  | python3 hooks/on_user_prompt.py

# 3. on_stop 실행
echo '{"session_id":"stop-smoke","transcript_path":"/tmp/tt-stop.jsonl","cwd":"/tmp","hook_event_name":"Stop"}' \
  | python3 hooks/on_stop.py
```

Expected stdout: JSON like
```json
{"systemMessage": "비용 $0.0050 · 2,635 toks · cache 95% · 0.0s", "continue": true}
```
(정확한 값은 fixture + 가격표 × elapsed에 따라 달라짐. `비용 $`, `toks`, `cache `, `s` 모두 포함되어야 함.)

- [ ] **Step 3: Cleanup**

```bash
rm -f /tmp/tt-stop.jsonl ~/.claude/plugins/token-tracker/state/stop-smoke.json
```

- [ ] **Step 4: Commit**

```bash
git add hooks/on_stop.py
git commit -m "feat(hooks): Stop hook aggregates request turns and emits systemMessage"
```

---

## Task 10: End-to-end 통합 테스트

**Files:**
- Create: `token-tracker/tests/test_hook_end_to_end.py`

목적: subprocess로 실제 hook 스크립트 2개를 연쇄 호출해 stdout JSON이 올바른 형태로 나오는지 검증.

- [ ] **Step 1: Failing test 작성**

`tests/test_hook_end_to_end.py`:

```python
import json
import os
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
FIXTURE = REPO / "tests" / "fixtures" / "sample_session.jsonl"


def _run(script: str, payload: dict, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO / "hooks" / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )


def test_full_cycle(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"
    session_path.write_bytes(FIXTURE.read_bytes())

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)

    payload = {
        "session_id": "e2e-1",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
    }
    r1 = _run("on_user_prompt.py", payload, env)
    assert r1.returncode == 0, r1.stderr

    payload["hook_event_name"] = "Stop"
    r2 = _run("on_stop.py", payload, env)
    assert r2.returncode == 0, r2.stderr

    out = json.loads(r2.stdout)
    assert out.get("continue") is True
    msg = out.get("systemMessage", "")
    assert "toks" in msg
    assert "cache" in msg


def test_missing_state_still_succeeds(tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    session_path = tmp_path / "session.jsonl"
    session_path.write_bytes(FIXTURE.read_bytes())

    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO)

    payload = {
        "session_id": "no-state",
        "transcript_path": str(session_path),
        "cwd": str(tmp_path),
        "hook_event_name": "Stop",
    }
    r = _run("on_stop.py", payload, env)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out.get("continue") is True
```

- [ ] **Step 2: Run test — verify pass**

Run: `pytest tests/test_hook_end_to_end.py -v`
Expected: 2 passed.

(만약 실패하면: stderr를 찍어 원인 파악. `sys.path` 문제라면 Task 8/9의 `_setup_sys_path` 재점검.)

- [ ] **Step 3: 전체 테스트 스위트 통과 확인**

Run: `pytest -v`
Expected: 모든 테스트 통과 (Task 2~7 + Task 10 합계 ~25개).

- [ ] **Step 4: Commit**

```bash
git add tests/test_hook_end_to_end.py
git commit -m "test: end-to-end subprocess test for UserPromptSubmit→Stop cycle"
```

---

## Task 11: 로컬 설치 & 수동 인수 검증 (MVP 완료 기준)

**Files:**
- Modify: `~/.claude/settings.json` (plugin 등록) — Claude Code 표준 경로

목적: 실제 Claude Code 세션에서 플러그인이 로드되어 매 Stop에 한 줄이 뜨는지 확인.

- [ ] **Step 1: Claude Code plugin 로드 방식 확인**

공식 문서 `code.claude.com/docs/en/plugins` 참고. 보통은 `~/.claude/plugins/token-tracker/`로 symlink하거나 marketplace 설정에 등록.

로컬 개발용 symlink 예:

```bash
mkdir -p ~/.claude/plugins
ln -sfn /Users/i_brody/Desktop/harness/token-tracker ~/.claude/plugins/token-tracker
ls -la ~/.claude/plugins/token-tracker
```

Expected: symlink가 repo로 연결.

- [ ] **Step 2: Claude Code 재시작 또는 설정 reload**

사용자가 Claude Code 세션을 새로 시작.

- [ ] **Step 3: Hook 등록 확인**

Claude Code 세션 안에서:

```
/hooks
```

Expected output에 `UserPromptSubmit`과 `Stop` 엔트리로 `token-tracker`의 Python 명령이 보여야 함.

- [ ] **Step 4: 가벼운 프롬프트 실행 & 한 줄 요약 관찰**

프롬프트: `안녕`
Expected: 응답 아래 (systemMessage로) `비용 $0.xxxx · xxx toks · cache xx% · x.xs` 형태의 한 줄.

- [ ] **Step 5: 툴 여러 개 쓰는 프롬프트로 다시 확인**

프롬프트: `현재 디렉터리 파일 목록 보여줘` (또는 실제 Read/Grep 유도할만한 요청)
Expected: 더 큰 토큰수·비용이 한 줄에 반영.

- [ ] **Step 6: 캐시 적중 확인**

같은 세션에서 2번째, 3번째 턴 실행.
Expected: `cache XX%` 값이 0에서 점점 올라감 (cache hit rate 상승).

- [ ] **Step 7: 진단 로그 비어있는지 확인**

```bash
cat ~/.claude/plugins/token-tracker/log/error.log 2>/dev/null || echo "(no errors)"
```

Expected: 파일 없거나 빈 파일. 에러가 있으면 원인 분석 후 해당 Task로 복귀.

- [ ] **Step 8: MVP 인수 기준 통과 확인**

다음을 수동으로 모두 체크:
- [x] 매 Stop에 한 줄 요약이 표시됨
- [x] 비용/토큰/캐시적중률/소요시간 4개 필드가 모두 채워짐
- [x] 캐시 hit/miss 케이스 모두 동작
- [x] 3턴 이상 연속 대화에서 안정적으로 동작
- [x] error.log가 비어있음

- [ ] **Step 9: Commit**

변경된 코드는 없지만, 검증 완료 마커로 tag를 남김.

```bash
cd /Users/i_brody/Desktop/harness/token-tracker
git tag -a v0.1.0-mvp -m "Phase 1 MVP: Stop hook one-liner verified"
git log --oneline -10
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ 2.결정 사항 모두 구현 (Task 1~9)
- ✅ 3.Phase 1 범위 한정 (Phase 2/3는 별도 계획)
- ✅ 4.아키텍처 (Task 1: plugin.json, hooks.json, config.json)
- ✅ 5.데이터 흐름 (Task 8+9)
- ✅ 6.모듈별 책임 (Task 2~7)
- ✅ 7.에러 처리 (각 hook의 최상위 try/except, 미등록 모델 0.0, 손상 state None 반환)
- ✅ 8.테스트 전략 (unit Task 2~7, integration Task 10, 수동 Task 11)
- ✅ 10.엣지케이스 (offset>size fallback in `_read_tail`, state 없음 fallback, `CLAUDE_PLUGIN_ROOT` fallback, JSON 파싱 실패 skip, 미등록 모델 0)

**Placeholder scan:**
- TBD/TODO 없음
- 모든 step에 실제 코드/명령/기대값 명시
- "similar to" 반복 없음

**Type consistency:**
- `TurnUsage` 필드명 parser.py ↔ aggregator.py ↔ pricing.py ↔ formatter.py 전반 일치
- `Summary` 필드명 aggregator.py ↔ formatter.py ↔ end-to-end test 일치
- 함수 이름 `save_state`/`load_state`/`parse_line`/`compute_cost`/`aggregate`/`format_summary` 모든 참조 일치
- env 변수 `CLAUDE_PLUGIN_ROOT` 대소문자 일치
- 설정 키 `language` 일치
