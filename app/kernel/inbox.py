"""The kernel's inbox: what the owner says while a turn is still working (3c).

One ``Inbox`` belongs to one running kernel turn and lives in memory only (a restart closes everything through the work sweep).  The
endpoint puts a message in it; the loop takes the new ones at the end of its current small step (or between answer deltas) and shows
them to the model as the user's own words; the model decides each one with ``handle_message``.  Each message carries a future that the
decision resolves, which is how the request that brought the message learns the outcome (merged, separate, stopped).

A message nobody decided before the turn ended is ``separate`` (the safe default: it still gets its own answer), recorded as defaulted.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from ..agent_workflow import tools

HANDLE = "handle_message"
MERGE, SEPARATE, STOP = "merge", "separate", "stop"
DECISIONS = (MERGE, SEPARATE, STOP)
NOTE_MAX = 200
MIN_ID_PREFIX = 4       # the shortest prefix of a message id that names it
SHORT_ID = 8          # how many characters of a message id the model is shown (and may give back)
DEFAULT_STOP_SENTENCE = "好的，已停下。"
UNKNOWN = "没有这条消息；只能处理系统说明里列出的编号。"
WITHDRAWN = "你在这条消息之前提出的卡片操作已撤回；需要的话按新的说法重新提出。"
ALREADY = "这条消息已经处理过了，不能再改。"

HANDLE_SCHEMA: dict = {
    "type": "function",
    "function": {
        "name": HANDLE,
        "description": "用户在你工作时又发来的消息，逐条说明怎么处理，写回答之前必须处理完。"
                       "merge：补充或修正，并入正在做的这件事（已查到的资料全部保留，回答一并答）；"
                       "separate：另一件事，另起一个回答同时做；stop：用户不要了，立即停下（note 写一句话告诉用户）。",
        "parameters": {
            "type": "object",
            "properties": {"message_id": {"type": "string", "minLength": 1, "maxLength": 64},
                           "decision": {"type": "string", "enum": list(DECISIONS)},
                           "note": {"type": "string", "maxLength": NOTE_MAX}},
            "required": ["message_id", "decision"],
            "additionalProperties": False,
        },
    },
}


@dataclass
class Outcome:
    """How a message was settled: what the request that brought it streams back."""
    decision: str
    into_turn: str
    defaulted: bool = False


@dataclass(eq=False)
class Message:
    id: str                      # the stored row's id
    text: str
    turn_id: str                 # the turn id its row was stored under: the separate turn's own id when it becomes one
    sequence: int | None = None  # the row's sequence: a separate turn reads the history as of this
    excluded: frozenset = frozenset()   # the turns that were running when it arrived (a separate turn does not carry their unfinished rows)
    future: asyncio.Future | None = field(default=None, repr=False)
    shown: bool = False          # the model has been shown it
    withdraws: tuple = ()        # the card proposals the turn had made when it was shown this message: a merge withdraws them
    decision: str | None = None
    note: str = ""
    defaulted: bool = False


class Inbox:
    def __init__(self, turn_id: str, own_message_id: str | None = None):
        self.turn_id = turn_id
        self.own_message_id = own_message_id      # the message that started the turn
        self.messages: list[Message] = []         # arrival order
        self.closed = False
        self.started = False                      # the turn's loop has begun: only a turn that can decide takes messages
        self.stopping = False                     # a message was decided ``stop``
        self.stop_note = ""
        self.adopt = None                         # async (message): the endpoint's hook that moves a merged or stopped row into this turn

    def put(self, message: Message) -> bool:
        """Take a message; False (nothing taken) when the turn no longer accepts them."""
        if self.closed:
            return False
        self.messages.append(message)
        return True

    def fresh(self) -> list[Message]:
        return [m for m in self.messages if not m.shown]

    def has_fresh(self) -> bool:
        return any(not m.shown for m in self.messages)

    def undecided(self) -> list[Message]:
        return [m for m in self.messages if m.decision is None]

    def find(self, key) -> Message | None:
        """A shown message by its id or by a unique prefix of it (what the model was given)."""
        key = str(key or "").strip().lower()
        if len(key) < MIN_ID_PREFIX:
            return None
        found = [m for m in self.messages if m.shown and (m.id.lower() == key or m.id.lower().startswith(key))]
        return found[0] if len(found) == 1 else None

    def decide(self, message: Message, decision: str, note: str = "", defaulted: bool = False) -> None:
        message.decision, message.note, message.defaulted = decision, note, defaulted
        if decision == STOP:
            self.stopping = True
            self.stop_note = note or self.stop_note
        if message.future is not None and not message.future.done():
            message.future.set_result(Outcome(decision, self.turn_id, defaulted))

    def close(self) -> list[Message]:
        """The turn ends: whatever nobody decided is ``separate``, by default.  Returns those messages."""
        self.closed = True
        left = self.undecided()
        for message in left:
            self.decide(message, SEPARATE, defaulted=True)
        return left

    def merged_ids(self) -> list[str]:
        return [m.id for m in self.messages if m.decision == MERGE]

    def reply_to(self) -> list[str]:
        """The user messages this turn's answer answers: the one that started it, then the merged ones, in arrival order."""
        return [*([self.own_message_id] if self.own_message_id else []), *self.merged_ids()]

    def record(self) -> list[dict]:
        return [{"message_id": m.id, "decision": m.decision, "defaulted": m.defaulted, **({"note": m.note} if m.note else {})}
                for m in self.messages]


# --- the running kernel turns of each conversation ---------------------------------------------------------------------------

ACTIVE: dict[str, list[Inbox]] = {}      # conversation id -> its running kernel turns' inboxes, oldest first


def register(conversation_id: str, inbox: Inbox) -> None:
    ACTIVE.setdefault(str(conversation_id), []).append(inbox)


def unregister(conversation_id: str, inbox: Inbox) -> None:
    turns = ACTIVE.get(str(conversation_id))
    if turns is None:
        return
    if inbox in turns:
        turns.remove(inbox)
    if not turns:
        ACTIVE.pop(str(conversation_id), None)


def target(conversation_id: str) -> Inbox | None:
    """The running turn a new message goes to: the newest one that still accepts messages."""
    for inbox in reversed(ACTIVE.get(str(conversation_id)) or []):
        if inbox.started and not inbox.closed:
            return inbox
    return None


def finishing(conversation_id: str) -> bool:
    """A turn of the conversation has begun and no longer takes messages: it is storing its answer."""
    return any(inbox.started and inbox.closed for inbox in ACTIVE.get(str(conversation_id)) or [])


# The newest card each conversation's turns minted (not a card a turn only carried): parallel turns keep to one pending card.
MINTED: dict[str, tuple[float, str, dict]] = {}
MINTED_KEEP_SECONDS = 900


def note_minted(conversation_id: str, turn_id: str, card: dict) -> None:
    import time
    now = time.monotonic()
    for key in [k for k, (at, _, _) in MINTED.items() if now - at > MINTED_KEEP_SECONDS]:
        MINTED.pop(key, None)
    MINTED[str(conversation_id)] = (now, str(turn_id), card)


def other_card_since(conversation_id: str, turn_id: str, since: float) -> dict | None:
    """The card another turn of this conversation minted after ``since`` (this turn's start), if it is still good."""
    from datetime import UTC, datetime
    found = MINTED.get(str(conversation_id))
    if found is None or found[0] <= since or found[1] == str(turn_id):
        return None
    try:
        if datetime.fromisoformat(str(found[2].get("expires_at"))) <= datetime.now(UTC):
            return None
    except (TypeError, ValueError):
        pass
    return found[2]


def running_turns(conversation_id: str) -> list[str]:
    return [inbox.turn_id for inbox in ACTIVE.get(str(conversation_id)) or []]


async def settle(run, args: dict) -> dict:
    """One ``handle_message`` call: record the decision on the run's inbox (the first one stands)."""
    inbox = getattr(run, "inbox", None)
    if inbox is None:
        return tools.error("tool_not_in_bot_scope")
    decision = args.get("decision")
    note = args.get("note")
    if set(args) - {"message_id", "decision", "note"} or decision not in DECISIONS or (note is not None and not isinstance(note, str)):
        return tools.error("invalid_arguments")
    message = inbox.find(args.get("message_id"))
    if message is None:
        return {**tools.error("invalid_arguments"), "reason": UNKNOWN}
    if message.decision is not None:
        return {"ok": False, "data": [], "error_code": "already_decided", "reason": ALREADY}
    note = (note or "").strip()[:NOTE_MAX]
    if decision in (MERGE, STOP) and inbox.adopt is not None:
        await inbox.adopt(message)      # its row now belongs to this turn (the history reads the turn as one)
    withdrawn = 0
    if decision == MERGE and message.withdraws:
        # A correction replaces what the turn had put on a card before it: those proposals are withdrawn, to be proposed again as he now says.
        before = len(run.proposals)
        run.proposals[:] = [p for p in run.proposals if id(p) not in message.withdraws]
        withdrawn = before - len(run.proposals)
    inbox.decide(message, decision, note)
    result = {"status": "recorded", "message_id": message.id[:SHORT_ID], "decision": decision}
    if withdrawn:
        result.update(withdrawn_proposals=withdrawn, note=WITHDRAWN)
    return {"ok": True, "data": [result]}
