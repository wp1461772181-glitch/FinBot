"""B7: the earnings judgments read path (list and by-id, owner-only), the follow-up's own model, and the outcome
filled inside ``tick`` once the first post-release session has closed.  Reuses the scripted sources / reader of
test_earnings_monitor."""
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app import earnings_monitor as em
from app import earnings_reader as er
from app.agent_chat_models import EarningsEvent, EarningsHistory
from app.database import SessionLocal
from tests.test_agent_bots import GUEST, H, OWNER, OWNER_HASH  # noqa: F401
from tests.test_earnings_monitor import E_ACC, E_AT, FakeReader, FakeSources, first, items, owner as _earnings_owner  # noqa: F401

# The first regular session after E_AT (Thu 2026-10-29, 16:31 New York) is Fri 2026-10-30; this is after its close.
AFTER_CLOSE = datetime(2026, 10, 31, 15, 0, tzinfo=UTC)
DURING_FIRST_SESSION = datetime(2026, 10, 30, 14, 0, tzinfo=UTC)


@pytest.fixture
def owner(_earnings_owner, monkeypatch):  # noqa: F811
    from app.models import SecFilingInventory
    import app.agent_chat_identity as identity
    monkeypatch.setattr(identity, "owner_credential_matches", lambda c: c == OWNER)
    em._last_fill.clear()
    with SessionLocal() as db:
        db.query(SecFilingInventory).delete()
        db.commit()
    return _earnings_owner


class SecondModelReader(FakeReader):
    """The owner re-bound the model between the first message and the follow-up."""
    def model_for_owner(self, owner):
        return {"provider": "fake", "model": "second-model", "api_key": "k", "base_url": None}


class CountingSources(FakeSources):
    def __init__(self, *args, fail=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail, self.close_calls = fail, 0

    def daily_closes(self, symbol):
        self.close_calls += 1
        if self.fail and self.close_calls > self.allowed:
            raise RuntimeError("prices down")
        return super().daily_closes(symbol)


def judge_once(reader=None, sources=None, **fields):
    reader = reader or FakeReader()
    sources = sources or FakeSources()
    first(sources, reader, **fields)
    em.tick(E_AT + timedelta(minutes=31), sources=sources, reader=reader)
    return reader, sources


def listed(client, query=""):
    response = client.get(f"/agent-chat/earnings-judgments{query}", headers=H)
    assert response.status_code == 200
    return response.json()["judgments"]


def set_history(accession, **fields):
    with SessionLocal() as db:
        row = db.query(EarningsHistory).filter(EarningsHistory.accession == accession).one()
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()


def test_followup_records_its_own_model(owner, client):
    first(FakeSources(), FakeReader())
    em.tick(E_AT + timedelta(minutes=31), sources=FakeSources(), reader=SecondModelReader())
    [row] = listed(client)
    assert row["model"] == "second-model" and row["model_source"] == "followup"
    assert row["reader_version"] == er.READER_VERSION
    with SessionLocal() as db:
        detail = db.query(EarningsEvent).one().detail
    assert detail["model"] == "fake-model" and detail["followup"]["model"] == "second-model"   # the first stage keeps its own


def test_older_row_is_labelled_first_stage(owner, client):
    judge_once()
    with SessionLocal() as db:
        event = db.query(EarningsEvent).one()
        follow = {k: v for k, v in event.detail["followup"].items() if k not in {"model", "reader_version"}}
        event.detail = {**event.detail, "followup": follow}      # a row written before B7
        db.commit()
    [row] = listed(client)
    assert row["model"] == "fake-model" and row["model_source"] == "first_stage" and row["reader_version"] == er.READER_VERSION


def test_outcome_pending_before_first_session_close(owner, client):
    judge_once()
    em.tick(DURING_FIRST_SESSION, sources=FakeSources(), reader=FakeReader())
    [row] = listed(client)
    assert row["outcome"] == {"status": "pending", "reaction": None, "sigma": None}
    assert row["promotion"] == {"available": False, "reason": "first_session_open"}


def test_outcome_after_close_uses_defined_label(owner, client):
    # After-hours +12.6%, but the first session closes with no marked move: the label is flat, not a hit.
    judge_once(sources=FakeSources(after_hours=0.126), reader=FakeReader("up", "high"))
    em.tick(AFTER_CLOSE, sources=FakeSources(after_hours=0.126), reader=FakeReader("up", "high"))
    [row] = listed(client)
    assert row["after_hours"] == pytest.approx(0.126)
    assert row["outcome"]["status"] == "no_marked_move" and row["outcome"]["reaction"] is not None and row["outcome"]["sigma"]
    # And the same closes read against a call in either direction once the label is up / down.
    for verdict, direction, status in (("up", "up", "matched"), ("down", "up", "mismatched"), ("up", "down", "mismatched")):
        set_history(E_ACC, verdict=verdict)
        with SessionLocal() as db:
            event = db.query(EarningsEvent).one()
            event.detail = {**event.detail, "followup": {**event.detail["followup"], "direction": direction}}
            db.commit()
        assert listed(client)[0]["outcome"]["status"] == status


def test_outcome_is_not_applicable_for_unclear(owner, client):
    judge_once(reader=FakeReader("unclear", "low"))
    set_history(E_ACC, verdict="up")
    [row] = listed(client)
    assert row["direction"] == "unclear" and row["outcome"]["status"] == "not_applicable"


def test_tick_fill_is_throttled_and_cannot_fail_tick(owner):
    judge_once()
    sources = CountingSources()
    base = sources.close_calls
    assert em.fill_due_outcomes(DURING_FIRST_SESSION, sources, FakeReader()) == ["INTC"]
    assert em.fill_due_outcomes(DURING_FIRST_SESSION + timedelta(minutes=30), sources, FakeReader()) == []     # same hour: skipped
    assert sources.close_calls == base + 1
    assert em.fill_due_outcomes(DURING_FIRST_SESSION + timedelta(minutes=61), sources, FakeReader()) == ["INTC"]
    assert sources.close_calls == base + 2
    # A price source that raises neither escapes fill_due_outcomes nor fails tick.
    em._last_fill.clear()
    broken = CountingSources(fail=True)
    broken.allowed = 0
    assert em.fill_due_outcomes(AFTER_CLOSE, broken, FakeReader()) == ["INTC"]
    em._last_fill.clear()
    assert em.tick(AFTER_CLOSE + timedelta(hours=2), sources=broken, reader=FakeReader()) == {"first": 0, "followup": 0}
    with SessionLocal() as db:
        assert db.query(EarningsHistory).filter(EarningsHistory.accession == E_ACC).one().reaction is None   # nothing was invented


def test_fill_only_looks_at_recent_releases_before_today(owner):
    judge_once()
    sources = CountingSources()
    same_day = datetime(2026, 10, 29, 23, 0, tzinfo=UTC)                       # still the release day in New York
    assert em.fill_due_outcomes(same_day, sources, FakeReader()) == []
    assert em.fill_due_outcomes(E_AT + timedelta(days=15), sources, FakeReader()) == []     # older than 14 days
    assert sources.close_calls == 0


def test_skipped_rows_are_listed_with_delivered_false(owner, client):
    judge_once(reader=FakeReader("unclear", "low"))
    judge_once(reader=FakeReader("down", "low"), symbol="NVDA", held=False, accession="0001045810-26-000001")
    rows = {r["symbol"]: r for r in listed(client)}
    assert rows["INTC"]["followup_status"] == "skipped_unclear" and rows["INTC"]["delivered"] is False
    assert rows["NVDA"]["followup_status"] == "skipped_low_confidence" and rows["NVDA"]["delivered"] is False
    assert rows["NVDA"]["reasons"] and rows["NVDA"]["counter_argument"]
    assert [r["symbol"] for r in listed(client, "?symbol=nvda")] == ["NVDA"]
    assert len(listed(client, "?limit=1")) == 1


def test_sent_row_is_delivered_and_fetchable_by_id(owner, client):
    judge_once()
    [row] = listed(client)
    assert row["delivered"] is True and row["followup_status"] == "sent" and row["held"] is True
    assert row["accession"] == E_ACC and row["direction"] == "down" and row["validated"] is False
    fetched = client.get(f"/agent-chat/earnings-judgments/{row['id']}", headers=H)
    assert fetched.status_code == 200 and fetched.json()["judgment"] == row
    assert client.get(f"/agent-chat/earnings-judgments/{uuid.uuid4()}", headers=H).status_code == 404
    assert client.get("/agent-chat/earnings-judgments/not-a-uuid", headers=H).status_code == 404


def test_event_without_a_judgment_is_not_listed(owner, client):
    first()                                                  # first message only; the follow-up is not due yet
    assert listed(client) == []
    with SessionLocal() as db:
        event_id = db.query(EarningsEvent).one().id
    assert client.get(f"/agent-chat/earnings-judgments/{event_id}", headers=H).status_code == 404


def test_inbox_items_carry_event_id(owner):
    judge_once()
    with SessionLocal() as db:
        event_id = str(db.query(EarningsEvent).one().id)
    for key, _, _, payload in items():
        assert payload["event_id"] == event_id
        assert key in {f"earnings:{E_ACC}:first", f"earnings:{E_ACC}:followup"}          # dedupe keys unchanged


def test_promotion_follows_session_and_library(owner, client):
    from app.models import SecFilingInventory
    judge_once()
    em.tick(AFTER_CLOSE, sources=FakeSources(), reader=FakeReader())
    [row] = listed(client)
    assert row["filing_source_id"] is None and row["promotion"] == {"available": False, "reason": "filing_not_in_library"}
    with SessionLocal() as db:
        item = SecFilingInventory(symbol="INTC", cik="0000050863", accession_number=E_ACC, form="8-K", filed_at=date(2026, 10, 29),
                                  primary_document="x.htm", source_url="https://www.sec.gov/x", source="sec_edgar",
                                  review_status="pending_review", observed_at=E_AT, content_status="not_fetched")
        db.add(item)
        db.commit()
        library_id = str(item.id)
    [row] = listed(client)
    assert row["filing_source_id"] == library_id and row["promotion"] == {"available": True, "reason": None}


def test_judgments_are_owner_only(owner, client):
    judge_once()
    assert client.get("/agent-chat/earnings-judgments").status_code == 403
    assert client.get("/agent-chat/earnings-judgments", headers={"X-Chat-Session": GUEST}).status_code == 403
    with SessionLocal() as db:
        event_id = db.query(EarningsEvent).one().id
    assert client.get(f"/agent-chat/earnings-judgments/{event_id}").status_code == 403
    assert client.get(f"/agent-chat/earnings-judgments/{event_id}", headers={"X-Chat-Session": GUEST}).status_code == 403
    assert len(listed(client)) == 1


def test_shares_line_stays_in_followup(owner):
    event = EarningsEvent(symbol="INTC", accession=E_ACC, accepted_at=E_AT, held=True)
    judgment = er.Judgment(direction="down", confidence="high", counter_argument="", reasons=[{"text": "t", "quote": "q"}])
    holding = FakeSources().holding
    _, body = em.render_followup(event, judgment, -0.05, holding, {"validated": True, "min_confidence": "high"})
    assert "可买" in body and "够补仓" in body
