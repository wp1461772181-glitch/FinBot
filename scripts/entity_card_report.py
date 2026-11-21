#!/usr/bin/env python3
"""Read-only count of the "请确认这次指代的公司" card (FINBOT_PH2_ENTITY_CARD_SHADOW, pre-hardcode audit M-12).

Every time that card is asked, the turn's audit keeps one record under ``entity_card_shadow``: what the classifier gave
(symbol / company), the first 200 characters of the user's own words, why each way of grounding the company did not settle
it, and the entity the turn would have used had the card not been asked. This script reads those records from the stored
assistant messages (``agent_messages.tool_calls.audit``) and reports how often the card appeared, grouped by the entity
the classifier gave, with a few of the user's own sentences. It never writes to the database.

    python -m scripts.entity_card_report --days 30 --samples 3
    python -m scripts.entity_card_report --json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable, Mapping

AUDIT_KEY = "entity_card_shadow"


def records_from_audit(audit: Any) -> list[dict]:
    """The card records of one turn's audit; anything that is not a list of mappings is nothing."""
    value = audit.get(AUDIT_KEY) if isinstance(audit, Mapping) else None
    return [dict(item) for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def entity_label(record: Mapping) -> str:
    """The classifier's entity as one line: ``MSFT / Microsoft Corporation`` (a missing half is left out)."""
    given = record.get("classifier") if isinstance(record.get("classifier"), Mapping) else {}
    parts = [str(given[key]) for key in ("symbol", "company") if given.get(key)]
    return " / ".join(parts) or "(none)"


def summarize(records: Iterable[Mapping], samples: int = 3) -> dict:
    """Total count, then one group per classifier entity: count, why each fallback did not pass, and sample user sentences."""
    groups: dict[str, dict] = defaultdict(lambda: {"count": 0, "fallback_reasons": defaultdict(Counter), "samples": [], "would_use": Counter()})
    total = 0
    for record in records:
        total += 1
        group = groups[entity_label(record)]
        group["count"] += 1
        fallbacks = record.get("fallbacks") if isinstance(record.get("fallbacks"), Mapping) else {}
        for name, reason in fallbacks.items():
            group["fallback_reasons"][str(name)][str(reason)] += 1
        used = record.get("would_use") if isinstance(record.get("would_use"), Mapping) else {}
        group["would_use"][" / ".join(str(used[k]) for k in ("symbol", "company") if used.get(k)) or "(none)"] += 1
        words = str(record.get("user_words") or "").strip()
        if words and len(group["samples"]) < samples and words not in group["samples"]:
            group["samples"].append(words)
    ordered = sorted(groups.items(), key=lambda item: (-item[1]["count"], item[0]))
    return {"total": total, "by_classifier_entity": [
        {"entity": name, "count": group["count"],
         "fallback_reasons": {fb: dict(counter.most_common()) for fb, counter in group["fallback_reasons"].items()},
         "would_use": dict(group["would_use"].most_common()), "samples": group["samples"]}
        for name, group in ordered]}


def load_records(*, days: int, limit: int) -> list[dict]:
    """Stored assistant messages from the last ``days`` days (newest ``limit`` rows) that carry card records. Reads only."""
    from sqlalchemy import desc, select

    from app.agent_chat_models import AgentMessage
    from app.database import SessionLocal

    cutoff = datetime.now(UTC) - timedelta(days=days)
    found: list[dict] = []
    with SessionLocal() as db:
        stmt = (select(AgentMessage.tool_calls).where(AgentMessage.role == "assistant", AgentMessage.created_at >= cutoff)
                .order_by(desc(AgentMessage.created_at)).limit(limit))
        for tool_calls in db.scalars(stmt):
            audit = tool_calls.get("audit") if isinstance(tool_calls, Mapping) else None
            found.extend(records_from_audit(audit))
    return found


def render(summary: dict) -> str:
    lines = [f"公司核对卡共出现 {summary['total']} 次。"]
    for group in summary["by_classifier_entity"]:
        lines.append(f"\n{group['entity']}：{group['count']} 次；放行会用：{', '.join(f'{k}×{v}' for k, v in group['would_use'].items())}")
        for name, reasons in group["fallback_reasons"].items():
            lines.append(f"  {name}: " + ", ".join(f"{reason}×{n}" for reason, n in reasons.items()))
        for sample in group["samples"]:
            lines.append(f"  「{sample}」")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=30, help="look back this many days (default 30)")
    parser.add_argument("--limit", type=int, default=20000, help="scan at most this many newest assistant messages")
    parser.add_argument("--samples", type=int, default=3, help="user sentences kept per entity")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = parser.parse_args(argv)
    summary = summarize(load_records(days=args.days, limit=args.limit), samples=args.samples)
    print(json.dumps(summary, ensure_ascii=False, indent=2) if args.json else render(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
