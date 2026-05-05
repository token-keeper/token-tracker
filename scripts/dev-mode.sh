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
