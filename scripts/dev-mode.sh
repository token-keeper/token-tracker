#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLUGIN_SRC="$REPO_ROOT/plugins/token-tracker"
PLUGIN_MANIFEST="$PLUGIN_SRC/.claude-plugin/plugin.json"
CACHE_BASE="$HOME/.claude/plugins/cache/token-tracker-local/token-tracker"

# _resolve_paths 가 set 함
MANIFEST_VERSION=""    # plugin.json 의 현재 version
DEV_VERSION=""         # cache 에 dev mode artifact 가 있는 version (없으면 빈 string)
VERSION=""             # 실제 사용할 version (DEV_VERSION 우선, 없으면 MANIFEST_VERSION)
TARGET=""
BACKUP=""

get_version() {
    if [[ ! -f "$PLUGIN_MANIFEST" ]]; then
        echo "ERROR: plugin manifest not found: $PLUGIN_MANIFEST" >&2
        exit 1
    fi
    local v
    v="$(python3 - "$PLUGIN_MANIFEST" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
except Exception as e:
    print(f"ERROR: plugin.json 파싱 실패: {e}", file=sys.stderr)
    sys.exit(2)
v = data.get("version")
if not v:
    print("ERROR: plugin.json 에 'version' 키가 없습니다", file=sys.stderr)
    sys.exit(2)
print(v)
PY
)" || exit 1

    # semver 검증 — path traversal / 공백 등 비정상 값 차단
    if ! [[ "$v" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?$ ]]; then
        echo "ERROR: plugin.json 의 version 값이 semver 형식이 아닙니다: $v" >&2
        echo "조치: plugin.json 의 'version' 을 'X.Y.Z' 또는 'X.Y.Z-prerelease' 형태로 수정." >&2
        exit 1
    fi

    printf '%s\n' "$v"
}

# cache_base 를 스캔해서 dev mode artifact 가 있는 version 을 찾는다.
# 출력: 발견된 version (한 개), 없으면 빈 string. 여러 version 이 동시에 발견되면 stderr + exit 1.
# artifact = (a) entry 가 symlink, (b) entry 가 <X>.backup 형태의 dir 중 하나라도.
find_active_dev_version() {
    if [[ ! -d "$CACHE_BASE" ]]; then
        return 0
    fi

    local entry name v
    declare -a versions=()
    while IFS= read -r entry; do
        name="$(basename "$entry")"
        v=""
        if [[ -L "$entry" ]]; then
            v="$name"
        elif [[ -d "$entry" && "$name" == *.backup ]]; then
            v="${name%.backup}"
        fi
        if [[ -n "$v" ]]; then
            # semver 검증을 거친 값만 채택 (cache 안의 우연한 dir 무시)
            if [[ "$v" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.]+)?$ ]]; then
                versions+=("$v")
            fi
        fi
    done < <(find "$CACHE_BASE" -mindepth 1 -maxdepth 1 2>/dev/null)

    if [[ ${#versions[@]} -eq 0 ]]; then
        return 0
    fi

    local unique
    unique="$(printf '%s\n' "${versions[@]}" | sort -u)"
    local count
    count="$(printf '%s\n' "$unique" | wc -l | tr -d ' ')"
    if [[ "$count" -gt 1 ]]; then
        echo "ERROR: 여러 version 에 dev mode artifact 가 동시에 존재합니다:" >&2
        printf '  - %s\n' $unique >&2
        echo "조치: 어느 쪽이 정상인지 확인 후 수동 정리:" >&2
        echo "  ls -la '$CACHE_BASE/'" >&2
        exit 1
    fi

    printf '%s\n' "$unique"
}

_resolve_paths() {
    [[ -n "$VERSION" ]] && return 0
    MANIFEST_VERSION="$(get_version)"
    DEV_VERSION="$(find_active_dev_version)"
    # active dev version 이 있으면 그쪽이 truth (manifest 가 bump 됐어도 dev mode 는 그 version 위에 있음).
    # 없으면 manifest version 사용 (= 정상 OFF 상태에서 dev mode 새로 켜는 케이스).
    if [[ -n "$DEV_VERSION" ]]; then
        VERSION="$DEV_VERSION"
    else
        VERSION="$MANIFEST_VERSION"
    fi
    TARGET="$CACHE_BASE/$VERSION"
    BACKUP="$CACHE_BASE/$VERSION.backup"
}

cmd_status() {
    _resolve_paths

    # 인터럽트된 on 작업 잔재 (target 없음 + backup 만 존재, dangling symlink 제외)
    if [[ ! -e "$TARGET" && ! -L "$TARGET" && -d "$BACKUP" ]]; then
        echo "경고: 인터럽트된 on 작업 잔재 감지."
        echo "  cache:  없음"
        echo "  backup: $BACKUP (남아있음)"
        echo "조치: $0 off 로 backup 복원."
        return 0
    fi

    if [[ -L "$TARGET" ]]; then
        echo "dev mode: ON"
        echo "  cache:  $TARGET"
        local link
        link="$(readlink "$TARGET")"
        if [[ -e "$TARGET" ]]; then
            echo "  → link: $link"
        else
            echo "  → link: $link  (DANGLING — 대상이 존재하지 않음)"
            echo "조치: $0 off 로 backup 복원 (PLUGIN_SRC 가 사라진 것으로 보임)."
        fi
        return 0
    fi

    if [[ -d "$TARGET" ]]; then
        if [[ -d "$BACKUP" ]]; then
            echo "경고: dev mode 가 reinstall 로 끊긴 것 같습니다."
            echo "  cache:  $TARGET (정상 dir)"
            echo "  backup: $BACKUP (남아있음)"
            echo "조치: $0 off 안내 메시지를 따라 수동 처리."
            return 0
        fi
        echo "dev mode: OFF (정상 cache)"
        echo "  cache: $TARGET"
        return 0
    fi

    echo "ERROR: cache 가 없습니다: $TARGET" >&2
    echo "조치: /plugin install 먼저 실행하세요." >&2
    exit 1
}

cmd_on() {
    _resolve_paths

    # 다른 version 의 dev mode 가 활성 상태에서 manifest 만 bump 된 경우 명시 안내
    if [[ -n "$DEV_VERSION" && "$DEV_VERSION" != "$MANIFEST_VERSION" ]]; then
        echo "ERROR: 이미 다른 version 의 dev mode 가 활성 상태입니다." >&2
        echo "  현재 plugin.json: $MANIFEST_VERSION" >&2
        echo "  활성 dev mode:    $DEV_VERSION" >&2
        echo "조치: 먼저 활성 dev mode 를 끄세요:" >&2
        echo "  $0 off    # $DEV_VERSION 의 cache 를 정리" >&2
        echo "그 후 다시 $0 on 을 호출하면 $MANIFEST_VERSION 으로 dev mode 가 켜집니다." >&2
        exit 1
    fi

    if [[ ! -e "$TARGET" ]]; then
        echo "ERROR: cache 가 없습니다: $TARGET" >&2
        echo "조치: /plugin install 먼저 실행하세요." >&2
        exit 1
    fi

    if [[ -L "$TARGET" ]]; then
        echo "이미 dev mode 입니다 (no-op)."
        echo "  cache:  $TARGET"
        echo "  → link: $(readlink "$TARGET")"
        return 0
    fi

    if [[ -e "$BACKUP" ]]; then
        echo "ERROR: backup dir 이 이미 존재합니다: $BACKUP" >&2
        echo "조치: 수동으로 정리하세요. 보통 다음 중 하나:" >&2
        echo "  - rm -rf '$BACKUP'   (backup 버리고 현재 cache 유지)" >&2
        echo "  - rm -rf '$TARGET' && mv '$BACKUP' '$TARGET'   (현재 cache 버리고 backup 복원)" >&2
        exit 1
    fi

    if [[ ! -d "$PLUGIN_SRC" ]]; then
        echo "ERROR: 작업 폴더 plugin 경로가 없습니다: $PLUGIN_SRC" >&2
        exit 1
    fi

    # 트랜잭션: mv 후 ln 실패 시 즉시 backup → target 복원. 복원도 실패하면 수동 안내.
    mv "$TARGET" "$BACKUP"
    if ! ln -s "$PLUGIN_SRC" "$TARGET"; then
        echo "ERROR: symlink 생성 실패. backup → target 복원 중..." >&2
        if ! mv "$BACKUP" "$TARGET"; then
            echo "ERROR: 복원도 실패. 수동 복구 필요:" >&2
            echo "  mv '$BACKUP' '$TARGET'" >&2
            exit 1
        fi
        echo "복원 완료." >&2
        exit 1
    fi

    echo "dev mode: ON"
    echo "  cache:  $TARGET"
    echo "  → link: $PLUGIN_SRC"
    echo ""
    echo "이제 코드 수정이 즉시 반영됩니다."
    echo "daemon 코드를 수정한 경우 /token-tracker:token-history-stop 후 재호출."
    echo "끄려면: $0 off"
}

cmd_off() {
    _resolve_paths

    # 1. 인터럽트된 on 작업 잔재 (target 없음 + backup 만 존재, dangling symlink 제외)
    # — 자가복구. dangling symlink + backup 케이스는 case 4 가 처리함 (rm symlink + mv backup).
    if [[ ! -e "$TARGET" && ! -L "$TARGET" && -d "$BACKUP" ]]; then
        echo "감지: 인터럽트된 on 작업 잔재 (target 없음, backup 존재)."
        echo "backup 을 원본 위치로 복원합니다."
        mv "$BACKUP" "$TARGET"
        echo "복원 완료: $TARGET"
        return 0
    fi

    # 2. 이미 정상 mode (정상 dir + backup 없음)
    if [[ -d "$TARGET" && ! -L "$TARGET" && ! -e "$BACKUP" ]]; then
        echo "이미 정상 mode 입니다 (no-op)."
        echo "  cache: $TARGET"
        return 0
    fi

    # 3. reinstall 로 끊긴 상태 (정상 dir + backup 동시 존재) — 자동 처리 안 함
    if [[ -d "$TARGET" && ! -L "$TARGET" && -d "$BACKUP" ]]; then
        echo "감지: dev mode 가 reinstall 로 끊긴 것으로 보입니다." >&2
        echo "  cache:  $TARGET  (정상 dir)" >&2
        echo "  backup: $BACKUP (이전 정상 dir)" >&2
        echo "" >&2
        echo "어느 쪽이 truth 인지 스크립트가 판단할 수 없으므로 자동 정리하지 않습니다." >&2
        echo "조치: 어느 쪽이 정상인지 확인 후 수동 처리:" >&2
        echo "  - 현재 cache 가 정상이면:  rm -rf '$BACKUP'" >&2
        echo "  - backup 이 정상이면:      rm -rf '$TARGET' && mv '$BACKUP' '$TARGET'" >&2
        exit 1
    fi

    # 4. 정상 dev mode (symlink + backup) — 표준 off 흐름
    if [[ -L "$TARGET" && -d "$BACKUP" ]]; then
        rm "$TARGET"          # symlink 만 제거 (대상 폴더는 안전)
        if ! mv "$BACKUP" "$TARGET"; then
            echo "ERROR: backup → target 복원 실패." >&2
            echo "조치: $0 off 를 다시 실행하면 자가복구됩니다 (case 1 분기)." >&2
            exit 1
        fi
        echo "dev mode: OFF"
        echo "  cache: $TARGET (원본 복원됨)"
        echo ""
        echo "cache 를 최신 코드로 갱신하려면 plugin reinstall 필요."
        return 0
    fi

    # 5. symlink 만 있고 backup 없음 (이상 상태)
    if [[ -L "$TARGET" && ! -e "$BACKUP" ]]; then
        echo "ERROR: symlink 는 있는데 backup 이 없습니다." >&2
        echo "  cache: $TARGET → $(readlink "$TARGET")" >&2
        echo "조치: symlink 를 수동 제거하고 plugin reinstall:" >&2
        echo "  rm '$TARGET'" >&2
        echo "  /plugin install token-tracker@token-tracker-local" >&2
        exit 1
    fi

    # 6. fall-through — 알려진 케이스 모두 안 맞음
    echo "ERROR: 알 수 없는 cache 상태입니다." >&2
    echo "조치: ls -la '$CACHE_BASE/' 로 확인 후 수동 복구." >&2
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
