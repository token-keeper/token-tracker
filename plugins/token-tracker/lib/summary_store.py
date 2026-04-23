from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback
from dataclasses import asdict
from pathlib import Path

from lib import paths
from lib.aggregator import Summary
from lib.parser import TurnUsage


SCHEMA_VERSION = 1


def _summary_path(session_id: str) -> Path:
    d = paths.state_dir() / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d / "last_summary.json"


def save_last_summary(session_id: str, summary: Summary) -> None:
    target = _summary_path(session_id)
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "saved_at": time.time(),
        "summary": asdict(summary),
    }
    fd, tmp = tempfile.mkstemp(
        prefix=".tmp-", suffix=".json", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(envelope, f)
        os.replace(tmp, target)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_last_summary(session_id: str) -> Summary | None:
    target = _summary_path(session_id)
    if not target.exists():
        return None
    try:
        with target.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        print(traceback.format_exc(), file=sys.stderr)
        return None

    if data.get("schema_version") != SCHEMA_VERSION:
        print(
            f"[summary_store] unsupported schema_version={data.get('schema_version')} at {target}",
            file=sys.stderr,
        )
        return None

    sd = data.get("summary")
    if not isinstance(sd, dict):
        return None
    try:
        turns = [TurnUsage(**t) for t in sd.get("turns", [])]
        return Summary(
            total_cost=float(sd["total_cost"]),
            total_input_tokens=int(sd["total_input_tokens"]),
            total_output_tokens=int(sd["total_output_tokens"]),
            cache_hit_rate=float(sd["cache_hit_rate"]),
            total_elapsed=float(sd["total_elapsed"]),
            turns=turns,
        )
    except (KeyError, TypeError, ValueError):
        print(traceback.format_exc(), file=sys.stderr)
        return None
