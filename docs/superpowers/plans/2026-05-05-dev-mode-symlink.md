# token-tracker dev-mode.sh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 작업 디렉터리 ↔ cache 디렉터리 사본을 매번 `cp` / `reinstall` 로 동기화하던 마찰을 없애는 `scripts/dev-mode.sh on|off|status` 토글 스크립트 추가.

**Architecture:** 단일 bash 스크립트가 `plugin.json` 의 `version` 을 읽어 cache target 경로 (`~/.claude/plugins/cache/token-tracker-local/token-tracker/<version>/`) 를 계산. `on` 시 원본 dir 을 `<version>.backup/` 으로 rename 후 작업 폴더 (`plugins/token-tracker/`) 를 가리키는 symlink 로 교체. `off` 시 역순. `status` 는 현재 상태와 reinstall 로 끊긴 케이스도 함께 보고. README 에 사용법 + 수동 검증 체크리스트.

**Tech Stack:** bash 4+, `python3` (manifest JSON 파싱 — jq 없는 환경 대비), POSIX 표준 도구 (`mv`, `ln`, `rm`, `readlink`).

**Spec:** `docs/superpowers/specs/2026-05-05-dev-mode-symlink-design.md`

---

## File Structure

| 파일 | 역할 |
|---|---|
| `scripts/dev-mode.sh` (신규) | on/off/status 토글 단일 스크립트. version 자동 추출. |
| `README.md` (수정) | "Development" 섹션 신설 — 사용법 + 수동 검증 체크리스트 + reinstall 주의점 |

자동화 테스트 파일 없음 (spec §11 — bash + cache + plugin 시스템 의존성, 비용 대비 가치 낮음).

---

## Task 1: 스크립트 스켈레톤 + `status` 명령

**Files:**
- Create: `scripts/dev-mode.sh`

`status` 는 read-only 라 가장 안전. 먼저 만들어서 환경 인식 (manifest 파싱 + cache 경로 계산) 이 정확한지 검증한다.

- [ ] **Step 1: 스크립트 파일 생성**

`scripts/dev-mode.sh` 에 다음 내용 작성:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLUGIN_SRC="$REPO_ROOT/plugins/token-tracker"
PLUGIN_MANIFEST="$PLUGIN_SRC/.claude-plugin/plugin.json"
CACHE_BASE="$HOME/.claude/plugins/cache/token-tracker-local/token-tracker"

get_version() {
    if [[ ! -f "$PLUGIN_MANIFEST" ]]; then
        echo "ERROR: plugin manifest not found: $PLUGIN_MANIFEST" >&2
        exit 1
    fi
    python3 -c "import json; print(json.load(open('$PLUGIN_MANIFEST'))['version'])"
}

cmd_status() {
    local version target backup
    version="$(get_version)"
    target="$CACHE_BASE/$version"
    backup="$CACHE_BASE/$version.backup"

    # 인터럽트된 on 작업의 잔재 (target 없음 + backup 만 존재)
    if [[ ! -e "$target" && -d "$backup" ]]; then
        echo "경고: 인터럽트된 on 작업 잔재 감지."
        echo "  cache:  없음"
        echo "  backup: $backup (남아있음)"
        echo "조치: $0 off 로 backup 복원."
        return 0
    fi

    if [[ -L "$target" ]]; then
        echo "dev mode: ON"
        echo "  cache:  $target"
        echo "  → link: $(readlink "$target")"
        return 0
    fi

    if [[ -d "$target" ]]; then
        if [[ -d "$backup" ]]; then
            echo "경고: dev mode 가 reinstall 로 끊긴 것 같습니다."
            echo "  cache:  $target (정상 dir)"
            echo "  backup: $backup (남아있음)"
            echo "조치: $0 off 안내 메시지를 따라 수동 처리."
            return 0
        fi
        echo "dev mode: OFF (정상 cache)"
        echo "  cache: $target"
        return 0
    fi

    echo "ERROR: cache 가 없습니다: $target" >&2
    echo "조치: /plugin install 먼저 실행하세요." >&2
    exit 1
}

cmd_on() {
    echo "ERROR: 아직 구현되지 않음 (Task 2)" >&2
    exit 1
}

cmd_off() {
    echo "ERROR: 아직 구현되지 않음 (Task 2)" >&2
    exit 1
}

case "${1:-}" in
    on) cmd_on ;;
    off) cmd_off ;;
    status) cmd_status ;;
    *)
        echo "사용법: $0 {on|off|status}"
        exit 1
        ;;
esac
```

- [ ] **Step 2: 실행 권한 부여**

```bash
chmod +x scripts/dev-mode.sh
```

- [ ] **Step 3: status 명령 수동 검증 — 정상 cache 인식**

```bash
./scripts/dev-mode.sh status
```

기대 출력:
```
dev mode: OFF (정상 cache)
  cache: /Users/brody/.claude/plugins/cache/token-tracker-local/token-tracker/0.9.0
```

cache 경로의 마지막 segment 가 `plugin.json` 의 version (현재 `0.9.0`) 과 일치해야 한다. 다르면 `get_version` 또는 `CACHE_BASE` 를 점검.

- [ ] **Step 4: 인자 없음 / 잘못된 인자 처리 검증**

```bash
./scripts/dev-mode.sh
```

기대: `사용법: ./scripts/dev-mode.sh {on|off|status}` + exit code 1.

```bash
./scripts/dev-mode.sh on || echo "exit=$?"
```

기대: `ERROR: 아직 구현되지 않음 (Task 2)` + `exit=1`.

- [ ] **Step 5: commit**

```bash
git add scripts/dev-mode.sh
git commit -m "feat(scripts): dev-mode.sh 스켈레톤 + status 명령 추가

plugin.json 에서 active version 을 자동 추출해 cache 경로를 계산,
현재 cache 가 정상 dir / symlink / reinstall 로 끊긴 상태인지를
보고하는 read-only status 명령 구현. on/off 는 다음 task 에서.

관련: docs/superpowers/specs/2026-05-05-dev-mode-symlink-design.md §6"
```

---

## Task 2: `on` + `off` 명령 + 사용자 수동 검증

**Files:**
- Modify: `scripts/dev-mode.sh` (`cmd_on`, `cmd_off` 본문 교체)

`on` 만 구현하고 검증하면 검증 실패 시 backup 으로 수동 복구가 어렵다. `on` 과 `off` 를 같이 구현해 사용자 수동 검증 step 에서 안전하게 toggle 가능하게 한다.

- [ ] **Step 1: `cmd_on` 본문 구현**

`scripts/dev-mode.sh` 의 `cmd_on()` placeholder 를 다음으로 교체:

```bash
cmd_on() {
    local version target backup
    version="$(get_version)"
    target="$CACHE_BASE/$version"
    backup="$CACHE_BASE/$version.backup"

    if [[ ! -e "$target" ]]; then
        echo "ERROR: cache 가 없습니다: $target" >&2
        echo "조치: /plugin install 먼저 실행하세요." >&2
        exit 1
    fi

    if [[ -L "$target" ]]; then
        echo "이미 dev mode 입니다 (no-op)."
        echo "  cache:  $target"
        echo "  → link: $(readlink "$target")"
        return 0
    fi

    if [[ -e "$backup" ]]; then
        echo "ERROR: backup dir 이 이미 존재합니다: $backup" >&2
        echo "조치: 수동으로 정리하세요. 보통 다음 중 하나:" >&2
        echo "  - rm -rf '$backup'   (backup 버리고 현재 cache 유지)" >&2
        echo "  - rm -rf '$target' && mv '$backup' '$target'   (현재 cache 버리고 backup 복원)" >&2
        exit 1
    fi

    if [[ ! -d "$PLUGIN_SRC" ]]; then
        echo "ERROR: 작업 폴더 plugin 경로가 없습니다: $PLUGIN_SRC" >&2
        exit 1
    fi

    # 트랜잭션: mv 후 ln 실패 시 즉시 자동 rollback
    mv "$target" "$backup"
    if ! ln -s "$PLUGIN_SRC" "$target"; then
        echo "ERROR: symlink 생성 실패. backup → target 복원 중..." >&2
        mv "$backup" "$target"
        exit 1
    fi

    echo "dev mode: ON"
    echo "  cache:  $target"
    echo "  → link: $PLUGIN_SRC"
    echo ""
    echo "이제 코드 수정이 즉시 반영됩니다."
    echo "daemon 코드를 수정한 경우 /token-tracker:token-history-stop 후 재호출."
    echo "끄려면: $0 off"
}
```

- [ ] **Step 2: `cmd_off` 본문 구현**

`scripts/dev-mode.sh` 의 `cmd_off()` placeholder 를 다음으로 교체:

```bash
cmd_off() {
    local version target backup
    version="$(get_version)"
    target="$CACHE_BASE/$version"
    backup="$CACHE_BASE/$version.backup"

    # 1. 인터럽트된 on 작업 잔재 (target 없음 + backup 만 존재) — 자가복구
    if [[ ! -e "$target" && -d "$backup" ]]; then
        echo "감지: 인터럽트된 on 작업 잔재 (target 없음, backup 존재)."
        echo "backup 을 원본 위치로 복원합니다."
        mv "$backup" "$target"
        echo "복원 완료: $target"
        return 0
    fi

    # 2. 이미 정상 mode (정상 dir + backup 없음)
    if [[ -d "$target" && ! -L "$target" && ! -e "$backup" ]]; then
        echo "이미 정상 mode 입니다 (no-op)."
        echo "  cache: $target"
        return 0
    fi

    # 3. reinstall 로 끊긴 상태 (정상 dir + backup 동시 존재) — 자동 처리 안 함
    if [[ -d "$target" && ! -L "$target" && -d "$backup" ]]; then
        echo "감지: dev mode 가 reinstall 로 끊긴 것으로 보입니다." >&2
        echo "  cache:  $target  (정상 dir)" >&2
        echo "  backup: $backup (이전 정상 dir)" >&2
        echo "" >&2
        echo "어느 쪽이 truth 인지 스크립트가 판단할 수 없으므로 자동 정리하지 않습니다." >&2
        echo "조치: 어느 쪽이 정상인지 확인 후 수동 처리:" >&2
        echo "  - 현재 cache 가 정상이면:  rm -rf '$backup'" >&2
        echo "  - backup 이 정상이면:      rm -rf '$target' && mv '$backup' '$target'" >&2
        exit 1
    fi

    # 4. 정상 dev mode (symlink + backup) — 표준 off 흐름
    if [[ -L "$target" && -d "$backup" ]]; then
        rm "$target"          # symlink 만 제거 (대상 폴더는 안전)
        mv "$backup" "$target"
        echo "dev mode: OFF"
        echo "  cache: $target (원본 복원됨)"
        echo ""
        echo "cache 를 최신 코드로 갱신하려면 plugin reinstall 필요."
        return 0
    fi

    # 5. symlink 만 있고 backup 없음 (이상 상태)
    if [[ -L "$target" && ! -e "$backup" ]]; then
        echo "ERROR: symlink 는 있는데 backup 이 없습니다." >&2
        echo "  cache: $target → $(readlink "$target")" >&2
        echo "조치: symlink 를 수동 제거하고 plugin reinstall:" >&2
        echo "  rm '$target'" >&2
        echo "  /plugin install token-tracker@token-tracker-local" >&2
        exit 1
    fi

    # 6. fall-through — 알려진 케이스 모두 안 맞음
    echo "ERROR: 알 수 없는 cache 상태입니다." >&2
    echo "조치: ls -la '$CACHE_BASE/' 로 확인 후 수동 복구." >&2
    exit 1
}
```

- [ ] **Step 3: status 출력 확인 (현재는 OFF)**

```bash
./scripts/dev-mode.sh status
```

기대: `dev mode: OFF (정상 cache)`.

- [ ] **Step 4: `on` 실행 + 결과 확인**

```bash
./scripts/dev-mode.sh on
```

기대 출력:
```
dev mode: ON
  cache:  /Users/brody/.claude/plugins/cache/token-tracker-local/token-tracker/0.9.0
  → link: /Users/brody/Desktop/token-tracker/plugins/token-tracker

이제 코드 수정이 즉시 반영됩니다.
daemon 코드를 수정한 경우 /token-tracker:token-history-stop 후 재호출.
끄려면: ./scripts/dev-mode.sh off
```

이어서 실제 결과 확인:

```bash
ls -la ~/.claude/plugins/cache/token-tracker-local/token-tracker/
```

기대:
- `0.9.0` 이 작업 폴더 plugin 경로를 가리키는 symlink (`l` 시작 + `->` 포함)
- `0.9.0.backup/` 이 정상 dir 로 존재

```bash
./scripts/dev-mode.sh status
```

기대: `dev mode: ON` + 가리키는 경로 출력.

- [ ] **Step 5: idempotency — `on` 다시 호출**

```bash
./scripts/dev-mode.sh on
```

기대: `이미 dev mode 입니다 (no-op).` + exit 0.

- [ ] **Step 6: ★ 사용자 수동 검증 — symlink 가 plugin 시스템과 호환되는지**

> **중요**: 이 step 이 본 plan 의 **핵심 검증 지점** 이다. 결과에 따라 분기.

다음을 사용자가 직접 수행 (Claude Code UI 에서):

  a. `/reload-plugins` 실행 — "Reloaded: ..." 메시지 확인.
  b. 새 prompt 한 번 입력 (예: "지금 시간 알려줘") — 응답 도착 확인.
  c. 응답 마지막에 token-tracker hook 의 토큰 줄이 출력되는지 확인. 예: `🪙 input X.Xk · output Y.Yk · cost $Z.ZZZZ`.
  d. `/token-tracker:token-history` 실행 → 정상적으로 `http://127.0.0.1:8765/...` URL 응답 + 브라우저에서 history 페이지 정상 렌더 확인.
  e. 작업 폴더에서 `plugins/token-tracker/style.css` 한 줄 수정 (예: 주석 한 줄 추가) → 위 history 페이지 새로고침 (cmd+R) 으로 즉시 반영되는지 확인. **이게 dev mode 의 본 목적**.

  **분기:**
  - **모두 OK** → Step 7 (off 검증) 으로 진행.
  - **c 의 hook 출력 silent** 또는 **d 의 daemon 동작 안 함** → plugin 시스템이 symlink 를 무시하는 것. 본 plan **즉시 중단**:
    1. `./scripts/dev-mode.sh off` 실행 (Step 2 에서 이미 구현됨) 으로 안전 복원.
    2. 본 PR 폐기, 새 spec 작성 (`docs/superpowers/specs/2026-05-05-cache-sync-helper-design.md`) 으로 옵션 B (cp 기반 sync 헬퍼) 디자인 → spec §9 폴백.
    3. 사용자에게 보고 후 새 brainstorm 진행.

- [ ] **Step 7: `off` 실행 + 결과 확인 (검증 통과 시)**

```bash
./scripts/dev-mode.sh off
```

기대 출력:
```
dev mode: OFF
  cache: /Users/brody/.claude/plugins/cache/token-tracker-local/token-tracker/0.9.0 (원본 복원됨)

cache 를 최신 코드로 갱신하려면 plugin reinstall 필요.
```

```bash
ls -la ~/.claude/plugins/cache/token-tracker-local/token-tracker/
```

기대: `0.9.0/` 이 정상 dir 로 복원, `0.9.0.backup/` 사라짐.

- [ ] **Step 8: idempotency — `off` 다시 호출**

```bash
./scripts/dev-mode.sh off
```

기대: `이미 정상 mode 입니다 (no-op).` + exit 0.

- [ ] **Step 9: backup 충돌 케이스 검증**

```bash
mkdir -p ~/.claude/plugins/cache/token-tracker-local/token-tracker/0.9.0.backup
./scripts/dev-mode.sh on || echo "exit=$?"
```

기대 출력에 `ERROR: backup dir 이 이미 존재합니다` + `exit=1` 포함.

정리:
```bash
rmdir ~/.claude/plugins/cache/token-tracker-local/token-tracker/0.9.0.backup
```

- [ ] **Step 10: 인터럽트 시뮬레이션 — `cmd_off` 자가복구 검증**

`cmd_on` 이 `mv` 까지 끝내고 `ln -s` 직전에 죽었거나, 사용자가 SIGINT 로 중단한 상태를 시뮬레이션:

```bash
mv ~/.claude/plugins/cache/token-tracker-local/token-tracker/0.9.0 \
   ~/.claude/plugins/cache/token-tracker-local/token-tracker/0.9.0.backup
ls ~/.claude/plugins/cache/token-tracker-local/token-tracker/
```

기대: `0.9.0.backup/` 만 존재 (target 없음).

```bash
./scripts/dev-mode.sh status
```

기대 출력:
```
경고: 인터럽트된 on 작업 잔재 감지.
  cache:  없음
  backup: ...0.9.0.backup (남아있음)
조치: ./scripts/dev-mode.sh off 로 backup 복원.
```

```bash
./scripts/dev-mode.sh off
```

기대 출력:
```
감지: 인터럽트된 on 작업 잔재 (target 없음, backup 존재).
backup 을 원본 위치로 복원합니다.
복원 완료: /Users/brody/.claude/plugins/cache/token-tracker-local/token-tracker/0.9.0
```

```bash
ls ~/.claude/plugins/cache/token-tracker-local/token-tracker/
```

기대: `0.9.0/` 정상 dir 로 복원, `0.9.0.backup/` 사라짐.

- [ ] **Step 11: 이상 상태 검증 — case 3 (reinstall 끊김) + case 5 (symlink + no backup)**

코드리뷰 피드백 반영으로 추가된 검증. 평소 사용자 흐름에선 잘 안 만나지만 실제 사용 환경에서 발생 가능한 이상 상태 두 가지 시뮬.

**case 3 — reinstall 로 끊긴 상태 (정상 dir + backup 동시):**

```bash
# 시뮬: 정상 dir 자리에 빈 backup dir 도 만들어 reinstall 끊김 흉내
mkdir -p ~/.claude/plugins/cache/token-tracker-local/token-tracker/0.9.0.backup
ls ~/.claude/plugins/cache/token-tracker-local/token-tracker/
```

기대: `0.9.0/` (정상 dir) + `0.9.0.backup/` 동시 존재.

```bash
./scripts/dev-mode.sh status
```

기대 출력에 `경고: dev mode 가 reinstall 로 끊긴 것 같습니다.` 포함.

```bash
./scripts/dev-mode.sh off; echo "exit=$?"
```

기대: `자동 정리하지 않습니다` 안내 + 수동 처리 두 가지 옵션 (`rm -rf <backup>` 또는 `rm -rf <target> && mv ...`) 출력 + `exit=1`.

정리:
```bash
rmdir ~/.claude/plugins/cache/token-tracker-local/token-tracker/0.9.0.backup
```

**case 5 — symlink 만 있고 backup 없음 (이상 상태):**

```bash
# 시뮬: 정상 cache 를 잠시 옆으로 옮기고 symlink 만 만들기 (backup 없이)
mv ~/.claude/plugins/cache/token-tracker-local/token-tracker/0.9.0 \
   ~/.claude/plugins/cache/token-tracker-local/token-tracker/0.9.0.realcopy
ln -s /Users/brody/Desktop/token-tracker/plugins/token-tracker \
      ~/.claude/plugins/cache/token-tracker-local/token-tracker/0.9.0
ls -la ~/.claude/plugins/cache/token-tracker-local/token-tracker/
```

기대: `0.9.0` 이 symlink + `0.9.0.realcopy/` 정상 dir.

```bash
./scripts/dev-mode.sh off; echo "exit=$?"
```

기대 출력에 `ERROR: symlink 는 있는데 backup 이 없습니다.` + `rm '$target'` + `/plugin install` 안내 + `exit=1` 포함.

정리 (case 5 시뮬을 정리해서 정상 cache 복원):
```bash
rm ~/.claude/plugins/cache/token-tracker-local/token-tracker/0.9.0
mv ~/.claude/plugins/cache/token-tracker-local/token-tracker/0.9.0.realcopy \
   ~/.claude/plugins/cache/token-tracker-local/token-tracker/0.9.0
./scripts/dev-mode.sh status
```

기대 최종: `dev mode: OFF (정상 cache)`.

**ln 실패 rollback** (cmd_on 의 `mv` 후 `ln -s` 실패 시 자동 backup 복원) 은 ln 자체 실패 시뮬이 어려워 (mv 까지 끝난 상태에서 ln 만 실패하게 하려면 race 가 필요) 자동 검증에선 제외. 코드 inspection 으로 검증 — 분기 단순함 (`if ! ln -s ...; then echo + mv backup target + exit 1; fi`).

- [ ] **Step 11.5: manifest version bump 시나리오 — Codex review 반영**

dev mode 가 켜진 상태에서 `plugin.json` 의 version 을 새 버전으로 bump 하는 release 흐름을 시뮬. spec §3 의 "DEV_VERSION 우선" 정책이 올바르게 동작하는지 확인.

```bash
# 사전: dev mode 켜기
./scripts/dev-mode.sh on
./scripts/dev-mode.sh status
```

기대: dev mode ON, `0.9.0` symlink + `0.9.0.backup/`.

```bash
# manifest 만 0.10.0 으로 bump (실제 cache 는 그대로 0.9.0)
ORIG=$(cat plugins/token-tracker/.claude-plugin/plugin.json)
python3 -c "import json; m=json.load(open('plugins/token-tracker/.claude-plugin/plugin.json')); m['version']='0.10.0'; json.dump(m, open('plugins/token-tracker/.claude-plugin/plugin.json','w'))"

./scripts/dev-mode.sh status
```

기대: dev mode ON 으로 표시 + cache 경로가 여전히 `0.9.0` (DEV_VERSION 우선).

```bash
./scripts/dev-mode.sh on; echo "exit=$?"
```

기대: `ERROR: 이미 다른 version 의 dev mode 가 활성 상태입니다.` + 안내 + `exit=1`.

```bash
./scripts/dev-mode.sh off
ls ~/.claude/plugins/cache/token-tracker-local/token-tracker/
```

기대: `0.9.0/` 정상 dir 로 복원, backup 사라짐. (manifest 가 0.10.0 이라도 cache 의 truth 인 0.9.0 위에서 정상 off.)

```bash
./scripts/dev-mode.sh status; echo "exit=$?"
```

기대: `ERROR: cache 가 없습니다: <cache_base>/0.10.0` (manifest 기준 cache 가 없음 = plugin reinstall 필요한 상태).

정리:
```bash
echo "$ORIG" > plugins/token-tracker/.claude-plugin/plugin.json
./scripts/dev-mode.sh status
```

기대: `dev mode: OFF (정상 cache)`.

- [ ] **Step 12: commit**

```bash
git add scripts/dev-mode.sh
git commit -m "feat(scripts): dev-mode.sh on/off 명령 + 트랜잭션 안전성

on: cache target 을 \$version.backup/ 으로 백업 후 작업 폴더 symlink 로 교체.
    mv 후 ln -s 실패 시 즉시 backup → target 자동 rollback.
off: symlink 풀고 backup 으로 원본 복원. 6개 케이스 명시 분기:
     1. 인터럽트된 on 잔재 (target 없음 + backup) → 자가복구
     2. 이미 정상 mode → no-op
     3. reinstall 로 끊긴 상태 → 자동 처리 안 함, 수동 안내만
     4. 정상 dev mode → 표준 off
     5. symlink 만 있고 backup 없음 → 에러 + 안내
     6. 알 수 없는 상태 → 에러 + 안내

사용자 수동 검증으로 plugin 시스템이 symlink 를 정상 인식함을 확인 (Step 6),
인터럽트 시뮬레이션으로 자가복구 동작 확인 (Step 10).

관련: docs/superpowers/specs/2026-05-05-dev-mode-symlink-design.md §4 §5 §10"
```

---

## Task 3: README "Development" 섹션 추가

**Files:**
- Modify: `README.md`

dev-mode 사용법 + 수동 검증 체크리스트 + reinstall 시 주의점을 README 에 문서화.

- [ ] **Step 1: README 현재 구조 확인**

```bash
cat README.md
```

마지막 섹션 다음에 새 섹션을 추가할 위치 결정. 보통 README 끝 또는 "License" 같은 섹션 직전에 "Development" 섹션을 둔다.

- [ ] **Step 2: "Development" 섹션 작성**

README.md 의 끝에 다음 내용을 추가 (마지막 섹션이 다른 것이라면 그 직전에):

```markdown
## Development

### dev mode (작업 폴더 ↔ cache 즉시 반영)

플러그인 코드 수정 시 매번 plugin reinstall 하지 않고 작업 폴더 변경을
즉시 반영하려면 `scripts/dev-mode.sh` 의 dev mode 를 사용한다.

```bash
./scripts/dev-mode.sh on      # cache → 작업 폴더 symlink 로 교체
./scripts/dev-mode.sh off     # 원본 cache 복원
./scripts/dev-mode.sh status  # 현재 상태 확인
```

`on` 시 cache 디렉터리는 `<version>.backup/` 으로 백업되고, 그 자리에
작업 폴더의 `plugins/token-tracker/` 를 가리키는 symlink 가 생긴다.
`off` 는 그 역순으로 원본을 복원한다.

#### daemon 코드 수정 시

`lib/server_daemon.py`, `lib/http_server.py`, `lib/history_renderer.py`
같은 daemon 코드를 수정하면 실행 중 daemon 을 재시작해야 반영된다:

```bash
/token-tracker:token-history-stop
```

`style.css` / `app.js` / 템플릿 같은 정적 파일은 daemon 이 매 요청마다
디스크에서 읽으므로 브라우저 새로고침 (cmd+R) 만으로 즉시 반영된다.

#### plugin reinstall 과의 관계

dev mode 가 켜진 상태에서 `/plugin uninstall` + `/plugin install` 을 하면
plugin 시스템이 cache 디렉터리를 새로 만들면서 symlink 가 사라질 수 있다.
이 상태는 `./scripts/dev-mode.sh status` 가 감지해서 안내해준다.
조치: `./scripts/dev-mode.sh off` 로 backup 정리 후 필요하면 `on` 재실행.

#### 수동 검증 체크리스트

dev mode 를 처음 켜는 환경 / Claude Code 업데이트 후 등 기본 동작이
의심될 때:

1. `./scripts/dev-mode.sh status` → "OFF" 확인
2. `./scripts/dev-mode.sh on` → "ON" + 가리키는 경로 출력 확인
3. `/reload-plugins` 실행
4. 새 prompt 한 번 입력 → 응답 마지막에 `🪙 input ...` hook 출력 확인
5. `/token-tracker:token-history` → daemon 정상 동작 + URL 응답 확인
6. 작업 폴더의 `style.css` 한 줄 수정 → 위 페이지 새로고침으로 즉시 반영 확인
7. `./scripts/dev-mode.sh off` → "OFF" 복원 + `<version>.backup/` 사라짐 확인

3~5 가 실패하면 plugin 시스템이 symlink 를 인식하지 못하는 것이다.
즉시 `off` 로 복원하고 이슈 리포트.
```

(코드 fence 안에 코드 fence 가 들어가는 구조라, 실제 작성 시 outer 를 ` ````markdown `` 로, inner 를 ` ``` ` 로 적절히 처리)

- [ ] **Step 3: README 미리보기 검증**

```bash
cat README.md | tail -80
```

새로 추가한 섹션이 깨끗하게 렌더되는지 (markdown lint), 코드 블록 fence 가 짝이 맞는지 확인.

- [ ] **Step 4: commit**

```bash
git add README.md
git commit -m "docs(readme): Development 섹션 — dev-mode.sh 사용법 + 수동 검증 체크리스트

dev mode 의 동작 원리, daemon 재시작 / 정적 파일 즉시 반영 차이,
plugin reinstall 과의 상호작용, 7-step 수동 검증 체크리스트를 정리.

관련: docs/superpowers/specs/2026-05-05-dev-mode-symlink-design.md §12"
```

---

## 마무리

- [ ] **Step 1: 전체 변경 요약 확인**

```bash
git log --oneline main..HEAD
git diff main..HEAD --stat
```

기대 commit (4건 + code review 반영 시 +1~2):
1. `docs(spec): dev-mode.sh symlink 토글 설계 추가` (이미 done — Task 0 격)
2. `feat(scripts): dev-mode.sh 스켈레톤 + status 명령 추가`
3. `feat(scripts): dev-mode.sh on/off 명령 + 트랜잭션 안전성`
4. `docs(readme): Development 섹션 — dev-mode.sh 사용법 + 수동 검증 체크리스트`
5. (선택) `fix(scripts): code review 반영 — DRY / version 검증 / rollback 견고성`
6. (선택) `docs(plan): 검증 step 추가 — case 3 / case 5`

production 코드 (`scripts/dev-mode.sh`) 분량 ≈ 175줄, 룰 (300줄 이하) 충족.

- [ ] **Step 2: 사용자에게 PR 생성 승인 요청**

이 시점에 자동으로 push / PR 만들지 않는다. 사용자 룰: PR 생성 / 머지는 명시 승인 후. plan 의 모든 task 완료 + 사용자 수동 검증 (Task 2 Step 6) 통과 보고 후 사용자에게:
- 코드리뷰 병렬 dispatch 할지 (사용자 룰 §code-review)
- PR 만들지

선택지를 제시.

---

## 폴백 분기 (Task 2 Step 6 검증 실패 시)

위 plan 폐기. 다음을 진행:

1. `./scripts/dev-mode.sh off` 실행으로 cache 안전 복원
2. 본 brach 의 미완성 commit 들 (Task 1 의 status, Task 2 의 on/off) 은 그대로 두되 PR 생성 안 함
3. 사용자에게 보고 — symlink 호환성 결여 사실 + 폴백 옵션 제시:
   - 옵션 1: 현재 brach 폐기 후 `feature/cache-sync-helper` 새 brach 에서 옵션 B (cp 기반 `scripts/sync-cache.sh`) 로 새 brainstorm
   - 옵션 2: 현재 brach 의 dev-mode.sh 는 살리고 (수동 환경에서 쓸 사람도 있을 수 있음) PR 만들되 README 에 "experimental" 명시 + sync-cache.sh 도 추가
4. 사용자 결정에 따라 새 spec / plan 작성
