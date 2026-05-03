import json
import os
import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN_ROOT / "skills" / "token-detail" / "scripts" / "detail.py"


def _run_script(session_id: str, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(SCRIPT), session_id],
        capture_output=True, text=True, env=env, timeout=5,
    )


def _seed_last_summary(home: Path, session_id: str, payload: dict) -> None:
    d = home / ".claude" / "plugins" / "token-tracker" / "state" / session_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "last_summary.json").write_text(json.dumps(payload), encoding="utf-8")


def _valid_summary_payload(session_id: str) -> dict:
    return {
        "schema_version": 3,
        "session_id": session_id,
        "saved_at": 1745301234.5,
        "summary": {
            "total_cost": 0.01,
            "total_input_tokens": 100,
            "total_output_tokens": 50,
            "cache_hit_rate": 0.5,
            "total_elapsed": 1.2,
            "turns": [{
                "model": "claude-opus-4-7",
                "input_tokens": 100, "output_tokens": 50,
                "cache_creation_5m_tokens": 0, "cache_creation_1h_tokens": 0,
                "cache_read_tokens": 0,
                "tools_used": [{"name": "Read", "count": 1}],
                "timestamp_iso": "2026-04-23T10:00:00Z",
                "message_id": "m1", "index": 0,
                "subagents": [], "agent_tool_use_ids": [],
            }],
        },
    }


def test_script_always_exits_zero_with_no_state(tmp_path):
    result = _run_script("sess-missing", env_overrides={"HOME": str(tmp_path)})
    assert result.returncode == 0


def test_script_outputs_err_no_state_when_missing(tmp_path):
    result = _run_script("sess-missing", env_overrides={"HOME": str(tmp_path)})
    assert ("아직 기록된 request" in result.stdout) or ("No recorded request" in result.stdout)


def test_script_outputs_formatted_detail_when_state_exists(tmp_path):
    _seed_last_summary(tmp_path, "sess-ok", _valid_summary_payload("sess-ok"))
    result = _run_script("sess-ok", env_overrides={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert "Read×1" in result.stdout


def test_script_outputs_err_parse_on_corrupted_state(tmp_path):
    d = tmp_path / ".claude" / "plugins" / "token-tracker" / "state" / "sess-bad"
    d.mkdir(parents=True)
    (d / "last_summary.json").write_text("{not valid", encoding="utf-8")
    result = _run_script("sess-bad", env_overrides={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert ("손상" in result.stdout) or ("corrupted" in result.stdout.lower())


def test_script_outputs_err_unsupported_schema(tmp_path):
    payload = {"schema_version": 99, "summary": {}}
    _seed_last_summary(tmp_path, "sess-future", payload)
    result = _run_script("sess-future", env_overrides={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert ("호환되지 않습니다" in result.stdout) or ("not compatible" in result.stdout)


def test_detail_script_imports_supported_schema_versions_from_summary_store():
    """detail.py가 summary_store.SUPPORTED_SCHEMA_VERSIONS를 import해서 사용 (DRY).
    하드코딩 (3,) 대신 단일 진실원에 의존 → v4 bump 시 silent skew 회귀 방지 (CRITICAL #2)."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "from lib.summary_store import" in src and "SUPPORTED_SCHEMA_VERSIONS" in src
    # 하드코딩 (3,) / (1, 2) 같은 inline tuple 잔존 금지
    assert "not in (3,)" not in src
    assert "not in (1, 2)" not in src


def test_script_accepts_v3_schema(tmp_path):
    """v0.7.0 v3 schema 파일은 정상 렌더링되어야 한다."""
    payload = _valid_summary_payload("sess-v3")
    _seed_last_summary(tmp_path, "sess-v3", payload)
    result = _run_script("sess-v3", env_overrides={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert "Read×1" in result.stdout


def test_script_rejects_v2_schema_as_unsupported(tmp_path):
    """v0.7.0에서 옛 v2 파일은 unsupported schema로 거부된다 (회귀 가드)."""
    payload = _valid_summary_payload("sess-old-v2")
    payload["schema_version"] = 2
    # v2 형식의 cache_creation_tokens(5m/1h 미분리)으로 다운그레이드
    t = payload["summary"]["turns"][0]
    t.pop("cache_creation_5m_tokens", None)
    t.pop("cache_creation_1h_tokens", None)
    t["cache_creation_tokens"] = 0
    _seed_last_summary(tmp_path, "sess-old-v2", payload)
    result = _run_script("sess-old-v2", env_overrides={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert ("호환되지 않습니다" in result.stdout) or ("not compatible" in result.stdout)
