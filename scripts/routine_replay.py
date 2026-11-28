"""Run one scheduled task (a brief routine) once, on the shadow database, and print what came of it (stage 6a).

  set -a; . /opt/finbot/ruler.env; set +a; export RULER_DATABASE_URL="$DATABASE_URL"
  python -m scripts.routine_replay --instruction "看一下 AAPL 最新的公告，有值得做预测的新材料就建议做一份" [--symbols AAPL] [--keep]

Run it from the code under test (the shadow's ``/opt/finbot/ruler-src`` with the branch synced in).  It refuses unless the shadow
environment is loaded (the same check as ``scripts.wake_replay``).  The task is made under the owner's default bot, run once through the
task runner exactly as the scheduler runs it (``agent_task_runner.run_brief``), and deleted afterwards unless ``--keep``.  Nothing the
shadow writes is sent: the shadow's outbox rows are read by no bridge.  Prints the engine, the run's status, the answer, the inbox items
the run made and any message it queued.  With ``--press`` each 待你确认 item is then made into its card (``agent_tasks.mint_card``) and
its 同意 button pressed through the shadow API (``--base``), as the owner would in the inbox; the press turn's status and answer are printed."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.wake_replay import refusal  # noqa: E402


def _confirm_value(conversation_id: str, request_id: str) -> str | None:
    """The 同意 button's value of the card ``mint_card`` stored (it holds the one-time capability: it never leaves this process)."""
    from sqlalchemy import select
    from app.agent_chat_models import AgentMessage
    from app.database import SessionLocal
    with SessionLocal() as db:
        for calls in db.scalars(select(AgentMessage.tool_calls).where(AgentMessage.conversation_id == uuid.UUID(conversation_id),
                                                                      AgentMessage.role == "assistant").order_by(AgentMessage.sequence.desc())):
            card = (calls or {}).get("clarification") or {}
            if card.get("request_id") == request_id:
                return next((c["value"] for c in card.get("choices") or [] if str(c.get("value", "")).startswith("confirm:")), None)
    return None


async def _press(credential: str, owner: str, task_id, base: str) -> list[dict]:
    """Mint and press every 待你确认 item of the task through the API; what each press turn ended with."""
    import httpx
    from sqlalchemy import select
    from app import agent_tasks as tasks
    from app.agent_chat_models import AgentInboxItem
    from app.database import SessionLocal
    with SessionLocal() as db:
        items = [str(i.id) for i in db.scalars(select(AgentInboxItem).where(AgentInboxItem.task_id == task_id, AgentInboxItem.section == "confirm"))]
    pressed = []
    for item in items:
        card = await tasks.mint_card(credential, item)
        value = _confirm_value(card["conversation_id"], card["request_id"])
        # A run's conversation is not the bot's own line: the browser opens it as a conversation outside a line and its turns carry
        # ``catalog_model`` "" (the catalog's default), not ``bot_id`` (ChatSessionProvider).
        body = {"message": value, "pending_request_id": card["request_id"], "conversation_id": card["conversation_id"], "catalog_model": ""}
        answer, status = "", None
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream("POST", f"{base}/agent-chat/stream", json=body, headers={"X-Chat-Session": credential}) as response:
                if response.status_code != 200:
                    pressed.append({"item": item, "http": response.status_code, "detail": (await response.aread()).decode()[:300]})
                    continue
                event = None
                async for line in response.aiter_lines():
                    if line.startswith("event:"):
                        event = line[6:].strip()
                    elif line.startswith("event:") is False and event == "answer_reset":
                        answer = ""       # the kernel took back what it had streamed
                    elif line.startswith("data:") and event in ("delta", "done", "error"):
                        data = json.loads(line[5:])
                        if event == "delta":
                            answer += data.get("text") or ""
                        else:
                            status = data.get("status") or data.get("code")
        pressed.append({"item": item, "http": response.status_code, "status": status, "answer": answer[:600]})
    return pressed


def _report(owner: str, task_id, started: datetime) -> dict:
    from sqlalchemy import select
    from app.agent_chat_models import AgentInboxItem, AgentMessage, AgentTask, AgentTelegramMessage
    from app.database import SessionLocal
    with SessionLocal() as db:
        task = db.get(AgentTask, task_id)
        conversation = task.last_conversation_id if task else None
        items = db.scalars(select(AgentInboxItem).where(AgentInboxItem.task_id == task_id)).all()
        answer = db.scalars(select(AgentMessage).where(AgentMessage.conversation_id == conversation, AgentMessage.role == "assistant")
                            .order_by(AgentMessage.sequence.desc())).first() if conversation else None
        calls = [((c or {}).get("calls") or []) for c in db.scalars(select(AgentMessage.tool_calls).where(
            AgentMessage.conversation_id == conversation, AgentMessage.role == "assistant"))] if conversation else []
        queued = db.scalars(select(AgentTelegramMessage).where(AgentTelegramMessage.owner_hash == owner, AgentTelegramMessage.source == "notify",
                                                               AgentTelegramMessage.created_at >= started)).all()
        protocol = (answer.tool_calls or {}) if answer else {}
        return {"status": task.last_status if task else None, "conversation_id": str(conversation) if conversation else None,
                "engine": ((protocol.get("audit") or {}).get("engine")), "answer": answer.content if answer else None,
                "tools": [((call.get("function") or {}).get("name")) for group in calls for call in group if isinstance(call, dict)],
                "writes": (protocol.get("audit") or {}).get("writes"),
                "inbox": [{"section": i.section, "kind": i.kind, "title": i.title, "operation": (i.payload or {}).get("operation", {}).get("name")}
                          for i in items],
                "notify": [{"channel": m.channel, "status": m.status, "text": m.text[:300]} for m in queued]}


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="在影子库上真跑一次定时任务（只在影子环境里）")
    parser.add_argument("--instruction", required=True)
    parser.add_argument("--symbols", default="", help="逗号分隔；不给则用研究队列")
    parser.add_argument("--keep", action="store_true", help="跑完不删任务")
    parser.add_argument("--press", action="store_true", help="把「待你确认」的建议转成卡片并点同意（经影子接口）")
    parser.add_argument("--base", default="http://127.0.0.1:9031")
    args = parser.parse_args(argv)
    reason = refusal()
    if reason:
        print(reason, file=sys.stderr)
        return 2
    from app import agent_tasks as tasks
    from app.agent_bots import ensure_default_bot
    from app.agent_chat_store import owner_hash
    from app.agent_task_runner import owner_credential, run_brief
    credential = owner_credential()
    if not credential:
        print("影子环境里没有所有者登录配置。", file=sys.stderr)
        return 2
    owner = owner_hash(credential)
    bot = ensure_default_bot(owner)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    fields = {"name": "影子回放 · 定时任务", "kind": "brief", "schedule_kind": "daily", "schedule_time": "09:00", "timezone": "Asia/Shanghai",
              "instruction": args.instruction, "scope": "symbols" if symbols else "research_queue", "symbols": symbols, "bot_id": str(bot.id)}
    task = tasks.create_task(owner, fields)
    task_id = uuid.UUID(str(task["id"]))
    started = datetime.now(UTC)
    try:
        status = await run_brief(task_id, credential, now=started)
        report = {"run": status, **_report(owner, task_id, started)}
        if args.press:
            report["pressed"] = await _press(credential, owner, task_id, args.base)
    finally:
        if not args.keep:
            tasks.delete_task(owner, task["id"])
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
