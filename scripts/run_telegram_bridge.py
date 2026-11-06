"""Telegram bridge for the personal agent (plan §2.4).

Long-polls the Telegram Bot API with getUpdates (no webhook).  Only handles messages and button presses
from the bound account in the bound chat; strangers are ignored.  Until a chat is bound it answers
only /bind <code> (or /start <code>) in a private chat.  Owner text goes to a bot's line through the agent
chat API (second edition, stage D): a reply to a bot's message goes to that bot, a message starting with
「@名字」 to the bot of that name, anything else to the default bot 「助理」 (whose line the old 「手机」
conversation was folded into).  Each answer starts with the bot's name and is remembered by its Telegram
message id, so replying to it continues with that bot.  Answers go out as plain chat text: no [n] markers
and no sources list (agent_telegram.chat_text); links written in the answer stay.  Consent cards become
inline keyboard buttons with a short id (the real token stays in this process); pressing one sends the
card's own button value to that bot's line, exactly as the web page does, so the write runs through the
same confirmed handler (save to 资料库, index, ...) and the receipt is the bot's own report.  A single-choice
card (「请确认这次指代的公司」) gets one button per choice, pressed the same way with the choice's own value.
Messages the bots queued (notify_telegram, alerts with 也发 Telegram) are sent from the outbox to the
bound chat only.

    python scripts/run_telegram_bridge.py            # long-poll forever
    python scripts/run_telegram_bridge.py --dry-run  # validate config and exit

The bridge reads the bot token and binding from the database (encrypted), the owner credential from
data/personal-chat-login.json.  It calls the local agent-chat stream endpoint via HTTP with a bot id only,
so the model (and its key) comes from the server's catalog for that bot; the API server must be running.
Fails closed when the token is missing; with no chat bound yet it waits for /bind.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

TELEGRAM_API = "https://api.telegram.org"
LOCAL_API = os.environ.get("TELEGRAM_BRIDGE_API_URL", "http://127.0.0.1:8000")
LONG_POLL_TIMEOUT = 60
OUTBOX_CHECK_INTERVAL = 30
MESSAGE_MAX_CHARS = 4000
ANSWER_MAX_CHARS = 3800
# Short ids of cards already pressed, so a second tap is told the card was handled, not that it expired.
USED_CARDS_KEPT = 256
_USED_CARDS: dict[str, None] = {}
# httpx puts the request URL, and with it /bot<token>/, into its error text.
BOT_TOKEN_PATTERN = re.compile(r"\d{5,}:[A-Za-z0-9_-]{30,}")

os.chdir(PROJECT_ROOT)


def _redact(value) -> str:
    return BOT_TOKEN_PATTERN.sub("***", str(value))


def _owner_credential() -> str:
    """Read the configured owner credential, like the task runner."""
    from app.agent_chat_identity import _load_config
    config = _load_config()
    if not config:
        raise SystemExit("no owner credential configured (data/personal-chat-login.json)")
    return config[3]


async def main(dry_run: bool = False) -> int:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    try:
        import httpx
    except ImportError:
        print("httpx is required.  Run: pip install httpx", file=sys.stderr)
        return 1

    credential = _owner_credential()
    from app.agent_chat_store import engine as store_engine, owner_hash
    from app import agent_telegram as tg
    owner = owner_hash(credential)

    bot_token = await asyncio.to_thread(tg.load_bot_token, owner)
    if not bot_token:
        print("Telegram bridge: no bot token saved.  Save one in the settings page first.")
        return 0 if dry_run else 1

    # No chat bound yet is fine: the bridge has to be running to receive the /bind that binds one.
    bind = await asyncio.to_thread(tg.load_bind, owner) or {}
    bound_chat = bind.get("chat_id")
    bound_user = bind.get("user_id")
    del bind  # the decrypted token stays in bot_token only

    if dry_run:
        print("Bot token: ****" + bot_token[-4:])
        print(f"Bound chat: {bound_chat or '(none yet; send /bind <code> to the bot in a private chat)'}")
        print("Model: each bot's model from the server catalog")
        print(f"Local API: {LOCAL_API}")
        return 0

    lock = _single_instance_lock()
    if lock is None:
        print("Telegram bridge: another bridge is already running (data/telegram-bridge.lock).", file=sys.stderr)
        return 1

    global _RUNNER
    _RUNNER = TurnRunner()
    pending_cards: dict[str, dict] = {}
    last_outbox_check = 0.0
    offset = 0
    # UX batch 2 (P4): bots with their own Telegram bot, one polling task each, reconciled every round.
    own_tasks: dict[str, tuple[str, asyncio.Task]] = {}

    print(f"Telegram bridge started.  Chat: {bound_chat or 'none yet, waiting for /bind'}, API: {LOCAL_API}")

    async with httpx.AsyncClient(timeout=httpx.Timeout(LONG_POLL_TIMEOUT + 15)) as client:
        while True:
            try:
                # Re-read the token and binding every round, so a first /bind, an unbind or a new token saved
                # in the settings page takes effect without restarting the bridge.
                latest_token = await asyncio.to_thread(tg.load_bot_token, owner)
                if not latest_token:
                    print("Telegram bridge: the bot token is gone or no longer decrypts.  Stopping.",
                          file=sys.stderr)
                    return 1
                if latest_token != bot_token:
                    bot_token, offset = latest_token, 0  # update ids belong to one bot
                bind = await asyncio.to_thread(tg.load_bind, owner) or {}
                bound_chat, bound_user = bind.get("chat_id"), bind.get("user_id")
                del bind

                await _reconcile_own_channels(client, credential, owner, own_tasks, tg)

                now = time.time()
                if bound_chat is not None and now - last_outbox_check >= OUTBOX_CHECK_INTERVAL:
                    await _deliver_outbox(client, owner, bound_chat, tg)
                    last_outbox_check = now

                updates = await _get_updates(client, bot_token, offset, LONG_POLL_TIMEOUT)
                if updates is None:
                    await asyncio.sleep(5)
                    continue
                for update in updates:
                    if not isinstance(update, dict):
                        continue
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        offset = update_id + 1
                    await _dispatch_update(client, update, credential, owner, bound_chat, bound_user,
                                           pending_cards, tg)
            except Exception as exc:
                print(f"Bridge error: {_redact(exc)}", file=sys.stderr)
                await asyncio.sleep(10)


async def _dispatch_update(client, update: dict, credential: str, owner: str, bound_chat, bound_user,
                           pending_cards: dict, tg) -> None:
    """One update of the shared bot.  Returns as soon as the turn it starts is handed to the runner."""
    message = update.get("message")
    callback = update.get("callback_query")
    if isinstance(message, dict):
        await _handle_message(client, credential, owner, message, bound_chat, bound_user, pending_cards, tg)
    elif isinstance(callback, dict):
        await _handle_callback(client, callback, pending_cards, owner, credential, bound_chat, bound_user, tg)


# --- feedback while a turn runs (Task 10) -------------------------------------------------------------
# A turn takes 20-100 s.  The user sees "typing" at once, a placeholder within 2 s that is edited as the
# stream reports steps (no extra model call), and the full answer as a separate message (so it notifies).
# Turns run as background tasks, one queue per bot: other bots, buttons and the outbox are never held up.
TYPING_INTERVAL = 4.0
PROGRESS_MIN_INTERVAL = 2.0
CONNECT_TIMEOUT = 5.0
BUSY_RETRY_DELAY = 3.0
BUSY_RETRIES = 5
ACK_TEXT = "收到，正在处理……"
QUEUED_TEXT = "收到，排在上一条后面。"
DONE_TEXT = "处理完成，回答见下一条。"
BACKEND_DOWN_TEXT = "后端暂时连不上，提醒不受影响。"
BUSY_GIVEUP_TEXT = "这个对话正在别处回答中，请稍后再发一次。"

_RUNNER: "TurnRunner | None" = None


class BackendUnavailable(Exception):
    """The local API did not accept the connection."""


class ConversationBusy(Exception):
    """The API answered 409 conversation_busy: the same conversation is answering elsewhere."""


class TurnRunner:
    """Runs turns as background tasks: one at a time per key (a bot), different keys in parallel."""

    def __init__(self) -> None:
        self._queues: dict[str, list] = {}
        self._tasks: set[asyncio.Task] = set()

    def busy(self, key: str) -> bool:
        return key in self._queues

    async def submit(self, key: str, job, on_queued=None) -> None:
        queue = self._queues.get(key)
        if queue is not None:
            queue.append(job)
            if on_queued is not None:
                await on_queued()
            return
        self._queues[key] = [job]
        task = asyncio.create_task(self._drain(key))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _drain(self, key: str) -> None:
        queue = self._queues[key]
        try:
            while queue:
                job = queue.pop(0)
                try:
                    await job()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    print(f"Bridge turn error: {_redact(exc)}", file=sys.stderr)
        finally:
            self._queues.pop(key, None)

    async def wait_idle(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


async def _run_turn(client, credential: str, owner: str, chat_id: int, pending_cards: dict, tg,
                    bot_id: str, bot_name: str, text: str, channel: dict | None = None, **press) -> None:
    """Hand one turn to the runner (and tell the user when it has to wait); without a runner run it inline."""
    if _RUNNER is None:
        await _bot_turn(client, credential, owner, chat_id, pending_cards, tg, bot_id, bot_name, text,
                        channel, **press)
        return

    async def job():
        await _bot_turn(client, credential, owner, chat_id, pending_cards, tg, bot_id, bot_name, text,
                        channel, feedback=True, **press)

    async def queued():
        token = channel["token"] if channel else _bot_token_for_send(owner, tg)
        await _send_text(client, token, chat_id, QUEUED_TEXT, markdown=False)

    await _RUNNER.submit(bot_id, job, queued)


async def _keep_typing(client, bot_token: str, chat_id: int) -> None:
    try:
        while True:
            await asyncio.sleep(TYPING_INTERVAL)
            await _send_action(client, bot_token, chat_id)
    except asyncio.CancelledError:
        pass


def _progress_text(kind: str, data: dict) -> str | None:
    """A progress line from a stream step event; None for events that are not steps."""
    if kind == "tool_start" and data.get("name"):
        return f"{ACK_TEXT}\n正在调用：{data['name']}"
    if kind == "status" and data.get("step"):
        return f"{ACK_TEXT}\n进展：{data['step']}"
    return None


class _Progress:
    """The placeholder message: sent at once, edited at most every PROGRESS_MIN_INTERVAL seconds."""

    def __init__(self, client, bot_token: str, chat_id: int) -> None:
        self.client, self.bot_token, self.chat_id = client, bot_token, chat_id
        self.message_id: int | None = None
        self.last_text = ACK_TEXT
        self.last_edit = time.monotonic()

    async def start(self) -> None:
        self.message_id = await _send_text(self.client, self.bot_token, self.chat_id, ACK_TEXT, markdown=False)
        self.last_edit = time.monotonic()

    async def on_event(self, kind: str, data: dict) -> None:
        text = _progress_text(kind, data)
        if text is None or text == self.last_text or self.message_id is None:
            return
        now = time.monotonic()
        if now - self.last_edit < PROGRESS_MIN_INTERVAL:
            return
        self.last_text, self.last_edit = text, now
        await _edit_text(self.client, self.bot_token, self.chat_id, self.message_id, text)

    async def finish(self) -> None:
        if self.message_id is not None:
            await _edit_text(self.client, self.bot_token, self.chat_id, self.message_id, DONE_TEXT)


async def _get_updates(client, bot_token: str, offset: int, timeout: int) -> list | None:
    import httpx
    try:
        response = await client.get(
            f"{TELEGRAM_API}/bot{bot_token}/getUpdates",
            params={"offset": offset, "timeout": timeout, "allowed_updates": ["message", "callback_query"]},
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            print(f"Telegram API error: {_redact(data)}", file=sys.stderr)
            return None
        return data.get("result") or []
    except httpx.TimeoutException:
        return []
    except Exception as exc:
        print(f"Telegram API error: {_redact(exc)}", file=sys.stderr)
        return None


def _from_owner(chat: dict, sender: dict | None, bound_chat: int, bound_user: int | None) -> bool:
    """Only the bound account in the bound chat.  A bind saved before the user id was recorded falls back
    to the chat id, which is the user id in a private chat; a group with no user id is refused."""
    if not isinstance(chat, dict) or chat.get("id") != bound_chat:
        return False
    owner_id = bound_user if bound_user is not None else (bound_chat if chat.get("type") == "private" else None)
    return owner_id is not None and isinstance(sender, dict) and sender.get("id") == owner_id


async def _handle_message(client, credential: str, owner: str, message: dict,
                          bound_chat: int | None, bound_user: int | None, pending_cards: dict, tg):
    chat = message.get("chat", {})
    text = str(message.get("text") or message.get("caption") or "").strip()
    entities = message.get("entities") or []
    bot_cmd = None
    for entity in entities:
        if entity.get("type") == "bot_command" and isinstance(entity.get("offset"), int):
            cmd_text = text[entity["offset"]:entity["offset"] + entity["length"]]
            if cmd_text.startswith("/"):
                bot_cmd = cmd_text
                break
    binding = bool(bot_cmd) and bot_cmd.startswith(("/start", "/bind"))
    if bound_chat is None:
        # Nothing is bound yet: the one thing a chat can do is bind with the code from the settings page.
        if binding:
            await _handle_bind_command(client, chat, message.get("from"), owner, text[len(bot_cmd):].strip(), tg)
        return
    if not _from_owner(chat, message.get("from"), bound_chat, bound_user):
        return
    from app.agent_context_summary import parse_compact_command
    if bot_cmd and not parse_compact_command(text)[0]:
        if binding:
            await _handle_bind_command(client, chat, message.get("from"), owner, text[len(bot_cmd):].strip(), tg)
        return

    if not text:
        return
    upper_text = text.strip().upper()
    if upper_text.startswith(("CONFIRM ", "SKIP ", "LATER ")):
        parts = text.strip().split(maxsplit=1)
        if len(parts) == 2:
            verb, code = parts[0].upper(), parts[1].strip().upper()
            action_map = {"CONFIRM": "confirm", "SKIP": "skip", "LATER": "later"}
            from app import fin_news_engine
            from app.agent_chat_store import owner_hash
            result = await asyncio.to_thread(
                fin_news_engine.handle_inline_confirmation_action,
                code,
                action_map[verb],
                owner_hash=owner_hash(credential),
            )
            bot_token = _bot_token_for_send(owner, tg)
            if result.get("ok"):
                msg = f"已处理（{result.get('confirmation_state')}）。"
            else:
                msg = f"确认码无效或已过期（{result.get('error_code')}）。"
            await _send_text(client, bot_token, bound_chat, msg)
            return
    reply_to = (message.get("reply_to_message") or {}).get("message_id")
    if await _ack_by_reply(bound_chat, reply_to):
        await _send_text(client, _bot_token_for_send(owner, tg), bound_chat, "已确认这条提醒。", markdown=False)
        return
    target = await asyncio.to_thread(tg.route, owner, text, reply_to if isinstance(reply_to, int) else None)
    if not target["text"]:
        return
    compact, focus = parse_compact_command(target["text"])
    if compact:
        await _compact_command(client, credential, owner, bound_chat, tg, target["bot_id"], target["bot_name"], focus)
        return
    await _run_turn(client, credential, owner, bound_chat, pending_cards, tg, target["bot_id"], target["bot_name"],
                    target["text"])


async def _compact_command(client, credential: str, owner: str, chat_id: int, tg, bot_id: str, bot_name: str,
                           focus: str, channel: dict | None = None) -> None:
    """「/压缩 [重点]」: compress this bot's line now and say what happened (the web shows the same line)."""
    import httpx
    bot_token = channel["token"] if channel else _bot_token_for_send(owner, tg)
    try:
        response = await client.post(f"{LOCAL_API}/agent-chat/bots/{bot_id}/compact", json={"focus": focus},
                                     headers={"X-Chat-Session": credential},
                                     timeout=httpx.Timeout(180, connect=CONNECT_TIMEOUT))
        if response.status_code == 200:
            text = str(response.json().get("message") or "完成。")
        else:
            text = "这次压缩没有成功，稍后再试。"
    except Exception:  # noqa: BLE001 - the chat gets a plain sentence, never a traceback
        text = BACKEND_DOWN_TEXT
    prefix = "" if channel else f"【{bot_name}】\n"
    await _send_text(client, bot_token, chat_id, prefix + text, markdown=False)


async def _bot_turn(client, credential: str, owner: str, bound_chat: int, pending_cards: dict, tg,
                    bot_id: str, bot_name: str, text: str, channel: dict | None = None, *,
                    feedback: bool = False, **press):
    """One turn of a bot, sent back as its chat message(s); ``press`` carries a card press (its conversation,
    card id and the button's label).  ``channel`` is the bot's own Telegram bot (UX batch 2, P4): the answer goes
    out through it, without the name in front, since that chat is the bot's alone.  ``feedback`` adds the
    typing indicator and the progress placeholder (the runner turns it on)."""
    bot_token = channel["token"] if channel else _bot_token_for_send(owner, tg)
    typing = progress = None
    if feedback:
        await _send_action(client, bot_token, bound_chat)
        typing = asyncio.create_task(_keep_typing(client, bot_token, bound_chat))
        progress = _Progress(client, bot_token, bound_chat)
        await progress.start()
    try:
        try:
            answer, cards, cid = await _ask_with_retry(client, credential, bot_id, text,
                                                       on_event=progress.on_event if progress else None, **press)
        except BackendUnavailable:
            await _send_text(client, bot_token, bound_chat, BACKEND_DOWN_TEXT, markdown=False)
            return
        except ConversationBusy:
            await _send_text(client, bot_token, bound_chat, BUSY_GIVEUP_TEXT, markdown=False)
            return
    finally:
        if typing:
            typing.cancel()
    keyboard = _make_keyboard(cards, pending_cards, cid, credential, bot_id, bot_name) if cid else None
    # Only a ticking card (``options``) has a web form Telegram lacks; a card with no choices has nothing to
    # answer on either side, and a typed reply works on both, so the note would mislead there.
    ticked = any(isinstance(card, dict) and card.get("options") for card in cards)
    if ticked and not keyboard:
        answer = answer.strip() + "\n\n（这一步需要在网页里选择后确认。）"
    answer = ("" if channel else f"【{bot_name}】\n") + (answer.strip() or ("完成。" if keyboard else "（这条回复没有内容。）"))
    chunks = [answer[i:i+ANSWER_MAX_CHARS] for i in range(0, len(answer), ANSWER_MAX_CHARS)]
    for i, chunk in enumerate(chunks):
        kb = keyboard if i == len(chunks) - 1 else None
        sent = await _send_text(client, bot_token, bound_chat, chunk, inline_keyboard=kb)
        # Each part is remembered with its bot, so replying to any of them continues with that bot.
        if channel:
            await asyncio.to_thread(tg.record_reply, owner, bot_id, chunk, sent, channel["row_id"])
        else:
            await asyncio.to_thread(tg.record_reply, owner, bot_id, chunk, sent)
    if progress:
        await progress.finish()


async def _ask_with_retry(client, credential: str, bot_id: str, text: str, *, on_event=None, **press):
    """``_ask_agent``, waiting out a 409 conversation_busy a few times.  The extra argument is only passed
    when there is a progress callback."""
    extra = {"on_event": on_event} if on_event else {}
    for attempt in range(BUSY_RETRIES + 1):
        try:
            return await _ask_agent(client, credential, bot_id, text, **press, **extra)
        except ConversationBusy:
            if attempt == BUSY_RETRIES:
                raise
            await asyncio.sleep(BUSY_RETRY_DELAY)


async def _handle_bind_command(client, chat: dict, sender: dict | None, owner: str, code: str, tg):
    from app.agent_telegram import TelegramError
    chat_id = chat.get("id")
    bot_token = _bot_token_for_send(owner, tg)
    if chat.get("type") != "private":
        await _send_text(client, bot_token, chat_id, "请在和 bot 的私聊里绑定。")
        return
    if not code:
        await _send_text(client, bot_token, chat_id, "请发送绑定码，例如 /bind abcdef01")
        return
    try:
        # The sender's id is recorded so later messages and button presses can be checked against it.
        result = tg.confirm_bind(owner, code, chat_id, (sender or {}).get("id"))
        bound = result.get("bound")
        if bound:
            await _send_text(client, bot_token, chat_id, "绑定成功！现在可以从这个聊天使用 Agent。")
        else:
            await _send_text(client, bot_token, chat_id, "绑定码无效或已过期。请在设置页面重新生成。")
    except TelegramError as exc:
        await _send_text(client, bot_token, chat_id, f"绑定失败：{_redact(exc)}")


def _bot_token_for_send(owner: str, tg) -> str:
    from app import agent_telegram
    # Not load_bind: before any chat is bound the bridge still has to answer /bind.
    return agent_telegram.load_bot_token(owner) or ""


async def _ask_agent(client, credential: str, bot_id: str, text: str, *, conversation_id: str | None = None,
                     pending_request_id: str | None = None, display_message: str | None = None, on_event=None):
    """One turn of the bot (its line, its model from the server catalog).  Returns the answer as chat text,
    any cards, and the conversation id the turn ran in.  A card press sends the button's value with the
    card id, as the web page does.  ``on_event(kind, data)`` is awaited for each stream event as it arrives.
    Raises BackendUnavailable when the API cannot be reached (5 s) and ConversationBusy on a 409."""
    import codecs

    import httpx
    from app.agent_telegram import sse_events

    body = {"bot_id": bot_id, "message": text[:MESSAGE_MAX_CHARS]}
    if conversation_id:
        body["conversation_id"] = conversation_id
    if pending_request_id:
        body["pending_request_id"] = pending_request_id
        if display_message:
            body["display_message"] = display_message[:120]
    raw = ""
    pending = ""
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    try:
        async with client.stream(
            "POST",
            f"{LOCAL_API}/agent-chat/stream",
            json=body,
            headers={"X-Chat-Session": credential, "Accept": "text/event-stream"},
            timeout=httpx.Timeout(300, connect=CONNECT_TIMEOUT),
        ) as response:
            if response.status_code == 409:
                raise ConversationBusy()
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                piece = decoder.decode(chunk)
                raw += piece
                if on_event:
                    pending += piece
                    while "\n\n" in pending:
                        block, pending = pending.split("\n\n", 1)
                        for kind, data in sse_events(block + "\n\n"):
                            await on_event(kind, data)
    except (ConversationBusy, BackendUnavailable):
        raise
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise BackendUnavailable() from exc
    except Exception as exc:
        raw += "\n\n" + "event: delta\ndata: " + json.dumps({"text": f"\n\n（Agent 回答出错：{_redact(exc)}）"}, ensure_ascii=False) + "\n\n"
    return format_turn(sse_events(raw))


def format_turn(events: list[tuple[str, dict]]):
    """The answer as Telegram chat text (no [n] markers, no sources list), the cards and the conversation id
    of a parsed stream.  The citations event is the web page's; Telegram does not list it."""
    from app.agent_telegram import chat_text
    answer_parts: list[str] = []
    cards: list[dict] = []
    unverified: list[dict] = []
    conversation_id = None
    for kind, data in events:
        if kind == "conversation":
            conversation_id = data.get("conversation_id")
        elif kind == "delta":
            answer_parts.append(str(data.get("text", "")))
        elif kind == "unverified_lines":
            unverified.extend(item for item in data.get("items") or [] if isinstance(item, dict))
        elif kind == "clarification":
            # The stream names the card ``request_id`` (agent_chat_stream); the consent record calls it ``id``.
            card = dict(data)
            if not card.get("id") and card.get("request_id"):
                card["id"] = card["request_id"]
            cards.append(card)
    return chat_text("".join(answer_parts), unverified), cards, conversation_id


def _make_keyboard(cards: list[dict], pending: dict, cid: str, credential: str, bot_id: str | None = None,
                   bot_name: str = "") -> list | None:
    """Inline buttons for the cards Telegram can answer with a tap.  A write card gets 同意 and 取消 on one row.
    A single-choice card (its choices are ``reply:`` values) gets one button per choice, one per row, labelled
    with the choice.  A card that needs ticking (forecast revision sources, ``options``) has no Telegram form
    and gets no buttons."""
    buttons = []
    for card in cards:
        if not isinstance(card, dict) or card.get("options"):
            continue
        card_id = card.get("id") or card.get("request_id")
        if not card_id:
            continue
        row, picks, group = [], [], []
        for choice in card.get("choices") or []:
            value = str((choice or {}).get("value", "")) if isinstance(choice, dict) else ""
            if value.startswith("confirm:"):
                kind, default = "ok", "同意"
            elif value.startswith("cancel:"):
                kind, default = "no", "取消"
            elif value.startswith("reply:"):
                kind, default = "pick", value.removeprefix("reply:")
            else:
                continue
            label = str(choice.get("label") or default)[:20]
            if not label:
                continue
            short_id = _make_short_id()
            pending[short_id] = {"value": value, "card_id": str(card_id), "conversation_id": cid,
                                 "credential": credential, "bot_id": bot_id, "bot_name": bot_name, "label": label, "group": []}
            group.append(short_id)
            button = {"text": label, "callback_data": f"{kind}:{short_id}"}
            if kind == "pick":
                picks.append([button])
            else:
                row.append(button)
        # Any button of a card uses the card up, so pressing one forgets the others.
        for short_id in group:
            pending[short_id]["group"] = group
        buttons.extend(([row] if row else []) + picks)
    return buttons or None


def _make_short_id() -> str:
    # Pressing a button needs nothing but this id, so it must not be guessable.
    return secrets.token_urlsafe(9)


async def _handle_callback(client, callback: dict, pending: dict, owner: str, credential: str,
                           bound_chat: int, bound_user: int | None, tg=None, channel: dict | None = None):
    cb_id = callback.get("id")
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    data = str(callback.get("data") or "")

    if not chat_id or not cb_id:
        return
    if not _from_owner(chat, callback.get("from"), bound_chat, bound_user):
        return

    if tg is None:
        from app import agent_telegram as tg
    bot_token = channel["token"] if channel else _bot_token_for_send(owner, tg)

    kind, _, short_id = data.partition(":")
    if kind == "ack":
        await _ack_alert_press(client, bot_token, cb_id, chat_id, message.get("message_id"), short_id)
        return
    if kind not in {"ok", "no", "pick"}:
        await _answer_callback(client, bot_token, cb_id)
        return
    entry = pending.pop(short_id, None)
    if not entry:
        if short_id in _USED_CARDS:
            # A second tap while the first one runs (the agent turn takes seconds, live 2026-10-28) is not a
            # stale card: say so on the button, not with a chat message under the answer still on its way.
            await _answer_callback(client, bot_token, cb_id, "这张确认卡已经处理过了，结果见上面的回复。")
            return
        await _answer_callback(client, bot_token, cb_id)
        await _send_text(client, bot_token, chat_id, "这张确认卡已经过期了（每张卡只能用一次）。")
        return
    for other in entry.get("group") or [short_id]:
        pending.pop(other, None)
        _USED_CARDS[other] = None
    while len(_USED_CARDS) > USED_CARDS_KEPT:
        _USED_CARDS.pop(next(iter(_USED_CARDS)))
    await _answer_callback(client, bot_token, cb_id, {"ok": "正在执行……", "no": "正在取消……"}.get(kind, "正在处理……"))
    # The card's buttons go at once, so the card cannot be pressed again while its turn runs.
    await _clear_keyboard(client, bot_token, chat_id, message.get("message_id"))
    if not entry.get("bot_id"):
        await _send_text(client, bot_token, chat_id, "这张确认卡已经过期了，请在网页里重新确认。")
        return
    # The press goes to the bot's line as the button's own value, like a press on the web page: the server
    # finds the card, runs consent.execute with the operations it saved and the confirmed handler, and the
    # bot reports what was saved.  Calling consent.execute from here could not: the bridge holds neither
    # the operations (the payload digest) nor the turn context the handler needs.
    await _run_turn(client, entry.get("credential") or credential, owner, bound_chat, pending, tg,
                    entry["bot_id"], entry.get("bot_name") or "", entry["value"], channel=channel,
                    conversation_id=entry.get("conversation_id"), pending_request_id=entry["card_id"],
                    display_message=entry.get("label"))


def _sentinel_store():
    from sentinel.store import Store
    return Store()


async def _ack_alert_press(client, bot_token: str, cb_id: str, chat_id: int, message_id, alert_id: str) -> None:
    """「收到」on a sentinel alert: write the acknowledgement into data/sentinel.db (the sentinel stops escalating)."""
    try:
        await asyncio.to_thread(_sentinel_store().ack_alert, int(alert_id))
    except Exception as exc:  # the file is the only channel to the sentinel; say so rather than pretend
        print(f"Alert ack failed: {_redact(exc)}", file=sys.stderr)
        await _answer_callback(client, bot_token, cb_id, "确认没有记上，请再点一次。")
        return
    await _answer_callback(client, bot_token, cb_id, "已确认")
    await _clear_keyboard(client, bot_token, chat_id, message_id)


async def _ack_by_reply(chat_id: int, reply_to) -> bool:
    """A reply to an alert message counts as the acknowledgement; True when the message was an alert."""
    if not isinstance(reply_to, int):
        return False
    try:
        return await asyncio.to_thread(_sentinel_store().ack_by_message, chat_id, reply_to) is not None
    except Exception as exc:
        print(f"Alert ack failed: {_redact(exc)}", file=sys.stderr)
        return False


async def _deliver_outbox(client, owner: str, bound_chat: int, tg, channel: dict | None = None) -> None:
    """Send what the bots queued (notify_telegram, alerts) to the bound chat, the only recipient there is.
    Each sent message keeps its Telegram id, so a reply to it goes back to its bot.  With ``channel`` only the
    messages queued for that bot's own Telegram bot, through it."""
    bot_token = channel["token"] if channel else _bot_token_for_send(owner, tg)
    if not bot_token:
        return
    queued = (await asyncio.to_thread(tg.pending_messages, owner, 20, channel["row_id"]) if channel
              else await asyncio.to_thread(tg.pending_messages, owner))
    for item in queued:
        sent = await _send_text(client, bot_token, bound_chat, item["text"], markdown=False)
        if sent is None:
            await asyncio.to_thread(tg.mark_failed, item["id"])
        else:
            await asyncio.to_thread(tg.mark_sent, item["id"], sent)


def _message_id(response) -> int | None:
    try:
        value = response.json().get("result", {}).get("message_id")
    except Exception:
        return None
    return value if isinstance(value, int) else None


async def _send_text(client, bot_token: str, chat_id: int, text: str,
                     inline_keyboard: list | None = None, *, markdown: bool = True) -> int | None:
    """Send one message; returns its Telegram message id, or None when it was not sent."""
    import httpx
    if not bot_token:
        return None
    url = f"{TELEGRAM_API}/bot{bot_token}/sendMessage"
    body: dict = {"chat_id": chat_id, "text": text[:ANSWER_MAX_CHARS], "disable_web_page_preview": True}
    if markdown:
        body["parse_mode"] = "Markdown"
    if inline_keyboard:
        body["reply_markup"] = {"inline_keyboard": inline_keyboard}
    try:
        response = await client.post(url, json=body)
    except httpx.HTTPError:
        response = None
    if response is not None and (response.status_code != 400 or not markdown):
        if response.status_code >= 400:
            print(f"Telegram sendMessage failed: {response.status_code} {_redact(response.text[:200])}",
                  file=sys.stderr)
            return None
        return _message_id(response)
    # Telegram answers 400, without raising, when it cannot parse the Markdown (one stray * or _ is enough).
    # Send the same words as plain text; deleting characters instead would turn -14.93% into 1493%.
    body["text"] = _plain(body["text"])
    body.pop("parse_mode", None)
    try:
        response = await client.post(url, json=body)
        if response.status_code >= 400:
            print(f"Telegram sendMessage failed: {response.status_code} {_redact(response.text[:200])}",
                  file=sys.stderr)
            return None
        return _message_id(response)
    except httpx.HTTPError as exc:
        print(f"Telegram sendMessage failed: {_redact(exc)}", file=sys.stderr)
        return None


def _plain(text: str) -> str:
    """The text as plain text: drop the backslashes that escaped Markdown, keep every other character."""
    return re.sub(r"\\([\[\]*_`])", r"\1", text)


async def _answer_callback(client, bot_token: str, callback_id: str, text: str | None = None) -> None:
    import httpx
    body = {"callback_query_id": callback_id}
    if text:
        body["text"] = text
    try:
        await client.post(f"{TELEGRAM_API}/bot{bot_token}/answerCallbackQuery", json=body)
    except httpx.HTTPError:
        pass


async def _send_action(client, bot_token: str, chat_id: int, action: str = "typing") -> None:
    """sendChatAction (the "typing…" indicator lasts 5 s, so the caller renews it).  Best effort."""
    if not bot_token:
        return
    try:
        await client.post(f"{TELEGRAM_API}/bot{bot_token}/sendChatAction", json={"chat_id": chat_id, "action": action})
    except Exception as exc:
        print(f"Telegram sendChatAction failed: {_redact(exc)}", file=sys.stderr)


async def _edit_text(client, bot_token: str, chat_id: int, message_id: int, text: str) -> None:
    """editMessageText with plain text.  Best effort: a failed progress edit must not stop the turn."""
    if not bot_token or not isinstance(message_id, int):
        return
    try:
        await client.post(f"{TELEGRAM_API}/bot{bot_token}/editMessageText",
                          json={"chat_id": chat_id, "message_id": message_id, "text": text[:ANSWER_MAX_CHARS]})
    except Exception as exc:
        print(f"Telegram editMessageText failed: {_redact(exc)}", file=sys.stderr)


async def _clear_keyboard(client, bot_token: str, chat_id: int, message_id) -> None:
    """Take the buttons off a card message.  Best effort: a failed edit must not stop the press itself."""
    if not bot_token or not isinstance(message_id, int):
        return
    try:
        await client.post(f"{TELEGRAM_API}/bot{bot_token}/editMessageReplyMarkup",
                          json={"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}})
    except Exception as exc:
        print(f"Telegram editMessageReplyMarkup failed: {_redact(exc)}", file=sys.stderr)



# --- bots with their own Telegram bot (UX batch 2, P4) ---------------------------------------------------
# The shared bot above keeps working exactly as before.  Each bot that saved its own token gets one polling
# task here: whatever that Telegram bot receives from the owner goes to that bot's line (no 「@名字」), its
# answers and its queued messages go out through it, and its offset is kept in the database.  A 401 stops
# that task only (status invalid), a 409 (the token polled elsewhere) marks it conflict.  No limit on how many.

def _single_instance_lock():
    """An exclusive lock on data/telegram-bridge.lock for the life of the process; None when another bridge
    holds it (two pollers of one token make Telegram answer 409)."""
    import fcntl
    path = PROJECT_ROOT / "data" / "telegram-bridge.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


async def _reconcile_own_channels(client, credential: str, owner: str, tasks: dict, tg) -> None:
    """Start a task for each new own token, stop the ones removed or replaced, leave the rest running."""
    from app import agent_telegram_bots as own
    wanted = {c["row_id"]: c for c in await asyncio.to_thread(own.channels, owner)}
    for row_id, (fingerprint, task) in list(tasks.items()):
        current = wanted.get(row_id)
        if current is None or current["fingerprint"] != fingerprint or task.done():
            task.cancel()
            tasks.pop(row_id, None)
    for row_id, channel in wanted.items():
        if row_id not in tasks:
            tasks[row_id] = (channel["fingerprint"], asyncio.create_task(_own_channel_loop(client, credential, owner, channel, tg)))


async def _poll_own(client, token: str, offset: int) -> tuple[list | None, int | None]:
    """getUpdates for an own token: (updates, None), or (None, HTTP status) when Telegram refused."""
    import httpx
    try:
        response = await client.get(f"{TELEGRAM_API}/bot{token}/getUpdates",
                                    params={"offset": offset, "timeout": LONG_POLL_TIMEOUT,
                                            "allowed_updates": ["message", "callback_query"]})
    except httpx.TimeoutException:
        return [], None
    except httpx.HTTPError as exc:
        print(f"Telegram API error: {_redact(exc)}", file=sys.stderr)
        return None, 0
    if response.status_code in (401, 404, 409):
        return None, response.status_code
    try:
        data = response.json()
    except ValueError:
        return None, 0
    return (data.get("result") or [], None) if data.get("ok") else (None, response.status_code)


async def _own_channel_loop(client, credential: str, owner: str, channel: dict, tg) -> None:
    from app import agent_telegram_bots as own
    pending: dict[str, dict] = {}
    last_outbox = 0.0
    name = channel.get("bot_username") or channel["bot_name"]
    print(f"Telegram bridge: own bot @{name} for 「{channel['bot_name']}」 started.")
    await asyncio.to_thread(own.mark, channel["row_id"], "running")
    while True:
        try:
            state = await asyncio.to_thread(own.channel, channel["row_id"])
            if state is None:
                return
            channel = {**channel, "chat_id": state["chat_id"], "user_id": state["user_id"]}
            offset = max(int(state["offset"]), int(channel.get("offset") or 0))
            now = time.time()
            if channel["chat_id"] is not None and now - last_outbox >= OUTBOX_CHECK_INTERVAL:
                await _deliver_outbox(client, owner, channel["chat_id"], tg, channel)
                last_outbox = now
            updates, refused = await _poll_own(client, channel["token"], offset)
            if refused in (401, 404):
                await asyncio.to_thread(own.mark, channel["row_id"], "invalid", "Telegram 拒绝了这个 token（401）。请在 BotFather 检查后换一个。")
                print(f"Telegram bridge: own bot @{name}: token refused, stopped.", file=sys.stderr)
                return
            if refused == 409:
                await asyncio.to_thread(own.mark, channel["row_id"], "conflict", "这个 token 正在被别处轮询（409）。")
                await asyncio.sleep(30)
                continue
            if updates is None:
                await asyncio.sleep(5)
                continue
            for update in updates:
                if not isinstance(update, dict):
                    continue
                if isinstance(update.get("update_id"), int):
                    offset = update["update_id"] + 1
                    channel["offset"] = offset
                if isinstance(update.get("message"), dict):
                    await _handle_own_message(client, credential, owner, update["message"], channel, pending, tg)
                elif isinstance(update.get("callback_query"), dict) and channel["chat_id"] is not None:
                    await _handle_callback(client, update["callback_query"], pending, owner, credential,
                                           channel["chat_id"], channel["user_id"], tg, channel)
            if updates:
                await asyncio.to_thread(own.save_offset, channel["row_id"], offset)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"Bridge error (own bot @{name}): {_redact(exc)}", file=sys.stderr)
            await asyncio.sleep(10)


async def _handle_own_message(client, credential: str, owner: str, message: dict, channel: dict, pending: dict, tg):
    """A message to a bot's own Telegram bot: /start <code> binds it; the owner's text goes to that bot."""
    chat = message.get("chat") or {}
    text = str(message.get("text") or message.get("caption") or "").strip()
    command = text.split(maxsplit=1)[0] if text.startswith("/") else ""
    if command.split("@", 1)[0] in {"/start", "/bind"}:
        if channel["chat_id"] is None or _from_owner(chat, message.get("from"), channel["chat_id"], channel["user_id"]):
            await _handle_own_bind(client, chat, message.get("from"), channel, text[len(command):].strip())
        return
    if channel["chat_id"] is None or not _from_owner(chat, message.get("from"), channel["chat_id"], channel["user_id"]):
        return
    from app.agent_context_summary import parse_compact_command
    compact, focus = parse_compact_command(text)
    if compact:
        await _compact_command(client, credential, owner, channel["chat_id"], tg, channel["bot_id"], channel["bot_name"],
                               focus, channel=channel)
        return
    if command or not text:
        return
    await _run_turn(client, credential, owner, channel["chat_id"], pending, tg, channel["bot_id"], channel["bot_name"],
                    text, channel=channel)


async def _handle_own_bind(client, chat: dict, sender: dict | None, channel: dict, code: str):
    from app import agent_telegram_bots as own
    from app.agent_telegram import TelegramError
    chat_id = chat.get("id")
    if chat.get("type") != "private":
        await _send_text(client, channel["token"], chat_id, "请在和 bot 的私聊里绑定。", markdown=False)
        return
    if not code:
        await _send_text(client, channel["token"], chat_id, f"请在「{channel['bot_name']}」的档案页生成绑定码，再点那里的链接。", markdown=False)
        return
    try:
        await asyncio.to_thread(own.confirm_bind, channel["row_id"], code, chat_id, (sender or {}).get("id"))
        channel["chat_id"], channel["user_id"] = chat_id, (sender or {}).get("id")
        await _send_text(client, channel["token"], chat_id, f"绑定成功！这里的消息都会交给「{channel['bot_name']}」。", markdown=False)
    except TelegramError as exc:
        reason = {"bind_code_expired": "绑定码已过期（30 分钟），请重新生成。", "bind_code_mismatch": "绑定码不对，请重新生成。"}.get(str(exc), "绑定码无效或已过期，请在档案页重新生成。")
        await _send_text(client, channel["token"], chat_id, reason, markdown=False)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Telegram bridge for the personal agent.")
    parser.add_argument("--dry-run", action="store_true", help="validate config and exit")
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(main(args.dry_run)))
    except KeyboardInterrupt:
        print("")
        raise SystemExit(0)