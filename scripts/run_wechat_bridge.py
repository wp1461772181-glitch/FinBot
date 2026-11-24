"""WeChat bridge for the personal agent (ClawBot / iLink): the owner's WeChat messages reach a bot, its answer goes back.

Long-polls the iLink bot API (no webhook, no public address).  Only the WeChat id that scanned the login is answered.
A message starting with 「@名字」 goes to the bot of that name, anything else to the default bot; the turn runs through
the local agent-chat stream endpoint exactly as the Telegram bridge does, so the bot's model, memory and tools are the
same.  WeChat has no buttons: a card that needs a click (a write to confirm) is answered with a note to confirm it on
the web page or in Telegram.  One turn per bot at a time, queued; a turn that takes a while sends one short note.

    python scripts/run_wechat_bridge.py login                  # print a QR link, wait for the scan, save the login
    python scripts/run_wechat_bridge.py import-probe STATE     # reuse the login of the earlier probe script
    python scripts/run_wechat_bridge.py --dry-run              # validate and exit
    python scripts/run_wechat_bridge.py                        # run

The login (data/wechat-bridge.json) is a credential: owner-only, never printed.  Only one process may poll a login.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app import agent_wechat as wx
from app import channels

LOCAL_API = os.environ.get("WECHAT_BRIDGE_API_URL", "http://127.0.0.1:8000")
CONNECT_TIMEOUT = 5.0
SLOW_NOTICE_AFTER = 8.0
PROGRESS_AFTER_SECONDS = 10  # a kernel turn still running at this mark gets one sentence
BUSY_RETRY_DELAY = 3.0
BUSY_WAIT_SECONDS = 1260  # a turn's hard cap is 1200 s
STALE_PAUSE_SECONDS = 3600
PASS_SECONDS = 60  # one delivery pass stops taking rows after this long (the rest stay pending, their claim lapses)
OUTBOX_INTERVAL = 5  # seconds between delivery passes of the proactive-message outbox
MESSAGE_MAX_CHARS = 4000
SLOW_TEXT = "收到，我在查，稍等一下。"
BACKEND_DOWN_TEXT = "后端暂时连不上，提醒不受影响。"
BUSY_WAITING_TEXT = "这条对话线正在别处回答（比如网页），你的消息已排队，那边结束后自动开始。"
BUSY_GIVEUP_TEXT = "这个对话一直在别处回答，请稍后再发一次。"
NON_TEXT_TEXT = "目前我只能读文字消息，请把内容打成文字发给我。"
CARD_TEXT = "（这一步需要你确认，请到网页或 Telegram 里点确认。）"
STALE_ALERT = "微信通道的登录失效了，需要重新扫码才能继续收发。我已暂停一小时再试，登录恢复前，原本要发到微信的消息会改发 Telegram。"


class BackendUnavailable(Exception):
    """The local API did not accept the connection."""


class ConversationBusy(Exception):
    """The API answered 409; ``code`` is its detail.  Only conversation_busy is worth waiting in line for."""

    def __init__(self, code: str = "conversation_busy"):
        super().__init__(code)
        self.code = code


_monotonic = time.monotonic  # a seam for tests


def _log(event: str, **fields) -> None:
    print(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, **fields}, ensure_ascii=False), flush=True)


class _Progress:
    """The at-most-two extra messages of one kernel turn: the checklist once, one sentence at the mark.
    WeChat cannot edit a message, so each of these is a new message.  Old-engine turns emit no such events."""

    def __init__(self, send):
        self.send = send  # async (text) -> None, never raises
        self.kernel = False  # a checklist or sentence has been seen
        self.checklist_sent = self.sentence_sent = self.mark_passed = False
        self.newest = ""
        self._timer: asyncio.Task | None = None

    def start(self) -> None:
        """Begin the turn's clock (call when the stream is actually being asked for)."""
        self.stop()
        self._timer = asyncio.create_task(self._mark())

    def stop(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None

    async def _mark(self) -> None:
        await asyncio.sleep(PROGRESS_AFTER_SECONDS)
        self.mark_passed = True
        await self._sentence()

    async def _sentence(self) -> None:
        if self.sentence_sent or not self.newest:
            return
        self.sentence_sent = True
        await self.send(self.newest)

    async def on_event(self, kind: str, data: dict) -> None:
        if kind == "checklist":
            self.kernel = True
            texts = [str(item.get("text", "")).strip() for item in data.get("items") or [] if isinstance(item, dict)]
            texts = [t for t in texts if t]
            if not self.checklist_sent and texts:
                self.checklist_sent = True
                await self.send("我分几步来做：\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(texts, 1)))
        elif kind == "narration":
            self.kernel = True
            text = str(data.get("text", "")).strip()
            if text:
                self.newest = text
                if self.mark_passed:
                    await self._sentence()


class Bridge:
    """Everything that decides what happens to one inbound message, with the I/O passed in so tests can fake it."""

    def __init__(self, ilink: wx.Ilink, state: dict, *, owner: str, route, ask, save=lambda: None):
        self.ilink, self.state, self.owner, self.route, self.ask, self.save = ilink, state, owner, route, ask, save
        self.locks: dict[str, asyncio.Lock] = {}
        self.tasks: set[asyncio.Task] = set()
        self.paused_until = 0.0  # time.time() until which the login is stale: the poll and the outbox both wait

    async def deliver_outbox(self) -> None:
        """One pass over the proactive messages queued for WeChat: deliver, then sweep (so a row the producer stamped
        long ago is tried once before the sweep can close it, and the sweep's claim check protects the rows just
        tried).  Never raises; a stale login only lets rows expire."""
        try:
            if time.time() >= self.paused_until:
                await self._deliver_pending()
        except Exception as exc:  # noqa: BLE001 - the bridge and the poll go on
            _log("outbox_pass_failed", error=type(exc).__name__)
        try:
            await asyncio.to_thread(channels.expire_stuck, self.owner)
        except Exception as exc:  # noqa: BLE001
            _log("outbox_sweep_failed", error=type(exc).__name__)

    async def _deliver_pending(self) -> None:
        started = _monotonic()
        for row in await asyncio.to_thread(channels.pending, self.owner, "wechat"):
            if _monotonic() - started >= PASS_SECONDS:
                _log("outbox_pass_capped")
                break
            await self._deliver_row(row)

    async def _deliver_row(self, row: dict) -> None:
        """Send one row to the login's owner (never to an id from the row).  A failure of the first chunk fails the
        row (it is retried, then moves to the next channel); once any chunk is out the row counts as sent, because
        sending it again would show the owner the same words twice."""
        reason, sent, total = None, 0, 0
        try:
            await asyncio.to_thread(channels.claim, row["id"])   # a fresh lease for this row, whatever the pass has used
        except Exception as exc:  # noqa: BLE001 - the pending() claim still stands
            _log("outbox_claim_failed", id=row["id"], error=type(exc).__name__)
        try:
            to_user = self.state["owner_user_id"]
            token = (self.state.get("context_tokens") or {}).get(to_user)
            chunks = wx.split_text(wx.plain_text(row["text"]))
            total = len(chunks)
            for chunk in chunks:
                reason = wx.send_result(await self.ilink.send_text(to_user, chunk, token))
                if reason:
                    break
                sent += 1
        except Exception as exc:  # noqa: BLE001 - one row's failure must not hold up the next
            reason = type(exc).__name__
        try:
            if reason and sent == 0:
                _log("outbox_failed", id=row["id"], reason=reason)
                await asyncio.to_thread(channels.mark_failed, row["id"], "send_failed")
            else:
                if reason:
                    _log("outbox_partial", id=row["id"], chunks_sent=sent, chunks_total=total, reason=reason)
                    await asyncio.to_thread(channels.mark_partial, row["id"])
                else:
                    _log("outbox_sent", id=row["id"])
                    await asyncio.to_thread(channels.mark_sent, row["id"])
        except Exception as exc:  # noqa: BLE001
            _log("outbox_mark_failed", id=row["id"], error=type(exc).__name__)

    async def _acknowledge(self, message: dict | None = None) -> None:
        """The owner wrote: rows sent by the time of their message count as seen.  The message's own time when it
        carries one (``create_time_ms``), else the time it was received."""
        seen = None
        try:
            millis = (message or {}).get("create_time_ms")
            seen = datetime.fromtimestamp(int(millis) / 1000, UTC) if millis else None
        except (TypeError, ValueError, OverflowError, OSError):
            seen = None
        try:
            await asyncio.to_thread(channels.acknowledge, self.owner, "wechat", None, seen or datetime.now(UTC))
        except Exception as exc:  # noqa: BLE001 - the message is handled either way
            _log("acknowledge_failed", error=type(exc).__name__)

    async def reply(self, to_user: str, token: str | None, text: str) -> bool:
        ok = True
        for chunk in wx.split_text(wx.plain_text(text)):
            try:
                reason = wx.send_result(await self.ilink.send_text(to_user, chunk, token))
            except Exception as exc:  # noqa: BLE001 - one lost message must not stop the loop
                reason = type(exc).__name__
            if reason:
                _log("send_failed", reason=reason)
                ok = False
        return ok

    async def handle(self, message: dict) -> None:
        """One message of ``getupdates``.  Returns as soon as the turn it starts is handed to a task."""
        if message.get("message_type") != wx.USER:
            return
        if not wx.from_owner(message, self.state):
            _log("ignored_stranger")
            return
        await self._acknowledge(message)
        uid, token = str(message.get("from_user_id")), message.get("context_token")
        if token:
            self.state.setdefault("context_tokens", {})[uid] = token
        text = wx.inbound_text(message)
        if not text:
            await self.reply(uid, token, NON_TEXT_TEXT)
            return
        target = await asyncio.to_thread(self.route, self.owner, text, None)
        if not target.get("text"):
            return
        _log("inbound", chars=len(text), bot=target.get("bot_name"), has_context_token=bool(token), fields=sorted(str(k) for k in message)[:40])
        task = asyncio.create_task(self._turn(uid, token, target))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _turn(self, uid: str, token: str | None, target: dict) -> None:
        async with self.locks.setdefault(target["bot_id"], asyncio.Lock()):
            progress = _Progress(lambda text: self._send_progress(uid, token, text))
            slow = asyncio.create_task(self._slow_note(uid, token, progress))
            try:
                answer, cards = await self._ask_waiting(target, uid, token, progress)
            except BackendUnavailable:
                answer, cards = BACKEND_DOWN_TEXT, []
            except ConversationBusy:
                answer, cards = BUSY_GIVEUP_TEXT, []
            except Exception as exc:  # noqa: BLE001
                _log("turn_failed", error=type(exc).__name__)
                answer, cards = "这次没有处理成功，稍后再发一次。", []
            finally:
                slow.cancel()
                progress.stop()
            prefix = f"【{target['bot_name']}】\n" if target.get("via") == "mention" else ""
            body = answer.strip() or ("完成。" if cards else "（这条回复没有内容。）")
            if cards:
                body += "\n\n" + CARD_TEXT
            await self.reply(uid, token, prefix + body)

    async def _send_progress(self, uid: str, token: str | None, text: str) -> None:
        try:
            await self.reply(uid, token, text)
        except Exception as exc:  # noqa: BLE001 - a lost progress message never stops the turn
            _log("progress_failed", error=type(exc).__name__)

    async def _slow_note(self, uid: str, token: str | None, progress: _Progress) -> None:
        await asyncio.sleep(SLOW_NOTICE_AFTER)
        if not progress.kernel:  # a kernel turn already speaks for itself
            progress.sentence_sent = True  # the note takes the turn's sentence slot
            await self.reply(uid, token, SLOW_TEXT)

    async def _ask_waiting(self, target: dict, uid: str, token: str | None, progress: _Progress):
        started, told = time.monotonic(), False
        while True:
            try:
                progress.start()  # the 10 s clock runs from the stream, not from waiting in line
                answer, cards, _cid = await self.ask(target["bot_id"], target["text"], on_event=progress.on_event)
                return answer, cards
            except ConversationBusy as busy:
                progress.stop()
                if busy.code != "conversation_busy" or time.monotonic() - started > BUSY_WAIT_SECONDS:
                    raise
                if not told:
                    told = True
                    await self.reply(uid, token, BUSY_WAITING_TEXT)
                await asyncio.sleep(BUSY_RETRY_DELAY)


def parse_turn(raw: str):
    """The answer text, the cards and the conversation id of one raw stream.  Text before an ``answer_reset`` is dropped."""
    from app.agent_telegram import chat_text, sse_events

    parts, cards, cid = [], [], None
    for kind, data in sse_events(raw):
        if kind == "conversation":
            cid = data.get("conversation_id")
        elif kind == "delta":
            parts.append(str(data.get("text", "")))
        elif kind == "answer_reset":
            parts.clear()
        elif kind == "clarification":
            cards.append(data)
    return chat_text("".join(parts), None), cards, cid


async def ask_agent(http, credential: str, bot_id: str, text: str, on_event=None):
    """One turn of the bot through the local stream endpoint.  Returns (answer text, cards, conversation id)."""
    import codecs

    import httpx
    from app.agent_telegram import sse_events

    raw, pending, decoder = "", "", codecs.getincrementaldecoder("utf-8")("replace")
    try:
        async with http.stream("POST", f"{LOCAL_API}/agent-chat/stream",
                               json={"bot_id": bot_id, "message": text[:MESSAGE_MAX_CHARS]},
                               headers={"X-Chat-Session": credential, "Accept": "text/event-stream"},
                               timeout=httpx.Timeout(300, connect=CONNECT_TIMEOUT)) as response:
            if response.status_code == 409:
                body = b"".join([piece async for piece in response.aiter_bytes()])
                try:
                    code = str(json.loads(body).get("detail") or "conversation_busy")
                except (ValueError, AttributeError):
                    code = "conversation_busy"
                raise ConversationBusy(code)
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
    except ConversationBusy:
        raise
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise BackendUnavailable() from exc
    return parse_turn(raw)


def _lock():
    import fcntl
    path = PROJECT_ROOT / "data" / "wechat-bridge.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def _owner_credential() -> str:
    from app.agent_chat_identity import _load_config
    config = _load_config()
    if not config:
        raise SystemExit("no owner credential configured (data/personal-chat-login.json)")
    return config[3]


def _mark_stale(state: dict) -> None:
    """Record when the login went stale, so the outbox sees WeChat as not connected (channels.available) and a
    message with WeChat first does not wait out the sweep.  Cleared by the next good poll."""
    state["stale_since"] = time.time()
    wx.save_state(state)


def _clear_stale(state: dict) -> None:
    state.pop("stale_since", None)  # saved with the cursor at the end of the poll


def _notify_stale(owner: str) -> None:
    """Tell the owner in Telegram that the WeChat login needs a new scan.  Best effort: the log has it either way."""
    try:
        from app import agent_telegram
        from app.agent_bots import ensure_default_bot
        from app.database import SessionLocal
        default = ensure_default_bot(owner)
        with SessionLocal() as db:
            # About WeChat being down: it goes to Telegram whatever the preference says.
            agent_telegram.enqueue(db, owner, str(default.id), STALE_ALERT, source="alert", channels=["telegram"])
            db.commit()
    except Exception as exc:  # noqa: BLE001
        _log("stale_notice_failed", error=type(exc).__name__)


async def _outbox_loop(bridge: Bridge) -> None:
    """The delivery pass every OUTBOX_INTERVAL seconds, on its own task so a long poll cannot hold it up."""
    while True:
        try:
            await bridge.deliver_outbox()
        except Exception as exc:  # noqa: BLE001 - this loop never ends on its own
            try:
                _log("outbox_loop_error", error=type(exc).__name__)
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(OUTBOX_INTERVAL)


def _start_outbox(bridge: Bridge) -> asyncio.Task:
    return asyncio.create_task(_outbox_loop(bridge))


async def _enter_stale(bridge: Bridge, owner: str) -> None:
    """The login is stale: remember it, tell the owner on Telegram, and pause the poll and the outbox together."""
    _log("session_stale", pause_s=STALE_PAUSE_SECONDS)
    _mark_stale(bridge.state)
    await asyncio.to_thread(_notify_stale, owner)
    bridge.paused_until = time.time() + STALE_PAUSE_SECONDS


async def run(dry_run: bool = False) -> int:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    import httpx

    os.chdir(PROJECT_ROOT)
    state = wx.load_state()
    if not state.get("bot_token") or not state.get("owner_user_id"):
        print("WeChat bridge: no login saved.  Run: login  (or import-probe STATE)", file=sys.stderr)
        return 0 if dry_run else 1
    credential = _owner_credential()
    from app.agent_chat_store import owner_hash
    from app import agent_telegram
    owner = owner_hash(credential)
    if dry_run:
        print(f"Bot: {state.get('ilink_bot_id')}  owner id set: yes  context tokens: {len(state.get('context_tokens', {}))}")
        print(f"Local API: {LOCAL_API}")
        return 0
    lock = _lock()
    if lock is None:
        print("WeChat bridge: another bridge is already running (data/wechat-bridge.lock).", file=sys.stderr)
        return 1

    async with httpx.AsyncClient(timeout=httpx.Timeout(60)) as http:
        async def ask(bot_id, text, on_event=None):
            return await ask_agent(http, credential, bot_id, text, on_event)

        bridge = Bridge(wx.Ilink(http, state), state, owner=owner, route=agent_telegram.route, ask=ask,
                        save=lambda: wx.save_state(state))
        failures = 0
        _log("bridge_start", bot=state.get("ilink_bot_id"))
        outbox = _start_outbox(bridge)
        try:
            while True:
                if time.time() < bridge.paused_until:
                    await asyncio.sleep(30)
                    continue
                try:
                    response = await bridge.ilink.get_updates()
                    failures = 0
                except httpx.ReadTimeout:
                    continue
                except Exception as exc:  # noqa: BLE001 - keep polling
                    failures += 1
                    _log("poll_error", error=type(exc).__name__, failures=failures)
                    await asyncio.sleep(30 if failures >= 3 else 2)
                    continue
                status = wx.poll_status(response)
                if status == "stale":
                    await _enter_stale(bridge, owner)
                    continue
                if status == "rejected":
                    _log("poll_rejected", **{k: response.get(k) for k in ("ret", "errcode", "errmsg")})
                    await asyncio.sleep(5)
                    continue
                _clear_stale(state)
                if response.get("get_updates_buf"):
                    state["get_updates_buf"] = response["get_updates_buf"]
                # The cursor is saved before the messages are handled: a crash then loses one message rather than
                # answering it twice.
                for message in response.get("msgs") or []:
                    try:
                        await bridge.handle(message)
                    except Exception as exc:  # noqa: BLE001
                        _log("handle_failed", error=type(exc).__name__)
                wx.save_state(state)
        finally:
            outbox.cancel()


async def do_login() -> int:
    import httpx

    def show(link: str) -> None:
        print(f"QR link (render it as a QR code and scan with the WeChat account to connect): {link}", flush=True)

    async with httpx.AsyncClient() as http:
        state = await wx.login(http, show)
    if not state:
        print("Login failed or timed out.", file=sys.stderr)
        return 1
    wx.save_state(state)
    print(f"Login saved for bot {state.get('ilink_bot_id')}.")
    return 0


def import_probe(path: str) -> int:
    """Reuse the login the probe script saved (token, cursor, owner id, context tokens), so no new scan is needed."""
    probe = json.loads(Path(path).read_text(encoding="utf-8"))
    tokens = {uid: user["context_token"] for uid, user in (probe.get("users") or {}).items() if user.get("context_token")}
    state = wx.new_state(bot_token=probe["bot_token"], baseurl=probe.get("baseurl") or wx.ILINK_BASE,
                         bot_id=str(probe.get("ilink_bot_id") or ""), owner_user_id=str(probe["ilink_user_id"]),
                         cursor=probe.get("get_updates_buf", ""), context_tokens=tokens)
    wx.save_state(state)
    print(f"Imported the login of bot {state['ilink_bot_id']}; {len(tokens)} context token(s).")
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["login"]:
        return asyncio.run(do_login())
    if argv[:1] == ["import-probe"] and len(argv) == 2:
        return import_probe(argv[1])
    return asyncio.run(run(dry_run="--dry-run" in argv))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
