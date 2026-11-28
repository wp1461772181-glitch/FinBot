"""The two old 长期指令 of docs/finbot-humanlike-plan-2026-11-28 (section C), as the owner decided on 11-28 (「全部按你推荐的来」).

- 「说到"那些企业"等泛称时，应先对应到具体公司，再据此搜索」: archived (it made 「这些企业看着就挺狠呐」 a question about which companies,
  right after it had listed them).  Archived, not deleted: the memory page can restore it.
- 「回答前先上网搜索」: rewritten to 「涉及最新消息和行情时先联网查」 (as written it asked for a web search before small talk too).  The
  edit is recorded with the old text, as an edit on the memory page is.

Only items whose text starts with these words are touched; anything else is left as it is.  Without ``--apply`` it prints what it would do.

    python -m scripts.humanlike_memory_cleanup [--apply]
"""
from __future__ import annotations

import argparse
import sys

ARCHIVE_PREFIXES = ("用户要求：说到“那些企业”等泛称时，应先对应到具体公司",)
REWRITE = {"回答前先上网搜索": "涉及最新消息和行情时先联网查"}


def planned(items: list[dict]) -> list[tuple[str, dict, str | None]]:
    """(action, item, new text) for the owner's active 长期指令 the plan names."""
    out = []
    for item in items:
        if item.get("status") != "active" or item.get("kind") != "instruction":
            continue
        text = str(item.get("text") or "")
        if text.startswith(ARCHIVE_PREFIXES):
            out.append(("archive", item, None))
            continue
        for old, new in REWRITE.items():
            if text.startswith(old):
                out.append(("rewrite", item, new))
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.humanlike_memory_cleanup")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    from app import agent_profile as profile
    from app import memory_events
    from app.sentinel_bridge import owner_hash_from_login_config
    owner = owner_hash_from_login_config()
    if not owner:
        print("没有配置 owner")
        return 1
    plan = planned(profile.list_items(owner, include_archived=False))
    if not plan:
        print("没有要处理的条目")
        return 0
    for action, item, new in plan:
        line = f"{action} #{str(item['id'])[:8]} 「{item['text']}」" + (f" → 「{new}」" if new else "")
        if args.apply:
            done = (profile.archive_item(owner, str(item["id"]), by=memory_events.PAGE) if action == "archive"
                    else profile.update_item(owner, str(item["id"]), {"text": new}, by=memory_events.PAGE))
            line += " ✓" if done else " ✗（没找到）"
        print(line)
    if not args.apply:
        print("（只是预览；加 --apply 才会改）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
