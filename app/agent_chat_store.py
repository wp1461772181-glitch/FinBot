import asyncio, hashlib, uuid, json
from sqlalchemy import select, func, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from .config import DATABASE_URL
from .agent_chat_models import (AgentConversation, AgentConversationSummary, AgentConversationTitle, AgentMessage,
                                AgentResearchQueue)
from . import agent_context as layers
from . import agent_recall as recall
from .agent_workflow.fp_flags import flag
ASYNC_URL=DATABASE_URL
engine=create_async_engine(ASYNC_URL,pool_pre_ping=True,connect_args={"connect_timeout":3})
Session=async_sessionmaker(engine,expire_on_commit=False)
async def _recall(hook,*args):
    # The past-conversation index is derived data: a failed update never fails the write it follows.
    await asyncio.to_thread(recall.safe_hook,hook,*args)
def owner_hash(credential: str)->str: return hashlib.sha256(credential.encode()).hexdigest()
def _message_bytes(m):
    return layers.row_bytes({"role":m.role,"content":m.content,"tool_calls":m.tool_calls,
                             "tool_call_id":m.tool_call_id,"status":m.status,"turn_id":str(m.turn_id)})
async def create_conversation(credential: str, origin: str | None = None)->str:
    async with Session() as s:
        obj=AgentConversation(owner_hash=owner_hash(credential),origin=origin); s.add(obj); await s.commit(); return str(obj.id)
async def verify_conversation(conversation_id: str, credential: str)->bool:
    try: cid=uuid.UUID(conversation_id)
    except ValueError:return False
    async with Session() as s:
        return await s.scalar(select(AgentConversation.id).where(AgentConversation.id==cid,AgentConversation.owner_hash==owner_hash(credential))) is not None
async def append_message(conversation_id: str, turn_id: str, role: str, content: str, *, tool_calls=None, tool_call_id=None,status="complete",message_id: str | None = None):
    """Store one row; returns its sequence.  ``message_id``: the row's id when the caller needs to name it before it is stored (the owner's
    messages, which the answers say they answer)."""
    async with Session() as s:
        cid=uuid.UUID(conversation_id)
        seq=(await s.scalar(select(func.coalesce(func.max(AgentMessage.sequence),0)).where(AgentMessage.conversation_id==cid)))+1
        s.add(AgentMessage(**({"id":uuid.UUID(message_id)} if message_id else {}),conversation_id=cid,turn_id=uuid.UUID(turn_id),sequence=seq,role=role,content=content,tool_calls=tool_calls,tool_call_id=tool_call_id,status=status))
        conv=await s.get(AgentConversation,cid)
        if conv: conv.updated_at=func.now()
        await s.commit()
    if role=="user":await _recall(recall.index_question,conversation_id,content)
    return seq
async def message_texts(conversation_id: str, ids) -> dict:
    """The user messages of this conversation with these ids, id -> text (what an answer on this page quotes from an earlier page)."""
    try:cid=uuid.UUID(str(conversation_id))
    except ValueError:return {}
    wanted = []
    for item in ids:
        try:wanted.append(uuid.UUID(str(item)))
        except ValueError:pass
    if not wanted:return {}
    async with Session() as s:
        rows=(await s.execute(select(AgentMessage.id,AgentMessage.content).where(AgentMessage.conversation_id==cid,
              AgentMessage.role=="user",AgentMessage.id.in_(wanted)))).all()
    return {str(i):content for i,content in rows}
async def move_message(conversation_id: str, message_id: str, turn_id: str) -> bool:
    """Put a stored row under another turn (the owner's message that a running turn took in: from then on it is part of that turn).
    False when there is no such row in this conversation."""
    async with Session() as s:
        row=await s.get(AgentMessage,uuid.UUID(message_id))
        if row is None or row.conversation_id!=uuid.UUID(conversation_id): return False
        row.turn_id=uuid.UUID(turn_id)
        await s.commit()
        return True
async def history(conversation_id: str, credential: str, limit_bytes=14000):
    if not await verify_conversation(conversation_id,credential): return None
    async with Session() as s:
        rows=(await s.scalars(select(AgentMessage).where(AgentMessage.conversation_id==uuid.UUID(conversation_id)).order_by(AgentMessage.sequence.desc()).limit(500))).all()
        rows=list(reversed(rows))
        output=[]; used=0
        # Keep complete turns only; group by turn ID and include newest full groups.
        groups=[(group[0].turn_id,group) for group in layers.group_by_turn(rows,key=lambda row:row.turn_id)]
        for _,group in reversed(groups):
            if not group or group[0].role != "user" or group[-1].role != "assistant" or group[-1].status != "complete":
                continue
            size=sum(_message_bytes(m) for m in group)
            if used+size>limit_bytes: break
            output[0:0]=[{"id":str(m.id),"role":m.role,"content":m.content,"tool_calls":m.tool_calls,"tool_call_id":m.tool_call_id,"status":m.status,"turn_id":str(m.turn_id)} for m in group]; used+=size
        return output
CONTEXT_ROWS = 500       # how many of the newest rows a turn reads


async def conversation_context(conversation_id: str, credential: str, *, window: int | None = None,
                               l1_bytes: int | None = None, l2_bytes: int | None = None, l3_bytes: int | None = None,
                               anchored: bool = False, upto_sequence: int | None = None, exclude_turns=()):
    """What the next turn of this conversation carries of the turns before it, by layer (the rule is
    ``agent_context.layer_rows``; this reads the rows and the segments).  None when the conversation
    is not this credential's.  ``anchored`` (kernel turns) moves the layer boundary on a fixed grid.
    ``upto_sequence`` / ``exclude_turns``: the history as of a moment, without the rows of turns that were still running then
    (a separate turn started from a message that arrived while another turn worked, 3c)."""
    if not await verify_conversation(conversation_id, credential):
        return None
    # The sizes follow the window of the model that will read them (the catalog's window; default 128k).
    sizes = layers.layer_sizes(window) if window else (layers.L1_BYTES, layers.L2_BYTES, layers.L3_BYTES)
    l1_bytes, l2_bytes, l3_bytes = (given if given is not None else size
                                    for given, size in zip((l1_bytes, l2_bytes, l3_bytes), sizes))
    cid = uuid.UUID(conversation_id)
    limit = layers.ANCHORED_ROWS if anchored else CONTEXT_ROWS
    async with Session() as s:
        rows = (await s.scalars(select(AgentMessage).where(AgentMessage.conversation_id == cid)
                                .order_by(AgentMessage.sequence.desc()).limit(limit))).all()
        segments = (await s.scalars(select(AgentConversationSummary)
                                    .where(AgentConversationSummary.conversation_id == cid)
                                    .order_by(AgentConversationSummary.seq.asc()))).all()
    skip = {uuid.UUID(str(t)) for t in exclude_turns or ()}
    stored = [{"id": str(m.id), "role": m.role, "content": m.content, "tool_calls": m.tool_calls, "tool_call_id": m.tool_call_id,
               "status": m.status, "turn_id": m.turn_id, "sequence": m.sequence} for m in reversed(rows)
              if (upto_sequence is None or m.sequence <= upto_sequence) and m.turn_id not in skip]
    made = [{"seq": x.seq, "from_sequence": x.from_sequence, "upto_sequence": x.upto_sequence, "content": x.content,
             "turn_ids": [str(t) for t in x.turn_ids] if x.turn_ids else None}
            for x in segments]
    if not anchored:
        return layers.layer_rows(stored, made, l1_bytes=l1_bytes, l2_bytes=l2_bytes, l3_bytes=l3_bytes)
    stored, front = layers.window_rows(stored, made[-1]["upto_sequence"] if made else 0, len(rows) >= limit, layers.ANCHOR_GRID)
    # Kernel turns only: each turn's citation entry stands after its own answer (a stable prefix), not once after the question.
    inline = {"inline_catalogue": True} if flag("FINBOT_KERNEL_INLINE_CATALOGUE", True) else {}
    return layers.layer_rows(stored, made, l1_bytes=l1_bytes, l2_bytes=l2_bytes, l3_bytes=l3_bytes,
                             anchor_grid=layers.ANCHOR_GRID, anchor_front=front, **inline)


async def load_turn_citation(conversation_id: str, credential: str, turn_id: str, ordinal: int) -> dict:
    """Read one immutable citation manifest entry from an owned final answer."""
    try:
        cid, tid = uuid.UUID(conversation_id), uuid.UUID(turn_id)
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
            return {"ok": False, "error_code": "history_citation_invalid"}
    except (ValueError, TypeError, AttributeError):
        return {"ok": False, "error_code": "history_citation_not_found"}
    async with Session() as s:
        owner = await s.scalar(select(AgentConversation.id).where(
            AgentConversation.id == cid, AgentConversation.owner_hash == owner_hash(credential)))
        if owner is None: return {"ok": False, "error_code": "history_citation_not_found"}
        rows = (await s.scalars(select(AgentMessage).where(AgentMessage.conversation_id == cid,
            AgentMessage.turn_id == tid, AgentMessage.role == "assistant").order_by(AgentMessage.sequence))).all()
    finals = [m for m in rows if m.status == "complete" and m.content and not (
        isinstance(m.tool_calls, dict) and m.tool_calls.get("calls"))]
    if not finals: return {"ok": False, "error_code": "history_citation_not_found"}
    if len(finals) != 1: return {"ok": False, "error_code": "history_citation_invalid"}
    manifest = finals[0].tool_calls.get("citations", []) if isinstance(finals[0].tool_calls, dict) else []
    if not isinstance(manifest, list): return {"ok": False, "error_code": "history_citation_invalid"}
    candidate_matches = [c for c in manifest if isinstance(c, dict) and c.get("ordinal") == ordinal]
    if any(isinstance(c.get("ordinal"), bool) or not isinstance(c.get("ordinal"), int) for c in candidate_matches):
        return {"ok": False, "error_code": "history_citation_invalid"}
    matches = candidate_matches
    if len(matches) > 1: return {"ok": False, "error_code": "history_citation_invalid"}
    if not matches: return {"ok": False, "error_code": "history_citation_not_found"}
    if (not isinstance(matches[0].get("source_type"), str) or not isinstance(matches[0].get("title"), str)
            or not isinstance(matches[0].get("quote"), str)):
        return {"ok": False, "error_code": "history_citation_invalid"}
    return {"ok": True, "citation": dict(matches[0]), "origin": {"turn_id": str(tid), "ordinal": ordinal}}


READ_TURN_CHARS = 12000


def _cut_text(text: str) -> tuple[str, bool]:
    """A stored text for ``read_turn``: whole, or its first 12,000 characters and a mark saying how long it was."""
    text = text or ""
    if len(text) <= READ_TURN_CHARS: return text, False
    return text[:READ_TURN_CHARS] + f"\n…（已截断，原文共 {len(text)} 字）", True


async def read_turn(conversation_id: str, credential: str, turn_id: str) -> dict | None:
    """One earlier turn of this conversation as it was said: the owner's message(s) of the turn in order, its final answer, its time and the
    turns just before and after.  None when the conversation is not this credential's or has no such turn."""
    try:
        cid, tid = uuid.UUID(str(conversation_id)), uuid.UUID(str(turn_id))
    except (ValueError, TypeError, AttributeError):
        return None
    async with Session() as s:
        owned = await s.scalar(select(AgentConversation.id).where(AgentConversation.id == cid, AgentConversation.owner_hash == owner_hash(credential)))
        if owned is None: return None
        rows = (await s.scalars(select(AgentMessage).where(AgentMessage.conversation_id == cid, AgentMessage.role.in_(("user", "assistant")))
                                .order_by(AgentMessage.sequence))).all()
    first: dict = {}
    for m in rows:
        first.setdefault(m.turn_id, m.sequence)
    if tid not in first: return None
    order = sorted(first, key=first.get)
    at = order.index(tid)
    mine = [m for m in rows if m.turn_id == tid]
    users = [m for m in mine if m.role == "user"]
    final = next((m for m in reversed(mine) if m.role == "assistant" and (m.content or "").strip()
                  and not (isinstance(m.tool_calls, dict) and m.tool_calls.get("calls"))), None)
    named = layers.reply_to_of({"tool_calls": final.tool_calls} if final is not None else None)
    if named:     # the answer names the messages it answered; a message it did not answer is not part of this turn's story
        answered = [m for m in users if str(m.id) in named]
        users = answered or users
    texts = [_cut_text(m.content) for m in users]
    answer = _cut_text(final.content) if final is not None else (None, False)
    stamp = (users[0] if users else mine[0]).created_at
    return {"turn_id": str(tid), "time": stamp.isoformat() if stamp else None, "user_messages": [t for t, _ in texts], "answer": answer[0], "answer_status": (final.status or "complete") if final is not None else "no_answer",
            "cut": any(c for _, c in texts) or answer[1], "previous_turn_id": str(order[at - 1]) if at else None,
            "next_turn_id": str(order[at + 1]) if at + 1 < len(order) else None}


async def citation_remembered(conversation_id: str, credential: str, turn_id: str, ordinal: int) -> bool:
    """Whether a {turn_id, ordinal} may be fetched although the turn is no longer in the visible catalogue:
    the newest rolling summary names it as a source, or the turn lies inside what the summary covers."""
    try:
        cid, tid = uuid.UUID(conversation_id), uuid.UUID(turn_id)
    except (ValueError, TypeError, AttributeError):
        return False
    if not await verify_conversation(conversation_id, credential):
        return False
    async with Session() as s:
        latest = (await s.scalars(select(AgentConversationSummary).where(AgentConversationSummary.conversation_id == cid)
                                  .order_by(AgentConversationSummary.seq.desc()).limit(1))).first()
        if latest is None:
            return False
        rolling = layers.parse_rolling(latest.content)
        for key in layers.ROLLING_SOURCED:
            for item in (rolling or {}).get(key, []):
                if isinstance(item, dict) and item.get("turn_id") == turn_id and item.get("ordinal") == ordinal:
                    return True
        last = await s.scalar(select(func.max(AgentMessage.sequence)).where(AgentMessage.conversation_id == cid,
                                                                             AgentMessage.turn_id == tid))
    return last is not None and last <= latest.upto_sequence


async def append_summary(conversation_id: str, from_sequence: int, upto_sequence: int, content: str, turn_ids=None) -> bool:
    """Append the next summary segment.  False when it would not move the covered range forward
    (another task got there first) or when the segment number was taken in the meantime."""
    cid = uuid.UUID(conversation_id)
    async with Session() as s:
        last = (await s.execute(select(AgentConversationSummary.seq, AgentConversationSummary.upto_sequence)
                                .where(AgentConversationSummary.conversation_id == cid)
                                .order_by(AgentConversationSummary.seq.desc()).limit(1))).first()
        if last is not None and upto_sequence <= last.upto_sequence:
            return False
        s.add(AgentConversationSummary(conversation_id=cid, seq=(last.seq if last else 0) + 1,
                                       from_sequence=from_sequence, upto_sequence=upto_sequence, content=content,
                                       turn_ids=[str(t) for t in turn_ids] if turn_ids else None))
        seq=(last.seq if last else 0) + 1
        try:
            await s.commit()
        except IntegrityError:
            await s.rollback()
            return False
    await _recall(recall.index_summary, conversation_id, seq, content)
    return True


def _eligible_turn_groups(rows):
    groups=layers.group_by_turn(rows,key=lambda row:row.turn_id)
    # A tool-request row is written complete before its tools run, so a turn that ends on one
    # is still running: its answer is not there yet and must not be restored half-finished.
    def tool_request(row):
        protocol=getattr(row,"tool_calls",None)
        return isinstance(protocol,dict) and bool(protocol.get("calls"))
    return [group for group in groups
            if group and group[0].role=="user" and group[-1].role=="assistant"
            and group[-1].status in {"complete","failed","cancelled"}
            and not tool_request(group[-1])]


def _select_message_page(groups, before_sequence=None, limit_turns=20):
    """Choose complete turns for the browser, newest first.

    The browser history is not the model context: it has no total byte budget.  A page
    is bounded by whole turns so a restored answer always carries its own tool rows;
    before_sequence is the exclusive cursor returned as next_before.
    """
    # Turns that ran together overlap in their rows.  A page is a set of whole turns taken in the order they were answered (the order of
    # the model's history too), so the cursor is a position in that order: every turn left for the next page ends before it.
    groups=sorted(groups,key=lambda group:group[-1].sequence)
    if before_sequence is not None:
        groups=[group for group in groups if group[-1].sequence < before_sequence]
    if limit_turns is None:
        selected,rest=groups,[]
    else:
        keep=max(1,min(100,int(limit_turns)))
        selected,rest=groups[-keep:],groups[:-keep]
    has_more=bool(rest)
    next_before=None
    if has_more and selected:
        # The first row of the oldest turn on the page, as always, when everything left ends before it; else (a turn left behind
        # overlaps it) the last row of that turn, which every turn left ends before.
        next_before=selected[0][0].sequence if selected[0][0].sequence > max(group[-1].sequence for group in rest) else selected[0][-1].sequence
    return selected,has_more,next_before


async def owned_message_page(conversation_id: str, credential: str, *, before_sequence=None, limit_turns=20):
    """One page of complete turns for the browser, independent of the model context budget."""
    if not await verify_conversation(conversation_id,credential): return None
    async with Session() as s:
        rows=(await s.scalars(select(AgentMessage)
              .where(AgentMessage.conversation_id==uuid.UUID(conversation_id))
              .order_by(AgentMessage.sequence.asc()))).all()
    async with Session() as s:
        versions=(await s.scalars(select(AgentConversationSummary)
                  .where(AgentConversationSummary.conversation_id==uuid.UUID(conversation_id))
                  .order_by(AgentConversationSummary.seq.asc()))).all()
    selected,has_more,next_before=_select_message_page(_eligible_turn_groups(rows),before_sequence,limit_turns)
    return {"messages":[{**({"id":str(m.id)} if getattr(m,"id",None) else {}),"role":m.role,"content":m.content,"tool_calls":m.tool_calls,"tool_call_id":m.tool_call_id,
                         "status":m.status,"turn_id":str(m.turn_id)} for group in selected for m in group],
            "has_more":has_more,"next_before":next_before,
            "compactions":compaction_notices(rows,versions)}


def compaction_notices(rows,versions):
    """The 「已压缩 N 轮」 lines of a conversation: one per rolling summary version, placed after the newest
    turn that existed when it was made, with the summary text to open.  Legacy free-text segments make none."""
    notices=[]
    for version in versions:
        rolling=layers.parse_rolling(version.content)
        if rolling is None: continue
        # After the last answer that existed then (an unfinished turn gets its notice once it has answered).
        before=[m for m in rows if m.role=="assistant" and m.content and m.status=="complete"
                and m.created_at and version.created_at and m.created_at<=version.created_at]
        notices.append({"id":version.seq,"after_turn_id":str(before[-1].turn_id) if before else None,
                        "turns":int(rolling.get("turns_compacted",0)),"total":int(rolling.get("total_compacted",0)),
                        "focus":rolling.get("focus"),"summary":layers.render_rolling(rolling),
                        "created_at":version.created_at.isoformat() if version.created_at else None})
    return notices


async def owned_messages(conversation_id: str,credential: str):
    """All complete turns for legacy callers; the browser uses owned_message_page."""
    page=await owned_message_page(conversation_id,credential,limit_turns=None)
    return None if page is None else page["messages"]

def ensure_conversation_archive_column() -> None:
    """Add the archive column to an existing table.  A fresh database gets it from the model.

    This module's own engine is the async one; startup DDL must use the synchronous engine.
    """
    from sqlalchemy import text
    from .database import engine as sync_engine
    with sync_engine.begin() as connection:
        connection.execute(text("ALTER TABLE agent_conversations ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ"))
        # The bot whose line a conversation is (agent_bots); NULL until the default bot adopts it.
        connection.execute(text("ALTER TABLE agent_conversations ADD COLUMN IF NOT EXISTS bot_id UUID"))
        # Where a conversation came from when it was not the owner ("ruler"): left out of the memory review (11-28).
        connection.execute(text("ALTER TABLE agent_conversations ADD COLUMN IF NOT EXISTS origin VARCHAR(16)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_conversations_bot_id ON agent_conversations (bot_id)"))
        # The turns a summary covers, by id (3c: turns that ran together overlap in their rows).  Older segments keep NULL and read by range.
        connection.execute(text("ALTER TABLE IF EXISTS agent_conversation_summaries ADD COLUMN IF NOT EXISTS turn_ids JSON"))


async def set_conversation_archived(credential: str, conversation_id: str, archived: bool) -> bool:
    """Archive (hide) or restore one of this credential's conversations.  False when it is not theirs."""
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        return False
    async with Session() as s:
        owned = await s.scalar(select(AgentConversation.id).where(
            AgentConversation.id == cid, AgentConversation.owner_hash == owner_hash(credential)))
        if owned is None:
            return False
        row = await s.get(AgentConversation, cid)
        row.archived_at = func.now() if archived else None
        await s.commit()
        return True


async def finish_conversation(conversation_id: str, status: str):
    async with Session() as s:
        conv=await s.get(AgentConversation,uuid.UUID(conversation_id))
        if conv:
            conv.status=status
            await s.commit()

async def list_conversations(credential: str, limit: int = 20, offset: int = 0, include_archived: bool = False):
    """Return only conversations owned by this credential, with a bounded title lookup: the name the
    owner gave it, else the first question.  Archived conversations are hidden unless asked for."""
    async with Session() as s:
        first_question = (select(AgentMessage.content)
            .where(AgentMessage.conversation_id == AgentConversation.id, AgentMessage.role == "user")
            .order_by(AgentMessage.sequence.asc()).limit(1).scalar_subquery())
        rows = (await s.execute(
            select(AgentConversation.id, AgentConversation.created_at, AgentConversation.updated_at, first_question,
                   AgentConversationTitle.title)
            .outerjoin(AgentConversationTitle, AgentConversationTitle.conversation_id == AgentConversation.id)
            .where(AgentConversation.owner_hash == owner_hash(credential))
            .where(AgentConversation.archived_at.is_(None) if not include_archived else true())
            .order_by(AgentConversation.updated_at.desc(), AgentConversation.id.desc())
            .offset(offset).limit(limit)
        )).all()
        output = []
        for cid, created_at, updated_at, title, custom in rows:
            output.append({"id": str(cid), "created_at": created_at.isoformat(), "updated_at": updated_at.isoformat(),
                           "title": (custom or title or "新建对话")[:120], "custom_title": bool(custom)})
        return output


async def set_conversation_title(credential: str, conversation_id: str, title: str | None) -> bool:
    """Name (or, with None, un-name) one of this owner's conversations.  False when it is not theirs."""
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        return False
    async with Session() as s:
        owned = await s.scalar(select(AgentConversation.id).where(
            AgentConversation.id == cid, AgentConversation.owner_hash == owner_hash(credential)))
        if owned is None:
            return False
        row = await s.get(AgentConversationTitle, cid)
        if not title:
            if row is not None:
                await s.delete(row)
        elif row is None:
            s.add(AgentConversationTitle(conversation_id=cid, title=title))
        else:
            row.title = title
        await s.commit()
    await _recall(recall.index_title, conversation_id)
    return True


MAX_RESEARCH_QUEUE = 30  # the same bound as the front end's list


def clean_queue(symbols) -> list[str]:
    """Tickers in the form the workspace uses, each once, at most MAX_RESEARCH_QUEUE; anything else is dropped."""
    from .symbols import normalize_market_symbol
    seen: list[str] = []
    for value in symbols if isinstance(symbols, (list, tuple)) else []:
        try:
            symbol = normalize_market_symbol(value)
        except ValueError:
            continue
        if symbol not in seen:
            seen.append(symbol)
    return seen[:MAX_RESEARCH_QUEUE]


async def get_research_queue(credential: str) -> list[str] | None:
    """The owner's saved queue; None when none was ever saved (an empty list is a queue the owner emptied)."""
    async with Session() as s:
        row = await s.get(AgentResearchQueue, owner_hash(credential))
        return None if row is None else clean_queue(row.symbols)


async def put_research_queue(credential: str, symbols) -> list[str]:
    queue = clean_queue(symbols)
    async with Session() as s:
        row = await s.get(AgentResearchQueue, owner_hash(credential))
        if row is None:
            s.add(AgentResearchQueue(owner_hash=owner_hash(credential), symbols=queue))
        else:
            row.symbols = queue
        await s.commit()
    return queue

