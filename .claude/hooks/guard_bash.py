#!/usr/bin/env python3
"""PreToolUse hook for shell commands (docs/claude/collaboration-rules.md, sections 1, 4 and 5).

Two jobs, both read-only:

1. A command that commits, pushes, merges, rebases or tags gets the current branch and repository
   path attached, so the wrong branch is noticed at once instead of after the fact.
2. A remote command that could leave the box unreachable (boot settings, mounts, disk checks,
   network, reboot) or that kills processes by name is turned into a question for the owner.
   It is never denied here: whether to go ahead is the owner's call.

Anything this script cannot parse is let through unchanged.
"""

import json
import re
import subprocess
import sys

REMOTE_TOOLS = ("mcp__dsh__dsh_run",)

# ssh/scp/rsync in command position, so that the words inside a commit message do not count.
_REMOTE = re.compile(r"(?:^|&&|\|\||;|\||\$\(|\n)\s*(?:sudo\s+)?(?:sshpass\s+\S+\s+\S+\s+)?(?:ssh|scp|rsync)\b")

_BOOT_FILE = r"(?:armbianEnv\.txt|uEnv\.txt|extlinux\.conf|boot\.cmd|boot\.scr|/etc/fstab|/boot/)"
_WRITES = r"(?:\bsed\s+-\w*i|\btee\b|\bcp\b|\bmv\b|\brm\b|\bnano\b|\bvim?\b|\bdd\b|>>?\s*\S*" + _BOOT_FILE + ")"

_RISKS = (
    ("按名字杀进程（pkill -f / killall），可能杀掉自己的连接",
     re.compile(r"\bpkill\s+(?:-\w+\s+)*-\w*f|\bkillall\b")),
    ("重启或关机",
     re.compile(r"\b(?:reboot|poweroff|halt)\b|\bshutdown\s|\bsystemctl\s+(?:reboot|poweroff|halt)\b")),
    ("磁盘检查或改文件系统",
     re.compile(r"\b(?:e2fsck|fsck(?:\.\w+)?|tune2fs|resize2fs|mkfs(?:\.\w+)?|fdisk|parted|wipefs)\b"
                r"|\bdd\s[^|;\n]*\bof=/dev/")),
    ("改挂载方式",
     re.compile(r"\bmount\s[^|;\n]*\bremount\b|\bumount\b")),
    ("网络、防火墙或 Tailscale",
     re.compile(r"\btailscale\s+(?:down|logout)\b"
                r"|\bsystemctl\s+(?:stop|disable|mask|restart)\s+\S*"
                r"(?:tailscaled|NetworkManager|networking|systemd-networkd|sshd?|wpa_supplicant)"
                r"|\bnmcli\s+(?:con|connection|dev|device|radio|networking)\s+"
                r"(?:down|delete|modify|mod|disconnect|off)\b"
                r"|\bip\s+(?:link\s+set\s+\S+\s+down|route\s+(?:del|flush)|addr\s+(?:del|flush))\b"
                r"|\bip6?tables\s+(?:-\w*[ADIFPX]\b|--(?:append|delete|insert|flush|policy)\b)"
                r"|\bnft\s+(?:add|delete|flush|-f)\b"
                r"|\bufw\s+(?:enable|deny|reject|delete|reset|default)\b"
                r"|\bnetplan\s+apply\b|\bifdown\b")),
    ("内核或引导更新",
     re.compile(r"\barmbian-(?:update|install)\b|\bupdate-initramfs\b|\b(?:dist|full)-upgrade\b")),
)
_BOOT_WRITE = re.compile(_BOOT_FILE)
_BOOT_WRITE_VERB = re.compile(_WRITES)

# git in command position, so that a commit message or a heredoc that merely mentions it does not count.
_GIT_WRITE = re.compile(r"(?:^|&&|\|\||;|\||\$\()\s*git\s+(?:-C\s+\S+\s+)?(?:commit|push|merge|rebase|tag)\b")
_GIT_SWITCH = re.compile(r"\bgit\s+(?:switch\s+(?:-q\s+)?-[cC]|checkout\s+(?:-q\s+)?-[bB])")
_LEADING_CD = re.compile(r"""^\s*cd\s+(?:"([^"]+)"|'([^']+)'|(\S+))\s*(?:&&|;)""")


def is_remote(tool_name: str, command: str) -> bool:
    return tool_name in REMOTE_TOOLS or bool(_REMOTE.search(command))


def box_risks(command: str) -> list[str]:
    """The kinds of risky change this command would make on a remote machine."""
    found = [label for label, pattern in _RISKS if pattern.search(command)]
    if _BOOT_WRITE.search(command) and _BOOT_WRITE_VERB.search(command):
        found.append("改启动配置（启动参数、fstab、/boot）")
    return found


def git_context(command: str, cwd: str) -> str | None:
    """One line naming the branch and repository a git write is about to act on."""
    if not _GIT_WRITE.search(command):
        return None
    match = _LEADING_CD.match(command)
    directory = next((part for part in match.groups() if part), cwd) if match else cwd

    def git(*args: str) -> str | None:
        try:
            done = subprocess.run(["git", "-C", directory, *args], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            return None
        return done.stdout.strip() if done.returncode == 0 else None

    branch, top = git("rev-parse", "--abbrev-ref", "HEAD"), git("rev-parse", "--show-toplevel")
    if not branch or not top:
        return None
    line = f"提交前核对：钩子运行时的分支是 {branch}，仓库是 {top}。"
    if _GIT_SWITCH.search(command):
        line += "这条命令自己会切分支，以切换之后的分支为准。"
    return line


def decide(payload: dict) -> dict | None:
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    if tool_name == "Bash":
        command = tool_input.get("command")
        command = command if isinstance(command, str) else ""
    else:
        command = "\n".join(value for value in tool_input.values() if isinstance(value, str))
    if not command:
        return None

    output: dict = {"hookEventName": "PreToolUse"}
    if is_remote(tool_name, command):
        risks = box_risks(command)
        if risks:
            output["permissionDecision"] = "ask"
            output["permissionDecisionReason"] = (
                "这条远程命令涉及：" + "；".join(risks) + "。"
                "按协作规范第一节，动手前要确认有退路（TF 救援卡在不在手边），"
                "并讲清最坏会怎样、需要 owner 到现场做什么。停进程请用记下的进程号。"
            )
    if tool_name == "Bash":
        context = git_context(command, str(payload.get("cwd") or "."))
        if context:
            output["additionalContext"] = context
    return {"hookSpecificOutput": output} if len(output) > 1 else None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    result = decide(payload)
    if result:
        print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
