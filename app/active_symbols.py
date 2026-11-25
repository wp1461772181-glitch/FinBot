"""Bounded runtime ticker discovery shared by refresh and SEC monitors."""
import os

from sqlalchemy import inspect, select

from .forecast_jobs import DEFAULT_STOCKS
from .symbols import normalize_market_symbol

MAX_ACTIVE_SYMBOLS = 80   # the default of FINBOT_ACTIVE_SYMBOLS_MAX


def max_active_symbols() -> int:
    """How many symbols the hourly monitors cover at most (``FINBOT_ACTIVE_SYMBOLS_MAX``, default 80; read on every call)."""
    try:
        return max(1, int(os.environ.get("FINBOT_ACTIVE_SYMBOLS_MAX", MAX_ACTIVE_SYMBOLS)))
    except ValueError:
        return MAX_ACTIVE_SYMBOLS


def _subject_symbols(db, inspector) -> list[str]:
    """Non-retired archive subjects: held first, then the research queue, then the most recently asked."""
    from .models import ArchiveSubject
    if ArchiveSubject.__tablename__ not in inspector.get_table_names():
        return []
    rows = db.execute(
        select(ArchiveSubject.symbol).where(ArchiveSubject.retired_at.is_(None))
        .order_by(ArchiveSubject.held.desc(), ArchiveSubject.queued.desc(), ArchiveSubject.asked_at.desc().nulls_last(), ArchiveSubject.symbol)
        .limit(max_active_symbols())).all()
    return [row[0] for row in rows]


def active_symbols(db, *, extra_models=()) -> tuple[str, ...]:
    """Defaults first, then the archive subjects (held, queued, recently asked), then stable validated persisted symbols; capped (``max_active_symbols``)."""
    values = set(DEFAULT_STOCKS)
    candidates = set()
    inspector = inspect(db.get_bind())
    from .models import MarketPrice, MarketPriceRevision
    models = [MarketPrice, MarketPriceRevision, *extra_models]
    for model in models:
        if model.__tablename__ not in inspector.get_table_names():
            continue
        candidates.update(db.scalars(select(model.symbol).distinct().limit(500)))
    extras = set()
    for value in candidates:
        try:
            normalized = normalize_market_symbol(value)
        except ValueError:
            continue
        if normalized not in values:
            extras.add(normalized)
    ordered = sorted(values)
    seen = set(ordered)
    for symbol in [*_subject_symbols(db, inspector), *sorted(extras)]:
        if symbol not in seen:
            seen.add(symbol)
            ordered.append(symbol)
    return tuple(ordered[:max(len(values), max_active_symbols())])
