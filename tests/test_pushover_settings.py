import json

import pytest

from app import agent_pushover, sentinel_bridge
from app.agent_chat_models import AgentPushoverConfig
from app.database import SessionLocal, engine

USER = "u" * 30
TOKEN = "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5"


@pytest.fixture
def owner(monkeypatch, disposable_database):
    AgentPushoverConfig.__table__.create(engine, checkfirst=True)
    with SessionLocal() as db:
        db.query(AgentPushoverConfig).delete()
        db.commit()
    monkeypatch.setattr(agent_pushover, "_refresh", lambda: None)
    yield "owner-pushover-test"
    with SessionLocal() as db:
        db.query(AgentPushoverConfig).delete()
        db.commit()


def test_keys_encrypted_at_rest_and_never_returned(owner):
    result = agent_pushover.save(owner, USER, TOKEN)
    assert result["configured"] is True and USER not in json.dumps(result) and TOKEN not in json.dumps(result)
    with SessionLocal() as db:
        row = db.get(AgentPushoverConfig, owner)
        assert USER not in row.user_key_cipher and TOKEN not in row.app_token_cipher
    assert agent_pushover.load(owner) == {"user_key": USER, "app_token": TOKEN}


def test_invalid_keys_rejected_and_clear(owner):
    with pytest.raises(agent_pushover.PushoverError):
        agent_pushover.save(owner, "short", TOKEN)
    assert agent_pushover.status(owner)["configured"] is False
    agent_pushover.save(owner, USER, TOKEN)
    assert agent_pushover.clear(owner)["configured"] is False and agent_pushover.load(owner) is None


def test_saved_pair_goes_into_the_sentinel_snapshot(owner, monkeypatch):
    agent_pushover.save(owner, USER, TOKEN)
    for name in ("_research_queue", "_telegram"):
        monkeypatch.setattr(sentinel_bridge, name, lambda o: [] if name == "_research_queue" else {})
    snap = sentinel_bridge.build_snapshot(owner)
    assert snap["pushover"] == {"user_key": USER, "app_token": TOKEN}
