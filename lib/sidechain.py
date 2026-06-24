from __future__ import annotations

import json
import re
from pathlib import Path

from lib.parser import (
    SubagentUsage,
    parse_agent_tool_uses,
    parse_async_launch,
    parse_sidechain_assistant,
)


# agent_id is interpolated into a filename (`agent-{agent_id}.jsonl`) and
# comes from the main jsonl, which is external input. Restrict to a safe
# alphabet so attackers can't inject `../` segments or absolute paths to read
# arbitrary files via the path traversal.
_SAFE_AGENT_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def _is_safe_agent_id(agent_id: str) -> bool:
    return bool(isinstance(agent_id, str) and _SAFE_AGENT_ID.fullmatch(agent_id))


def find_sidechain_dir(transcript_path: str) -> Path | None:
    """transcript_path 옆의 sidechain 디렉터리를 반환한다.

    예: ~/.claude/projects/{project}/{session_id}.jsonl
        → ~/.claude/projects/{project}/{session_id}/subagents
    실제 디렉터리가 존재하지 않으면 None.
    """
    if not transcript_path:
        return None
    try:
        path = Path(transcript_path)
    except (TypeError, ValueError):
        return None
    candidate = path.parent / path.stem / "subagents"
    if candidate.is_dir():
        return candidate
    return None


def extract_async_launches(
    entries: list[dict],
) -> dict[str, tuple[str, str, str]]:
    """메인 jsonl entries에서 async Agent 호출의 (tool_use_id, agent_type, model) 매핑.

    1) `parse_agent_tool_uses`로 모든 assistant 라인의 (id, subagent_type, model) 룩업.
    2) user 라인의 async_launched toolUseResult에서 (tool_use_id, agent_id) 추출.
    3) 둘을 합쳐 {agent_id: (tool_use_id, agent_type, model)} 반환.

    `model`은 caller가 dispatch 시 명시한 값(input.model). sidechain assistant의
    `message.model`이 더 정확하므로 이 값은 fallback 용도다.
    agent_type 정보가 없으면 빈 문자열.
    """
    # tool_use_id → (agent_type, model)
    info_by_tu_id: dict[str, tuple[str, str]] = {}
    for e in entries:
        for tu_id, sa_type, model in parse_agent_tool_uses(e):
            info_by_tu_id[tu_id] = (sa_type, model)

    # agent_id → (tool_use_id, agent_type, model)
    out: dict[str, tuple[str, str, str]] = {}
    for e in entries:
        pair = parse_async_launch(e)
        if pair is None:
            continue
        tool_use_id, agent_id = pair
        agent_type, model = info_by_tu_id.get(tool_use_id, ("", ""))
        out[agent_id] = (tool_use_id, agent_type, model)
    return out


def extract_async_launches_from_file(
    transcript_path: str,
) -> dict[str, tuple[str, str, str]]:
    """메인 jsonl 전체를 한 줄씩 stream parse 해서 async launches 매핑을 반환.

    `extract_async_launches`(entries 리스트 in-memory 버전)는 caller가 넘긴
    엔트리 리스트만 본다. Stop hook의 `_read_tail(transcript_path, offset)`은
    `offset` 뒤만 읽으므로, dispatch가 이전 turn에서 일어나고 다음 turn에 Stop
    이 발화하면 dispatch 라인을 못 본다 → launches 누락 → sub 매칭 실패.

    이 함수는 offset을 무시하고 jsonl을 처음부터 끝까지 읽는다. 한 줄씩 stream
    parse 하므로 메모리 효율은 라인 1개 분.

    빈 경로/없는 파일/읽기 실패는 silent로 빈 dict 반환.
    invalid JSON 라인은 skip하고 진행.
    """
    if not transcript_path:
        return {}
    try:
        path = Path(transcript_path)
    except (TypeError, ValueError):
        return {}
    if not path.is_file():
        return {}

    # tool_use_id → (agent_type, model)
    info_by_tu_id: dict[str, tuple[str, str]] = {}
    # agent_id → (tool_use_id, agent_type, model)
    out: dict[str, tuple[str, str, str]] = {}
    # async_launched 라인이 assistant 라인보다 먼저 오는 경우는 없지만, 방어적으로
    # 두 번 순회하지 않고 한 번에 처리한다 — async_launched 도달 시 lookup이
    # 이미 채워져 있는 표준 순서를 가정. 이는 기존 in-memory 변형과 동일한
    # 가정이며, 실제 jsonl 순서가 보장하므로 안전.
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # 1) assistant Agent tool_use → lookup 채움
                for tu_id, sa_type, model in parse_agent_tool_uses(entry):
                    info_by_tu_id[tu_id] = (sa_type, model)
                # 2) user async_launched → out에 매핑 추가
                pair = parse_async_launch(entry)
                if pair is not None:
                    tool_use_id, agent_id = pair
                    agent_type, model = info_by_tu_id.get(tool_use_id, ("", ""))
                    out[agent_id] = (tool_use_id, agent_type, model)
    except OSError:
        return {}
    return out


# task-notification XML matcher: extract task-id only when status is completed.
# Tolerates whitespace and arbitrary order of <task-id>/<status>.
_COMPLETED_TASK_RE = re.compile(
    r"<task-notification\b[^>]*>(?P<body>.*?)</task-notification>",
    re.DOTALL,
)
_TASK_ID_RE = re.compile(r"<task-id>\s*([A-Za-z0-9_-]+)\s*</task-id>")
_STATUS_COMPLETED_RE = re.compile(r"<status>\s*completed\s*</status>", re.IGNORECASE)


def _completed_agent_ids_in_text(text: str) -> list[str]:
    """task-notification XML 텍스트에서 status=completed인 task-id 들을 모두 추출."""
    out: list[str] = []
    for m in _COMPLETED_TASK_RE.finditer(text):
        body = m.group("body")
        if not _STATUS_COMPLETED_RE.search(body):
            continue
        tid = _TASK_ID_RE.search(body)
        if tid:
            out.append(tid.group(1))
    return out


def _completed_agent_ids(entry: dict) -> list[str]:
    """엔트리에서 task-notification status=completed의 task-id 집합.

    Claude Code는 같은 task-notification XML을 여러 라인 형태로 흘리며,
    버전·OS·세션 전환에 따라 다른 형태로 나타난다. 회귀로 일부 형태를 놓치면
    active가 영원히 줄지 않아 token-tracker 출력이 silent로 묶이는 버그가
    발생한다. 다음 형태들을 모두 cover한다:

      1) type=="queue-operation"  — 최상위 `content`가 XML 텍스트
         (실측 가장 많음. 메인 jsonl의 권위적 신호)
      2) type=="user"             — `message.content`가 XML 텍스트 (string)
      3) type=="user"             — `message.content`가 list of dict
         (각 block의 `text` 또는 `content` 필드에 XML 텍스트)
      4) type=="attachment"       — `attachment.type`=="queued_command"이고
         `attachment.prompt` 또는 `attachment.content`에 XML 텍스트

    `_completed_agent_ids_in_text`가 status=completed인 것만 골라내므로
    무관한 텍스트(예: tool_result에 XML 일부가 섞여 들어와도 status가
    completed가 아니면 매칭 0)에는 영향 없음.
    """
    if not isinstance(entry, dict):
        return []
    # Form 1: queue-operation line with top-level `content` as XML string
    if entry.get("type") == "queue-operation":
        content = entry.get("content")
        if isinstance(content, str) and "<task-notification" in content:
            return _completed_agent_ids_in_text(content)
    # Form 2 & 3: user line with message.content as string or list of blocks
    msg = entry.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str) and "<task-notification" in content:
            return _completed_agent_ids_in_text(content)
        if isinstance(content, list):
            ids: list[str] = []
            for blk in content:
                if not isinstance(blk, dict):
                    continue
                text = blk.get("text") or blk.get("content")
                if isinstance(text, str) and "<task-notification" in text:
                    ids.extend(_completed_agent_ids_in_text(text))
            if ids:
                return ids
    # Form 4: attachment with queued_command (prompt 또는 content)
    attachment = entry.get("attachment")
    if isinstance(attachment, dict) and attachment.get("type") == "queued_command":
        for field in ("prompt", "content"):
            value = attachment.get(field)
            if isinstance(value, str) and "<task-notification" in value:
                return _completed_agent_ids_in_text(value)
    return []


def count_active_async_agents(entries: list[dict]) -> int:
    """현재 launch됐지만 아직 completed 알림이 없는 async agent 수.

    Stop hook에서 활성 background agent가 1개라도 있으면 출력 silent 처리에
    사용된다. 시각적으로: 7개 background dispatch → 7개 모두 끝날 때까지 token-tracker
    한 줄 요약은 안 보이고, 마지막에 1번만 emit.

    Args:
        entries: 메인 jsonl 엔트리 리스트 (Stop hook이 _read_tail로 읽은 것)

    Returns:
        len(launched_agent_ids - completed_agent_ids)
    """
    launches = extract_async_launches(entries)
    launched_ids = set(launches.keys())
    completed_ids: set[str] = set()
    for e in entries:
        for aid in _completed_agent_ids(e):
            completed_ids.add(aid)
    return len(launched_ids - completed_ids)


def _scan_completed_task_notifications(transcript_path: str) -> set[str]:
    """메인 jsonl을 한 번 read하면서 task-notification status=completed인 task-id 집합 반환."""
    completed_ids: set[str] = set()
    try:
        path = Path(transcript_path)
    except (TypeError, ValueError):
        return completed_ids
    if not path.is_file():
        return completed_ids
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for aid in _completed_agent_ids(entry):
                    completed_ids.add(aid)
    except OSError:
        return completed_ids
    return completed_ids


def count_active_async_agents_from_file(transcript_path: str) -> int:
    """`count_active_async_agents`의 file-based 변형.

    완료 판별은 메인 jsonl의 task-notification(status=completed) 한 가지 권위
    신호만 사용한다. 과거에 sidechain jsonl에 assistant 라인이 1개라도 있으면
    완료로 간주하는 OR 분기를 둔 적이 있었으나 (T16), 이는 sub가 첫 응답만
    작성하고 더 많은 turn을 만드는 케이스에서 false-positive를 일으켜 제거됨.

    `_read_tail` offset 한계는 `extract_async_launches_from_file`로 이미 해결됨.
    """
    if not transcript_path:
        return 0
    try:
        path = Path(transcript_path)
    except (TypeError, ValueError):
        return 0
    if not path.is_file():
        return 0

    launches = extract_async_launches_from_file(transcript_path)
    if not launches:
        return 0

    completed_via_notification = _scan_completed_task_notifications(transcript_path)

    active = 0
    for agent_id in launches.keys():
        if agent_id in completed_via_notification:
            continue
        active += 1
    return active


def collect_sidechain_subagents(
    sidechain_dir: Path,
    launches: dict[str, tuple[str, str, str]],
) -> list[SubagentUsage]:
    """sidechain_dir 안의 agent-{agent_id}.jsonl 파일들을 파싱해 SubagentUsage 리스트 반환.

    각 파일의 type=="assistant" 라인을 모두 추출하므로 한 agent가 여러 turn을
    돌렸으면 그 수만큼 SubagentUsage가 생성된다. 파일 없거나 읽기 실패 시 silent skip.
    한 줄이 invalid JSON이면 그 줄만 skip하고 진행.

    `launches`의 model은 fallback용. sidechain assistant 라인이 자체 model을
    노출하면 그 값이 우선이고, 없을 때만 launches의 model로 채운다.
    """
    out: list[SubagentUsage] = []
    if not isinstance(sidechain_dir, Path):
        sidechain_dir = Path(sidechain_dir)
    sidechain_resolved = sidechain_dir.resolve()
    for agent_id, (tool_use_id, agent_type, fallback_model) in launches.items():
        # Path traversal guard: only allow safe filename characters.
        if not _is_safe_agent_id(agent_id):
            continue
        path = sidechain_dir / f"agent-{agent_id}.jsonl"
        if not path.is_file():
            continue
        # Symlink guard: refuse to follow links — they could point outside
        # sidechain_dir (e.g., to another user's files).
        if path.is_symlink():
            continue
        # Defense in depth: even with the regex + symlink check, ensure the
        # resolved path stays inside sidechain_dir.
        try:
            if not path.resolve().is_relative_to(sidechain_resolved):
                continue
        except (OSError, ValueError):
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    sub = parse_sidechain_assistant(
                        entry,
                        agent_type=agent_type,
                        tool_use_id=tool_use_id,
                    )
                    if sub is not None:
                        # sidechain message.model wins; fall back to launch
                        # input.model only when sidechain didn't expose one.
                        if not sub.model and fallback_model:
                            sub.model = fallback_model
                        sub.agent_id = agent_id
                        out.append(sub)
        except OSError:
            continue
    return out


def collect_sub_tool_names(
    sidechain_dir: Path | str, agent_id: str
) -> list[dict]:
    """Real per-tool usage for one subagent from its sidechain transcript.

    Reads `{sidechain_dir}/agent-{agent_id}.jsonl` and counts every
    `tool_use` block's name across all assistant lines, returning
    [{"name": str, "count": int}] ordered by first appearance. This recovers
    exact tool names — including MCP tools like
    `mcp__claude_ai_Notion__notion-fetch` — which `toolStats` buckets lose.

    Both foreground and async subs write this transcript. Returns an empty
    list when the file is missing/unreadable, so callers keep their fallback
    (bucketed toolStats). Applies the same path-safety guards as
    `collect_sidechain_subagents`."""
    if not isinstance(sidechain_dir, Path):
        sidechain_dir = Path(sidechain_dir)
    if not _is_safe_agent_id(agent_id):
        return []
    try:
        sidechain_resolved = sidechain_dir.resolve()
    except (OSError, ValueError):
        return []
    path = sidechain_dir / f"agent-{agent_id}.jsonl"
    if not path.is_file() or path.is_symlink():
        return []
    try:
        if not path.resolve().is_relative_to(sidechain_resolved):
            return []
    except (OSError, ValueError):
        return []

    counts: dict[str, int] = {}
    order: list[str] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = entry.get("message") if isinstance(entry, dict) else None
                if not isinstance(msg, dict):
                    continue
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "tool_use":
                        continue
                    name = block.get("name")
                    if not isinstance(name, str) or not name:
                        continue
                    if name not in counts:
                        counts[name] = 0
                        order.append(name)
                    counts[name] += 1
    except OSError:
        return []
    return [{"name": n, "count": counts[n]} for n in order]
