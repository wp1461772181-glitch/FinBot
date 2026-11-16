"""Read and bind previously saved citation snapshots as current-turn evidence."""
from __future__ import annotations

import asyncio
import copy

from .fp_flags import flag

# SW2 (R2): a saved source is read back in pages of the full saved text, never the 5000-char display quote.
HISTORY_PAGE_CHARS = 8000
HISTORY_PAGE_NOTE = '这是已保存正文的第 {start}–{end} 字，共 {total} 字。没读到的部分不能当作"原文没有"；要继续读，用 offset={next_offset} 再调一次。'
HISTORY_STORED_PARTIAL_NOTE = '这份来源保存时超过 120000 字，后面的部分没有保存；在已保存部分里找不到的内容，只能说"已保存部分里没有"。'
# Keys a paged read adds to the bound row (K1); a read with the flag off never has them, so the bound row keeps its five keys.
PAGE_KEYS = ("offset", "chars_total", "next_offset", "complete", "stored_partial", "note")


def _failure(code: str) -> dict:
    return {"ok": False, "data": [], "error_code": code}


async def read_history_citation(args: dict, context, *, page_chars: int | None = None) -> dict:
    turn_id, ordinal = args.get("turn_id"), args.get("ordinal")
    if not isinstance(turn_id, str) or isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1:
        return _failure("history_citation_not_found")
    allowed = next((x for x in context.history_citation_catalogue
                   if isinstance(x, dict) and x.get("turn_id") == turn_id and any(
                       isinstance(s, dict) and not isinstance(s.get("ordinal"), bool)
                       and type(s.get("ordinal")) is int and s.get("ordinal") == ordinal
                       for s in x.get("sources", []) if isinstance(x.get("sources", []), (list, tuple)))), None)
    from ..agent_chat_store import citation_remembered, load_turn_citation
    # A turn that a rolling summary has folded away is out of the catalogue, but the summary's own
    # {turn_id, ordinal} marker (or recall's hit on its text) is a legitimate way back to the saved source.
    if allowed is None and not await citation_remembered(context.conversation_id, context.identity_credential,
                                                         turn_id, ordinal):
        return _failure("history_citation_not_found")
    found = await load_turn_citation(context.conversation_id, context.identity_credential, turn_id, ordinal)
    if not found.get("ok"): return _failure(found.get("error_code", "history_citation_not_found"))
    citation = found["citation"]
    calculation = citation.get("calculation") if isinstance(citation.get("calculation"), dict) else {}
    if citation.get("derived") or citation.get("source_type") in {"calculation", "formula_calculation"}:
        parents = citation.get("parents") or calculation.get("parents") or []
        return {
            **_failure("history_citation_derived"),
            "parents": parents,
            "hint": "这是计算来源，不能直接取回；先读取 parents 中的原始来源，再用 calculate 或 calculate_formula 重算。",
        }
    try:
        from ..agent_chat_stream import _restore_citations
        restored = await asyncio.to_thread(_restore_citations, [citation], context.identity_credential)
    except Exception:
        return _failure("history_citation_unavailable")
    if not restored or restored[0].get("source_type") == "unavailable" or not str(restored[0].get("quote") or "").strip():
        return _failure("history_citation_unavailable")
    snapshot = copy.deepcopy(restored[0])
    if flag("FINBOT_SW2_HISTORY_PAGES", True):
        return _paged_outcome(snapshot, found["origin"], args, page_chars)
    quote = str(snapshot.get("quote") or "")
    # Keep the verified full snapshot for this turn's manifest; bound only the tool payload.
    truncated = bool(snapshot.get("truncated")) or len(quote.encode("utf-8")) > 5200
    if truncated:
        quote = quote.encode("utf-8")[:5200].decode("utf-8", "ignore")
    data = {key: snapshot.get(key) for key in ("title", "source_type")}
    data.update(quote=quote, truncated=truncated, origin=found["origin"])
    return {"ok": True, "data": [data], "source": "history_citation", "_snapshot": snapshot}


def _paged_outcome(snapshot: dict, origin: dict, args: dict, page_chars: int | None) -> dict:
    """One page of the full saved text (the longer of quote and check_text), with its position stated."""
    offset = args.get("offset", 0)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return _failure("invalid_arguments")
    body = max(str(snapshot.get("quote") or ""), str(snapshot.get("check_text") or ""), key=len)
    total = len(body)
    start = min(offset, total)
    end = min(start + (page_chars or HISTORY_PAGE_CHARS), total)
    complete = end >= total
    stored_partial = bool(snapshot.get("evidence_incomplete"))
    notes = []
    if not complete:
        notes.append(HISTORY_PAGE_NOTE.format(start=start + 1, end=end, total=total, next_offset=end))
    if stored_partial:
        notes.append(HISTORY_STORED_PARTIAL_NOTE)
    data = {key: snapshot.get(key) for key in ("title", "source_type")}
    data.update(quote=body[start:end], truncated=(not complete) or stored_partial, origin=origin,
                offset=start, chars_total=total, next_offset=None if complete else end,
                complete=complete, stored_partial=stored_partial)
    if notes:
        data["note"] = " ".join(notes)
    return {"ok": True, "data": [data], "source": "history_citation", "_snapshot": snapshot}


def bind_history_citation(outcome: dict, citations: list[dict]) -> dict:
    if not outcome.get("ok") or not isinstance(outcome.get("_snapshot"), dict):
        return _failure(outcome.get("error_code", "history_citation_unavailable"))
    origin = outcome["data"][0]["origin"]
    existing = next((c for c in citations if c.get("origin") == origin), None)
    if existing is None:
        snapshot = copy.deepcopy(outcome["_snapshot"])
        snapshot["ordinal"] = len(citations) + 1
        snapshot["origin"] = origin
        citations.append(snapshot)
        ordinal = snapshot["ordinal"]
    else:
        ordinal = existing["ordinal"]
    row = outcome["data"][0]
    bound = {"citation": f"[{ordinal}]", "title": row.get("title"),
        "source_type": row.get("source_type"), "quote": row.get("quote"), "truncated": row.get("truncated", False)}
    # SW2 K1: the model sees only this bound row, so the page facts ride on it; a row without them stays five keys.
    bound.update({key: row[key] for key in PAGE_KEYS if key in row})
    return {"ok": True, "data": [bound]}
