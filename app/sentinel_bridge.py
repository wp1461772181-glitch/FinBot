"""Hand the sentinel a snapshot of what it needs when the API is down.

The sentinel (``sentinel/``) is stdlib-only and never imports ``app``.  It reads
``data/sentinel-config.json`` and reloads it when the mtime changes, so with the
API down it still holds the last snapshot.  Written with mode 0600: it holds the
Telegram bot token.  Sections that cannot be read (a table that does not exist
yet, a database that is down) are left empty instead of failing the caller.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "sentinel-config.json"


def snapshot_path() -> Path:
    return Path(os.environ.get("SENTINEL_CONFIG_PATH") or DEFAULT_PATH)


def _section(name: str, fn, default):
    try:
        return fn()
    except Exception:  # a missing section must not stop the snapshot
        logger.warning("sentinel snapshot: section %s unavailable", name, exc_info=True)
        return default


def _research_queue(owner_hash: str) -> list[str]:
    from .agent_chat_models import AgentResearchQueue
    from .agent_chat_store import clean_queue
    from .database import SessionLocal

    with SessionLocal() as db:
        row = db.get(AgentResearchQueue, owner_hash)
        return [] if row is None else clean_queue(row.symbols)


def _telegram(owner_hash: str) -> dict:
    from . import agent_telegram

    bind = agent_telegram.load_bind(owner_hash)
    if not bind:
        return {}
    return {"bot_token": bind["bot_token"], "chat_id": bind["chat_id"]}


def _pushover(owner_hash: str) -> dict:
    """The pair saved on the settings page (encrypted in the database); environment variables are a fallback."""
    from . import agent_pushover

    saved = agent_pushover.load(owner_hash)
    if saved:
        return saved
    return {"user_key": os.environ.get("PUSHOVER_USER_KEY", ""), "app_token": os.environ.get("PUSHOVER_APP_TOKEN", "")}


def _portfolio(owner_hash: str) -> dict:
    """Positions, preset plans and total assets come from app.portfolio (Task 6).  Until it exists they are empty."""
    try:
        from . import portfolio  # type: ignore[attr-defined]
    except ImportError:
        return {"positions": [], "plans": [], "total_assets": None}
    return portfolio.sentinel_view(owner_hash)


def _kept(name: str):
    """What the snapshot on disk already says about ``name`` (None when there is no readable file or no such section)."""
    try:
        return json.loads(snapshot_path().read_text(encoding="utf-8")).get(name)
    except Exception:
        return None


def _rules(owner_hash: str) -> list[dict]:
    """The owner's own watch rules (enabled, not expired), each as ``watch_rules.rule_dict``; the sentinel checks them without a model."""
    from . import watch_rules

    try:
        return watch_rules.snapshot_rules(owner_hash)
    except Exception:
        # Not reading the rules is not "he has none": keep what the snapshot on disk already says, so a database blip does not switch his rules off.
        logger.warning("sentinel snapshot: rules unreadable, keeping the existing snapshot's rules", exc_info=True)
        kept = _kept("rules")
        return kept if isinstance(kept, list) else []


def _presets(owner_hash: str) -> list[dict]:
    """The system's default rules that are switched on, resolved with the owner's overrides (``watch_presets.snapshot_presets``).  Unreadable: the
    last snapshot's, so a database blip does not switch the defaults off (or back on after he switched one off)."""
    from . import watch_presets

    try:
        return watch_presets.snapshot_presets(owner_hash)
    except Exception:
        logger.warning("sentinel snapshot: presets unreadable, keeping the existing snapshot's presets", exc_info=True)
        kept = _kept("presets")
        return kept if isinstance(kept, list) else []


def _alert_settings(owner_hash: str) -> dict:
    """{sensitivity, short_moves}; unreadable: the last snapshot's, else empty (the sentinel then falls back to its old keys and the environment)."""
    from . import watch_presets

    try:
        return watch_presets.get_settings(owner_hash)
    except Exception:
        logger.warning("sentinel snapshot: alert settings unreadable, keeping the existing snapshot's", exc_info=True)
        kept = _kept("alert_settings")
        return kept if isinstance(kept, dict) else {}


def build_snapshot(owner_hash: str) -> dict:
    portfolio = _section("portfolio", lambda: _portfolio(owner_hash), {"positions": [], "plans": [], "total_assets": None})
    return {
        "version": 1,
        "written_at": datetime.now(UTC).isoformat(),
        "api_base": os.environ.get("SENTINEL_API_BASE", "http://127.0.0.1:8000"),
        "positions": portfolio.get("positions", []),
        "plans": portfolio.get("plans", []),
        "total_assets": portfolio.get("total_assets"),
        "alert_settings": _alert_settings(owner_hash),
        "rules": _rules(owner_hash),
        "presets": _presets(owner_hash),
        "research_queue": _section("research_queue", lambda: _research_queue(owner_hash), []),
        "telegram": _section("telegram", lambda: _telegram(owner_hash), {}),
        "pushover": _section("pushover", lambda: _pushover(owner_hash), {}),
    }


def write_sentinel_snapshot(owner_hash: str) -> None:
    path = snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(build_snapshot(owner_hash), handle, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)  # atomic: the sentinel never reads a half-written file


def owner_hash_from_login_config() -> str | None:
    """The owner's hash without a request (API startup): the same sha256 as agent_chat_store.owner_hash."""
    from .agent_chat_identity import _load_config

    config = _load_config()
    return None if config is None else hashlib.sha256(config[3].encode()).hexdigest()


def refresh_sentinel_snapshot() -> None:
    """Best effort for data-mutation points and startup: never raises."""
    try:
        owner = owner_hash_from_login_config()
        if owner:
            write_sentinel_snapshot(owner)
    except Exception:
        logger.warning("sentinel snapshot write failed", exc_info=True)
