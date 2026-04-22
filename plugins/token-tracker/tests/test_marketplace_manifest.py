import json
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PLUGIN_ROOT.parent.parent
MANIFEST = REPO_ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN_MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
HOOKS_JSON = PLUGIN_ROOT / "hooks" / "hooks.json"


def test_marketplace_manifest_exists():
    assert MANIFEST.is_file(), f"marketplace.json missing at {MANIFEST}"


def test_marketplace_manifest_has_required_fields():
    data = json.loads(MANIFEST.read_text())
    assert data["name"] == "token-tracker-local"
    assert "owner" in data and "name" in data["owner"]
    assert isinstance(data["plugins"], list) and len(data["plugins"]) == 1


def test_marketplace_plugin_entry_points_to_plugin_dir():
    data = json.loads(MANIFEST.read_text())
    entry = data["plugins"][0]
    assert entry["name"] == "token-tracker"
    assert entry["source"] == "./plugins/token-tracker"


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
