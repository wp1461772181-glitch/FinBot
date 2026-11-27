#!/usr/bin/env python3
"""Stop hook: a turn may not end with background commands running unless Claude has told the owner.

docs/claude/collaboration-rules.md, section 5: the owner should not have to open the background
panel to find out that something is idling. This reads the session transcript, pairs each
background command with its completion notice, and finds the ones that have none.

If any are running and Claude's closing message does not mention background work at all, the stop
is held back once and the list is handed to Claude, who then has to account for each one in the
reply the owner reads. A closing message that already talks about it passes untouched, and so does
a turn with nothing running. It never holds the same stop back twice.

Covers shell commands started in the background; scheduled wake-ups and subagents are not listed.
"""

import json
import re
import sys
from datetime import datetime

_ENDED = re.compile(r"<task-id>([\w-]+)</task-id>")


def running_tasks(lines) -> list[dict]:
    """Background commands that were started and have no completion notice yet, oldest first."""
    described: dict[str, str] = {}  # tool_use id -> what the command was for
    started: dict[str, dict] = {}  # task id -> {"what", "at"}
    ended: set[str] = set()
    for line in lines:
        if "task-id" in line:
            ended.update(_ENDED.findall(line))
        if "run_in_background" not in line and "backgroundTaskId" not in line and "TaskStop" not in line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        message = row.get("message")
        blocks = message.get("content") if isinstance(message, dict) else None
        blocks = blocks if isinstance(blocks, list) else []
        if row.get("type") == "assistant":
            for block in blocks:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                arguments = block.get("input") if isinstance(block.get("input"), dict) else {}
                if block.get("name") == "TaskStop":
                    task_id = arguments.get("task_id") or arguments.get("shell_id")
                    if isinstance(task_id, str):
                        ended.add(task_id)
                elif arguments.get("run_in_background"):
                    what = arguments.get("description") or arguments.get("command") or ""
                    described[str(block.get("id"))] = str(what).strip().splitlines()[0][:80] if what else ""
        result = row.get("toolUseResult")
        task_id = result.get("backgroundTaskId") if isinstance(result, dict) else None
        if isinstance(task_id, str) and task_id:
            use_id = next((str(block.get("tool_use_id")) for block in blocks
                           if isinstance(block, dict) and block.get("type") == "tool_result"), "")
            started[task_id] = {"what": described.get(use_id, ""), "at": row.get("timestamp")}
    return [{"id": task_id, **info} for task_id, info in started.items() if task_id not in ended]


def local_clock(timestamp) -> str:
    """The transcript stores UTC; the owner reads local time."""
    try:
        moment = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return "时间不详"
    return moment.astimezone().strftime("%H:%M")


def message_for(tasks: list[dict]) -> str | None:
    if not tasks:
        return None
    rows = [f"- {task['what'] or '（没有说明）'}（{local_clock(task['at'])} 启动，编号 {task['id']}）" for task in tasks]
    return (
        f"还有 {len(tasks)} 个后台命令在运行，而你的收尾没有向 owner 提到后台：\n" + "\n".join(rows)
        + "\n请在给 owner 的话里逐个说明：它在等什么、什么会叫醒你、最晚什么时候结束；没用的现在就停掉。"
    )


def last_reply(lines) -> str:
    """The text of Claude's most recent message in the transcript."""
    latest = ""
    for line in lines:
        if '"assistant"' not in line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("type") != "assistant":
            continue
        message = row.get("message")
        blocks = message.get("content") if isinstance(message, dict) else None
        texts = [block.get("text", "") for block in blocks or []
                 if isinstance(block, dict) and block.get("type") == "text"]
        if any(text.strip() for text in texts):
            latest = "\n".join(texts)
    return latest


def decide(payload: dict, lines: list[str]) -> dict | None:
    """Hold the stop back when something is running and the closing message is silent about it."""
    if payload.get("stop_hook_active"):
        return None
    reason = message_for(running_tasks(lines))
    if reason is None:
        return None
    closing = payload.get("last_assistant_message")
    closing = closing if isinstance(closing, str) and closing.strip() else last_reply(lines)
    if "后台" in closing:
        return None
    return {"decision": "block", "reason": reason}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        with open(payload["transcript_path"], encoding="utf-8", errors="replace") as transcript:
            result = decide(payload, transcript.readlines())
    except (ValueError, KeyError, TypeError, OSError):
        return 0
    if result:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
