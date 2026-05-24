#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path


def _setup_sys_path() -> Path:
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        root = Path(env)
    else:
        root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    return root


def _log_error(msg: str) -> None:
    try:
        from lib.paths import log_dir
        log_file = log_dir() / "error.log"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


# Synthetic prompts that Claude Code surfaces through UserPromptSubmit but are
# not real human input (background-task completion notifications, system
# reminders, command-message wrappers). If we let these bump the offset, the
# windowed `_read_tail` in on_stop.py would skip earlier dispatch turns and
# lose the binding between Agent tool_use_ids and their subagent results —
# the user reported regression "sub 0개" after 7 background reviewers
# completed in distinct turns.
#
# Every entry here is a literal prefix check applied to a `lstrip()`-ed
# prompt. Conservative list: only patterns that the user never originates
# from a human input. Slash commands (`<command-name>`), bash invocations
# (`<bash-input>`), and command stdout wrappers are TRIGGERED by the user
# and should keep updating offset like normal prompts.
_SYNTHETIC_PROMPT_PREFIXES = (
    "<task-notification",
    "<system-reminder",
)


def _is_synthetic_prompt(prompt: object) -> bool:
    """True when the UserPromptSubmit payload's `prompt` is a system-injected
    event (background task completion, system reminder), not a human prompt.

    Why this matters: Claude Code fires UserPromptSubmit for these synthetic
    events too. If we update offset on every one, the on_stop hook's
    `_read_tail(offset)` window walks past the dispatch turn that issued the
    parent `Agent` tool_use, leaving subs with no parent turn to attach to.
    Symptom: "sub 0개" in the final emit even when sidechain jsonls are full
    of completed work.

    Conservative: when in doubt (non-string prompt, unrecognized shape),
    treat as real user input and update offset — current behavior preserved.
    """
    if not isinstance(prompt, str):
        return False
    head = prompt.lstrip()
    return head.startswith(_SYNTHETIC_PROMPT_PREFIXES)


def main() -> int:
    _setup_sys_path()
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
        session_id = hook_input.get("session_id")
        transcript_path = hook_input.get("transcript_path")
        if not session_id or not transcript_path:
            return 0

        # Skip offset update for system-injected synthetic prompts. The real
        # user input's offset must persist across N task-notification
        # interruptions so on_stop's tail still includes the dispatch turn.
        if _is_synthetic_prompt(hook_input.get("prompt")):
            return 0

        from lib.state import save_state
        import secrets

        size = os.path.getsize(transcript_path) if os.path.exists(transcript_path) else 0
        # spec §4.4.1: real user prompt에만 prompt_id 발급. synthetic은 위에서
        # early return되므로 여기 도달하지 않음. 결과적으로 synthetic event 후
        # 발생하는 Stop은 직전 real prompt의 prompt_id로 누적된다 (의도된 동작).
        raw_prompt = hook_input.get("prompt")
        prompt_text = raw_prompt if isinstance(raw_prompt, str) else ""
        save_state(
            session_id,
            {
                "offset": size,
                "started_at": time.time(),
                "prompt_id": f"p_{secrets.token_hex(3)}",
                "prompt_text": prompt_text,
            },
        )
    except Exception:
        _log_error(f"[on_user_prompt] {traceback.format_exc()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
