"""Re-check the Exhibit 99.1 of saved 8-Ks whose earlier lookup found nothing.

Before the exhibit was located by SEC's official file type, many 8-K earnings
press releases (NVIDIA ``q3fy27pr.htm``, Apple ``a8-k…ex991….htm``) were judged
``not_found`` and only the cover page was saved.  This lists those filings and,
with ``--apply``, looks again through ``fetch_inventory_content(...,
recheck_attachment=True)``, which updates the row through the normal path
(``content_kind='exhibit_99_1'``, source URL, document name, text).

Default is a dry run: it only lists symbol, accession and filing date.  Each
filing is committed on its own and one failure does not stop the rest; the SEC
provider's own limiter keeps requests under the published rate.

    python -m scripts.recheck_8k_exhibits [--symbol NVDA] [--limit 20]
    python -m scripts.recheck_8k_exhibits --apply [--symbol NVDA] [--limit 20]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import SecFilingInventory
from app.sec_filings import SecEdgarProvider, fetch_inventory_content

RECHECK_STATUSES = ("not_found", "unavailable")


@dataclass
class RecheckStats:
    candidates: int = 0
    rechecked: int = 0
    newly_fetched: int = 0
    still_missing: int = 0
    errors: int = 0
    error_details: list[str] = field(default_factory=list)


def select_candidates(db: Session, *, symbol: str | None = None, limit: int | None = None) -> list[SecFilingInventory]:
    query = select(SecFilingInventory).where(
        SecFilingInventory.form == "8-K",
        SecFilingInventory.content_status == "fetched",
        SecFilingInventory.related_attachment_status.in_(RECHECK_STATUSES),
    )
    if symbol:
        query = query.where(SecFilingInventory.symbol == symbol.strip().upper())
    query = query.order_by(SecFilingInventory.filed_at.desc(), SecFilingInventory.accession_number.desc())
    if limit is not None:
        query = query.limit(limit)
    return list(db.scalars(query))


def run(
    db: Session,
    *,
    provider: SecEdgarProvider | None = None,
    apply: bool = False,
    symbol: str | None = None,
    limit: int | None = None,
    out=print,
) -> RecheckStats:
    stats = RecheckStats()
    targets = [(row.symbol, row.accession_number, row.filed_at) for row in select_candidates(db, symbol=symbol, limit=limit)]
    stats.candidates = len(targets)
    for sym, accession, filed_at in targets:
        if not apply:
            out(f"[dry-run] {sym} {accession} filed {filed_at}")
            continue
        stats.rechecked += 1
        try:
            filing, _ = fetch_inventory_content(
                symbol=sym, accession_number=accession, db=db, provider=provider, recheck_attachment=True,
            )
            if filing.related_attachment_status == "fetched" and filing.content_kind == "exhibit_99_1":
                stats.newly_fetched += 1
                out(f"[fetched] {sym} {accession} -> {filing.content_document_name}")
            else:
                stats.still_missing += 1
                out(f"[none]    {sym} {accession}")
        except Exception as exc:  # one filing failing must not stop the others
            db.rollback()
            stats.errors += 1
            stats.error_details.append(f"{sym} {accession}: {exc}")
            out(f"[error]   {sym} {accession}: {exc}")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol", help="only this symbol")
    parser.add_argument("--limit", type=int, help="at most this many filings (newest first)")
    parser.add_argument("--apply", action="store_true", help="actually re-check and update; without it only list")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    provider = SecEdgarProvider() if args.apply else None
    with SessionLocal() as db:
        stats = run(db, provider=provider, apply=args.apply, symbol=args.symbol, limit=args.limit)
    print(
        f"candidates={stats.candidates} rechecked={stats.rechecked} newly_fetched={stats.newly_fetched} "
        f"still_missing={stats.still_missing} errors={stats.errors}"
    )
    if not args.apply:
        print("dry run only; use --apply to re-check these filings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
