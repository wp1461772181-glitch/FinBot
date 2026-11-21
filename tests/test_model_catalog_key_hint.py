"""key_hint: the one trace of a stored key the catalog API gives back (2026-11-21).

The owner fills a key in the model dialog, and afterwards needs to tell which key it was.  The server works the hint
out from the decrypted key when it answers, and sends the head and tail only; the whole key never leaves the server,
and neither the key nor the hint goes to the log.
"""
import json
import logging

import pytest

from app import agent_model_catalog as catalog
from app.agent_chat_models import AgentModelEntry
from app.database import SessionLocal
from tests.test_agent_bots import H, owner  # noqa: F401  (fixture)

LONG_KEY = "sk-ant-usr-1jsQ9xK2mLpV7wRtYz3HbNcD8fGeUaXyzxgAA"   # 47 characters
MID_KEY = "abcdefghijklmnopqrst"                              # 20: the shortest that shows a head
SHORT_KEY = "short-key-123456789"                              # 19: tail only
ENV_KEY = "sk-env-only-0123456789abcdefghijkl"


@pytest.mark.parametrize(("key", "hint"), [
    (LONG_KEY, "sk-ant-usr-1…xgAA"),
    (MID_KEY, "abcdefghijkl…qrst"),
    (SHORT_KEY, "…6789"),
    ("12345678", "…5678"),
])
def test_hint_shows_twelve_and_four_from_twenty_characters_and_only_the_tail_below(key, hint):
    assert catalog.key_hint(key) == hint


def _everything_but_the_hint_absent(text, key):
    """The sensitive middle of the key, and the key, are not in the text; only the hint may overlap with it."""
    assert key not in text
    assert key[12:-4] not in text


def test_list_add_and_edit_answers_carry_only_the_hint_of_a_vault_key(owner, client, monkeypatch):
    added = client.post("/agent-chat/model-catalog", headers=H, json={
        "name": "alpha", "provider": "anthropic", "model": "claude-haiku-5-5", "api_key": LONG_KEY, "is_default": True})
    assert added.status_code == 200 and added.json()["model"]["key_hint"] == "sk-ant-usr-1…xgAA"
    monkeypatch.setenv("BRAVO_API_KEY", ENV_KEY)
    client.post("/agent-chat/model-catalog", headers=H, json={
        "name": "bravo", "provider": "qwen", "model": "qwen-plus", "key_env": "BRAVO_API_KEY"})
    listed = client.get("/agent-chat/model-catalog", headers=H)
    by_name = {m["name"]: m for m in listed.json()["models"]}
    assert by_name["alpha"]["key_hint"] == "sk-ant-usr-1…xgAA" and by_name["alpha"]["key_status"] == "configured"
    # An entry that reads an environment variable shows no hint at all.
    assert "key_hint" not in by_name["bravo"] and by_name["bravo"]["key_status"] == "configured"
    assert ENV_KEY[:12] not in listed.text and ENV_KEY[-4:] not in listed.text
    # Editing without a new key keeps the stored one, and the answer still names only its hint.
    edited = client.patch("/agent-chat/model-catalog/alpha", headers=H, json={"model": "claude-sonnet-5-5"})
    assert edited.status_code == 200 and edited.json()["model"]["key_hint"] == "sk-ant-usr-1…xgAA"
    for response in (added, listed, edited):
        _everything_but_the_hint_absent(response.text, LONG_KEY)
        # The only keys an entry has are the documented fields: no field holds the key or a longer piece of it.
        for model in (response.json().get("models") or [response.json()["model"]]):
            assert not any(isinstance(v, str) and LONG_KEY[:13] in v for v in model.values())


def test_a_new_key_changes_the_hint_and_a_key_that_cannot_be_read_has_none(owner, client):
    client.post("/agent-chat/model-catalog", headers=H, json={
        "name": "alpha", "provider": "deepseek", "model": "deepseek-chat", "api_key": SHORT_KEY})
    first = client.get("/agent-chat/model-catalog", headers=H).json()["models"][0]
    assert first["key_hint"] == "…6789"
    edited = client.patch("/agent-chat/model-catalog/alpha", headers=H, json={"api_key": MID_KEY})
    assert edited.json()["model"]["key_hint"] == "abcdefghijkl…qrst"
    with SessionLocal() as db:
        row = db.get(AgentModelEntry, "alpha")
        row.ciphertext = "garbage-that-cannot-be-decrypted"
        db.commit()
    broken = client.get("/agent-chat/model-catalog", headers=H).json()["models"][0]
    assert broken["key_status"] == "missing" and "key_hint" not in broken


def test_the_hint_is_not_stored_and_neither_it_nor_the_key_reaches_the_log(owner, client, caplog):
    caplog.set_level(logging.DEBUG)
    client.post("/agent-chat/model-catalog", headers=H, json={
        "name": "alpha", "provider": "deepseek", "model": "deepseek-chat", "api_key": LONG_KEY})
    client.get("/agent-chat/model-catalog", headers=H)
    bad = client.post("/agent-chat/model-catalog", headers=H, json={
        "name": "BAD NAME", "provider": "deepseek", "model": "m", "api_key": LONG_KEY})
    assert bad.status_code == 422
    for text in (caplog.text, bad.text, "\n".join(catalog.startup_report())):
        assert LONG_KEY not in text and LONG_KEY[12:-4] not in text
        assert catalog.key_hint(LONG_KEY) not in text
    with SessionLocal() as db:
        row = db.get(AgentModelEntry, "alpha")
        stored = json.dumps({c.name: str(getattr(row, c.name)) for c in row.__table__.columns})
    assert catalog.key_hint(LONG_KEY) not in stored and LONG_KEY[12:-4] not in stored


def test_a_guest_gets_no_catalog_at_all(owner, client):
    from tests.test_agent_bots import GUEST
    assert client.get("/agent-chat/model-catalog", headers={"X-Chat-Session": GUEST}).status_code == 403
