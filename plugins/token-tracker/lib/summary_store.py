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
from lib.parser import SubagentUsage, TurnUsage


SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = (1, 2)


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


def _turn_from_dict(raw: dict) -> TurnUsage:
    """Reconstruct a TurnUsage from a dict, normalizing across schema versions.

    v1 turns may be missing `subagents` and `agent_tool_use_ids`. v2 turns
    include both, with `subagents` as a list of dicts that we lift back into
    SubagentUsage instances.
    """
    data = dict(raw)
    raw_subs = data.pop("subagents", None) or []
    subs: list[SubagentUsage] = []
    for s in raw_subs:
        if isinstance(s, dict):
            subs.append(SubagentUsage(**s))
    turn = TurnUsage(**data)
    turn.subagents = subs
    return turn


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

    schema_version = data.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        print(
            f"[summary_store] unsupported schema_version={schema_version} at {target}",
            file=sys.stderr,
        )
        return None

    sd = data.get("summary")
    if not isinstance(sd, dict):
        return None
    try:
        turns = [_turn_from_dict(t) for t in sd.get("turns", [])]
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
