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

case "${1:-}" in
    on) cmd_on ;;
    off) cmd_off ;;
    status) cmd_status ;;
    *)
        echo "사용법: $0 {on|off|status}"
        exit 1
        ;;
esac
