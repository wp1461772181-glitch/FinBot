"""The owner's Pushover credentials for the sentinel's emergency alerts (Task 12).

Both values are encrypted with secret_box; ``status`` only says whether they are set.  After a change the
sentinel's snapshot file is rewritten so the sentinel (which never imports ``app``) sees the new pair.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from .agent_chat_models import AgentPushoverConfig
from .database import SessionLocal
from .secret_box import CredentialEncryptionError, decrypt_secret, encrypt_secret

_KEY = re.compile(r"^[A-Za-z0-9]{20,40}$")   # Pushover keys are 30 characters of letters and digits


class PushoverError(ValueError):
    """A short code the API may show; never a stored value."""


def status(owner_hash: str) -> dict:
    with SessionLocal() as db:
        row = db.get(AgentPushoverConfig, owner_hash)
        return {"configured": row is not None, "updated_at": row.updated_at.astimezone(UTC).isoformat() if row else None}


def save(owner_hash: str, user_key: str, app_token: str) -> dict:
    user_key, app_token = (user_key or "").strip(), (app_token or "").strip()
    if not _KEY.match(user_key) or not _KEY.match(app_token):
        raise PushoverError("invalid_pushover_key")
    try:
        user_cipher, token_cipher = encrypt_secret(user_key), encrypt_secret(app_token)
    except CredentialEncryptionError as exc:
        raise PushoverError("credential_key_missing") from exc
    with SessionLocal() as db:
        row = db.get(AgentPushoverConfig, owner_hash)
        if row is None:
            row = AgentPushoverConfig(owner_hash=owner_hash, user_key_cipher=user_cipher, app_token_cipher=token_cipher)
            db.add(row)
        row.user_key_cipher, row.app_token_cipher = user_cipher, token_cipher
        row.updated_at = datetime.now(UTC)
        db.commit()
    _refresh()
    return status(owner_hash)


def clear(owner_hash: str) -> dict:
    with SessionLocal() as db:
        row = db.get(AgentPushoverConfig, owner_hash)
        if row is not None:
            db.delete(row)
            db.commit()
    _refresh()
    return status(owner_hash)


def load(owner_hash: str) -> dict | None:
    """``{"user_key", "app_token"}`` decrypted, for the sentinel snapshot only; None if unset or undecryptable."""
    with SessionLocal() as db:
        row = db.get(AgentPushoverConfig, owner_hash)
        if row is None:
            return None
        try:
            return {"user_key": decrypt_secret(row.user_key_cipher), "app_token": decrypt_secret(row.app_token_cipher)}
        except CredentialEncryptionError:
            return None


def _refresh() -> None:
    from .sentinel_bridge import refresh_sentinel_snapshot
    refresh_sentinel_snapshot()
