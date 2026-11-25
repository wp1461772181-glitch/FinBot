"""4e Task 2: the routes of the 「它眼中的你」 page: ``GET /agent-chat/memory/overview``, ``GET /agent-chat/memory/export``.
Review Focus 1 (guests get 403 on all four routes of the slice; another owner's data never appears) and the export's headers.  The view page
writes (``POST /views/{symbol}`` and ``/drop``) are in ``tests/test_owner_views.py``.  Disposable Postgres; no model, no network."""
import json
import re

import pytest

from app import agent_bots, memory_overview as overview, owner_views
from app.agent_chat_models import (AgentBot, AgentConversation, AgentConversationSummary, AgentMessage, AgentProfileItem, AgentResearchQueue,
                                   AgentTask, MemoryJob, OwnerView, PortfolioPlan, ViewReview)
from app.agent_chat_store import owner_hash
from app.database import Base, SessionLocal, engine
from tests.test_memory_overview import _bot, _item, _review, _view

CREDENTIAL = "owner-credential-for-the-page"
OWNER = owner_hash(CREDENTIAL)
OTHER = owner_hash("somebody-else")
HEADERS = {"X-Chat-Session": CREDENTIAL}
GUEST = {"X-Chat-Session": "g" * 64}
TABLES = (ViewReview, OwnerView, AgentProfileItem, AgentConversationSummary, AgentMessage, AgentConversation, AgentBot, MemoryJob, AgentTask,
          AgentResearchQueue, PortfolioPlan)
FOUR = (("GET", "/agent-chat/memory/overview", None), ("GET", "/agent-chat/memory/export", None), ("GET", "/agent-chat/memory/export?format=md", None),
        ("POST", "/agent-chat/views/NVDA", {"text": "估值太高，先不加仓"}), ("POST", "/agent-chat/views/NVDA/drop", None))


@pytest.fixture(autouse=True)
def world(monkeypatch, disposable_database):
    import app.agent_chat_identity as identity
    import app.agent_tasks  # noqa: F401
    import app.main  # noqa: F401
    from app import agent_profile as profile
    Base.metadata.create_all(engine)
    profile.ensure_review_columns()
    profile.ensure_seen_columns()
    owner_views.ensure_archive_column()
    with SessionLocal() as db:
        for model in TABLES:
            db.query(model).delete()
        db.commit()
    monkeypatch.setattr(identity, "owner_credential_matches", lambda credential: credential == CREDENTIAL)
    for name in ("FINBOT_MEMORY_REVIEW_DAYS", "FINBOT_MEMORY_REVIEW_MIN_MESSAGES", "FINBOT_MEMORY_QUARTER_ANCHORS"):
        monkeypatch.delenv(name, raising=False)


def _seed():
    """What the owner keeps: three kinds of profile item (one on a bot's layer, one waiting guess with examples, one archived), two companies' views
    (one with three versions and a 4d review), and the same kinds of rows for another owner, which must never show."""
    bot = _bot("研究员", owner=OWNER)
    agent_bots.ensure_default_bot(OWNER)
    _item("回答先给结论", origin="explicit", owner=OWNER)
    _item("喜欢看表格", origin="manual", owner=OWNER, bot_id=bot)
    _item("常问半导体", origin="inferred", owner=OWNER)
    _item("多半想先看风险", origin="pattern", status="proposed", owner=OWNER, examples=["问过三次回撤", "问过两次止损"])
    _item("以前的偏好", origin="explicit", status="archived", reason="很久没提了", owner=OWNER)
    _view("NVDA", "先不碰英伟达", "dropped", age=300, ended=None, owner=OWNER)
    _view("NVDA", "英伟达估值太高", "superseded", age=120, owner=OWNER)
    active = _view("NVDA", "英伟达还能翻倍", "active", age=20, owner=OWNER)
    _view("AMD", "AMD 再等等", "archived", age=250, owner=OWNER, reason="很久没提了")
    _review(active, owner=OWNER, text="到目前为止成立。", stray=("37%",))
    _item("别人的偏好 SECRET-OTHER", origin="explicit", owner=OTHER)
    _view("NVDA", "别人的看法 SECRET-OTHER", "active", owner=OTHER)
    return active


# ---- Review Focus 1: owner only ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("headers", [GUEST, {}], ids=["a guest session", "no session"])
def test_a_guest_gets_403_owner_only_on_every_route_of_the_slice(client, headers):
    _seed()
    for method, path, body in FOUR:
        answer = client.request(method, path, json=body, headers=headers)
        assert answer.status_code == 403 and answer.json()["detail"] == "owner_only", (method, path)
        assert "SECRET-OTHER" not in answer.text and "owner_hash" not in answer.text


def test_the_overview_is_the_owners_alone(client):
    _seed()
    answer = client.get("/agent-chat/memory/overview", headers=HEADERS)
    assert answer.status_code == 200
    body = answer.json()
    assert "SECRET-OTHER" not in answer.text and "别人的" not in answer.text
    assert set(body) == {"counts", "views", "watch", "jobs", "seen_block", "errors"} and body["errors"] == []
    assert body["counts"] == {"said": 1, "typed": 1, "inferred": 1, "guesses_confirmed": 0, "guesses_waiting": 1, "archived": 1,
                              "views_current": 1, "views_companies": 2, "watch": 0}
    assert [g["symbol"] for g in body["views"]] == ["NVDA", "AMD"] and len(body["views"][0]["versions"]) == 3
    assert body["views"][0]["current"]["review"]["text"] == "到目前为止成立。"
    assert "回答先给结论" in body["seen_block"] and "SECRET-OTHER" not in body["seen_block"]
    assert body["counts"] == overview.collect(OWNER)["counts"]
    # the other owner's own overview holds only the other owner's rows
    theirs = overview.collect(OTHER)
    assert theirs["counts"]["said"] == 1 and theirs["counts"]["views_companies"] == 1 and "回答先给结论" not in (theirs["seen_block"] or "")


def test_one_part_failing_still_returns_the_page(client, monkeypatch):
    _seed()

    def broken(owner):
        raise RuntimeError("a broken table")
    monkeypatch.setattr(owner_views, "all_versions", broken)
    answer = client.get("/agent-chat/memory/overview", headers=HEADERS)
    assert answer.status_code == 200
    body = answer.json()
    assert body["views"] is None and body["errors"] == ["views"] and body["counts"]["said"] == 1 and body["seen_block"]


# ---- the export ---------------------------------------------------------------------------------------------------------------

def test_the_json_export_is_an_attachment_with_a_dated_name_and_holds_what_the_page_holds(client):
    _seed()
    answer = client.get("/agent-chat/memory/export", headers=HEADERS)
    assert answer.status_code == 200
    assert answer.headers["content-type"] == "application/json; charset=utf-8"
    assert re.fullmatch(r'attachment; filename="finbot-memory-\d{8}\.json"', answer.headers["content-disposition"])
    document = json.loads(answer.content.decode("utf-8"))
    assert document["schema"] == "finbot-memory-export/1" and len(document["profile_items"]) == 5 and "SECRET-OTHER" not in answer.text
    assert [len(g["versions"]) for g in document["views"]] == [3, 1]
    assert client.get("/agent-chat/memory/export?format=json", headers=HEADERS).headers["content-type"] == "application/json; charset=utf-8"       # the default is json


def test_the_markdown_export_is_an_attachment_in_the_readable_form(client):
    _seed()
    answer = client.get("/agent-chat/memory/export?format=md", headers=HEADERS)
    assert answer.status_code == 200
    assert answer.headers["content-type"] == "text/markdown; charset=utf-8"
    assert re.fullmatch(r'attachment; filename="finbot-memory-\d{8}\.md"', answer.headers["content-disposition"])
    text = answer.content.decode("utf-8")
    assert text.startswith("# 它眼中的你（导出于 ") and "## 你对公司的看法" in text and "英伟达还能翻倍" in text and "SECRET-OTHER" not in text


@pytest.mark.parametrize("fmt", ["xml", "JSON", "", "md;x"])
def test_any_other_format_is_422_invalid_format(client, fmt):
    answer = client.get("/agent-chat/memory/export", params={"format": fmt}, headers=HEADERS)
    assert answer.status_code == 422 and answer.json()["detail"] == "invalid_format"
    assert "content-disposition" not in answer.headers


def test_the_export_is_the_owners_alone_even_with_the_other_owner_having_more(client):
    _seed()
    _item("再多一条别人的 SECRET-OTHER", origin="manual", owner=OTHER)
    text = client.get("/agent-chat/memory/export", headers=HEADERS).text + client.get("/agent-chat/memory/export?format=md", headers=HEADERS).text
    assert "SECRET-OTHER" not in text and OTHER not in text and OWNER not in text and CREDENTIAL not in text
