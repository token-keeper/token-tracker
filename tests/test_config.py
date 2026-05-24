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

    def test_returns_defaults_when_json_is_array(self, plugin_root: Path):
        (plugin_root / "config.json").write_text("[1, 2, 3]", encoding="utf-8")
        assert load_config(plugin_root) == DEFAULTS

    def test_returns_defaults_when_json_is_scalar(self, plugin_root: Path):
        (plugin_root / "config.json").write_text("42", encoding="utf-8")
        assert load_config(plugin_root) == DEFAULTS


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

    def test_tmp_file_cleaned_up_on_replace_failure(
        self, plugin_root: Path, monkeypatch: pytest.MonkeyPatch
    ):
        _write(plugin_root, {"language": "ko", "verbose": False})

        def fail_replace(src, dst):
            raise OSError("simulated replace failure")

        monkeypatch.setattr("lib.config.os.replace", fail_replace)
        with pytest.raises(OSError):
            update_config(plugin_root, {"verbose": True})

        # Verify no .tmp sidecar is left behind.
        leftovers = list(plugin_root.glob("config.json*.tmp"))
        assert leftovers == [], f"tmp file leaked: {leftovers}"


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
    def test_env_non_whitelist_falls_back_to_cfg(self, env):
        assert is_verbose({"verbose": True}, env) is True
        assert is_verbose({"verbose": False}, env) is False

    def test_cfg_missing_verbose_defaults_false(self):
        assert is_verbose({}, None) is False
