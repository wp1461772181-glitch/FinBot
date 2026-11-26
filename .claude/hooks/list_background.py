#!/usr/bin/env python3
"""Stop hook: when a turn ends, show the owner which background commands are still running.

docs/claude/collaboration-rules.md, section 5: the owner should not have to open the background
panel to find out that something is idling. This reads the session transcript, pairs each
background command with its completion notice, and lists the ones that have none.

It only reports. It never blocks the turn from ending, and prints nothing when nothing is running.
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
    return f"还有 {len(tasks)} 个后台命令在运行：\n" + "\n".join(rows)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        path = payload["transcript_path"]
        with open(path, encoding="utf-8", errors="replace") as transcript:
            text = message_for(running_tasks(transcript))
    except (ValueError, KeyError, TypeError, OSError):
        return 0
    if text:
        print(json.dumps({"systemMessage": text}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
