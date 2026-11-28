"""Telegram: 同意 on a consent card lands the write in 资料库, and answers go out as plain chat text.

Regression (2026-10-28): the owner tapped 同意 on a Telegram card to save a material and nothing reached
资料库 or the vector index.  The bridge called ``consent.execute`` itself with an empty operation list (the
payload digest never matched, so ConsentError confirmation_parameter_mismatch) and with the async,
three-argument ``execute_reversible`` as the handler; no confirmed write could ever run from Telegram.  A
press now goes to the bot's line as the button's own value, like the web page, and the server runs it.
"""
import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.agent_workflow import consent, tools
from app.agent_workflow.models import AgentConsent
from app.agent_workflow.state import AgentRuntimeContext
from app.database import Base, SessionLocal, engine
from app.agent_chat_models import AgentSkill
from app.knowledge.models import KnowledgeUploadOwner
from app.models import UploadedEvidence
from scripts import run_telegram_bridge as bridge

OWNER_ID = 4242
OWNER_HASH = "o" * 64


@pytest.fixture
def owner(monkeypatch, disposable_database):
    Base.metadata.create_all(engine, tables=[AgentConsent.__table__, UploadedEvidence.__table__,
                                             KnowledgeUploadOwner.__table__, AgentSkill.__table__])
    monkeypatch.setattr(consent, "owner_credential_matches", lambda credential: credential == "owner")
    monkeypatch.setattr(tools, "owner_credential_matches", lambda credential: credential == "owner")
    return "owner"


def _material():
    return {"name": "save_material_evidence", "arguments": {
        "symbol": "TSLA", "title": "特斯拉三季度交付（测试）", "source_url": "https://ir.tesla.com/press/" + uuid.uuid4().hex,
        "published_at": "2026-10-02", "credibility_stars": 4, "credibility_reason": "公司公告。",
        "impact_severity": "medium", "content": "# 交付\n\n" + uuid.uuid4().hex}}


class _Telegram:
    def __init__(self):
        self.replies = []

    def record_reply(self, owner, bot_id, text, message_id):
        self.replies.append((bot_id, text))


def test_a_card_that_needs_ticking_gets_no_buttons_and_says_where_to_finish():
    card = {"id": "req-2", "reason": "choose_revision_sources", "options": [{"value": "1", "label": "材料"}],
            "choices": [{"label": "用所选材料修订", "value": "confirm:" + "t" * 40}]}
    assert bridge._make_keyboard([card], {}, "c-1", "cred", "b-1", "助理") is None


# --- plain chat text ---------------------------------------------------------------------------------------

def test_a_streamed_answer_goes_out_without_markers_or_a_sources_list():
    events = [("conversation", {"conversation_id": "c-1"}),
              ("delta", {"text": "特斯拉上一交易日收盘 [1]，公司公告见 https://ir.tesla.com/press [2]。"}),
              ("citations", {"items": [{"ordinal": 1, "title": "Yahoo Finance TSLA"},
                                       {"ordinal": 2, "title": "Tesla IR", "source_url": "https://ir.tesla.com"}]})]
    answer, cards, cid = bridge.format_turn(events)
    assert answer == "特斯拉上一交易日收盘，公司公告见 https://ir.tesla.com/press。"
    assert cid == "c-1" and cards == []
    assert "Yahoo Finance" not in answer and "——" not in answer and "[1]" not in answer


@pytest.mark.parametrize("appendix", [
    "\n\n来源：\n[1] Yahoo Finance https://finance.yahoo.com/quote/TSLA",
    "\n\n**参考资料**\n- [1] Yahoo Finance",
    "\n\n——\n  [1] Yahoo Finance",
    "\n\nSources:\n[1] Yahoo Finance",
    "\n来源：Yahoo Finance、Tesla IR",
])
def test_a_sources_block_the_model_wrote_itself_is_cut(appendix):
    from app.agent_telegram import chat_text
    body = "TSLA 的行情见 [雅虎财经](https://finance.yahoo.com/quote/TSLA) [1]。"
    assert chat_text(body + appendix) == "TSLA 的行情见 [雅虎财经](https://finance.yahoo.com/quote/TSLA)。"


def test_an_ordinary_line_that_starts_with_a_heading_word_is_kept():
    from app.agent_telegram import chat_text
    assert chat_text("结论如上。\n参考一下上季度的交付量。") == "结论如上。\n参考一下上季度的交付量。"


def test_a_notification_lists_no_sources():
    from app.agent_telegram import render
    citations = [{"ordinal": 1, "title": "Tesla IR", "source_url": "https://ir.tesla.com"}]
    assert render("抓新闻", "特斯拉发布交付数据 [1]。", citations, [1]) == "【抓新闻】\n特斯拉发布交付数据。"


# --- a card as it arrives on the wire ----------------------------------------------------------------------

