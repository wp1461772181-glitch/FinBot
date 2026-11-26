"""The Claude Code hooks under .claude/hooks: what they flag and, as important, what they leave alone."""

import importlib.util
import json
from pathlib import Path

import pytest

_HOOKS = Path(__file__).resolve().parent.parent / ".claude" / "hooks"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _HOOKS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load("guard_bash")
background = _load("list_background")


def _decision(command, tool="Bash"):
    result = guard.decide({"tool_name": tool, "cwd": str(_HOOKS), "tool_input": {"command": command}})
    return (result or {}).get("hookSpecificOutput", {})


@pytest.mark.parametrize("command", [
    "ssh heibao-ts 'pkill -f uvicorn'",
    "ssh root@heibao-ts \"sed -i 's/rw/ro/' /boot/armbianEnv.txt\"",
    "ssh heibao-ts 'e2fsck -fy /dev/mmcblk0p2'",
    "ssh heibao-ts reboot",
    "cd /tmp && ssh heibao-ts 'mount -o remount,ro /'",
    "ssh heibao-ts 'tailscale down'",
    "ssh heibao-ts 'systemctl restart NetworkManager'",
    "ssh heibao-ts 'echo x | tee -a /etc/fstab'",
])
def test_changes_that_could_strand_the_box_become_a_question(command):
    decision = _decision(command)
    assert decision.get("permissionDecision") == "ask" and "第一节" in decision["permissionDecisionReason"]


@pytest.mark.parametrize("command", [
    "ls -la",
    "pkill -f vite",
    "ssh heibao-ts 'cat /etc/fstab; ls /boot/; systemctl status finbot-api'",
    "ssh heibao-ts 'systemctl restart finbot-api && kill 12345'",
    "ssh heibao-ts 'tailscale status; iptables -L -n; journalctl -u finbot-api -n 50'",
    "ssh heibao-ts '/opt/finbot/bin/ruler_shadow.sh up'",
    "rsync -a ruler/ heibao-ts:/opt/finbot/ruler-src/ruler/",
])
def test_ordinary_commands_are_left_alone(command):
    assert "permissionDecision" not in _decision(command)


def test_words_inside_a_commit_message_do_not_count_as_a_remote_command():
    decision = _decision('git commit -m "ask before pkill -f over ssh; reboot notes"')
    assert "permissionDecision" not in decision


def test_the_remote_shell_tool_is_always_treated_as_remote():
    assert _decision("reboot", tool="mcp__dsh__dsh_run").get("permissionDecision") == "ask"
    assert "permissionDecision" not in _decision("uptime", tool="mcp__dsh__dsh_run")


def test_a_git_write_carries_the_branch_and_repository():
    context = _decision("git add . && git commit -m x").get("additionalContext", "")
    assert "分支" in context and "仓库" in context
    assert "切换之后" in _decision("git switch -c topic && git commit -m x").get("additionalContext", "")
    assert "additionalContext" not in _decision("git status")
    assert "additionalContext" not in _decision("cat > notes.txt <<'EOF'\nremember to git commit later\nEOF")


def test_unreadable_input_is_let_through():
    assert guard.decide({"tool_name": "Bash", "tool_input": None}) is None
    assert guard.decide({"tool_name": "Bash", "tool_input": {"command": 7}}) is None


def _started(task_id, use_id, description):
    return [
        json.dumps({"type": "assistant", "message": {"content": [{
            "type": "tool_use", "id": use_id, "name": "Bash",
            "input": {"command": "sleep 60", "description": description, "run_in_background": True}}]}},
            ensure_ascii=False),
        json.dumps({"type": "user", "timestamp": "2026-11-26T11:50:35.000Z",
                    "message": {"content": [{"type": "tool_result", "tool_use_id": use_id, "content": "started"}]},
                    "toolUseResult": {"backgroundTaskId": task_id}}),
    ]


def _notice(task_id):
    return json.dumps({"type": "queue-operation",
                       "content": f"<task-notification>\n<task-id>{task_id}</task-id>\n<status>completed</status>"})


def test_a_background_command_without_a_completion_notice_is_listed():
    lines = _started("aaa111", "toolu_1", "等 CI") + _started("bbb222", "toolu_2", "盯日志") + [_notice("aaa111")]
    tasks = background.running_tasks(lines)
    assert [(task["id"], task["what"]) for task in tasks] == [("bbb222", "盯日志")]
    text = background.message_for(tasks)
    assert "1 个" in text and "盯日志" in text and "bbb222" in text


def test_a_stopped_background_command_is_not_listed():
    stop = json.dumps({"type": "assistant", "message": {"content": [{
        "type": "tool_use", "id": "toolu_9", "name": "TaskStop", "input": {"task_id": "aaa111"}}]}})
    assert background.running_tasks(_started("aaa111", "toolu_1", "等 CI") + [stop]) == []


def test_nothing_running_means_nothing_is_shown():
    assert background.message_for(background.running_tasks(["not json", "{}"])) is None
