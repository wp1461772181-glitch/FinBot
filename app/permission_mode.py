"""How much the assistant may do without a confirmation card: the owner's choice of three modes (11-28, owner: 「把选择权交到用户身上」).

* ``ask`` (每步都问): every write waits for his press, even a note to its own memory.
* ``default`` (默认): what touches only its own records (memory, research queue, feedback) and fetching public material (an SEC original,
  a page into 资料库, a price history) runs at once; a change to his data or settings, and what spends money or cannot be undone, waits.
* ``full`` (完全放行): everything runs at once and the answer says what was done and how to undo it.

In every mode two things stay: after the turn has read outside material (a page, a filing, news) a write that could be asked for by that
material waits for his press (``kernel.act``), and keys, logins and trades are never the assistant's.  Changing the mode is his alone, on
the settings page (the route is exempt from ``act``).  No row means ``default``.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, SessionLocal

MODES = ("ask", "default", "full")
DEFAULT = "default"
LABELS = {"ask": "每步都问", "default": "默认", "full": "完全放行"}


class PermissionSetting(Base):
    __tablename__ = "permission_settings"
    owner_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(String(12), nullable=False, default=DEFAULT)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


def get(owner_hash: str | None) -> str:
    """The owner's mode; ``default`` when he never chose, or when it cannot be read (the middle, never the open end)."""
    if not owner_hash:
        return DEFAULT
    try:
        with SessionLocal() as db:
            row = db.get(PermissionSetting, owner_hash)
            return row.mode if row is not None and row.mode in MODES else DEFAULT
    except Exception:
        return DEFAULT


def set_mode(owner_hash: str, mode: str) -> dict:
    if mode not in MODES:
        raise ValueError("invalid_mode")
    with SessionLocal() as db:
        row = db.get(PermissionSetting, owner_hash)
        if row is None:
            db.add(PermissionSetting(owner_hash=owner_hash, mode=mode))
        else:
            row.mode = mode
        db.commit()
    return view(mode)


def view(mode: str) -> dict:
    return {"mode": mode, "label": LABELS[mode], "modes": [{"mode": m, "label": LABELS[m]} for m in MODES]}
