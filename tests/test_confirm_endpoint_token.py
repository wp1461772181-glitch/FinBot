"""POST /finbot/routines/{id}/confirm (app/main.py) is the notification-side copy of the confirm endpoint.  Unlike the three
/agent-chat routes it has no owner check, so it must always be given the card's own action token."""
from __future__ import annotations

from app import fin_news_engine as engine
from app.agent_chat_models import AgentInboxItem
from app.agent_chat_store import owner_hash
from app.database import SessionLocal

from tests.test_fin_news_engine_and_inline_confirm import H, OWNER, OWNER_HASH, news_env  # noqa: F401

URL = "/finbot/routines/{}/confirm"


def _card(operation=None):
    return engine.create_inline_confirmation(
        owner_hash=OWNER_HASH, title="t", summary="s", operation=operation or {"action": "acknowledge_news_digest"})


def _state(card_id: str) -> str:
    with SessionLocal() as db:
        import uuid
        row = db.get(AgentInboxItem, uuid.UUID(card_id))
        return row.payload.get("confirmation_state")


def test_no_token_is_refused_and_nothing_changes(news_env, client):
    card = _card()
    for body in ({}, {"action": "confirm"}, {"action": "confirm", "action_token": ""}, {"action": "skip", "action_token": None}):
        resp = client.post(URL.format(card["id"]), headers=H, json=body)
        assert resp.status_code == 403, body
    assert _state(card["id"]) == "pending_confirm"


def test_no_body_at_all_is_refused(news_env, client):
    card = _card()
    assert client.post(URL.format(card["id"]), headers=H).status_code == 403
    assert _state(card["id"]) == "pending_confirm"


def test_wrong_token_is_refused(news_env, client):
    card = _card()
    resp = client.post(URL.format(card["id"]), headers=H, json={"action": "confirm", "action_token": "x" * 32})
    assert resp.status_code == 403
    assert _state(card["id"]) == "pending_confirm"


def test_token_of_another_card_is_refused(news_env, client):
    a, b = _card(), _card()
    resp = client.post(URL.format(a["id"]), headers=H, json={"action": "confirm", "action_token": b["action_token"]})
    assert resp.status_code == 403
    assert _state(a["id"]) == "pending_confirm" and _state(b["id"]) == "pending_confirm"


def test_unknown_card_looks_the_same_as_a_wrong_token(news_env, client):
    resp = client.post(URL.format("00000000-0000-0000-0000-000000000000"), headers=H,
                       json={"action": "confirm", "action_token": "x" * 32})
    assert resp.status_code == 403


def test_right_token_confirms_and_skip_works_too(news_env, client):
    card = _card()
    resp = client.post(URL.format(card["id"]), headers=H, json={"action": "confirm", "action_token": card["action_token"]})
    assert resp.status_code == 200 and resp.json()["confirmation_state"] == "confirmed"
    other = _card()
    resp = client.post(URL.format(other["id"]), headers=H, json={"action": "skip", "action_token": other["action_token"]})
    assert resp.status_code == 200 and resp.json()["confirmation_state"] == "skipped"


def test_a_card_without_a_stored_token_cannot_be_confirmed_here(news_env, client):
    card = _card()
    with SessionLocal() as db:
        import uuid
        row = db.get(AgentInboxItem, uuid.UUID(card["id"]))
        payload = dict(row.payload)
        payload.pop("action_token")
        row.payload = payload
        db.commit()
    resp = client.post(URL.format(card["id"]), headers=H, json={"action": "confirm", "action_token": "anything"})
    assert resp.status_code == 403
    assert _state(card["id"]) == "pending_confirm"


def test_the_bridge_path_still_confirms_by_short_code_without_a_token(news_env):
    """The Telegram bridge calls the function in-process with the bound owner's hash and the short code (scripts/run_telegram_bridge.py)."""
    card = _card()
    out = engine.handle_inline_confirmation_action(card["short_code"], "confirm", owner_hash=OWNER_HASH)
    assert out["ok"] is True and out["confirmation_state"] == "confirmed"


def test_the_owner_routes_still_confirm_without_a_token(news_env, client):
    """/agent-chat/... routes are gated by the owner's credential, which is what the web inbox uses."""
    for path in ("inbox/{}/confirm", "routines/{}/confirm", "routines/confirmations/{}/action"):
        card = _card()
        resp = client.post("/agent-chat/" + path.format(card["id"]), headers=H, json={"action": "confirm"})
        assert resp.status_code == 200 and resp.json()["confirmation_state"] == "confirmed", path


def test_the_owner_routes_refuse_without_the_owner_credential(news_env, client):
    card = _card()
    for path in ("inbox/{}/confirm", "routines/{}/confirm", "routines/confirmations/{}/action"):
        resp = client.post("/agent-chat/" + path.format(card["id"]), json={"action": "confirm"})
        assert resp.status_code in (401, 403), path
    assert _state(card["id"]) == "pending_confirm"
