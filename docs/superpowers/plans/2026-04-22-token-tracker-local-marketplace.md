# token-tracker Local Marketplace Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현재 `.claude/settings.local.json` 직등록 방식을 Claude Code 정식 local marketplace로 전환. 어느 디렉터리에서 Claude Code를 띄워도 token-tracker plugin이 동작하게 만든다.

**Architecture:** 기존 repo 루트를 **self-contained marketplace + plugin**으로 쓴다. `.claude-plugin/marketplace.json`을 추가하고 `source: "."`로 자기 자신을 plugin으로 가리킨다. `.claude-plugin/plugin.json`과 `hooks/hooks.json`은 이미 존재하므로 재사용. 사용자는 `/plugin marketplace add <repo path>` 한 번으로 설치 완료.

**Tech Stack:** Claude Code plugin system (marketplace.json / plugin.json / hooks.json), Python 3.10+ stdlib.

---

## 현재 상태 확인 (읽기 전용)

- **이미 존재**: `.claude-plugin/plugin.json` (name=token-tracker, v0.1.0), `hooks/hooks.json` (`${CLAUDE_PLUGIN_ROOT}` 사용)
- **추가/교체 필요**: `.claude-plugin/marketplace.json`, README 설치 섹션, handoff 문서
- **제거 대상**: `.claude/settings.local.json` (Task 4 사용자 검증 이후)
- **작업 경로**: `/Users/brody/Desktop/token-tracker`

---

## Task 1: marketplace.json + plugin.json 업데이트 + 스키마 유효성 테스트

**Files:**
- Create: `.claude-plugin/marketplace.json`
- Modify: `.claude-plugin/plugin.json` (hooks 필드 추가)
- Create: `tests/test_marketplace_manifest.py`

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/test_marketplace_manifest.py`:

```python
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"


def test_marketplace_manifest_exists():
    assert MANIFEST.is_file(), f"marketplace.json missing at {MANIFEST}"


def test_marketplace_manifest_has_required_fields():
    data = json.loads(MANIFEST.read_text())
    assert data["name"] == "token-tracker-local"
    assert "owner" in data and "name" in data["owner"]
    assert isinstance(data["plugins"], list) and len(data["plugins"]) == 1


def test_marketplace_plugin_entry_points_to_self():
    data = json.loads(MANIFEST.read_text())
    entry = data["plugins"][0]
    assert entry["name"] == "token-tracker"
    assert entry["source"] == "."


def test_marketplace_plugin_version_matches_plugin_json():
    marketplace = json.loads(MANIFEST.read_text())
    plugin = json.loads(PLUGIN_MANIFEST.read_text())
    assert marketplace["plugins"][0]["version"] == plugin["version"], (
        "marketplace.json과 plugin.json의 version이 일치해야 한다"
    )


def test_plugin_manifest_declares_hooks_path():
    data = json.loads(PLUGIN_MANIFEST.read_text())
    assert data.get("hooks") == "./hooks/hooks.json", (
        "plugin.json이 hooks 파일 경로를 명시해야 Claude Code가 확실히 로드한다"
    )
    assert HOOKS_JSON.is_file(), f"hooks.json missing at {HOOKS_JSON}"
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `cd /Users/brody/Desktop/token-tracker && pytest tests/test_marketplace_manifest.py -v`
Expected: 5개 중 최소 `test_marketplace_manifest_exists` / `test_plugin_manifest_declares_hooks_path` FAIL.

- [ ] **Step 3: marketplace.json 생성**

Create `.claude-plugin/marketplace.json`:

```json
{
  "name": "token-tracker-local",
  "owner": {
    "name": "brody",
    "email": "ghbcw424@gmail.com"
  },
  "plugins": [
    {
      "name": "token-tracker",
      "source": ".",
      "description": "한 번의 프롬프트가 소비한 토큰·비용을 Stop hook 응답 블록에 한 줄로 표시",
      "version": "0.1.0"
    }
  ]
}
```

- [ ] **Step 4: plugin.json에 hooks 필드 추가**

Edit `.claude-plugin/plugin.json` — `"author"` 뒤에 `"hooks": "./hooks/hooks.json"` 추가:

```json
{
  "name": "token-tracker",
  "description": "한 번의 프롬프트가 소비한 토큰·비용을 Stop hook 응답 블록에 한 줄로 표시",
  "version": "0.1.0",
  "author": { "name": "brody" },
  "hooks": "./hooks/hooks.json"
}
```

- [ ] **Step 5: 테스트 실행 → 통과 확인**

Run: `cd /Users/brody/Desktop/token-tracker && pytest tests/test_marketplace_manifest.py -v`
Expected: 5 passed.

- [ ] **Step 6: 전체 테스트 회귀 확인**

Run: `cd /Users/brody/Desktop/token-tracker && pytest -q`
Expected: 기존 41건 + 신규 5건 = **46 passed**.

- [ ] **Step 7: 커밋**

```bash
cd /Users/brody/Desktop/token-tracker
git add .claude-plugin/marketplace.json .claude-plugin/plugin.json tests/test_marketplace_manifest.py
git commit -m "feat(plugin): add marketplace.json + declare hooks path for local marketplace

self-contained marketplace + plugin 구조. source \".\"로 repo 루트를 plugin으로
가리켜서 /plugin marketplace add <repo> 한 번으로 설치 가능하게 한다.
plugin.json에 hooks 필드를 명시해 Claude Code가 확실히 hooks/hooks.json을
로드하도록 한다."
```

---

## Task 2: README 설치 섹션 교체

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 현재 Install 섹션 확인**

Run: `grep -n "## Install" /Users/brody/Desktop/token-tracker/README.md`
Expected: `## Install (local dev)` 한 줄 발견.

- [ ] **Step 2: Install 섹션 교체**

README.md의 `## Install (local dev)` 섹션 전체를 아래로 교체한다:

```markdown
## Install (local marketplace)

이 repo 자체가 self-contained Claude Code marketplace입니다. Claude Code CLI에서 한 번만 등록하면 이후 어느 디렉터리에서 Claude Code를 실행해도 hook이 발화합니다.

```bash
# 1. marketplace 등록 (repo를 clone 한 경로를 가리킨다)
/plugin marketplace add /absolute/path/to/token-tracker

# 2. plugin 활성화
/plugin install token-tracker@token-tracker-local
```

활성화 후 Claude Code를 재시작하면 Stop hook이 응답마다 아래 같은 한 줄을 출력합니다:

```
비용 $0.0180 · 1,546 toks · cache 85% · 12.3s
```

비활성화: `/plugin disable token-tracker@token-tracker-local`
제거: `/plugin uninstall token-tracker@token-tracker-local`

### 개발 모드

repo를 수정하면서 바로 반영하려면 symlink 방식을 쓸 수 있습니다:

```bash
ln -s /Users/you/Desktop/token-tracker ~/.claude/marketplaces/token-tracker-local
```

그 외 `.claude/settings.local.json`에 hook을 직접 등록하는 이전 방식은 더 이상 사용하지 않습니다.
```

Edit command:

```python
# Edit tool old_string:
## Install (local dev)

Hooks are registered via `.claude/settings.local.json` in this repo. When Claude Code is launched from this directory (or a subdir), the hooks fire automatically.

For permanent install, see Phase 2 (local marketplace packaging) — not yet shipped.

# new_string: (위의 교체 블록 전체)
```

- [ ] **Step 3: 커밋**

```bash
cd /Users/brody/Desktop/token-tracker
git add README.md
git commit -m "docs(readme): replace local-dev install with marketplace workflow

/plugin marketplace add + /plugin install 두 줄로 설치 완료. 개발 중 바로
반영하려면 symlink도 가능함을 명시."
```

---

## Task 3: handoff 문서 업데이트 (후보 A 완료 표시)

**Files:**
- Modify: `docs/handoff/2026-04-22-token-tracker-next-steps.md`

- [ ] **Step 1: 섹션 5-A를 "완료" 상태로 표시**

`## 5. 확정된 다음 작업 후보` 아래 `### A. 로컬 marketplace 패키징` 항목 전체를 아래로 교체:

```markdown
### A. 로컬 marketplace 패키징 ✅ 완료 (2026-04-22)

- `.claude-plugin/marketplace.json` 추가 (self-contained, `source: "."`).
- `/plugin marketplace add <repo>` + `/plugin install token-tracker@token-tracker-local`로 설치.
- 기존 `.claude/settings.local.json` 제거됨 — repo 밖에서 Claude Code를 띄워도 hook 발화.
- 관련 테스트: `tests/test_marketplace_manifest.py` (4건).
```

- [ ] **Step 2: 다음 후보 순번 재정리**

섹션 5의 B/C/D 항목 번호는 유지하되, 상단 "### A" 앞에 다음 문장을 삽입:

```markdown
> **다음 세션 권장**: B부터 시작 (`/token-detail` skill).
```

- [ ] **Step 3: 커밋**

```bash
cd /Users/brody/Desktop/token-tracker
git add docs/handoff/2026-04-22-token-tracker-next-steps.md
git commit -m "docs(handoff): mark candidate A (marketplace packaging) complete

남은 후보는 B/C/D. 다음 세션은 /token-detail skill(B)부터 진행."
```

---

## Task 4: 실전 검증 (사용자 개입 필수)

이 task는 사용자가 직접 Claude Code에서 명령을 실행해야 한다. 에이전트는 명령만 안내하고, 결과를 사용자로부터 받아 해석한다.

**Files:**
- Delete: `.claude/settings.local.json` (Step 5 이후)
- Verify: `~/.claude/settings.json` 의 `extraKnownMarketplaces` / `enabledPlugins` 항목

- [ ] **Step 1: 사용자에게 marketplace 등록 요청**

사용자에게 다음을 Claude Code 채팅창에 그대로 입력하도록 요청한다:

```
/plugin marketplace add /Users/brody/Desktop/token-tracker
```

Expected: Claude Code가 `token-tracker-local` marketplace를 등록했다고 응답. plugin 1개 감지.

**실패 시 대응**: `source: "."` 자기참조를 거부하면 plan 맨 아래 "Fallback" 섹션 참고.

- [ ] **Step 2: 사용자에게 plugin 설치 요청**

```
/plugin install token-tracker@token-tracker-local
```

Expected: 설치 성공 + Claude Code 재시작 안내.

- [ ] **Step 3: Claude Code 재시작 요청 (사용자 작업)**

사용자가 Claude Code를 완전히 종료 후 재시작. **이때 repo 디렉터리가 아닌 다른 폴더**(예: `~/`)에서 실행하도록 안내한다. 이전 `.claude/settings.local.json`은 아직 그대로 두고 간섭 여부 확인.

- [ ] **Step 4: hook 발화 확인**

사용자가 새 세션에서 임의의 메시지(예: "안녕") 입력 → 응답 끝에 `비용 $... · ... toks · cache ...% · ...s` 라인이 나오는지 확인.

**두 줄이 나오면 중복**: repo 내부 `.claude/settings.local.json`과 marketplace가 동시에 발화하는 것. 다음 Step 5에서 해결.

- [ ] **Step 5: 기존 settings.local.json 제거**

Claude Code 세션을 종료하고 터미널에서:

```bash
rm /Users/brody/Desktop/token-tracker/.claude/settings.local.json
```

그 후 repo 안/밖 양쪽에서 재시작 → 여전히 한 줄만 나오는지 확인.

- [ ] **Step 6: settings.local.json 제거 기록 커밋**

`.claude/settings.local.json`은 이미 `.gitignore` 대상이므로 git diff에는 안 뜬다. 별도 커밋 불필요. `.claude/` 디렉터리가 비었다면 그대로 두어도 된다 (향후 프로젝트별 설정을 다시 넣을 수 있음).

- [ ] **Step 7: 검증 결과 사용자에게 보고**

보고 포맷 예시:
```
✅ marketplace 등록: token-tracker-local
✅ plugin 설치: token-tracker@token-tracker-local
✅ repo 밖(~/)에서 hook 발화 확인
✅ settings.local.json 제거 후에도 정상 동작
```

이 보고 받은 뒤에만 Task 5로 진행.

---

## Task 5: 최종 마무리 (태그 + 로그 기록)

**Files:**
- Read-only: `git log`, `git tag`

- [ ] **Step 1: 지금까지 커밋 확인**

```bash
cd /Users/brody/Desktop/token-tracker && git log --oneline -10
```

Expected: Task 1/2/3의 커밋 3건이 `v0.1.0-mvp` 이후에 추가됨.

- [ ] **Step 2: 버전 범프 제안 (사용자 결정)**

`plugin.json`과 `marketplace.json`의 version을 `0.1.0` → `0.2.0` 으로 올릴지 사용자에게 묻는다. Phase 2-A(marketplace 패키징)가 정식 출시 수준이면 minor bump 권장.

사용자가 승인하면:

Edit `.claude-plugin/plugin.json`: `"version": "0.1.0"` → `"version": "0.2.0"`

Edit `.claude-plugin/marketplace.json`: plugins[0].version `"0.1.0"` → `"0.2.0"`

Run: `pytest tests/test_marketplace_manifest.py::test_marketplace_plugin_version_matches_plugin_json -v`
Expected: PASS.

커밋:
```bash
git add .claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "chore(release): bump version to 0.2.0 for marketplace packaging"
git tag v0.2.0
```

- [ ] **Step 3: 전체 테스트 최종 실행**

```bash
cd /Users/brody/Desktop/token-tracker && pytest -q
```

Expected: 45 passed (또는 신규 테스트 포함 총 개수).

- [ ] **Step 4: 사용자에게 최종 보고**

보고 포맷:
```
완료:
- .claude-plugin/marketplace.json 추가
- README 설치 섹션 교체
- handoff 문서 후보 A 완료 표시
- settings.local.json 제거
- 45/45 테스트 통과
- v0.2.0 태그 (optional)

다음 후보: B (/token-detail skill)
```

---

## Fallback: `source: "."` 자기참조가 실패할 경우

Task 4 Step 1에서 Claude Code가 self-reference를 거부하면(에러 메시지에 `invalid source` 등 포함), 즉시 아래 절차로 전환하고 사용자에게 보고:

1. `plugins/token-tracker/` 디렉터리를 만들고 `.claude-plugin/plugin.json` + `hooks/` + `lib/`를 그 아래로 이동.
2. repo 루트 `.claude-plugin/marketplace.json`의 `source`를 `"./plugins/token-tracker"`로 수정.
3. `tests/` 경로 import가 깨지므로 `conftest.py`에 `sys.path.insert(0, str(Path(__file__).parent.parent / "plugins/token-tracker"))` 추가.
4. 모든 테스트 재실행.
5. plan의 Task 2-3 문서 수정(설치 경로 예시에 반영).

이 경우 커밋 메시지에 `refactor(plugin): move plugin files under plugins/token-tracker for standard marketplace layout` 명시.

---

## Self-Review 결과

- **Spec coverage**: handoff 문서 섹션 5-A의 3가지 요구사항(디렉터리 생성, extraKnownMarketplaces 등록, /plugin 토글) 전부 Task 1+4에서 커버. ✅
- **Placeholder scan**: TBD/TODO/implement later 없음. 모든 step에 실제 명령/코드/예상 출력 명시. ✅
- **Type consistency**: marketplace.json의 plugin.version과 plugin.json의 version이 일치해야 한다는 invariant를 Task 1 test로 명시. Task 5 Step 2 bump 시 둘 다 수정. ✅

---

## Execution Handoff

**1. Subagent-Driven (추천)** — 태스크마다 서브에이전트 디스패치, 사이에 리뷰.
**2. Inline Execution** — 현 세션에서 바로 실행, 체크포인트마다 사용자 승인.

Task 4는 사용자 직접 개입이 필요하므로 어느 방식이든 거기서 일시정지한다.
