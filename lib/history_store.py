from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from lib import paths


SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = (1,)


def _history_path(session_id: str) -> Path:
    d = paths.state_dir() / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d / "history.jsonl"


def _build_envelope(
    *,
    prompt_id: str,
    session_id: str,
    user_prompt_text: str,
    started_at: float,
    ended_at: float,
    summary_dict: dict,
    models_used: list[str],
    has_subagent_other_model: bool,
    transcript_entries: list[dict],
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "prompt_id": prompt_id,
        "session_id": session_id,
        "started_at": started_at,
        "ended_at": ended_at,
        "user_prompt": {"text": user_prompt_text, "ts": started_at},
        "summary": summary_dict,
        "models_used": list(models_used),
        "has_subagent_other_model": bool(has_subagent_other_model),
        "transcript_entries": list(transcript_entries),
    }


def _atomic_write_lines(path: Path, lines: list[str]) -> None:
    """Write all lines atomically via tmp+replace."""
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".jsonl", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line)
                if not line.endswith("\n"):
                    f.write("\n")
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def append_or_update_history(
    *,
    session_id: str,
    prompt_id: str,
    user_prompt_text: str,
    started_at: float,
    ended_at: float,
    summary_dict: dict,
    models_used: list[str],
    has_subagent_other_model: bool,
    transcript_entries: list[dict],
) -> None:
    """Append a new entry, OR rewrite the last line in-place when the last
    line's prompt_id matches `prompt_id` (spec §4.4 dedupe policy: one
    user prompt = one row, even when multiple Stops fire).

    `summary_dict`: pass `dataclasses.asdict(Summary)` from `lib.aggregator`."""
    path = _history_path(session_id)
    envelope = _build_envelope(
        prompt_id=prompt_id, session_id=session_id,
        user_prompt_text=user_prompt_text, started_at=started_at,
        ended_at=ended_at, summary_dict=summary_dict,
        models_used=models_used,
        has_subagent_other_model=has_subagent_other_model,
        transcript_entries=transcript_entries,
    )
    new_line = json.dumps(envelope, ensure_ascii=False)

    existing: list[str] = []
    if path.exists():
        try:
            existing = [
                ln for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
        except OSError:
            existing = []

    if existing:
        try:
            last = json.loads(existing[-1])
            if last.get("prompt_id") == prompt_id:
                existing[-1] = new_line
                _atomic_write_lines(path, existing)
                return
        except json.JSONDecodeError:
            # Last line is corrupted JSON. Append the new entry rather than
            # try to rewrite — load_session_history will skip the bad line on
            # read, and preserving it leaves a forensic trail.
            pass

    _atomic_write_lines(path, existing + [new_line])


def load_session_history(session_id: str) -> list[dict]:
    """Load entries for a single session. Skips corrupted/unsupported lines."""
    path = paths.state_dir() / session_id / "history.jsonl"
    if not path.exists():
        return []
    out: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[history_store] failed to read {path}: {exc}", file=sys.stderr)
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            print(f"[history_store] skip corrupted line in {path}", file=sys.stderr)
            continue
        if data.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
            print(f"[history_store] unsupported schema_version={data.get('schema_version')} in {path}", file=sys.stderr)
            continue
        out.append(data)
    return out


def load_all_sessions_history() -> list[dict]:
    """Glob `state/*/history.jsonl` and merge all entries into one list.
    Each entry already carries `session_id`. Order: file glob order then
    line order within each file. Caller can sort by started_at if needed."""
    root = paths.state_dir()
    out: list[dict] = []
    for hist in sorted(root.glob("*/history.jsonl")):
        sess = hist.parent.name
        out.extend(load_session_history(sess))
    return out
