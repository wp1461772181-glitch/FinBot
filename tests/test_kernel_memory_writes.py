"""Slice A of the kernel memory writes: the model writes a guess on the spot (``add_noticed``), the quote comes from his visible words,
no card for ``remember`` / ``record_view`` after reading, the side extractor stays out of kernel turns, the review lists waiting guesses."""
import uuid
from datetime import UTC, datetime

import pytest

from app import agent_bots, agent_profile as profile
from app.agent_chat_models import (AgentBot, AgentConversation, AgentMessage, AgentProfileItem, AgentTelegramMessage, MemoryJob)
from app.database import Base, SessionLocal, engine

OWNER = "owner-hash-kernel-memory-writes"
NOW = datetime(2026, 12, 20, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def world(monkeypatch):
    import app.agent_tasks  # noqa: F401
    import app.main  # noqa: F401
    Base.metadata.create_all(engine)
    profile.ensure_review_columns()
    profile.ensure_seen_columns()
    with SessionLocal() as db:
        for model in (AgentProfileItem, AgentMessage, AgentConversation, AgentTelegramMessage, AgentBot, MemoryJob):
            db.query(model).delete()
        db.commit()
    monkeypatch.delenv("FINBOT_KERNEL_MEMORY_WRITES", raising=False)


def _rows(**where):
    with SessionLocal() as db:
        return db.query(AgentProfileItem).filter_by(owner_hash=OWNER, **where).all()


def _noticed(text="总先问同比", quote="NVDA 同比多少", **extra):
    return profile.add_noticed(OWNER, kind="preference", text=text, quote=quote, now=NOW, **extra)


# --- A1: add_noticed ---------------------------------------------------------------------------------------------------------------------

def test_a_noticed_guess_is_a_proposed_pattern_row_with_one_example_and_no_review_run():
    out = _noticed(message_id=str(uuid.uuid4()))
    assert out["status"] == "added" and out["item"]["status"] == "proposed" and out["item"]["origin"] == "pattern"
    row = _rows()[0]
    assert row.review_run is None and row.bot_id is None and row.quote == "NVDA 同比多少"
    assert row.examples[0]["quote"] == "NVDA 同比多少" and row.examples[0]["date"] == "2026-12-20" and row.examples[0]["message_id"]
    assert profile.render_block(OWNER)[0].count("总先问同比") == 1      # it shows in the 推测 section, not among his own items
    assert profile.PROPOSED_HEADING in profile.render_block(OWNER)[0]


def test_the_same_guess_twice_and_a_rejected_one_write_nothing():
    assert _noticed()["status"] == "added"
    assert _noticed(text="总先问同比")["status"] == "duplicate" and len(_rows()) == 1
    profile.delete_item(OWNER, str(_rows()[0].id))       # he says 不对: only the fingerprint stays
    assert _noticed()["status"] == "rejected" and [r.status for r in _rows()] == ["rejected"]


def test_an_active_item_with_the_same_text_is_a_duplicate_too():
    profile.add_manual_item(OWNER, kind="preference", text="只关心美股")
    assert _noticed(text="只关心美股")["status"] == "duplicate" and len(_rows(status="proposed")) == 0


def test_a_guess_lands_in_the_bots_layer_and_an_unknown_bot_is_refused():
    bot = agent_bots.ensure_default_bot(OWNER)
    out = _noticed(bot_id=str(bot.id))
    assert out["item"]["scope"] == "bot" and out["item"]["bot_id"] == str(bot.id)
    with pytest.raises(profile.ProfileError):
        _noticed(text="别的偏好", bot_id=str(uuid.uuid4()))


def test_only_the_newest_twenty_guesses_wait():
    for n in range(profile.MAX_PROPOSED + 3):
        profile.add_noticed(OWNER, kind="preference", text=f"习惯 {n}", quote="一句话", now=datetime(2026, 12, 1, 0, n, tzinfo=UTC))
    assert len(_rows(status="proposed")) == profile.MAX_PROPOSED and len(_rows(status="archived")) == 3
    assert not any(r.text == "习惯 0" for r in _rows(status="proposed"))
