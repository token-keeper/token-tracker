import json
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
HOOKS_JSON = PLUGIN_ROOT / "hooks" / "hooks.json"


def test_plugin_manifest_exists():
    assert PLUGIN_MANIFEST.is_file(), f"plugin.json missing at {PLUGIN_MANIFEST}"


def test_plugin_manifest_required_fields():
    data = json.loads(PLUGIN_MANIFEST.read_text())
    assert data["name"] == "token-tracker"
    assert "version" in data
    assert "description" in data


def test_plugin_manifest_does_not_redeclare_default_hooks():
    data = json.loads(PLUGIN_MANIFEST.read_text())
    assert "hooks" not in data, (
        "Claude Code가 hooks/hooks.json을 자동 로드하므로 plugin.json에 "
        "'hooks': './hooks/hooks.json'을 중복 선언하면 duplicate hooks file 에러가 난다"
    )
    assert HOOKS_JSON.is_file(), f"hooks.json missing at {HOOKS_JSON}"
