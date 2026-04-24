# v0.5.0 Code Review MAJOR Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** v0.5.0 병렬 코드리뷰에서 의도적으로 보류된 MAJOR 3건(config 추상화 / `$ARGUMENTS` injection 방어 / 쓰기 실패 UX)을 3개 독립 PR로 회수한다.

**Architecture:** 3개 PR을 순차 진행. PR1이 공통 기반(`lib/config.py`)을 먼저 깔고, PR2/PR3가 그 위에서 `verbose_toggle.py`를 좁게 수정한다. 각 PR은 독립적으로 테스트 통과 + 리뷰 게이트를 거친다.

**Tech Stack:** Python 3.10+ stdlib only, pytest, Claude Code plugin/skill system.

**Reference:** `docs/handoff/2026-04-22-token-tracker-next-steps.md` 섹션 5-E.

---

## 작업 원칙

- **테스트 실행**: repo 루트에서 `./venv/bin/pytest plugins/token-tracker/tests -q`.
- **커밋**: Conventional Commits, 한국어 본문. 각 Task 말미 또는 PR 종료 직전에 커밋.
- **TDD**: 테스트 먼저 작성 → 실패 확인 → 구현 → 통과 확인.
- **브랜치**: PR마다 feature 브랜치 신규 생성. `git checkout main && git checkout -b feature/...`. 이 repo는 **GitHub remote가 없음** (로컬 전용). `git push` / `gh pr create`는 실행하지 않는다 — 나중에 사용자가 GitHub repo 셋업 시 일괄 push 예정.
- **리뷰 승인 게이트**: 커밋 + 병렬 코드리뷰까지만 자동. 로컬 `main`으로의 `--no-ff` 머지는 사용자 명시 승인 후. 다음 PR은 이전 PR의 로컬 머지 후 착수. `--no-ff`로 PR 단위 히스토리를 merge commit에 보존한다.

---

## File Structure

**PR1 신규 파일:**
- `plugins/token-tracker/lib/config.py` — 공통 config API (load / update / is_verbose / get_language)
- `plugins/token-tracker/tests/test_config.py` — config.py 단위 테스트

**PR1 수정 파일:**
- `plugins/token-tracker/hooks/on_stop.py:22-29, 118-132` — `_load_config` 삭제, env 판정 로직 삭제 → `lib.config` 사용
- `plugins/token-tracker/skills/token-detail/scripts/detail.py:22-29` — `_load_language` 삭제 → `lib.config` 사용
- `plugins/token-tracker/skills/token-verbose/scripts/verbose_toggle.py:22-38` — `_load_config`/`_write_config` 삭제 → `lib.config.update_config` 사용

**PR2 수정 파일:**
- `plugins/token-tracker/skills/token-verbose/SKILL.md:8` — `"$ARGUMENTS"` argv → env var 경유로 변경
- `plugins/token-tracker/skills/token-verbose/scripts/verbose_toggle.py:41-51, 62-110` — argv 대신 `os.environ["TOKEN_VERBOSE_ARG"]` 읽기
- `plugins/token-tracker/tests/test_verbose_toggle_script.py:49-55` — subprocess env에 `TOKEN_VERBOSE_ARG` 주입
- `plugins/token-tracker/tests/test_verbose_integration.py` — 같은 이유로 env 주입 반영

**PR3 수정 파일:**
- `plugins/token-tracker/lib/i18n/ko.json`, `en.json` — `verbose_error_io` 키 추가
- `plugins/token-tracker/skills/token-verbose/scripts/verbose_toggle.py:62-110` — `OSError` / `PermissionError` 분리 → exit 1
- `plugins/token-tracker/tests/test_verbose_toggle_script.py` — read-only config 테스트 추가

---

# PR1 — `lib/config.py` 공통 API + 3개 호출처 리팩토링

**브랜치:** `feature/sprint5-pr1-config-abstraction`

**목표:** config.json을 건드리는 3개 파일이 각자 read(-modify-write)하는 중복을 `lib/config.py` 하나로 통합한다. atomic 쓰기와 env whitelist 폴백 로직도 여기에 집중시켜 last-writer-wins 리스크와 향후 필드 추가 시 유실 위험을 제거한다.

**공개 API (확정):**
```python
# lib/config.py
DEFAULTS = {"language": "en", "verbose": False}

def load_config(plugin_root: Path) -> dict: ...
    # 파일 없음/손상 시 DEFAULTS 복사본 반환. 기존 키는 덮어쓰지 않음.

def update_config(plugin_root: Path, patch: dict) -> dict: ...
    # load → merge(patch) → atomic write (tmp + os.replace). 병합 결과 반환.

def get_language(cfg: dict) -> str: ...
    # cfg.get("language", "en")

def is_verbose(cfg: dict, env_value: str | None) -> bool: ...
    # env_value whitelist: 1/true/yes/on → True, 0/false/no/off → False,
    # 그 외(None, 빈 문자열, 기타) → cfg.get("verbose", False).
```

---

## Task 1.1: `lib/config.py` 단위 테스트 작성 (TDD — Red)

**Files:**
- Create: `plugins/token-tracker/tests/test_config.py`

- [ ] **Step 1: test_config.py 작성**

```python
"""Unit tests for lib/config.py — the single owner of config.json access."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lib.config import (
    DEFAULTS,
    get_language,
    is_verbose,
    load_config,
    update_config,
)


@pytest.fixture
def plugin_root(tmp_path: Path) -> Path:
    return tmp_path


def _write(plugin_root: Path, cfg: dict) -> None:
    (plugin_root / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read(plugin_root: Path) -> dict:
    return json.loads((plugin_root / "config.json").read_text(encoding="utf-8"))


class TestLoadConfig:
    def test_returns_defaults_when_file_missing(self, plugin_root: Path):
        assert load_config(plugin_root) == DEFAULTS

    def test_returns_file_content_when_valid(self, plugin_root: Path):
        _write(plugin_root, {"language": "ko", "verbose": True})
        assert load_config(plugin_root) == {"language": "ko", "verbose": True}

    def test_returns_defaults_when_file_corrupted(self, plugin_root: Path):
        (plugin_root / "config.json").write_text("{not json", encoding="utf-8")
        assert load_config(plugin_root) == DEFAULTS

    def test_preserves_unknown_keys(self, plugin_root: Path):
        _write(plugin_root, {"language": "ko", "verbose": False, "extra": 42})
        assert load_config(plugin_root)["extra"] == 42

    def test_returns_copy_not_shared_defaults(self, plugin_root: Path):
        cfg = load_config(plugin_root)
        cfg["language"] = "zz"
        assert DEFAULTS["language"] == "en"  # DEFAULTS must not mutate


class TestUpdateConfig:
    def test_creates_file_when_missing(self, plugin_root: Path):
        update_config(plugin_root, {"verbose": True})
        assert (plugin_root / "config.json").exists()
        assert _read(plugin_root)["verbose"] is True

    def test_merges_patch_into_existing(self, plugin_root: Path):
        _write(plugin_root, {"language": "ko", "verbose": False, "extra": 42})
        update_config(plugin_root, {"verbose": True})
        cfg = _read(plugin_root)
        assert cfg == {"language": "ko", "verbose": True, "extra": 42}

    def test_atomic_write_uses_tmp_then_replace(
        self, plugin_root: Path, monkeypatch: pytest.MonkeyPatch
    ):
        _write(plugin_root, {"language": "ko", "verbose": False})
        seen_tmp: list[Path] = []
        real_replace = os.replace

        def spy_replace(src, dst):
            seen_tmp.append(Path(src))
            return real_replace(src, dst)

        monkeypatch.setattr("lib.config.os.replace", spy_replace)
        update_config(plugin_root, {"verbose": True})
        assert seen_tmp, "os.replace must be used for atomic write"
        assert seen_tmp[0].name.endswith(".tmp")

    def test_returns_merged_dict(self, plugin_root: Path):
        _write(plugin_root, {"language": "ko", "verbose": False})
        result = update_config(plugin_root, {"verbose": True})
        assert result == {"language": "ko", "verbose": True}

    def test_write_failure_propagates(self, plugin_root: Path):
        # Read-only directory → write must raise OSError (callers handle UX).
        plugin_root.chmod(0o500)
        try:
            with pytest.raises(OSError):
                update_config(plugin_root, {"verbose": True})
        finally:
            plugin_root.chmod(0o700)


class TestGetLanguage:
    def test_returns_language_when_present(self):
        assert get_language({"language": "ko"}) == "ko"

    def test_returns_en_when_missing(self):
        assert get_language({}) == "en"


class TestIsVerbose:
    @pytest.mark.parametrize("env", ["1", "true", "yes", "on", "TRUE", "On"])
    def test_env_truthy_overrides_cfg(self, env: str):
        assert is_verbose({"verbose": False}, env) is True

    @pytest.mark.parametrize("env", ["0", "false", "no", "off", "FALSE", "Off"])
    def test_env_falsy_overrides_cfg(self, env: str):
        assert is_verbose({"verbose": True}, env) is False

    @pytest.mark.parametrize("env", [None, "", "invalid", "maybe"])
    def test_env_non_whitelist_falls_back_to_cfg(self, env: str | None):
        assert is_verbose({"verbose": True}, env) is True
        assert is_verbose({"verbose": False}, env) is False

    def test_cfg_missing_verbose_defaults_false(self):
        assert is_verbose({}, None) is False
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_config.py -q`
Expected: ImportError / ModuleNotFoundError — `lib.config` 없음.

---

## Task 1.2: `lib/config.py` 구현 (TDD — Green)

**Files:**
- Create: `plugins/token-tracker/lib/config.py`

- [ ] **Step 1: config.py 구현**

```python
"""Single owner of token-tracker config.json.

All reads and read-modify-write updates go through this module so we don't
clobber fields across concurrent writers (hook + toggle skills).
"""
from __future__ import annotations

import json
import os
from pathlib import Path


DEFAULTS: dict = {"language": "en", "verbose": False}

_ENV_TRUE = {"1", "true", "yes", "on"}
_ENV_FALSE = {"0", "false", "no", "off"}


def _config_path(plugin_root: Path) -> Path:
    return plugin_root / "config.json"


def load_config(plugin_root: Path) -> dict:
    path = _config_path(plugin_root)
    if not path.exists():
        return dict(DEFAULTS)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)


def update_config(plugin_root: Path, patch: dict) -> dict:
    """Read current config, merge `patch`, write atomically. Returns merged dict.

    Raises OSError on write failure (callers handle UX).
    """
    merged = load_config(plugin_root)
    merged.update(patch)
    path = _config_path(plugin_root)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)
    return merged


def get_language(cfg: dict) -> str:
    return cfg.get("language", DEFAULTS["language"])


def is_verbose(cfg: dict, env_value: str | None) -> bool:
    if env_value is not None:
        norm = env_value.strip().lower()
        if norm in _ENV_TRUE:
            return True
        if norm in _ENV_FALSE:
            return False
    return bool(cfg.get("verbose", DEFAULTS["verbose"]))
```

- [ ] **Step 2: 테스트 통과 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_config.py -q`
Expected: `15 passed` (정확한 수는 parametrize로 다소 다를 수 있음 — 모두 통과).

---

## Task 1.3: `hooks/on_stop.py` 리팩토링

**Files:**
- Modify: `plugins/token-tracker/hooks/on_stop.py`

- [ ] **Step 1: `_load_config` 제거, env 판정 로직 제거, `lib.config` 사용**

`plugins/token-tracker/hooks/on_stop.py`의 다음 두 블록을 교체한다.

**삭제할 블록 1** (line 22-29):
```python
def _load_config(plugin_root: Path) -> dict:
    cfg_file = plugin_root / "config.json"
    if cfg_file.exists():
        try:
            return json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"language": "en", "verbose": False}
```
→ 통째로 삭제.

**교체할 블록 2** (line 118-135, `cfg = _load_config(...)` 부터 `format_detail` 호출까지):
```python
        cfg = _load_config(plugin_root)
        lang = cfg.get("language", "en")
        msg = format_summary(summary, lang)

        # verbose: env가 whitelist 값이면 env가 config을 override. whitelist 외 값
        # (빈 문자열, "invalid" 등)은 env 무시하고 config 사용 — 오타로 설정이 덮여
        # 꺼지는 회귀 방지.
        env_v = os.environ.get("TOKEN_TRACKER_VERBOSE")
        env_norm = env_v.strip().lower() if env_v is not None else None
        if env_norm in ("1", "true", "yes", "on"):
            verbose = True
        elif env_norm in ("0", "false", "no", "off"):
            verbose = False
        else:
            verbose = bool(cfg.get("verbose", False))
        if verbose and summary.turns:
            from lib.detail_formatter import format_detail
            msg = msg + "\n" + format_detail(summary, lang)
```
→ 다음으로 교체:
```python
        from lib.config import load_config, get_language, is_verbose

        cfg = load_config(plugin_root)
        lang = get_language(cfg)
        msg = format_summary(summary, lang)

        if is_verbose(cfg, os.environ.get("TOKEN_TRACKER_VERBOSE")) and summary.turns:
            from lib.detail_formatter import format_detail
            msg = msg + "\n" + format_detail(summary, lang)
```

- [ ] **Step 2: hook 전체 테스트 통과 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_hook_end_to_end.py plugins/token-tracker/tests/test_verbose_integration.py -q`
Expected: 기존 테스트 모두 통과 (동작 동일, 내부 경로만 이동).

---

## Task 1.4: `skills/token-detail/scripts/detail.py` 리팩토링

**Files:**
- Modify: `plugins/token-tracker/skills/token-detail/scripts/detail.py`

- [ ] **Step 1: `_load_language` 제거, `lib.config.load_config`+`get_language` 사용**

**삭제할 블록** (line 22-29):
```python
def _load_language(plugin_root: Path) -> str:
    cfg = plugin_root / "config.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text(encoding="utf-8")).get("language", "en")
        except Exception:
            pass
    return "en"
```
→ 삭제.

**교체할 블록** (line 49): `lang = _load_language(plugin_root)` →
```python
        from lib.config import load_config, get_language
        lang = get_language(load_config(plugin_root))
```
(import는 try 블록 안 함수 호출 직전에 배치 — 기존 import 패턴 유지. `_log_error`가 쓰는 `lib.paths` import와 동일 스타일.)

- [ ] **Step 2: detail 전체 테스트 통과 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_detail_script_e2e.py -q`
Expected: 모두 통과.

---

## Task 1.5: `skills/token-verbose/scripts/verbose_toggle.py` 리팩토링

**Files:**
- Modify: `plugins/token-tracker/skills/token-verbose/scripts/verbose_toggle.py`

- [ ] **Step 1: `_load_config`/`_write_config` 제거, `lib.config` 사용**

**삭제할 블록** (line 22-38):
```python
def _load_config(cfg_file: Path) -> dict:
    if cfg_file.exists():
        try:
            return json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_config(cfg_file: Path, cfg: dict) -> None:
    """Atomic write — write to a sibling tmp file then os.replace.
    Guarantees the reader (on_stop hook) never sees a partial / truncated file.
    """
    payload = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"
    tmp = cfg_file.with_suffix(cfg_file.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, cfg_file)
```
→ 삭제.

**`main` 교체** (line 62-110) — 기존 argv 파싱/상태 전환 로직은 유지하되 config 접근만 `lib.config` 경유:
```python
def main(argv: list[str]) -> int:
    plugin_root = _setup_sys_path()

    try:
        from lib.config import load_config, update_config, get_language
        from lib.i18n_loader import load_strings

        cfg = load_config(plugin_root)
        lang = get_language(cfg)
        strings = load_strings(lang)

        arg = _parse_arg(argv)

        if arg == "unknown":
            print(strings["verbose_usage"])
            return 0

        current = bool(cfg.get("verbose", False))
        on_label = strings["verbose_on"]
        off_label = strings["verbose_off"]
        current_label = on_label if current else off_label

        if arg == "":
            print(strings["verbose_status"].format(state=current_label))
            return 0

        new_value = (arg == "on")
        if new_value == current:
            print(strings["verbose_no_change"].format(state=current_label))
            return 0

        update_config(plugin_root, {"verbose": new_value})

        new_label = on_label if new_value else off_label
        print(strings["verbose_changed"].format(
            from_state=current_label, to_state=new_label
        ))
        return 0
    except Exception:
        tb = traceback.format_exc()
        _log_error(f"[verbose_toggle.py] {tb}")
        print(tb, file=sys.stderr)
        try:
            from lib.i18n_loader import load_strings
            print(load_strings("en")["verbose_error"])
        except Exception:
            print("verbose toggle: unexpected error")
        return 0
```

(주의: `cfg_file = plugin_root / "config.json"` 로컬 변수도 이제 안 쓰이므로 삭제. 상단에 남아 있으면 지운다.)

- [ ] **Step 2: verbose toggle 전체 테스트 통과 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_verbose_toggle_script.py plugins/token-tracker/tests/test_verbose_integration.py -q`
Expected: 모두 통과.

---

## Task 1.6: 전체 테스트 + 병렬 코드리뷰 + PR1 생성

- [ ] **Step 1: 전체 테스트 실행**

Run: `./venv/bin/pytest plugins/token-tracker/tests -q`
Expected: `119 passed` 부근 (기존 104 + config 테스트 15건 추가).

- [ ] **Step 2: 7개 에이전트 병렬 코드리뷰**

`rules/code-review.md` 프로세스 적용. CRITICAL 0건 확인 후 다음 단계.

- [ ] **Step 3: feature 브랜치 생성 + 커밋 (로컬 only)**

```bash
git checkout -b feature/sprint5-pr1-config-abstraction
git add plugins/token-tracker/lib/config.py \
  plugins/token-tracker/tests/test_config.py \
  plugins/token-tracker/hooks/on_stop.py \
  plugins/token-tracker/skills/token-detail/scripts/detail.py \
  plugins/token-tracker/skills/token-verbose/scripts/verbose_toggle.py
git commit -m "$(cat <<'EOF'
refactor(config): lib/config.py로 config.json 접근 일원화

v0.5.0 리뷰 MAJOR E-1 회수. hooks/on_stop.py, skills/token-detail/
scripts/detail.py, skills/token-verbose/scripts/verbose_toggle.py 세
곳에 흩어져 있던 read / write / env-verbose 판정 로직을 lib/config.py
단일 모듈로 통합한다. update_config는 atomic tmp+os.replace로 읽는
쪽(on_stop hook)이 부분 기록을 보지 못하게 보장한다. DEFAULTS 단일
정의로 필드 유실 리스크 제거.
EOF
)"
```

- [ ] **Step 4: 사용자에게 리뷰 리포트 + 브랜치 상태 보고 후 로컬 머지 승인 대기**

- [ ] **Step 5: 승인 후 로컬 `main`에 `--no-ff` 머지 (사용자가 "머지해"라고 명시한 후에만)**

```bash
git checkout main
git merge --no-ff feature/sprint5-pr1-config-abstraction -m "Merge: PR1 config abstraction"
git branch -d feature/sprint5-pr1-config-abstraction
```

---

# PR2 — `$ARGUMENTS` command injection 방어

**브랜치:** `feature/sprint5-pr2-arguments-env-passthrough`

**목표:** `SKILL.md`의 `!`python3 ... "$ARGUMENTS"`` 패턴에서 bash가 `$ARGUMENTS` 안의 `$(...)` / 백틱 / 큰따옴표를 재해석할 가능성을 제거한다. 공식 문서에 argv 경유가 안전하다고 명시되지 않은 이상, 환경변수 경유가 bash word splitting/파라미터 확장 경계 밖이라 명백히 안전하다.

**배경:** PR1 머지 후 시작 (순서 의존 없음. 독립적이지만 PR 큐를 지킨다).

---

## Task 2.1: 테스트 갱신 (TDD — Red)

**Files:**
- Modify: `plugins/token-tracker/tests/test_verbose_toggle_script.py`

- [ ] **Step 1: `_run` 헬퍼가 env로 arg 전달하도록 변경**

**교체할 블록** (line 49-55):
```python
def _run(root: Path, arg: str | None) -> subprocess.CompletedProcess:
    script = root / SCRIPT_RELATIVE
    argv = [sys.executable, str(script)]
    if arg is not None:
        argv.append(arg)
    env = {"CLAUDE_PLUGIN_ROOT": str(root), "PATH": ""}
    return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=5)
```
→
```python
def _run(root: Path, arg: str | None) -> subprocess.CompletedProcess:
    script = root / SCRIPT_RELATIVE
    argv = [sys.executable, str(script)]
    env = {"CLAUDE_PLUGIN_ROOT": str(root), "PATH": ""}
    if arg is not None:
        env["TOKEN_VERBOSE_ARG"] = arg
    return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=5)
```

- [ ] **Step 2: 새 injection-safety 테스트 추가**

파일 말미에 추가:
```python
def test_arg_with_shell_metacharacters_is_literal(tmp_plugin_root: Path):
    """$ARGUMENTS-origin values must not be re-evaluated by the script."""
    _write_config(tmp_plugin_root, {"language": "en", "verbose": False})
    # Evil-looking payloads — script must see them as literal strings.
    for payload in ("$(rm -rf /)", "`whoami`", "on; echo pwned", '"; cat /etc/passwd; "'):
        r = _run(tmp_plugin_root, payload)
        assert r.returncode == 0, f"payload={payload!r} crashed: {r.stderr}"
        # Any non-canonical token falls to the "usage" branch, not mutation.
        assert _read_config(tmp_plugin_root)["verbose"] is False, \
            f"payload={payload!r} mutated config"
```

- [ ] **Step 3: test_verbose_integration.py의 `_run` 헬퍼도 같은 방식으로 변경**

`plugins/token-tracker/tests/test_verbose_integration.py`를 열어 subprocess argv에 arg를 붙이는 모든 곳을 env `TOKEN_VERBOSE_ARG`로 통일 (정확한 위치는 파일을 읽어 확인).

- [ ] **Step 4: 테스트 실행 — 실패 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_verbose_toggle_script.py plugins/token-tracker/tests/test_verbose_integration.py -q`
Expected: arg가 env로 가는데 script는 아직 argv를 본다 → 상당수 테스트 실패 ("sys.argv[1]" 기대 vs env 기반).

---

## Task 2.2: `verbose_toggle.py` env 경유로 변경 (Green)

**Files:**
- Modify: `plugins/token-tracker/skills/token-verbose/scripts/verbose_toggle.py`

- [ ] **Step 1: `_parse_arg`를 env 기반으로 변경 + main signature 정리**

**교체할 블록** (line 41-51):
```python
def _parse_arg(argv: list[str]) -> str | None:
    """Return 'on' / 'off' / '' (status query) / 'unknown'."""
    raw = argv[1] if len(argv) > 1 else ""
    val = raw.strip().lower()
    if val == "":
        return ""
    if val in ("on", "1", "true", "yes"):
        return "on"
    if val in ("off", "0", "false", "no"):
        return "off"
    return "unknown"
```
→
```python
def _parse_arg(raw: str) -> str:
    """Return 'on' / 'off' / '' (status query) / 'unknown'."""
    val = raw.strip().lower()
    if val == "":
        return ""
    if val in ("on", "1", "true", "yes"):
        return "on"
    if val in ("off", "0", "false", "no"):
        return "off"
    return "unknown"
```

**`main` signature + 호출부 변경** (line 62 + line 73 + line 114):
- `def main(argv: list[str]) -> int:` → `def main() -> int:`
- `arg = _parse_arg(argv)` → `arg = _parse_arg(os.environ.get("TOKEN_VERBOSE_ARG", ""))`
- 말미 `sys.exit(main(sys.argv))` → `sys.exit(main())`

- [ ] **Step 2: 테스트 통과 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_verbose_toggle_script.py plugins/token-tracker/tests/test_verbose_integration.py -q`
Expected: 기존 + 신규 injection 테스트 모두 통과.

---

## Task 2.3: `SKILL.md` 업데이트

**Files:**
- Modify: `plugins/token-tracker/skills/token-verbose/SKILL.md`

- [ ] **Step 1: bash 호출 변경**

**교체할 블록** (line 7-9):
```
<script-output>
!`python3 ${CLAUDE_SKILL_DIR}/scripts/verbose_toggle.py "$ARGUMENTS"`
</script-output>
```
→
```
<script-output>
!`TOKEN_VERBOSE_ARG="$ARGUMENTS" python3 ${CLAUDE_SKILL_DIR}/scripts/verbose_toggle.py`
</script-output>
```

(bash 문법: `VAR=value command` 형태는 해당 명령 실행 시에만 env 주입. `"$ARGUMENTS"`는 큰따옴표로 감싸 word splitting만 방지하되, 안쪽 `$(...)` / 백틱은 여전히 해석될 수 있음 — 하지만 이제 그 결과 문자열이 **script 인자가 아닌 env var 값**이 되므로 bash가 한 번만 확장하고 끝. 스크립트는 그 문자열을 그대로 읽는다. 공격자가 `$(rm -rf ~)`를 넣어도 bash가 그걸 실행한 결과(일반적으로 빈 문자열)가 env value로 들어올 뿐, 원본 문자열 그 자체는 아님.)

(**주의 사항:** 이 패턴은 command substitution (`$(...)`)을 막지는 **않는다** — `$ARGUMENTS`가 double-quoted 자리에 들어가므로 bash는 여전히 확장한다. 다만 결과가 argv로 흘러 "두 번째 bash 재실행"이 되는 경로가 끊긴다. 완전한 의미의 injection-free는 Claude Code가 `$ARGUMENTS`를 literal 치환하는지, aftershell 확장 여부에 달려 있다. 본 PR의 목표는 "argv에 넣었을 때의 double-evaluation 리스크 제거"이며, 공식 문서 보강은 D 작업 시 같이 확인.)

---

## Task 2.4: 전체 테스트 + 리뷰 + PR2 생성

- [ ] **Step 1: 전체 테스트**

Run: `./venv/bin/pytest plugins/token-tracker/tests -q`
Expected: 전부 통과 (카운트는 PR1 + 신규 injection 1건).

- [ ] **Step 2: 병렬 코드리뷰 — CRITICAL 0건 확인**

- [ ] **Step 3: feature 브랜치 생성 + 커밋 (로컬 only)**

> 전제: PR1이 이미 로컬 `main`에 `--no-ff` 머지돼 있어야 함. 머지 안 됐다면 중단.

```bash
git checkout main
git checkout -b feature/sprint5-pr2-arguments-env-passthrough
# (위 Task 2.1–2.3 변경 반영)
git add plugins/token-tracker/skills/token-verbose/SKILL.md \
  plugins/token-tracker/skills/token-verbose/scripts/verbose_toggle.py \
  plugins/token-tracker/tests/test_verbose_toggle_script.py \
  plugins/token-tracker/tests/test_verbose_integration.py
git commit -m "$(cat <<'EOF'
fix(skill): $ARGUMENTS를 argv 대신 env var로 전달

v0.5.0 리뷰 MAJOR E-2 회수. bash가 "$ARGUMENTS" 안의 $(...)/백틱을
재해석한 결과가 script argv에 흘러들면 "두 번째 확장" 경로가 생긴다.
SKILL.md를 TOKEN_VERBOSE_ARG env var 경유로 바꿔 script가 받는 값이
bash word boundary 밖에 있도록 한다. 스크립트는 os.environ에서 직접
읽는다. 테스트에 shell metacharacter payload를 literal로 다루는 케이스
추가.
EOF
)"
```

- [ ] **Step 4: 리뷰 리포트 보고 후 로컬 머지 승인 대기**

- [ ] **Step 5: 승인 후 로컬 `main`에 `--no-ff` 머지**

```bash
git checkout main
git merge --no-ff feature/sprint5-pr2-arguments-env-passthrough -m "Merge: PR2 arguments env passthrough"
git branch -d feature/sprint5-pr2-arguments-env-passthrough
```

---

# PR3 — 쓰기 실패 시 exit 1 + 원인 포함 메시지

**브랜치:** `feature/sprint5-pr3-verbose-write-failure-ux`

**목표:** `verbose_toggle.py`가 PermissionError / 디스크풀 등 I/O 실패 시 현재 exit 0 + 포괄 메시지로 "반영됐는지 불투명"한 문제를 고친다. I/O 실패는 exit 1 + 원인 포함 i18n 메시지로 명확히 알린다.

---

## Task 3.1: i18n 리소스에 `verbose_error_io` 추가

**Files:**
- Modify: `plugins/token-tracker/lib/i18n/ko.json`
- Modify: `plugins/token-tracker/lib/i18n/en.json`

- [ ] **Step 1: ko.json에 키 추가**

기존 `verbose_error` 다음 줄에 추가:
```json
  "verbose_error_io": "config.json 쓰기에 실패했습니다 ({reason}). 권한/디스크 공간을 확인하세요."
```

(마지막 키라면 직전 키에 콤마 유지 확인.)

- [ ] **Step 2: en.json에 키 추가**

```json
  "verbose_error_io": "Failed to write config.json ({reason}). Check permissions / disk space."
```

---

## Task 3.2: verbose_toggle.py — OSError 분리 (TDD — Red)

**Files:**
- Modify: `plugins/token-tracker/tests/test_verbose_toggle_script.py`

- [ ] **Step 1: 테스트 추가**

파일 말미에 추가:
```python
def test_readonly_config_returns_exit_1(tmp_plugin_root: Path):
    _write_config(tmp_plugin_root, {"language": "en", "verbose": False})
    (tmp_plugin_root / "config.json").chmod(0o400)
    try:
        r = _run(tmp_plugin_root, "on")
        assert r.returncode == 1, f"expected exit 1, got {r.returncode}"
        assert "permission" in r.stdout.lower() or "쓰기" in r.stdout \
            or "권한" in r.stdout or "disk space" in r.stdout.lower()
    finally:
        (tmp_plugin_root / "config.json").chmod(0o600)


def test_readonly_dir_returns_exit_1(tmp_plugin_root: Path):
    # No config.json; dir read-only → update_config.tmp write fails.
    tmp_plugin_root.chmod(0o500)
    try:
        r = _run(tmp_plugin_root, "on")
        assert r.returncode == 1
    finally:
        tmp_plugin_root.chmod(0o700)
```

- [ ] **Step 2: 실패 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_verbose_toggle_script.py::test_readonly_config_returns_exit_1 plugins/token-tracker/tests/test_verbose_toggle_script.py::test_readonly_dir_returns_exit_1 -q`
Expected: 현재 구현은 `except Exception: ... return 0`이라 exit 0 → 실패.

---

## Task 3.3: verbose_toggle.py — OSError 분리 (Green)

**Files:**
- Modify: `plugins/token-tracker/skills/token-verbose/scripts/verbose_toggle.py`

- [ ] **Step 1: `update_config` 호출 구간을 분리해 OSError는 exit 1**

PR2 후 기준 `main()`의 `update_config(plugin_root, {"verbose": new_value})` 라인을 다음으로 교체:
```python
        try:
            update_config(plugin_root, {"verbose": new_value})
        except OSError as e:
            _log_error(f"[verbose_toggle.py] write failed: {e}")
            print(strings["verbose_error_io"].format(reason=str(e)), file=sys.stderr)
            return 1
```

(`format(reason=str(e))`는 `[Errno 13] Permission denied: ...` 같은 표준 메시지를 포함해 사용자가 원인을 바로 알 수 있게 한다.)

- [ ] **Step 2: 테스트 전체 통과 확인**

Run: `./venv/bin/pytest plugins/token-tracker/tests/test_verbose_toggle_script.py -q`
Expected: 모두 통과 (신규 2건 포함).

---

## Task 3.4: 전체 테스트 + 리뷰 + PR3 생성 + v0.5.1 태그

- [ ] **Step 1: 전체 테스트**

Run: `./venv/bin/pytest plugins/token-tracker/tests -q`
Expected: 전부 통과.

- [ ] **Step 2: 병렬 코드리뷰 — CRITICAL 0건**

- [ ] **Step 3: feature 브랜치 생성 + 커밋 (로컬 only)**

> 전제: PR2까지 이미 로컬 `main`에 `--no-ff` 머지돼 있어야 함.

```bash
git checkout main
git checkout -b feature/sprint5-pr3-verbose-write-failure-ux
# (위 Task 3.1–3.3 변경 반영)
git add plugins/token-tracker/lib/i18n/ko.json \
  plugins/token-tracker/lib/i18n/en.json \
  plugins/token-tracker/skills/token-verbose/scripts/verbose_toggle.py \
  plugins/token-tracker/tests/test_verbose_toggle_script.py
git commit -m "$(cat <<'EOF'
fix(skill): verbose 토글 쓰기 실패 시 exit 1 + 원인 메시지

v0.5.0 리뷰 MAJOR E-3 회수. 기존에는 PermissionError / 디스크풀이
포괄 except Exception → exit 0 + "verbose_error"로 떨어져 사용자가
반영 여부를 알 수 없었다. OSError를 분리해 i18n verbose_error_io에
errno 원인을 끼워 exit 1로 알린다. read-only config / read-only
dir 두 케이스 테스트 추가.
EOF
)"
```

- [ ] **Step 4: 리뷰 리포트 보고 후 로컬 머지 승인 대기**

- [ ] **Step 5: 승인 후 로컬 `main`에 `--no-ff` 머지**

```bash
git checkout main
git merge --no-ff feature/sprint5-pr3-verbose-write-failure-ux -m "Merge: PR3 verbose write failure UX"
git branch -d feature/sprint5-pr3-verbose-write-failure-ux
```

- [ ] **Step 6: 3개 PR 모두 머지된 후 v0.5.1 태그 + 핸드오프 문서 업데이트 (사용자 확인 후)**

태그·핸드오프 업데이트는 3개 PR이 모두 로컬 머지된 후 사용자가 명시적으로 요청할 때 수행. plan 자체에서 자동 수행 금지. GitHub push도 이 시점 또는 이후 사용자가 직접 지시할 때만.

---

## Self-Review 체크

- [x] Spec 커버리지: E-1, E-2, E-3 각각 PR 하나씩 대응. MINOR(E-4)는 범위 밖으로 의식적으로 제외.
- [x] Placeholder 없음: 모든 코드 블록에 실제 코드, 모든 명령에 정확한 경로.
- [x] Type 일관성: `load_config(plugin_root: Path) -> dict`, `update_config(plugin_root, patch) -> dict` — PR1 정의와 PR2/PR3 사용 시그니처 일치.
- [x] PR 300줄 제한: PR1이 가장 큼 (lib/config.py ~70줄 + test ~120줄 = 190줄 프로덕션+테스트 기준, 리팩토링 diff 포함 시 ~250줄 예상). PR2, PR3는 <100줄.
- [x] 리뷰 게이트: 각 PR Task 말미에 병렬 코드리뷰 + 사용자 머지 승인 대기 명시.
