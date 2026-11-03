"""Layered conversation context: what a turn gets of the conversation before it.

A turn used to see the newest complete turns up to a fixed size and nothing older.  Three layers
now share one budget:

* layer 1  the newest complete turns, word for word (half of the budget; see split_budget);
* layer 2  the turns before them, half compressed: the user's own words stay, an answer keeps its
           opening, and the tools a turn called stay as one line each (the result bodies live in
           the turn's result set, the names are what a later referent needs);
* layer 3  turns older still, as appended segment summaries (see ``agent_context_summary``).

The budget is not a hand-picked constant: it is half of the chosen model's context window
(``HISTORY_SHARE``; the model catalog carries the window per model, 128k by default), turned into
bytes with ``BYTES_PER_TOKEN`` (``budget_for_window``).  A different window recomputes the whole table;
there is no fixed ceiling.  When the history reaches ``COMPACT_AT`` of the budget it is compressed into
one rolling structured summary (``agent_context_summary``).  ``startup_self_check`` refuses a
configuration where a single turn cannot run.

Placement matters as much as size.  The three layers are the stable head of every request (layer 3
is appended after the user's own message, never merged into the system prompt), so that the bytes a
provider caches as a prefix survive into the next turn: only the newest question and the note after
it change.

This module holds the arithmetic and the rendering only (no database, no model), so that the turn
that sends a request and the endpoint that reports what the next request will carry share one
code path.  A conversation that fits in layer 1 is sent exactly as before.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

KB = 1024
BUDGET_KB_MIN = 16

# The history budget is a share of the model window, and it is spent the way a conversation is read:
# mostly on the newest turns, a little on the compressed ones, and the summary.
BYTES_PER_TOKEN = 3            # UTF-8 bytes per token: Chinese is ~3 bytes and ~1 token a character
DEFAULT_WINDOW_TOKENS = 128_000
HISTORY_SHARE = 0.5            # of the window: what earlier conversation may take
COMPACT_AT = 0.8               # history use (of the budget) at which the conversation is compressed
COMPACT_TARGET = 0.5           # ...and the use a compression aims to come back under
EXTRAS_TOKENS = 4_000          # one turn's evidence, notes and profile on top of the measured part


def measure_fixed_tokens() -> int:
    """What every request carries, measured: the fixed system prompt with its category list, the tool
    definitions of a default turn (the always-on set; categories come with load_tools or the intent),
    plus ``EXTRAS_TOKENS`` for evidence and the turn's own notes.  Bytes count as ``BYTES_PER_TOKEN``."""
    from .agent_system_prompt import INSTRUCTION, disclosure_note
    from .agent_tool_catalog import ALWAYS_ON, TOOL_CATEGORIES, schemas
    system = "\n".join(INSTRUCTION) + "\n" + disclosure_note(TOOL_CATEGORIES.values())
    tool_bytes = len(json.dumps(schemas(owner=True, names=ALWAYS_ON), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return -(-(len(system.encode("utf-8")) + tool_bytes) // BYTES_PER_TOKEN) + EXTRAS_TOKENS


FIXED_TOKENS = measure_fixed_tokens()


def window_tokens(raw: str | None) -> int:
    """The configured model window in tokens.  A window small enough to break a turn is refused
    rather than silently accepted (see ``startup_self_check``)."""
    try:
        value = int(str(raw).strip()) if raw not in (None, "") else DEFAULT_WINDOW_TOKENS
    except ValueError:
        value = DEFAULT_WINDOW_TOKENS
    return max(4_000, value)


def budget_for_window(window: int) -> int:
    """Bytes of earlier conversation a model with this window may be sent: half the window, in bytes.
    The only floor is ``BUDGET_KB_MIN``; there is no ceiling, a 1M window gets a 1M-sized budget."""
    return max(BUDGET_KB_MIN * KB, int(window * HISTORY_SHARE) * BYTES_PER_TOKEN)


def guard_for_window(window: int) -> int:
    """One request at the door: the history plus the fixed part and this turn's evidence."""
    return budget_for_window(window) * 3 // 2


def running_bytes_for_window(window: int) -> int:
    """A turn in flight also carries its own tool results; it may not outgrow the window itself."""
    return max(guard_for_window(window), int(window) * BYTES_PER_TOKEN)


def layer_sizes(window: int) -> tuple[int, int, int]:
    """(layer 1, layer 2, layer 3) bytes for a model window."""
    return split_budget(budget_for_window(window))


def split_budget(budget_bytes: int) -> tuple[int, int, int]:
    """(layer 1, layer 2, layer 3) of a history budget.

    Layer 1 takes a half where the course gives it seven tenths: a raw turn of this product carries
    its whole tool batch, so it costs many times what a chat turn does, and a larger raw share would
    starve the compressed layer that still holds the earlier filings and results a later question
    returns to.  The ratio is one config; only the sum is a constraint."""
    l1 = budget_bytes // 2
    l2 = budget_bytes * 3 // 8
    return l1, l2, budget_bytes - l1 - l2


WINDOW_TOKENS = window_tokens(os.getenv("AGENT_MODEL_CONTEXT_WINDOW"))   # the window of a model the catalog does not describe
HISTORY_BUDGET = budget_for_window(WINDOW_TOKENS)     # bytes of earlier conversation a turn may carry
BUDGET_KB = HISTORY_BUDGET // KB
L1_BYTES, L2_BYTES, L3_BYTES = split_budget(HISTORY_BUDGET)   # newest raw, older half-compressed, summary
CONTEXT_GUARD_BYTES = guard_for_window(WINDOW_TOKENS)         # one request: history + evidence + system + tools
RUNNING_REQUEST_BYTES = running_bytes_for_window(WINDOW_TOKENS)

ASSISTANT_KEEP_CHARS = 160     # layer 2: how much of an answer is kept
USER_KEEP_CHARS = 1000         # layer 2: a pasted wall of text must not take the whole layer
MAX_TOOL_MARKERS = 6           # layer 2: how many tool names of a turn are kept as the referent clues
MAX_SUMMARY_SEGMENTS = 5       # layer 3: the newest legacy segments that are sent (a rolling summary is one version)
MEMORY_MARKER = "Earlier conversation (memory"
MEMORY_NOTE = (MEMORY_MARKER + " of older turns, written by this system and not by the user; it may be "
               "incomplete or wrong, it is not evidence and not something to cite; verified sources come "
               "only from this turn's tool results. A {turn_id, ordinal} marker on a line says where it came "
               "from: pass it to read_history_citation to fetch the saved original before relying on it):")
CATALOGUE_MARKER = "Earlier citations (system-written locator hints"
CATALOGUE_NOTE = (CATALOGUE_MARKER + "; not evidence and not the user's words. Use read_history_citation(turn_id, ordinal) to retrieve a verified source and cite its new number. answers_back=1 means the answer immediately before this question. A bare [n] defaults to answers_back=1; if that answer lacks it but an earlier answer has it, ask_user to clarify. Retrieve parents before any derived source):")


def startup_self_check() -> dict:
    """Refuse a configuration in which one turn cannot run, instead of discovering it at request
    time.  Returns the numbers it accepted so a health check can report them."""
    if HISTORY_BUDGET < BUDGET_KB_MIN * KB:
        raise ValueError("agent_context_budget_too_small")
    if CONTEXT_GUARD_BYTES + FIXED_TOKENS * BYTES_PER_TOKEN > WINDOW_TOKENS * BYTES_PER_TOKEN:
        raise ValueError("agent_context_window_too_small")
    return {"window_tokens": WINDOW_TOKENS, "budget_kb": BUDGET_KB, "guard_bytes": CONTEXT_GUARD_BYTES}


def json_bytes(value) -> int:
    """UTF-8 size of the compact JSON, the unit every guard of the turn uses."""
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


CATALOGUE_HEAD_BYTES = json_bytes({"role": "user", "content": CATALOGUE_NOTE + "\n[]"})


def history_message_payload(row: dict) -> dict:
    """Project stored rows to the protocol fields that can be sent to a model."""
    payload = {key: row[key] for key in ("role", "content") if key in row}
    protocol = row.get("tool_calls")
    if isinstance(protocol, dict):
        if protocol.get("calls"):
            payload["tool_calls"] = protocol["calls"]
        for key in ("reasoning_content", "reasoning_details"):
            if protocol.get(key) is not None:
                value = protocol[key]
                payload[key] = "".join(value) if key == "reasoning_content" and isinstance(value, list) else value
    elif protocol:
        payload["tool_calls"] = protocol
    if row.get("tool_call_id") is not None:
        payload["tool_call_id"] = row["tool_call_id"]
    return payload


def estimate_tokens(size_bytes: int) -> int:
    return size_bytes // BYTES_PER_TOKEN


@dataclass(frozen=True)
class Turn:
    """One complete turn as text: the user's message, the answer that closed it, and the tools it
    called (kept as names only: the referent a later question points at is usually something a tool
    found, so the names stay while the result bodies do not)."""
    first_sequence: int
    last_sequence: int
    user: str
    assistant: str
    tools: tuple[str, ...] = ()
    turn_id: str = ""
    catalogue: dict | None = None


def row_bytes(row: dict) -> int:
    """Gate B history billing: only user/final assistant role and content are carried."""
    role = row.get("role")
    protocol = row.get("tool_calls")
    if role == "tool" or (role == "assistant" and isinstance(protocol, dict) and protocol.get("calls")):
        return 0
    if role not in {"user", "assistant"}:
        return 0
    return json_bytes({"role": role, "content": row.get("content") or ""})


def project_turn_history(group: list[dict]) -> list[dict]:
    user = next((r for r in group if r.get("role") == "user"), None)
    answer = next((r for r in reversed(group) if r.get("role") == "assistant" and not (
        isinstance(r.get("tool_calls"), dict) and r["tool_calls"].get("calls"))), None)
    result = []
    if user is not None: result.append({"role": "user", "content": user.get("content") or ""})
    if answer is not None and (answer.get("content") or "").strip():
        result.append({"role": "assistant", "content": answer["content"]})
    return result


def turn_catalogue_entry(group: list[dict]) -> dict | None:
    history = project_turn_history(group)
    if len(history) < 2: return None
    answer = history[-1]["content"]
    matches = {int(n) for n in re.findall(r"\[(\d{1,4})\]", answer)}
    final = next((r for r in reversed(group) if r.get("role") == "assistant" and not (
        isinstance(r.get("tool_calls"), dict) and r["tool_calls"].get("calls"))), {})
    protocol = final.get("tool_calls") or {}
    citations = protocol.get("citations", []) if isinstance(protocol, dict) else []
    sources = []
    for item in citations if isinstance(citations, list) else []:
        if not isinstance(item, dict): continue
        ordinal = item.get("ordinal")
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal not in matches: continue
        title = re.sub(r"https?://\S+", "", str(item.get("title") or "")).strip()[:80]
        source = {"ordinal": ordinal, "title": title,
                  "source_type": str(item.get("source_type") or "unknown"),
                  "available": bool(item.get("quote")) and not item.get("unavailable") and item.get("source_type") != "unavailable"}
        if item.get("derived") or item.get("source_type") in {"calculation", "formula_calculation"}:
            source["derived"] = True
            parents = item.get("parents") or (item.get("calculation") or {}).get("parents", [])
            source["parents"] = [p for p in parents if isinstance(p, int)]
        sources.append(source)
    if not sources: return None
    opening = re.sub(r"https?://\S+", "", answer[:80])
    opening = re.sub(r"\b[0-9a-fA-F]{64}\b", "", opening).strip()[:40]
    return {"turn_id": str(group[0].get("turn_id") or ""), "opening": opening, "sources": sources}


def render_citation_catalogue(entries: list[dict]) -> dict | None:
    if not entries: return None
    return {"role": "user", "content": CATALOGUE_NOTE + "\n" + json.dumps(entries, ensure_ascii=False, separators=(",", ":"))}


def catalogue_bytes(entries: list[dict]) -> int:
    """Exact serialized size of the catalogue message as it is sent to the model."""
    message = render_citation_catalogue(entries)
    return json_bytes(message) if message else 0


def catalogue_entry_bytes(entry: dict, existing: list[dict] | None = None) -> int:
    """Marginal serialized growth, including escaped JSON, commas and array brackets."""
    base = list(existing or [])
    before = catalogue_bytes(base)
    return catalogue_bytes(base + [entry]) - before


def is_catalogue_message(message: dict) -> bool:
    return isinstance(message.get("content"), str) and message["content"].startswith(CATALOGUE_MARKER)


def complete_turns(rows: list[dict]) -> list[list[dict]]:
    """Stored messages (oldest first) grouped by turn; only turns that began with the user's message
    and ended with a complete answer.  A failed, cancelled or unanswered turn is in no layer."""
    groups: list[list[dict]] = []
    for row in rows:
        if not groups or groups[-1][0]["turn_id"] != row["turn_id"]:
            groups.append([])
        groups[-1].append(row)
    return [g for g in groups
            if g[0]["role"] == "user" and g[-1]["role"] == "assistant" and g[-1].get("status") == "complete"]


def newest_within(groups: list[list[dict]], limit: int) -> tuple[list[list[dict]], int]:
    """The newest turns that fit ``limit`` bytes (oldest first) and what they take: the rule the
    history window has always followed, and the whole of layer 1."""
    kept: list[list[dict]] = []
    used = 0
    for group in reversed(groups):
        size = sum(row_bytes(row) for row in group)
        if used + size > limit:
            break
        kept.insert(0, group)
        used += size
    return kept, used


def turn_tools(group: list[dict]) -> tuple[str, ...]:
    """The tool names a stored turn called, in call order, deduplicated and bounded."""
    names: list[str] = []
    for row in group:
        protocol = row.get("tool_calls")
        calls = protocol.get("calls", []) if isinstance(protocol, dict) else (protocol or [])
        for call in calls if isinstance(calls, list) else []:
            name = ((call or {}).get("function") or {}).get("name") if isinstance(call, dict) else None
            if isinstance(name, str) and name and name not in names:
                names.append(name)
    return tuple(names[:MAX_TOOL_MARKERS])


def layer_rows(rows: list[dict], segments: list[dict], *, l1_bytes: int = L1_BYTES, l2_bytes: int = L2_BYTES,
               l3_bytes: int = L3_BYTES) -> dict:
    """What the next turn carries of the turns before it, by layer.  ``rows`` are the stored messages
    (oldest first, each with ``sequence``), ``segments`` the summary segments made so far.

    Layer 1 is the newest complete turns that fit (as stored, tool batches included).  Layer 2 is the
    complete turns before them that no segment covers yet, the newest that fit as text; what does not
    fit is ``overflow``, the turns the next segment has to take over.  Layer 3 is the newest segments
    that fit.  A conversation that fits layer 1 has nothing in the other two."""
    upto = segments[-1]["upto_sequence"] if segments else 0
    # A turn a summary version already covers is memory now: it is in no raw layer any more.
    complete = [g for g in complete_turns(rows) if g[0]["sequence"] > upto]
    entries = {str(g[0].get("turn_id")): turn_catalogue_entry(g) for g in complete}
    recent: list[list[dict]] = []
    # Reserve the fixed prefix in L1 only if at least one directory entry can fit in
    # either layer by itself; omitted/overflow-only entries must not consume budget.
    has_catalogue = any(entry and (
        sum(json_bytes(row) for row in project_turn_history(group)) + catalogue_bytes([{**entry, "answers_back": 1}]) <= l1_bytes
        or half_size(Turn(group[0]["sequence"], group[-1]["sequence"], group[0].get("content") or "",
                          project_turn_history(group)[-1]["content"] if len(project_turn_history(group)) > 1 else "",
                          (), str(group[0].get("turn_id") or ""), entry))
           + catalogue_bytes([{**entry, "answers_back": 1}]) <= l2_bytes)
        for group in complete if (entry := entries.get(str(group[0].get("turn_id")))))
    used = CATALOGUE_HEAD_BYTES if has_catalogue else 0
    recent_catalogue: list[dict] = []
    for group in reversed(complete):
        entry = entries.get(str(group[0].get("turn_id")))
        projected = project_turn_history(group)
        cost = sum(json_bytes(row) for row in projected)
        if entry:
            billed_entry = {**entry, "answers_back": len(recent) + 1}
            before = catalogue_bytes(recent_catalogue) if recent_catalogue else (CATALOGUE_HEAD_BYTES if has_catalogue else 0)
            cost += catalogue_bytes([*recent_catalogue, billed_entry]) - before
        if used + cost > l1_bytes: break
        recent.insert(0, group); used += cost
        if entry: recent_catalogue.append({**entry, "answers_back": len(recent)})
    older = complete[:len(complete) - len(recent)]
    turns = [Turn(g[0]["sequence"], g[-1]["sequence"], g[0].get("content") or "", project_turn_history(g)[-1]["content"] if len(project_turn_history(g)) > 1 else "",
                  (), str(g[0].get("turn_id") or ""), entries.get(str(g[0].get("turn_id"))))
             for g in older]
    live = [Turn(g[0]["sequence"], g[-1]["sequence"], g[0].get("content") or "",
                 project_turn_history(g)[-1]["content"] if len(project_turn_history(g)) > 1 else "",
                 (), str(g[0].get("turn_id") or ""), entries.get(str(g[0].get("turn_id")))) for g in complete]
    half: list[Turn] = []; used_half = 0
    selected_catalogue = [{**entries[str(g[0].get("turn_id"))], "answers_back": idx}
                          for idx, g in enumerate(reversed(recent), 1)
                          if entries.get(str(g[0].get("turn_id")))]
    for turn in reversed(turns):
        cost = half_size(turn)
        if turn.catalogue:
            billed_entry = {**turn.catalogue, "answers_back": len(recent) + len(half) + 1}
            before = catalogue_bytes(selected_catalogue) if selected_catalogue else (CATALOGUE_HEAD_BYTES if has_catalogue else 0)
            cost += catalogue_bytes([*selected_catalogue, billed_entry]) - before
        if used_half + cost > l2_bytes: break
        half.append(turn); used_half += cost
        if turn.catalogue:
            selected_catalogue.append({**turn.catalogue, "answers_back": len(recent) + len(half)})
    half.reverse(); overflow = turns[:len(turns)-len(half)]
    catalogue=[]
    visible = [str(g[0].get("turn_id")) for g in reversed(recent)] + [t.turn_id for t in reversed(half)]
    for idx, tid in enumerate(visible, 1):
        entry=entries.get(tid)
        if entry:
            catalogue.append({**entry,"answers_back":idx})
    # A candidate catalogue can reserve the fixed prefix during selection, then
    # disappear when its only source is summarized or falls outside both layers.
    # Charge that prefix only when the final rendered catalogue is nonempty.
    if not catalogue and has_catalogue:
        used = max(0, used - CATALOGUE_HEAD_BYTES)
    keys = ("role", "content", "tool_calls", "tool_call_id", "status", "turn_id")
    return {"l1_rows": [{key: (str(row[key]) if key == "turn_id" else row.get(key)) for key in keys}
                        for group in recent for row in group],
            "l1_turns": len(recent), "l1_bytes": used, "half_turns": half, "overflow": overflow,
            "segments": select_segments(segments, l3_bytes), "segments_total": len(segments), "summary_upto": upto,
            "catalogue": catalogue, "budget": l1_bytes + l2_bytes + l3_bytes, "live_turns": live}


def _head(text: str, keep: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= keep else text[:keep].rstrip() + "…(略)"


def half_messages(turn: Turn) -> list[dict]:
    """Layer 2 form of a turn: the user's words, the opening of the answer, and one line naming the
    tools it called.  The rule is cheap and mechanical on purpose -- compressing by model is what
    layer 3 is for."""
    messages = [{"role": "user", "content": _head(turn.user, USER_KEEP_CHARS)}]
    answer = _head(turn.assistant, ASSISTANT_KEEP_CHARS)
    if answer.strip():
        messages.append({"role": "assistant", "content": answer})
    return messages


def half_size(turn: Turn) -> int:
    return sum(json_bytes(message) for message in half_messages(turn))


def select_half(turns: list[Turn], budget: int) -> tuple[list[Turn], list[Turn]]:
    """``turns`` oldest first.  The newest that fit the budget are kept (still oldest first); the
    older rest is returned apart: those turns are what a summary has to take over."""
    kept: list[Turn] = []
    used = 0
    for turn in reversed(turns):
        size = half_size(turn)
        if used + size > budget:
            break
        kept.append(turn)
        used += size
    kept.reverse()
    return kept, turns[:len(turns) - len(kept)]


def select_segments(segments: list[dict], budget: int, limit: int = MAX_SUMMARY_SEGMENTS) -> list[dict]:
    """The newest segment summaries that fit (oldest first); older ones are no longer worth the room."""
    if segments and parse_rolling(segments[-1].get("content")) is not None:
        return [segments[-1]]          # a rolling version already holds everything before it
    chosen: list[dict] = []
    used = 0
    for segment in reversed(segments):
        size = len(str(segment.get("content", "")).encode("utf-8")) + 8
        if len(chosen) >= limit or used + size > budget:
            break
        chosen.append(segment)
        used += size
    chosen.reverse()
    return chosen


def summary_message(segments: list[dict]) -> dict | None:
    """Layer 3 as the one note that carries it, or None.

    It is sent *after* the user's own message, not as a second system message at the head: the head
    of a request is what a provider caches as a prefix, and a note that grows a segment every few
    turns would invalidate everything behind it.  It is a user turn because a system turn in the
    middle of the conversation is not portable across providers, and the text says who wrote it."""
    lines = []
    for index, segment in enumerate(segments, 1):
        rolling = parse_rolling(segment.get("content"))
        text = render_rolling(rolling) if rolling is not None else str(segment.get("content", "")).strip()
        if text:
            lines.append(f"{index}. {text}")
    if not lines:
        return None
    return {"role": "user", "content": MEMORY_NOTE + "\n" + "\n".join(lines)}


def is_memory_message(message: dict) -> bool:
    """Whether a message is this module's layer-3 note rather than something a person said."""
    content = message.get("content")
    return isinstance(content, str) and content.startswith(MEMORY_MARKER)


def conversation_messages(messages: list[dict]) -> list[dict]:
    """The messages that are the conversation itself: the compressed turns, the raw turns and the
    current question.  The layer-3 note is appended last and is not part of them."""
    return [message for message in messages if not is_memory_message(message) and not is_catalogue_message(message)]


def history_messages(half_turns: list[Turn]) -> list[dict]:
    """The head of a request before layer 1: the half-compressed turns, oldest first."""
    messages: list[dict] = []
    for turn in half_turns:
        messages.extend(half_messages(turn))
    return messages


ROLLING_VERSION = 2
ROLLING_LISTS = ("goals", "conclusions", "open", "preferences", "numbers")
ROLLING_SOURCED = ("conclusions", "numbers")     # items that must carry {turn_id, ordinal}


def parse_rolling(content) -> dict | None:
    """The structured rolling summary stored in a summary row, or None for a legacy free-text segment."""
    if not isinstance(content, str) or not content.startswith("{"):
        return None
    try:
        value = json.loads(content)
    except ValueError:
        return None
    return value if isinstance(value, dict) and value.get("v") == ROLLING_VERSION else None


def render_rolling(summary: dict) -> str:
    """The summary as the note's text.  Every conclusion and number shows its source marker, which
    ``read_history_citation(turn_id, ordinal)`` takes to fetch the saved original."""
    titles = {"goals": "目标", "conclusions": "结论与出处", "open": "未办完", "preferences": "偏好", "numbers": "关键数字"}
    lines = []
    for key in ROLLING_LISTS:
        items = summary.get(key) or []
        parts = []
        for item in items:
            if isinstance(item, dict):
                parts.append(f"{item.get('text', '')} {{turn_id={item.get('turn_id')}, ordinal={item.get('ordinal')}}}")
            else:
                parts.append(str(item))
        if parts:
            lines.append(f"{titles[key]}: " + "; ".join(parts))
    return "\n".join(lines)


def history_usage(context: dict) -> dict:
    """How much of the history budget the next turn would spend: the summary note, the raw turns, and
    every turn not yet summarized at its half-compressed size (the part layer 2 may have to drop)."""
    note = summary_message(context.get("segments", []))
    pending = sum(half_size(t) for t in [*context.get("half_turns", []), *context.get("overflow", [])])
    used = (json_bytes(note) if note else 0) + int(context.get("l1_bytes", 0)) + pending
    budget = int(context.get("budget") or HISTORY_BUDGET)
    return {"bytes": used, "budget": budget, "fraction": used / budget if budget else 0.0}


def should_compact(context: dict) -> bool:
    return history_usage(context)["fraction"] >= COMPACT_AT


def usage_report(*, system_bytes: int, tools_bytes: int, summary_bytes: int, summary_segments: int,
                 half_bytes: int, half_turns: int, recent_bytes: int, recent_turns: int,
                 hidden_turns: int, budget_bytes: int | None = None) -> dict:
    """The numbers of the context card.  "Remaining" is the room left in this product's history
    budget; it is not the window of whatever model the user chose (that is not known here)."""
    budget_bytes = int(budget_bytes or HISTORY_BUDGET)
    fixed = system_bytes + tools_bytes
    history = summary_bytes + half_bytes + recent_bytes
    capacity = fixed + budget_bytes
    remaining = max(0, budget_bytes - history)
    used_fraction = history / budget_bytes if budget_bytes else 0.0

    def part(key: str, size: int, **extra) -> dict:
        return {"key": key, "bytes": size, "tokens": estimate_tokens(size), **extra}

    return {
        "budget_kb": budget_bytes // KB,
        "budget_bytes": budget_bytes,
        "compact_at_percent": round(100 * COMPACT_AT),
        "history_used_percent": round(100 * used_fraction),
        "will_compact": used_fraction >= COMPACT_AT,
        "capacity_bytes": capacity,
        "used_bytes": fixed + history,
        "remaining_bytes": remaining,
        "remaining_percent": max(0, min(100, round(100 * remaining / capacity))) if capacity else 0,
        "compressing": bool(half_turns or summary_segments or hidden_turns),
        "hidden_turns": hidden_turns,
        "parts": [
            part("system", system_bytes),
            part("tools", tools_bytes),
            part("summary", summary_bytes, segments=summary_segments),
            part("compressed", half_bytes, turns=half_turns),
            part("recent", recent_bytes, turns=recent_turns),
            part("free", remaining),
        ],
    }
