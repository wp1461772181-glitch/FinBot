"""1f-1 backstage, task 2: the owner-only, read-only /backstage endpoints.

Real PostgreSQL (the test database).  The owner check is the app's own ``_owner_only``; the credential comparison is patched
the way the other API tests do it.
"""
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app import channels, memory_events, model_usage, owner_views
from app.agent_chat_models import (AgentBot, AgentConversation, AgentMessage, AgentProfileItem, AgentTelegramMessage, MemoryEvent, ModelCall)
from app.agent_chat_store import owner_hash
from app.agent_workflow import consent
from app.agent_workflow.models import AgentConsent
from app.database import Base, SessionLocal, engine
from app.alert_feedback import AlertFeedback
from app.duty_brief import DutyBrief
from app.duty_log import DutyLog

OWNER = "o" * 40
OWNER_HASH = owner_hash(OWNER)
GUEST = "g" * 40
H = {"X-Chat-Session": OWNER}
G = {"X-Chat-Session": GUEST}
NOW = datetime.now(UTC).replace(microsecond=0)
CONFIRM = "confirm:" + "Zq9" * 14          # a card's button value: must never come back
AUTHORIZE = "authorize:" + "Ab7" * 14
CHANGE = "change:" + str(uuid.uuid4())
REPLY = "reply:" + "Xy3" * 14
BUTTONS = (CONFIRM, AUTHORIZE, CHANGE, REPLY)
HASHES = ("c4p4b1l1ty" + "h" * 54, "d1g3st" + "d" * 58)

ENDPOINTS = ["/backstage/answers", f"/backstage/answers/{uuid.uuid4()}", "/backstage/usage", "/backstage/operations",
             "/backstage/deliveries", "/backstage/duty", "/backstage/memory"]


@pytest.fixture(autouse=True)
def world(monkeypatch, disposable_database):
    Base.metadata.create_all(engine, tables=[AgentConversation.__table__, AgentMessage.__table__, AgentBot.__table__,
                                             ModelCall.__table__, AgentConsent.__table__, AgentTelegramMessage.__table__,
                                             DutyLog.__table__, DutyBrief.__table__, AlertFeedback.__table__,
                                             AgentProfileItem.__table__, MemoryEvent.__table__])
    consent.ensure_columns()
    import app.agent_chat_identity as identity
    monkeypatch.setattr(identity, "owner_credential_matches", lambda value: value == OWNER)
    monkeypatch.setattr(consent, "owner_credential_matches", lambda value: value == OWNER)
    model_usage.flush(timeout=10)
    with SessionLocal() as db:
        for model in (MemoryEvent, AgentProfileItem, AlertFeedback, DutyBrief, DutyLog, ModelCall, AgentConsent, AgentTelegramMessage, AgentMessage,
                      AgentConversation, AgentBot):
            db.query(model).delete()
        db.commit()
    yield
    model_usage.flush(timeout=10)


def bot(name="助理"):
    with SessionLocal() as db:
        row = AgentBot(owner_hash=OWNER_HASH, name=name, is_default=(name == "助理"))
        db.add(row)
        db.commit()
        return row.id


def conversation(bot_id=None, owner=OWNER_HASH):
    with SessionLocal() as db:
        row = AgentConversation(owner_hash=owner, bot_id=bot_id)
        db.add(row)
        db.commit()
        return row.id


def kernel_record(**extra):
    record = {"route": "K", "tier": "low", "narration": ["先查申报。"], "checklist": [{"item": "查营收", "state": "done"}],
              "audit": {"engine": "v2", "model_calls": 2, "tool_calls": 1, "token_usage": 300, "cache_read_tokens": 100,
                        "cache_write_tokens": 20, "terminal_status": "succeeded", "tier": "low", "writes": [],
                        "calls": [{"tier": "low", "ms": 900, "tokens": 150, "cache_read": 50, "cache_write": 10, "model": "vendor/m-1"},
                                  {"tier": "low", "ms": 700, "tokens": 150, "cache_read": 50, "cache_write": 10, "model": "vendor/m-1"}]},
              "tool_trace": [{"call_id": "call-1", "name": "query_financials", "status": "complete",
                              "result": {"ok": True, "error_code": None, "count": 4, "job_status": None}}],
              "thinking_ms": 2500, "trace": [], "citations": [{"ordinal": 1, "title": "TSLA 10-Q", "url": "https://sec.example/x",
                                                               "source_type": "reported_figure", "evidence_key": "k" * 64}]}
    record.update(extra)
    return record


def turn(cid, question="特斯拉营收是多少", answer="营收 280 亿美元 [1]", *, record=None, status="complete", at=None,
         steps=True, turn_id=None, final=True):
    """A stored turn: the question, (for a kernel turn) one tool round, then the final answer.  Returns (turn_id, message_id)."""
    turn_id = turn_id or uuid.uuid4()
    at = at or NOW
    with SessionLocal() as db:
        seq = (db.execute(text("select coalesce(max(sequence),0) from agent_messages where conversation_id=:c"), {"c": cid}).scalar()) + 1
        rows = [AgentMessage(conversation_id=cid, turn_id=turn_id, sequence=seq, role="user", content=question, created_at=at)]
        if steps:
            call = {"id": "call-1", "type": "function", "function": {"name": "query_financials", "arguments": json.dumps(
                {"symbol": "TSLA", "metrics": ["revenue"], "confirm": CONFIRM, "say": "查一下"})}}
            rows.append(AgentMessage(conversation_id=cid, turn_id=turn_id, sequence=seq + 1, role="assistant", content="",
                                     tool_calls={"calls": [call]}, created_at=at))
            rows.append(AgentMessage(conversation_id=cid, turn_id=turn_id, sequence=seq + 2, role="tool", tool_call_id="call-1",
                                     content=json.dumps({"ok": True, "data": [{"title": "Q3 revenue"}, {"title": "Q2 revenue"},
                                                                              {"title": "Q1 revenue"}, {"title": "Q4 revenue"}]}),
                                     created_at=at))
            seq += 2
        final_row = AgentMessage(conversation_id=cid, turn_id=turn_id, sequence=seq + 1, role="assistant", content=answer,
                                 tool_calls=record, status=status, created_at=at + timedelta(seconds=2))
        if final:
            rows.append(final_row)
        db.add_all(rows)
        db.commit()
        return turn_id, (final_row.id if final else rows[0].id)


def ledger(turn_id, cid, *, model="m-1", catalog="cat-1", ms=800, cost=0.01, ok=True, purpose="chat", attempt=1, at=None,
           input_tokens=100, output_tokens=20, cache_read=30, cache_write=5, bot_id=None, owner=OWNER_HASH, error=None):
    with SessionLocal() as db:
        db.add(ModelCall(created_at=at or NOW, owner_hash=owner, purpose=purpose, provider="openrouter", model=model,
                         catalog_name=catalog, conversation_id=cid, turn_id=turn_id, bot_id=bot_id, attempt=attempt, ok=ok,
                         error=error, ms=ms, input_tokens=input_tokens, output_tokens=output_tokens,
                         cache_read_tokens=cache_read, cache_write_tokens=cache_write, cost_usd=cost))
        db.commit()


def get(client, path, headers=H, **params):
    return client.get(path, headers=headers, params=params)


# --- who may read ----------------------------------------------------------------------------------------------

def test_every_endpoint_refuses_a_guest_and_a_missing_or_wrong_credential(client):
    cid = conversation(bot())
    turn(cid, record=kernel_record())
    for path in ENDPOINTS:
        for headers in (G, {}, {"X-Chat-Session": ""}, {"X-Chat-Session": OWNER + "x"}):
            response = client.get(path, headers=headers)
            assert response.status_code == 403, (path, headers)
            assert response.json() == {"detail": "owner_only"}
            assert "营收" not in response.text and "特斯拉" not in response.text


def test_the_owner_is_let_in_everywhere(client):
    for path in ENDPOINTS:
        if "answers/" in path:
            assert client.get(path, headers=H).status_code == 404       # no such message, but not a refusal
        else:
            assert client.get(path, headers=H).status_code == 200


# --- answers: list -----------------------------------------------------------------------------------------------

def test_answers_list_item_for_a_kernel_turn(client):
    b = bot()
    cid = conversation(b)
    tid, mid = turn(cid, record=kernel_record(), answer="营收 280 亿美元 " + "字" * 300)
    ledger(tid, cid, ms=900, cost=0.01)
    ledger(tid, cid, ms=700, cost=0.02, input_tokens=10, output_tokens=5, cache_read=0, cache_write=0)
    model_usage.flush()
    body = get(client, "/backstage/answers").json()
    assert body["slow_threshold_ms"] is None
    item = body["items"][0]
    assert item["message_id"] == str(mid) and item["conversation_id"] == str(cid)
    assert item["bot_id"] == str(b) and item["bot_name"] == "助理"
    assert item["question"] == "特斯拉营收是多少" and len(item["answer"]) == 200
    assert (item["engine"], item["status"], item["tier"]) == ("v2", "succeeded", "low")
    assert item["models"] == ["cat-1"] and item["total_ms"] == 2500 and item["model_calls"] == 2
    assert item["tokens"] == {"total": 100 + 20 + 30 + 5 + 15, "cache_read": 30, "cache_write": 5}
    assert item["cost_usd"] == pytest.approx(0.03) and item["tool_count"] == 1
    assert item["write_outcomes"] == [] and item["created_at"]
    assert body["next_before"] is None


def test_cost_is_null_unless_every_call_has_a_price_or_the_calls_have_not_all_landed(client):
    cid = conversation(bot())
    tid, _ = turn(cid, record=kernel_record())
    ledger(tid, cid, cost=0.01)
    ledger(tid, cid, cost=None)
    model_usage.flush()
    assert get(client, "/backstage/answers").json()["items"][0]["cost_usd"] is None
    tid2, _ = turn(cid, record=kernel_record(), at=NOW + timedelta(minutes=1))
    ledger(tid2, cid, cost=0.01)                  # the audit says two calls; one row has landed so far
    model_usage.flush()
    one = get(client, "/backstage/answers").json()["items"][0]
    assert one["cost_usd"] is None and one["model_calls"] == 1


def test_a_turn_with_no_ledger_rows_shows_its_audit(client):
    cid = conversation(bot())
    turn(cid, record=kernel_record())
    item = get(client, "/backstage/answers").json()["items"][0]
    assert item["model_calls"] == 2 and item["cost_usd"] is None and item["models"] == ["vendor/m-1"]
    assert item["tokens"] == {"total": 300, "cache_read": 100, "cache_write": 20}


def test_old_engine_null_and_malformed_records_are_listed(client):
    cid = conversation(bot())
    turn(cid, "旧问题", "旧答案", record={"calls": [{"id": "x"}], "reasoning_content": "想"}, steps=False, at=NOW - timedelta(minutes=1))
    turn(cid, "空记录", "答案二", record=None, steps=False, at=NOW - timedelta(minutes=2))
    with SessionLocal() as db:        # a string where the JSON should be: stored text that is not an object
        _, mid = turn(cid, "坏记录", "答案三", record=None, steps=False, at=NOW - timedelta(minutes=3))
        db.execute(text("update agent_messages set tool_calls = to_json('{broken'::text) where id = :i"), {"i": mid})
        db.commit()
    items = get(client, "/backstage/answers").json()["items"]
    assert [i["question"] for i in items] == ["旧问题", "空记录", "坏记录"]
    assert all(i["engine"] == "v1" and i["status"] == "succeeded" and i["model_calls"] == 0 for i in items)
    assert all(i["tier"] is None and i["cost_usd"] is None for i in items)


def test_list_filters(client):
    b1, b2 = bot(), bot("研究员")
    c1, c2 = conversation(b1), conversation(b2)
    base = NOW - timedelta(hours=1)
    turn(c1, "alpha question", "alpha answer", record=kernel_record(), at=base)
    audit = kernel_record()["audit"] | {"terminal_status": "failed"}
    turn(c1, "beta question", "failed answer", record=kernel_record(audit=audit), status="failed", at=base + timedelta(minutes=1))
    turn(c2, "gamma", "gamma answer", record=kernel_record(tier="high", audit=kernel_record()["audit"] | {"tier": "high"}),
         at=base + timedelta(minutes=2))
    turn(c2, "delta", "cancelled answer", record=None, status="cancelled", steps=False, at=base + timedelta(minutes=3))
    wait = kernel_record(audit=kernel_record()["audit"] | {"terminal_status": "waiting_for_input"})
    turn(c2, "epsilon", "waiting answer", record=wait, at=base + timedelta(minutes=4))

    def questions(**params):
        return [i["question"] for i in get(client, "/backstage/answers", **params).json()["items"]]

    assert questions() == ["epsilon", "delta", "gamma", "beta question", "alpha question"]
    assert questions(bot_id=str(b1)) == ["beta question", "alpha question"]
    assert questions(engine="v1") == ["delta"]
    assert questions(engine="v2") == ["epsilon", "gamma", "beta question", "alpha question"]
    assert questions(status="failed") == ["beta question"]
    assert questions(status="cancelled") == ["delta"]
    assert questions(status="waiting_for_input") == ["epsilon"]
    assert questions(status="succeeded") == ["gamma", "alpha question"]
    assert questions(tier="high") == ["gamma"]
    assert questions(q="ALPHA") == ["alpha question"]           # question text, any case
    assert questions(q="waiting answer") == ["epsilon"]          # answer text
    assert questions(q="100%") == []                             # a wildcard character is just a character
    assert get(client, "/backstage/answers", status="bogus").status_code == 400
    assert get(client, "/backstage/answers", before="junk").status_code == 400
    assert get(client, "/backstage/answers", bot_id="not-a-uuid").status_code == 400


def test_a_guest_conversation_is_never_listed(client):
    conversation(None)
    cid = conversation(None, owner=owner_hash(GUEST))
    turn(cid, "guest secret question", "guest answer", record=None, steps=False)
    mine = conversation(bot())
    turn(mine, "mine", "my answer", record=None, steps=False)
    assert [i["question"] for i in get(client, "/backstage/answers").json()["items"]] == ["mine"]


def test_keyset_paging_walks_every_row_once_even_with_equal_timestamps(client):
    cid = conversation(bot())
    ids = []
    for index in range(7):
        ids.append(str(turn(cid, f"q{index}", f"a{index}", record=None, steps=False, at=NOW - timedelta(minutes=index // 2))[1]))
    seen, before = [], None
    for _ in range(10):
        params = {"limit": 3} | ({"before": before} if before else {})
        body = get(client, "/backstage/answers", **params).json()
        seen += [i["message_id"] for i in body["items"]]
        before = body["next_before"]
        if before is None:
            break
    assert sorted(seen) == sorted(ids) and len(seen) == len(set(seen)) == 7


def test_slow_keeps_the_turns_over_the_p90_of_the_window_and_says_the_threshold(client):
    cid = conversation(bot())
    for index in range(10):
        turn(cid, f"q{index}", "a", record=kernel_record(thinking_ms=1000 * (index + 1)), at=NOW - timedelta(minutes=index))
    body = get(client, "/backstage/answers", slow=1).json()
    assert body["slow_threshold_ms"] == pytest.approx(9100)
    assert [i["total_ms"] for i in body["items"]] == [10000]
    assert get(client, "/backstage/answers").json()["slow_threshold_ms"] is None


def test_a_conversation_of_2000_turns_lists_quickly(client):
    import time
    cid = conversation(bot())
    with SessionLocal() as db:
        rows = []
        for index in range(2000):
            t = uuid.uuid4()
            rows.append(AgentMessage(conversation_id=cid, turn_id=t, sequence=index * 2 + 1, role="user", content=f"q{index}",
                                     created_at=NOW - timedelta(seconds=index)))
            rows.append(AgentMessage(conversation_id=cid, turn_id=t, sequence=index * 2 + 2, role="assistant", content=f"a{index}",
                                     tool_calls=None, created_at=NOW - timedelta(seconds=index)))
        db.add_all(rows)
        db.commit()
    started = time.monotonic()
    body = get(client, "/backstage/answers", limit=50).json()
    assert len(body["items"]) == 50 and body["next_before"]
    assert time.monotonic() - started < 3


# --- answers: detail -----------------------------------------------------------------------------------------------

def card_record():
    request_id = str(uuid.uuid4())
    record = kernel_record(
        narration=["我先提出操作。", "已换用备用模型「备用」。"],
        clarification={"request_id": request_id, "reason": "write_confirmation", "question": None,
                       "display": {"title": "设置可用资金 · 12345.00", "targets": [{"kind": "现在 7688.00 → 12345.00"}]},
                       "choices": [{"label": "同意", "value": CONFIRM}, {"label": "换个操作", "value": CHANGE},
                                   {"label": "取消", "value": "cancel:" + request_id}, {"label": "回复", "value": REPLY}]})
    record["audit"] = record["audit"] | {"terminal_status": "waiting_for_input", "write_outcome": "proposed",
                                         "writes": [{"operation": "set_available_funds", "tier": 2, "outcome": "proposed"}],
                                         "fallback": {"from": "cat-1", "to": "backup-1", "reason": "http_500"}}
    return request_id, record


def test_detail_of_a_kernel_turn_with_a_tool_a_card_and_a_backup_model(client, monkeypatch):
    request_id, record = card_record()
    b = bot()
    cid = conversation(b)
    tid, mid = turn(cid, record=record, answer="请确认这张卡。")
    ledger(tid, cid, model="m-1", catalog="cat-1", ms=900, cost=None, ok=False, error="http_500", at=NOW)
    ledger(tid, cid, model="m-2", catalog="backup-1", ms=700, cost=0.02, attempt=2, at=NOW + timedelta(seconds=1))
    ledger(tid, cid, model="m-2", catalog="backup-1", ms=600, cost=0.01, attempt=1, at=NOW + timedelta(seconds=2))
    with SessionLocal() as db:
        db.add(AgentConsent(id=uuid.UUID(request_id), owner_hash=OWNER_HASH, conversation_id=str(cid), capability_hash=HASHES[0],
                            payload_digest=HASHES[1], operations=[{"name": "set_available_funds", "arguments": {"amount": 12345}}],
                            display={"title": "设置可用资金 · 12345.00"}, expires_at=NOW + timedelta(minutes=5), status="proposed"))
        db.commit()
    model_usage.flush()
    response = get(client, f"/backstage/answers/{mid}")
    assert response.status_code == 200
    body = response.json()
    assert body["partial"] is False and body["engine"] == "v2" and body["status"] == "waiting_for_input"
    assert body["question"] == "特斯拉营收是多少" and body["answer"] == "请确认这张卡。"
    assert body["bot_name"] == "助理" and body["turn_id"] == str(tid)
    assert body["narration"] == ["我先提出操作。", "已换用备用模型「备用」。"]
    assert body["checklist"] == [{"item": "查营收", "state": "done"}]
    calls = body["model_calls"]
    assert body["model_calls_source"] == "ledger" and [c["catalog_name"] for c in calls] == ["cat-1", "backup-1", "backup-1"]
    assert calls[0]["ok"] is False and calls[0]["error"] == "http_500" and calls[0]["cost_usd"] is None and calls[0]["priced"] is False
    assert calls[1]["attempt"] == 2 and calls[1]["tokens"] == {"input": 100, "output": 20, "cache_read": 30, "cache_write": 5, "total": 155}
    assert calls[1]["tier"] == "low"
    tool = body["tool_calls"][0]
    assert tool["name"] == "query_financials" and tool["status"] == "complete"
    assert tool["arguments"]["symbol"] == "TSLA" and CONFIRM not in json.dumps(tool["arguments"])
    assert tool["result"] == {"ok": True, "error_code": None, "count": 4, "row_titles": ["Q3 revenue", "Q2 revenue", "Q1 revenue"]}
    assert body["citations"] == [{"ordinal": 1, "title": "TSLA 10-Q", "url": "https://sec.example/x", "source_type": "reported_figure"}]
    assert body["writes"] == [{"operation": "set_available_funds", "tier": 2, "outcome": "proposed"}]
    assert body["write_outcome"] == "proposed"
    assert body["backup_model"] == {"from": "cat-1", "to": "backup-1", "reason": "http_500"}
    card = body["card"]
    assert card["request_id"] == request_id and card["title"] == "设置可用资金 · 12345.00"
    assert [c["label"] for c in card["choices"]] == ["同意", "换个操作", "取消", "回复"]
    assert card["consent"]["status"] == "proposed" and card["consent"]["expired"] is False and card["consent"]["operations"] == [{"name": "set_available_funds", "tier": 2}]
    assert body["langfuse_url"] is None
    for secret in (*BUTTONS, HASHES[0], HASHES[1], "k" * 64):
        assert secret not in response.text


def test_detail_falls_back_to_the_audit_when_the_ledger_has_not_landed(client):
    cid = conversation(bot())
    tid, mid = turn(cid, record=kernel_record())
    ledger(tid, cid, ms=900)                      # one row of the audit's two has landed
    model_usage.flush()
    body = get(client, f"/backstage/answers/{mid}").json()
    assert body["model_calls_source"] == "audit" and len(body["model_calls"]) == 2
    assert body["model_calls"][0] == {"tier": "low", "model": "vendor/m-1", "catalog_name": None, "purpose": "chat", "ms": 900,
                                      "tokens": {"input": None, "output": None, "cache_read": 50, "cache_write": 10, "total": 150},
                                      "attempt": None, "ok": None, "error": None, "cost_usd": None, "priced": False, "at": None, "recorded": False}


def test_the_detail_tolerates_a_ledger_row_with_no_tier_match(client):
    cid = conversation(bot())
    tid, mid = turn(cid, record=kernel_record())
    for _ in range(3):
        ledger(tid, cid)
    ledger(tid, cid, purpose="judge", model="j-1", catalog="judge-1")
    model_usage.flush()
    body = get(client, f"/backstage/answers/{mid}").json()
    assert body["model_calls_source"] == "ledger" and len(body["model_calls"]) == 4
    assert {c["purpose"] for c in body["model_calls"]} == {"chat", "judge"}
    assert all(c["tier"] is None for c in body["model_calls"])       # three chat rows against two audit lines: no guess


def test_detail_of_an_old_engine_message_is_partial(client):
    cid = conversation(bot())
    _, mid = turn(cid, "旧问题", "旧答案", record={"calls": [{"id": "call-1"}], "reasoning_content": "想一想"}, steps=True)
    body = get(client, f"/backstage/answers/{mid}").json()
    assert body["partial"] is True and body["engine"] == "v1"
    assert body["question"] == "旧问题" and body["answer"] == "旧答案"
    assert body["model_calls"] == [] and body["narration"] == [] and body["checklist"] == [] and body["citations"] == []
    assert body["tool_calls"][0]["name"] == "query_financials"
    assert body["card"] is None and body["backup_model"] is None


@pytest.mark.parametrize("stored", [None, "{broken", 42, ["x"]])
def test_detail_of_a_null_or_malformed_record_answers(client, stored):
    cid = conversation(bot())
    _, mid = turn(cid, "问", "答", record=None, steps=False)
    with SessionLocal() as db:
        db.execute(text("update agent_messages set tool_calls = cast(:v as json) where id = :i"), {"v": json.dumps(stored), "i": mid})
        db.commit()
    response = get(client, f"/backstage/answers/{mid}")
    assert response.status_code == 200
    body = response.json()
    assert body["partial"] is True and body["answer"] == "答" and body["question"] == "问"


def test_detail_404s(client):
    assert get(client, f"/backstage/answers/{uuid.uuid4()}").status_code == 404
    assert get(client, "/backstage/answers/not-a-uuid").status_code == 404
    cid = conversation(None, owner=owner_hash(GUEST))
    _, mid = turn(cid, record=None, steps=False)
    assert get(client, f"/backstage/answers/{mid}").status_code == 404        # not this owner's
    mine = conversation(bot())
    _, final_id = turn(mine, record=None, steps=True)
    with SessionLocal() as db:
        question_id = db.execute(text("select id from agent_messages where conversation_id=:c and role='user'"), {"c": mine}).scalar()
        round_id = db.execute(text("select id from agent_messages where conversation_id=:c and role='assistant' and content='' "
                                   "order by sequence limit 1"), {"c": mine}).scalar()
    opened = get(client, f"/backstage/answers/{question_id}")
    assert opened.status_code == 200 and opened.json()["message_id"] == str(final_id)       # the question's id opens the same turn
    assert get(client, f"/backstage/answers/{round_id}").status_code == 404          # a tool round is not an answer


# --- answers: the figure check (5d-1) ---------------------------------------------------------------------------------

FLAGGED = {"version": 1, "figures": 3, "flagged": [{"line": "利润是 8888 美元", "values": ["8888"]}]}
CLEAN = {"version": 1, "figures": 2, "flagged": []}


def reconcile_world():
    cid = conversation(bot())
    base = NOW - timedelta(hours=1)
    turn(cid, "flagged", "利润是 8888 美元。", record=kernel_record(reconciliation=FLAGGED), at=base)
    turn(cid, "clean", "营收是 4500 美元。", record=kernel_record(reconciliation=CLEAN), at=base + timedelta(minutes=1))
    turn(cid, "error", "答", record=kernel_record(reconciliation={"version": 1, "error": "KeyError"}), at=base + timedelta(minutes=2))
    turn(cid, "unchecked", "答", record=kernel_record(), at=base + timedelta(minutes=3))
    turn(cid, "damaged", "答", record=kernel_record(reconciliation={"version": 1, "flagged": "x"}), at=base + timedelta(minutes=4))
    turn(cid, "incomplete", final=False, at=base + timedelta(minutes=5))
    return cid


def test_each_answer_row_says_how_its_figure_check_went(client):
    reconcile_world()
    rows = {i["question"]: i["reconcile"] for i in get(client, "/backstage/answers").json()["items"]}
    assert rows == {"flagged": "flagged", "clean": "clean", "error": "error", "unchecked": None, "damaged": "clean", "incomplete": None}


def test_the_filter_keeps_only_the_answers_whose_figures_did_not_match(client):
    reconcile_world()
    assert [i["question"] for i in get(client, "/backstage/answers", reconcile="flagged").json()["items"]] == ["flagged"]
    assert get(client, "/backstage/answers", reconcile="clean").status_code == 400
    assert get(client, "/backstage/answers", reconcile="flagged", headers=G).status_code == 403


def test_the_detail_shows_the_figures_checked_and_each_flagged_line(client):
    cid = conversation(bot())
    flagged = {"version": 1, "figures": 3, "flagged": [{"line": f"利润是 8888 美元 {CONFIRM}", "values": ["8888"]}, {"line": "", "values": ["1"]}, "junk"]}
    _, mid = turn(cid, record=kernel_record(reconciliation=flagged), answer="利润是 8888 美元。")
    body = get(client, f"/backstage/answers/{mid}").json()
    assert body["reconciliation"] == {"state": "flagged", "figures": 3, "error": None,
                                      "flagged": [{"line": "利润是 8888 美元 [已移除]", "values": ["8888"]}]}
    _, clean = turn(cid, record=kernel_record(reconciliation=CLEAN), at=NOW + timedelta(minutes=1))
    assert get(client, f"/backstage/answers/{clean}").json()["reconciliation"] == {"state": "clean", "figures": 2, "flagged": [], "error": None}
    _, failed = turn(cid, record=kernel_record(reconciliation={"version": 1, "error": "KeyError"}), at=NOW + timedelta(minutes=2))
    assert get(client, f"/backstage/answers/{failed}").json()["reconciliation"] == {"state": "error", "figures": None, "flagged": [], "error": "KeyError"}
    _, unchecked = turn(cid, record=kernel_record(), at=NOW + timedelta(minutes=3))
    assert get(client, f"/backstage/answers/{unchecked}").json()["reconciliation"] is None
    assert get(client, f"/backstage/answers/{mid}", headers=G).status_code == 403


def test_no_stored_button_value_appears_in_any_response(client):
    request_id, record = card_record()
    record["narration"].append(f"值是 {CONFIRM} 和 {AUTHORIZE}")
    record["tool_trace"][0]["result"]["note"] = REPLY
    cid = conversation(bot())
    tid, mid = turn(cid, record=record, answer=f"点这个 {CONFIRM}")
    with SessionLocal() as db:
        db.add(AgentConsent(id=uuid.UUID(request_id), owner_hash=OWNER_HASH, conversation_id=str(cid), capability_hash=HASHES[0],
                            payload_digest=HASHES[1], operations=[{"name": "x", "arguments": {"token": CONFIRM}}],
                            display={"title": "t", "targets": [{"kind": AUTHORIZE}]}, expires_at=NOW + timedelta(minutes=5),
                            status="proposed", result={"ok": True, "data": [{"ok": True, "echo": CHANGE}]}))
        db.commit()
    for path in (f"/backstage/answers/{mid}", "/backstage/answers", "/backstage/operations"):
        text_ = get(client, path).text
        for value in BUTTONS:
            assert value not in text_, (path, value)
        assert HASHES[0] not in text_ and HASHES[1] not in text_


def test_the_langfuse_link_needs_configuration_and_a_stored_trace_id(client, monkeypatch):
    cid = conversation(bot())
    record = kernel_record()
    record["audit"] = record["audit"] | {"trace_id": "abc123"}
    _, with_id = turn(cid, record=record)
    _, without = turn(cid, record=kernel_record(), at=NOW + timedelta(minutes=1))
    for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
        monkeypatch.delenv(name, raising=False)
    assert get(client, f"/backstage/answers/{with_id}").json()["langfuse_url"] is None
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_HOST", "https://lf.example.test/")
    response = get(client, f"/backstage/answers/{with_id}")
    assert response.json()["langfuse_url"] == "https://lf.example.test/trace/abc123"
    assert "sk-lf-test" not in response.text and "pk-lf-test" not in response.text
    assert get(client, f"/backstage/answers/{without}").json()["langfuse_url"] is None


# --- usage -----------------------------------------------------------------------------------------------------------

def day(y, m, d, hour=12):
    return datetime(y, m, d, hour, tzinfo=UTC)


def test_usage_groups_totals_priced_and_unpriced_and_names_its_timezone(client):
    b = bot()
    cid = conversation(b)
    t = uuid.uuid4()
    ledger(t, cid, catalog="cat-1", ms=100, cost=0.10, at=day(2026, 11, 1), bot_id=b, purpose="chat")
    ledger(t, cid, catalog="cat-1", ms=300, cost=0.30, at=day(2026, 11, 1), bot_id=b, purpose="chat", ok=False, error="timeout")
    ledger(t, cid, catalog="cat-2", ms=500, cost=None, at=day(2026, 11, 2), bot_id=None, purpose="judge")
    ledger(t, cid, catalog=None, model="raw-model", ms=700, cost=None, at=day(2026, 11, 3), purpose="summary")
    ledger(t, cid, catalog="cat-1", at=day(2026, 11, 9), cost=9.0)                      # outside the range
    model_usage.flush()
    body = get(client, "/backstage/usage", **{"from": "2026-11-01", "to": "2026-11-03", "group": "model"}).json()
    assert body["timezone"] == "UTC" and "owner" in body["timezone_note"]
    assert body["from"] == "2026-11-01" and body["to"] == "2026-11-03" and body["group"] == "model"
    totals = body["totals"]
    assert totals["calls"] == 4 and totals["failed_calls"] == 1 and totals["unpriced_calls"] == 2
    assert totals["cost_usd"] == pytest.approx(0.40) and totals["ms_p50"] == pytest.approx(400)
    assert totals["tokens"] == {"input": 400, "output": 80, "cache_read": 120, "cache_write": 20}
    by_key = {g["key"]: g for g in body["groups"]}
    assert set(by_key) == {"cat-1", "cat-2", "raw-model"}
    assert by_key["cat-1"]["calls"] == 2 and by_key["cat-1"]["failed_calls"] == 1 and by_key["cat-1"]["cost_usd"] == pytest.approx(0.40)
    assert by_key["cat-2"]["unpriced_calls"] == 1 and by_key["cat-2"]["cost_usd"] is None
    assert by_key["cat-2"]["missing_prices"] == ["cache_read", "cache_write", "input", "output"] and by_key["cat-1"]["missing_prices"] == []
    assert sum(g["calls"] for g in body["groups"]) == totals["calls"]

    days = get(client, "/backstage/usage", **{"from": "2026-11-01", "to": "2026-11-03", "group": "day"}).json()
    assert [(g["key"], g["calls"]) for g in days["groups"]] == [("2026-11-01", 2), ("2026-11-02", 1), ("2026-11-03", 1)]
    purposes = get(client, "/backstage/usage", **{"from": "2026-11-01", "to": "2026-11-03", "group": "purpose"}).json()
    assert {g["key"] for g in purposes["groups"]} == {"chat", "judge", "summary"}
    bots = get(client, "/backstage/usage", **{"from": "2026-11-01", "to": "2026-11-03", "group": "bot"}).json()
    named = {g["key"]: g["label"] for g in bots["groups"]}
    assert named[str(b)] == "助理" and named["none"] == "（无）"


def test_usage_days_split_at_utc_midnight_and_the_range_is_inclusive(client):
    cid = conversation(bot())
    t = uuid.uuid4()
    ledger(t, cid, at=datetime(2026, 11, 1, 23, 59, 59, tzinfo=UTC))
    ledger(t, cid, at=datetime(2026, 11, 2, 0, 0, 0, tzinfo=UTC))
    model_usage.flush()
    body = get(client, "/backstage/usage", **{"from": "2026-11-01", "to": "2026-11-02", "group": "day"}).json()
    assert [(g["key"], g["calls"]) for g in body["groups"]] == [("2026-11-01", 1), ("2026-11-02", 1)]
    one = get(client, "/backstage/usage", **{"from": "2026-11-02", "to": "2026-11-02", "group": "day"}).json()
    assert one["totals"]["calls"] == 1


def test_usage_defaults_validation_and_whose_rows_count(client):
    cid = conversation(bot())
    ledger(uuid.uuid4(), cid, at=datetime.now(UTC))
    ledger(uuid.uuid4(), cid, at=datetime.now(UTC), owner=None)                       # background work with no owner tag
    ledger(uuid.uuid4(), cid, at=datetime.now(UTC), owner=owner_hash(GUEST))           # a guest's call is not the owner's
    model_usage.flush()
    body = get(client, "/backstage/usage").json()
    assert body["group"] == "day" and body["totals"]["calls"] == 2
    for bad in ({"group": "weird"}, {"from": "yesterday"}, {"from": "2026-11-05", "to": "2026-11-01"}):
        assert get(client, "/backstage/usage", **bad).status_code == 400


def test_a_renamed_models_past_calls_keep_the_name_they_had(client):
    cid = conversation(bot())
    t = uuid.uuid4()
    ledger(t, cid, catalog="old-name", model="vendor/m-1", at=day(2026, 11, 1), cost=0.1)
    ledger(t, cid, catalog="new-name", model="vendor/m-1", at=day(2026, 11, 2), cost=0.2)
    model_usage.flush()
    body = get(client, "/backstage/usage", **{"from": "2026-11-01", "to": "2026-11-02", "group": "model"}).json()
    assert {g["key"] for g in body["groups"]} == {"old-name", "new-name"}


# --- operations ----------------------------------------------------------------------------------------------------

def card_row(status="proposed", *, created=None, expires=None, decided=None, result=None, ops=None, conversation_id=None):
    with SessionLocal() as db:
        row = AgentConsent(owner_hash=OWNER_HASH, conversation_id=str(conversation_id or uuid.uuid4()),
                           capability_hash=uuid.uuid4().hex + uuid.uuid4().hex, payload_digest=uuid.uuid4().hex + uuid.uuid4().hex,
                           operations=ops or [{"name": "add_to_research_queue", "arguments": {"symbol": "ANT"}},
                                              {"name": "set_available_funds", "arguments": {"amount": 1}}],
                           display={"title": "确认以下操作", "targets": [{"symbol": "ANT", "title": "加入研究队列"}]},
                           expires_at=expires or NOW + timedelta(minutes=10), status=status, result=result,
                           created_at=created or NOW, decided_at=decided)
        db.add(row)
        db.commit()
        return row.id


def test_operations_list_never_shows_hashes_and_derives_expiry(client):
    b = bot()
    cid = conversation(b)
    done = card_row("complete", created=NOW - timedelta(minutes=5), conversation_id=cid, decided=NOW - timedelta(minutes=4),
                    result={"ok": True, "status": "complete", "data": [{"ok": True, "data": [{"secret_rows": ["x"] * 50}]},
                                                                         {"ok": False, "error_code": "market_data_unavailable", "reason": "r"}]})
    card_row("proposed", created=NOW - timedelta(minutes=30), expires=NOW - timedelta(minutes=20), conversation_id=cid)
    card_row("cancelled", created=NOW - timedelta(minutes=40), decided=NOW - timedelta(minutes=39))
    card_row("proposed", created=NOW)
    response = get(client, "/backstage/operations")
    body = response.json()
    assert [i["status"] for i in body["items"]] == ["proposed", "complete", "proposed", "cancelled"]
    assert [i["expired"] for i in body["items"]] == [False, False, True, False]
    item = body["items"][1]
    assert item["id"] == str(done) and item["title"] == "确认以下操作" and item["targets"] == [{"symbol": "ANT", "title": "加入研究队列"}]
    assert item["operations"] == [{"name": "add_to_research_queue", "tier": 1}, {"name": "set_available_funds", "tier": 2}]
    assert item["bot_name"] == "助理" and item["decided_at"].startswith((NOW - timedelta(minutes=4)).isoformat()[:19])
    assert item["result"] == {"ok": True, "status": "complete", "outcomes": [{"ok": True, "error_code": None},
                                                                              {"ok": False, "error_code": "market_data_unavailable"}]}
    expired = body["items"][2]
    assert expired["decided_at"] is None and expired["expired"] is True                    # nobody touched it: not "decided"
    for key in ("capability_hash", "payload_digest", "payload_digest", "operations_payload"):
        assert key not in response.text
    assert "secret_rows" not in response.text


def test_operations_paging(client):
    for index in range(5):
        card_row(created=NOW - timedelta(minutes=index))
    first = get(client, "/backstage/operations", limit=2).json()
    second = get(client, "/backstage/operations", limit=2, before=first["next_before"]).json()
    third = get(client, "/backstage/operations", limit=2, before=second["next_before"]).json()
    ids = [i["id"] for page in (first, second, third) for i in page["items"]]
    assert len(ids) == len(set(ids)) == 5 and third["next_before"] is None


def test_decided_at_is_set_when_a_card_is_executed_cancelled_changed_or_expires():
    from app.agent_workflow import consent as consents
    conv = "conv-1"
    def make(**kw):
        token = uuid.uuid4().hex + uuid.uuid4().hex
        ops = [{"name": "n", "arguments": {}}]
        card = consents.propose(OWNER, conv, ops, {"title": "t", "targets": []}, **kw)
        return card, ops, card["choices"][0]["value"].split(":", 1)[1]

    def decided(card):
        with SessionLocal() as db:
            row = db.get(AgentConsent, uuid.UUID(card["id"]))
            return row.status, row.decided_at

    card, ops, token = make()
    assert decided(card) == ("proposed", None)
    consents.execute(OWNER, conv, token, ops, lambda operation, key: {"ok": True})
    status, when = decided(card)
    assert status == "complete" and when is not None

    card, ops, token = make()
    consents.cancel(OWNER, conv, card["id"])               # a press on 取消, and on 换个操作, both go through cancel
    status, when = decided(card)
    assert status == "cancelled" and when is not None

    card, ops, token = make(now=NOW - timedelta(hours=1))   # minted an hour ago: its ten minutes are over
    with pytest.raises(consents.ConsentError, match="confirmation_expired"):
        consents.execute(OWNER, conv, token, ops, lambda operation, key: {"ok": True})
    status, when = decided(card)
    assert status == "proposed" and when is not None and when >= NOW


def test_ensure_columns_adds_decided_at_to_an_old_table():
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE agent_consents DROP COLUMN decided_at"))
    consent.ensure_columns()
    consent.ensure_columns()                                # twice is fine
    with engine.connect() as connection:
        found = connection.execute(text("select 1 from information_schema.columns where table_name='agent_consents' "
                                        "and column_name='decided_at'")).scalar()
    assert found == 1


# --- deliveries ------------------------------------------------------------------------------------------------------

def test_deliveries_list_and_paging(client):
    b = bot()
    with SessionLocal() as db:
        for index in range(5):
            db.add(AgentTelegramMessage(owner_hash=OWNER_HASH, bot_id=b, source="notify", text=f"消息{index}", status="sent",
                                        channel="telegram", created_at=NOW - timedelta(minutes=index)))
        db.add(AgentTelegramMessage(owner_hash=OWNER_HASH, bot_id=b, source="reply", text="回复不算", status="sent",
                                    channel="telegram", created_at=NOW))
        db.add(AgentTelegramMessage(owner_hash=owner_hash(GUEST), bot_id=b, source="notify", text="别人的", status="sent",
                                    channel="telegram", created_at=NOW))
        db.commit()
    first = get(client, "/backstage/deliveries", limit=2).json()
    assert [i["text"] for i in first["items"]] == ["消息0", "消息1"] and first["next_before"]
    assert set(first["items"][0]) >= {"id", "group_id", "bot_id", "source", "channel", "status", "failure", "created_at", "sent_at",
                                      "acked_at", "text"}
    second = get(client, "/backstage/deliveries", limit=2, before=first["next_before"]).json()
    third = get(client, "/backstage/deliveries", limit=2, before=second["next_before"]).json()
    texts = [i["text"] for page in (first, second, third) for i in page["items"]]
    assert texts == [f"消息{i}" for i in range(5)] and third["next_before"] is None
    assert channels.deliveries(OWNER_HASH, 50)[0]["text"] == "消息0"        # the list the settings page uses is unchanged


def test_nothing_under_backstage_writes_but_the_feedback(client):
    from app.main import app
    for route in app.routes:
        if getattr(route, "path", "").startswith("/backstage"):
            if route.path == "/backstage/feedback":
                assert route.methods == {"POST"}, route.path       # 5c-3b: 「有用／没用」, the one write
            else:
                assert route.methods <= {"GET", "HEAD"}, route.path


# --- 5c-3b: 「有用／没用」 on duty and brief messages ------------------------------------------------------------------

def outbox_row(source, text="【助理】\n消息", *, group=None, owner=OWNER_HASH, at=None):
    with SessionLocal() as db:
        row = AgentTelegramMessage(owner_hash=owner, source=source, text=text, status="sent", channel="telegram", group_id=group,
                                   created_at=at or NOW)
        db.add(row)
        db.commit()
        return row.id


def post_feedback(client, body, headers=H):
    return client.post("/backstage/feedback", headers=headers, json=body)


def stored_feedback():
    with SessionLocal() as db:
        return [(row.target, row.target_id, row.verdict, row.channel, row.kind) for row in db.query(AlertFeedback).order_by(AlertFeedback.id)]


@pytest.mark.parametrize("verdict", ["useful", "not_useful"])
def test_feedback_on_a_duty_group_is_recorded_from_the_web(client, verdict):
    group = uuid.uuid4()
    outbox_row("duty", "【助理】\nNVDA 今天跌了 6%。", group=group)
    outbox_row("duty", "NVDA 今天跌了 6%。", group=group)                  # the same message on a second channel: one group
    with SessionLocal() as db:
        db.add(DutyLog(owner_hash=OWNER_HASH, alert_id=31, event={"symbol": "NVDA"}, mode="on", outcome="decided", decision="tell_now",
                       message="NVDA 今天跌了 6%。", delivery="queued", delivery_group=group))
        db.commit()
    response = post_feedback(client, {"target": "outbox", "target_id": str(group), "verdict": verdict})
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert (body["target"], body["target_id"], body["verdict"], body["channel"]) == ("outbox", str(group), verdict, "web")
    assert (body["symbol"], body["kind"], body["text"]) == ("NVDA", "duty", "NVDA 今天跌了 6%。")
    assert stored_feedback() == [("outbox", str(group), verdict, "web", "duty")]


def test_feedback_on_a_brief_without_a_group_uses_its_own_id_and_the_last_press_wins(client):
    row_id = str(outbox_row("brief", "【助理】\n早上好。"))
    assert post_feedback(client, {"target": "outbox", "target_id": row_id, "verdict": "useful"}).json()["kind"] == "brief"
    assert post_feedback(client, {"target": "outbox", "target_id": row_id, "verdict": "not_useful"}).json()["verdict"] == "not_useful"
    assert stored_feedback() == [("outbox", row_id, "not_useful", "web", "brief")]


@pytest.mark.parametrize("body", [
    {"target": "outbox", "target_id": "not-a-uuid", "verdict": "useful"},
    {"target": "outbox", "target_id": "GROUP", "verdict": "useful"},                                 # replaced by an uppercase uuid below
    {"target": "outbox", "target_id": 7, "verdict": "useful"},
    {"target": "outbox", "target_id": None, "verdict": "useful"},
    {"target": "sentinel", "target_id": "7", "verdict": "useful"},
    {"target": "other", "target_id": "GOOD", "verdict": "useful"},
    {"target": "outbox", "target_id": "GOOD", "verdict": "great"},
    {"target": "outbox", "target_id": "GOOD", "verdict": None},
    {"target": "outbox", "target_id": "GOOD"},
    {"target": "outbox", "target_id": "GOOD", "verdict": "useful", "extra": 1},
    {}, [], "useful", None,
])
def test_every_other_body_is_400_and_records_nothing(client, body):
    group = uuid.uuid4()
    outbox_row("duty", group=group)
    if isinstance(body, dict):
        body = {key: str(group) if value == "GOOD" else str(group).upper() if value == "GROUP" else value for key, value in body.items()}
    response = post_feedback(client, body)
    assert response.status_code == 400 and response.json() == {"detail": "invalid_feedback"}
    assert stored_feedback() == []


def test_a_body_that_is_not_json_is_400(client):
    response = client.post("/backstage/feedback", headers={**H, "Content-Type": "application/json"}, content=b"{not json")
    assert response.status_code == 400 and response.json() == {"detail": "invalid_feedback"}


def test_feedback_on_a_message_that_is_not_his_duty_or_brief_is_404(client):
    notify_group, other_group = uuid.uuid4(), uuid.uuid4()
    outbox_row("notify", group=notify_group)
    outbox_row("duty", group=other_group, owner=owner_hash(GUEST))
    for target_id in (notify_group, other_group, uuid.uuid4()):
        response = post_feedback(client, {"target": "outbox", "target_id": str(target_id), "verdict": "useful"})
        assert response.status_code == 404, target_id
    assert stored_feedback() == []


def test_feedback_is_the_owners_alone(client):
    group = uuid.uuid4()
    outbox_row("duty", group=group)
    for headers in (G, {}, {"X-Chat-Session": ""}, {"X-Chat-Session": OWNER + "x"}):
        response = post_feedback(client, {"target": "outbox", "target_id": str(group), "verdict": "useful"}, headers=headers)
        assert response.status_code == 403 and response.json() == {"detail": "owner_only"}, headers
    assert post_feedback(client, [], headers=G).status_code == 403          # refused before the body is read
    assert stored_feedback() == []


def test_deliveries_carry_the_group_and_the_feedback_of_duty_and_brief_rows(client):
    group = uuid.uuid4()
    duty_id = outbox_row("duty", group=group, at=NOW)
    brief_id = outbox_row("brief", at=NOW - timedelta(minutes=1))
    notify_id = outbox_row("notify", group=uuid.uuid4(), at=NOW - timedelta(minutes=2))
    assert post_feedback(client, {"target": "outbox", "target_id": str(group), "verdict": "not_useful"}).status_code == 200
    items = {item["id"]: item for item in get(client, "/backstage/deliveries").json()["items"]}
    assert (items[str(duty_id)]["group_id"], items[str(duty_id)]["feedback"]) == (str(group), "not_useful")
    assert (items[str(brief_id)]["group_id"], items[str(brief_id)]["feedback"]) == (str(brief_id), None)
    assert items[str(notify_id)]["feedback"] is None and items[str(notify_id)]["group_id"] != str(notify_id)


def test_a_pressed_button_is_shown_as_what_it_was_not_as_its_value(client):
    cid = conversation(bot())
    turn(cid, CONFIRM, "已执行", record=None, steps=False, at=NOW - timedelta(minutes=1))
    turn(cid, "reply:好的，就这样", "收到", record=None, steps=False)
    items = get(client, "/backstage/answers").json()["items"]
    assert [i["question"] for i in items] == ["好的，就这样", "（卡片按钮）"]


# --- fix round 1 -----------------------------------------------------------------------------------------------------

def tool_round_row(cid, turn_id, sequence, at=None):
    with SessionLocal() as db:
        db.add(AgentMessage(conversation_id=cid, turn_id=turn_id, sequence=sequence, role="assistant", content="",
                            tool_calls={"calls": [{"id": "call-9", "type": "function",
                                                   "function": {"name": "query_financials", "arguments": "{\"symbol\": \"TSLA\"}"}}]},
                            created_at=at or NOW))
        db.commit()


def test_a_crashed_turn_is_one_incomplete_item_and_never_an_answer(client):
    b = bot()
    cid = conversation(b)
    base = NOW - timedelta(hours=1)
    turn(cid, "normal", "fine", record=kernel_record(), at=base)
    crashed, question_id = turn(cid, "crashed after a tool round", "", record=None, final=False, at=base + timedelta(minutes=1))
    with SessionLocal() as db:
        top = db.execute(text("select max(sequence) from agent_messages where conversation_id=:c"), {"c": cid}).scalar()
    tool_round_row(cid, crashed, top + 1, at=base + timedelta(minutes=1))
    nothing, nothing_id = turn(cid, "never answered", "", record=None, steps=False, final=False, at=base + timedelta(minutes=2))
    items = get(client, "/backstage/answers").json()["items"]
    assert [i["question"] for i in items] == ["never answered", "crashed after a tool round", "normal"]     # one item per turn
    lost, died, fine = items
    assert (lost["status"], died["status"], fine["status"]) == ("incomplete", "incomplete", "succeeded")
    assert lost["message_id"] == str(nothing_id) and died["message_id"] == str(
        db_first_assistant_or_user(crashed, question_id))
    assert died["answer"] == "" and died["engine"] is None and died["tier"] is None
    assert [i["question"] for i in get(client, "/backstage/answers", status="incomplete").json()["items"]] == [
        "never answered", "crashed after a tool round"]
    assert [i["question"] for i in get(client, "/backstage/answers", status="succeeded").json()["items"]] == ["normal"]
    assert get(client, "/backstage/answers", status="failed").json()["items"] == []
    assert [i["question"] for i in get(client, "/backstage/answers", engine="v1").json()["items"]] == []
    detail = get(client, f"/backstage/answers/{died['message_id']}").json()
    assert detail["status"] == "incomplete" and detail["partial"] is True and detail["answer"] == ""
    assert detail["question"] == "crashed after a tool round" and {c["call_id"]: c["status"] for c in detail["tool_calls"]} == {"call-1": "complete", "call-9": "unfinished"}
    assert get(client, f"/backstage/answers/{lost['message_id']}").json()["status"] == "incomplete"


def db_first_assistant_or_user(turn_id, question_id):
    return question_id           # a turn with no final row is listed by its question's id


def test_a_kernel_turn_with_a_card_is_one_waiting_item(client):
    request_id, record = card_record()
    cid = conversation(bot())
    _, mid = turn(cid, record=record, answer="请确认这张卡。")
    items = get(client, "/backstage/answers").json()["items"]
    assert len(items) == 1 and items[0]["message_id"] == str(mid)
    assert items[0]["status"] == "waiting_for_input" and items[0]["write_outcomes"] == ["proposed"]
    assert get(client, "/backstage/answers", status="incomplete").json()["items"] == []


def test_a_nul_character_in_a_stored_record_does_not_break_the_filters(client):
    cid = conversation(bot())
    _, mid = turn(cid, "has nul", "answer", record=kernel_record(), at=NOW)
    turn(cid, "other", "answer", record=kernel_record(), at=NOW - timedelta(minutes=1))
    with SessionLocal() as db:
        db.execute(text("update agent_messages set tool_calls = cast(:v as json) where id = :i"),
                   {"v": '{"route": "K", "audit": {"terminal_status": "succeeded"}, "narration": ["a\\u0000b"]}', "i": mid})
        db.commit()
    for params in ({"engine": "v2"}, {"status": "succeeded"}, {"tier": "low"}, {"status": "incomplete"}):
        assert get(client, "/backstage/answers", **params).status_code == 200, params
    assert len(get(client, "/backstage/answers", engine="v2").json()["items"]) == 2


def test_q_is_capped_and_wildcards_are_literal(client):
    cid = conversation(bot())
    turn(cid, "plain a_b", "x", record=None, steps=False, at=NOW)
    turn(cid, "plain axb", "x", record=None, steps=False, at=NOW - timedelta(minutes=1))
    assert [i["question"] for i in get(client, "/backstage/answers", q="a_b").json()["items"]] == ["plain a_b"]
    assert get(client, "/backstage/answers", q="x" * 101).status_code == 422
    assert get(client, "/backstage/answers", q="x" * 100).status_code == 200


def test_the_list_cost_counts_only_chat_rows_against_the_audit(client):
    cid = conversation(bot())
    tid, _ = turn(cid, record=kernel_record())            # the audit says two chat calls
    ledger(tid, cid, cost=0.01)
    ledger(tid, cid, cost=0.01, purpose="judge")         # a judge row landed, the second chat row has not
    model_usage.flush()
    assert get(client, "/backstage/answers").json()["items"][0]["cost_usd"] is None
    ledger(tid, cid, cost=0.01)
    model_usage.flush()
    assert get(client, "/backstage/answers").json()["items"][0]["cost_usd"] == pytest.approx(0.03)


def test_usage_dates_out_of_bounds_are_422_not_500(client):
    for params in ({"to": "9999-12-31"}, {"from": "0001-01-01"}, {"from": "1999-01-01", "to": "1999-01-02"}):
        assert get(client, "/backstage/usage", **params).status_code == 422, params


def test_usage_says_which_price_is_missing(client, monkeypatch):
    from app import agent_model_catalog as catalog
    monkeypatch.setattr(catalog, "entries", lambda: ([{"name": "cat-a", "price_input": 1.0, "price_output": 2.0, "price_cache_read": None,
                                                        "price_cache_write": None}], None))
    cid = conversation(bot())
    ledger(uuid.uuid4(), cid, catalog="cat-a", cost=None, at=day(2026, 11, 1))        # has cache tokens, no cache-read price
    ledger(uuid.uuid4(), cid, catalog="cat-b", cost=None, at=day(2026, 11, 1))        # no entry at all
    model_usage.flush()
    body = get(client, "/backstage/usage", **{"from": "2026-11-01", "to": "2026-11-01", "group": "model"}).json()
    by_key = {g["key"]: g for g in body["groups"]}
    assert by_key["cat-a"]["missing_prices"] == ["cache_read", "cache_write"]
    assert by_key["cat-b"]["missing_prices"] == ["cache_read", "cache_write", "input", "output"]
    assert body["totals"]["missing_prices"] == ["cache_read", "cache_write", "input", "output"] and body["totals"]["cost_usd"] is None


def test_every_backstage_response_is_no_store(client):
    for headers in (H, G):
        for path in ENDPOINTS:
            assert client.get(path, headers=headers).headers.get("cache-control") == "no-store", (path, headers)
    assert client.get("/backstage/usage?group=weird", headers=H).headers.get("cache-control") == "no-store"
    assert client.get("/backstage/answers?limit=0", headers=H).headers.get("cache-control") == "no-store"       # 422


def test_the_legacy_access_key_header_is_not_the_owner(client):
    for path in ENDPOINTS:
        assert client.get(path, headers={"X-App-Access-Key": OWNER}).status_code == 403


# --- fix round 1: true time order, and the state of a turn's cost ----------------------------------------------------
def with_timeline(entries, **extra):
    record = kernel_record(**extra)
    record["audit"]["timeline"] = entries
    return record


TIMELINE = [{"kind": "call", "at_ms": 300, "step": 1, "index": 0}, {"kind": "say", "at_ms": 310, "step": 1, "index": 0},
            {"kind": "tool", "at_ms": 320, "step": 1, "call_id": "call-1", "name": "query_financials"},
            {"kind": "tool_done", "at_ms": 900, "step": 1, "call_id": "call-1"}, {"kind": "call", "at_ms": 1700, "step": 2, "index": 1}]


def test_the_detail_interleaves_its_events_by_the_timeline(client):
    cid = conversation(bot())
    tid, mid = turn(cid, record=with_timeline(TIMELINE))
    ledger(tid, cid, ms=900, at=NOW)
    ledger(tid, cid, ms=700, at=NOW + timedelta(seconds=1))
    model_usage.flush()
    body = get(client, f"/backstage/answers/{mid}").json()
    assert body["ordered"] is True
    assert [(e["kind"], e.get("index"), e.get("call_id"), e["at_ms"], e["step"]) for e in body["events"]] == [
        ("model_call", 0, None, 300, 1), ("narration", 0, None, 310, 1), ("tool_call", None, "call-1", 320, 1),
        ("tool_done", None, "call-1", 900, 1), ("model_call", 1, None, 1700, 2)]
    assert len(body["model_calls"]) == 2 and len(body["narration"]) == 1 and body["tool_calls"][0]["call_id"] == "call-1"


def test_a_failed_attempt_sits_before_the_call_that_followed_it_and_a_judge_row_goes_last(client):
    cid = conversation(bot())
    tid, mid = turn(cid, record=with_timeline(TIMELINE))
    ledger(tid, cid, ok=False, error="http_500", at=NOW)
    ledger(tid, cid, at=NOW + timedelta(seconds=1))
    ledger(tid, cid, at=NOW + timedelta(seconds=2))
    ledger(tid, cid, purpose="judge", model="j-1", catalog="judge-1", at=NOW + timedelta(seconds=3))
    model_usage.flush()
    body = get(client, f"/backstage/answers/{mid}").json()
    refs = [e["index"] for e in body["events"] if e["kind"] == "model_call"]
    assert [body["model_calls"][i]["purpose"] for i in refs] == ["chat", "chat", "chat", "judge"]
    assert [body["model_calls"][i]["ok"] for i in refs][:2] == [False, True]
    timed = [e["at_ms"] for e in body["events"] if e["at_ms"] is not None]
    assert timed == sorted(timed) and sorted(refs) == list(range(4))
    assert body["events"][0]["kind"] == "model_call" and body["events"][0]["at_ms"] is None      # the failed attempt has no time of its own


def test_an_old_record_has_no_time_order_and_keeps_the_kind_order(client):
    cid = conversation(bot())
    tid, mid = turn(cid, record=kernel_record())
    ledger(tid, cid)
    ledger(tid, cid)
    model_usage.flush()
    body = get(client, f"/backstage/answers/{mid}").json()
    assert body["ordered"] is False
    assert [e["kind"] for e in body["events"]] == ["narration", "model_call", "model_call", "tool_call"]
    assert all(e["at_ms"] is None for e in body["events"])
    old = get(client, f"/backstage/answers/{turn(cid, record=None, steps=False)[1]}").json()
    assert old["ordered"] is False and old["events"] == []


def test_a_damaged_timeline_is_ignored_not_trusted(client):
    cid = conversation(bot())
    entries = ["x", None, {"kind": "tool", "at_ms": "soon"}, {"kind": "say", "at_ms": 5, "index": 99}, {"kind": "tool", "at_ms": 7, "call_id": "nope"}]
    tid, mid = turn(cid, record=with_timeline(entries))
    body = get(client, f"/backstage/answers/{mid}").json()
    assert body["ordered"] is False and len(body["events"]) >= 1


def test_cost_state_priced_unpriced_pending_none(client, monkeypatch):
    from app import agent_model_catalog as catalog
    monkeypatch.setattr(catalog, "entries", lambda: ([{"name": "cat-1", "price_input": 1.0, "price_output": 2.0, "price_cache_read": None,
                                                        "price_cache_write": None}], None))
    cid = conversation(bot())
    old = NOW - timedelta(minutes=30)
    priced, priced_msg = turn(cid, record=kernel_record(), at=old)
    ledger(priced, cid, cost=0.01, at=old)
    ledger(priced, cid, cost=0.02, at=old)
    unpriced, unpriced_msg = turn(cid, record=kernel_record(), at=old + timedelta(minutes=1))
    ledger(unpriced, cid, cost=0.01, at=old)
    ledger(unpriced, cid, cost=None, at=old)
    pending, pending_msg = turn(cid, record=kernel_record(), at=NOW)
    ledger(pending, cid, cost=0.01, at=NOW)            # the audit says two calls; one row has landed and the turn just ended
    stale, stale_msg = turn(cid, record=kernel_record(), at=old + timedelta(minutes=2))
    ledger(stale, cid, cost=0.01, at=old)              # one row short, but two minutes have long passed: not "pending" any more
    none, none_msg = turn(cid, record={"route": "K", "audit": {"engine": "v2", "model_calls": 0, "calls": []}}, at=old + timedelta(minutes=3), steps=False)
    model_usage.flush()
    items = {item["message_id"]: item for item in get(client, "/backstage/answers").json()["items"]}
    states = {name: (items[str(mid)]["cost_state"], items[str(mid)]["missing_prices"]) for name, mid in
              (("priced", priced_msg), ("unpriced", unpriced_msg), ("pending", pending_msg), ("stale", stale_msg), ("none", none_msg))}
    assert states["priced"] == ("priced", [])
    assert states["unpriced"] == ("unpriced", ["cache_read", "cache_write"])
    assert states["pending"][0] == "pending"
    assert states["stale"] == ("unrecorded", [])       # rows are short for good: nothing says a price was missing
    assert states["none"] == ("none", [])
    assert items[str(pending_msg)]["cost_usd"] is None
    for name, mid in (("priced", priced_msg), ("unpriced", unpriced_msg), ("pending", pending_msg), ("none", none_msg)):
        detail = get(client, f"/backstage/answers/{mid}").json()
        assert (detail["cost_state"], detail["missing_prices"]) == states[name], name


def test_a_turn_with_no_ledger_and_an_audit_is_pending_while_fresh_and_unrecorded_once_old(client):
    cid = conversation(bot())
    turn(cid, record=kernel_record(), at=NOW)
    turn(cid, record=kernel_record(), at=NOW - timedelta(hours=2))
    items = get(client, "/backstage/answers").json()["items"]
    assert [i["cost_state"] for i in items] == ["pending", "unrecorded"]


def test_unrecorded_is_not_unpriced_and_its_detail_lines_say_so(client):
    cid = conversation(bot())
    old = NOW - timedelta(hours=3)
    tid, mid = turn(cid, record=kernel_record(), at=old)           # from before the ledger: the audit counted two calls, no row exists
    body = get(client, f"/backstage/answers/{mid}").json()
    assert (body["cost_state"], body["missing_prices"], body["model_calls_source"]) == ("unrecorded", [], "audit")
    assert [c["recorded"] for c in body["model_calls"]] == [False, False]
    tid2, mid2 = turn(cid, record=kernel_record(), at=old + timedelta(minutes=1))
    ledger(tid2, cid, cost=None, at=old)
    ledger(tid2, cid, cost=0.01, at=old)
    model_usage.flush()
    full = get(client, f"/backstage/answers/{mid2}").json()
    assert full["cost_state"] == "unpriced" and [c["recorded"] for c in full["model_calls"]] == [True, True]


def test_an_incomplete_turn_is_pending_while_fresh(client):
    cid = conversation(bot())
    tid, mid = turn(cid, final=False, steps=True, at=NOW)
    ledger(tid, cid, cost=0.01, at=NOW)
    model_usage.flush()
    item = get(client, "/backstage/answers").json()["items"][0]
    assert item["status"] == "incomplete" and item["cost_state"] == "pending"
    assert get(client, f"/backstage/answers/{mid}").json()["cost_state"] == "pending"
    old_tid, old_mid = turn(cid, final=False, steps=True, at=NOW - timedelta(hours=1))
    ledger(old_tid, cid, cost=0.01, at=NOW - timedelta(hours=1))
    model_usage.flush()
    older = [i for i in get(client, "/backstage/answers").json()["items"] if i["message_id"] == str(old_mid)][0]
    assert older["cost_state"] == "priced"


@pytest.mark.parametrize("entry", [
    {"kind": "call", "at_ms": 1, "step": 1, "index": [0]}, {"kind": "call", "at_ms": 1, "step": 1, "index": {"a": 1}},
    {"kind": "say", "at_ms": 1, "index": [0]}, {"kind": "say", "at_ms": 1, "index": True},
    {"kind": "tool", "at_ms": 1, "call_id": ["call-1"]}, {"kind": "tool_done", "at_ms": 1, "call_id": {"x": 1}},
    {"kind": ["tool"], "at_ms": 1, "call_id": "call-1"}, {"kind": "tool", "at_ms": [1], "call_id": "call-1"},
    {"kind": "tool", "at_ms": 1, "step": "x", "call_id": "call-1"}, {"kind": "tool", "at_ms": -5, "call_id": "call-1"}, 7, "x", None, [1]])
def test_a_damaged_timeline_entry_is_skipped_never_a_500(client, entry):
    cid = conversation(bot())
    tid, mid = turn(cid, record=with_timeline([entry, *TIMELINE]))
    ledger(tid, cid)
    ledger(tid, cid)
    model_usage.flush()
    response = get(client, f"/backstage/answers/{mid}")
    assert response.status_code == 200
    body = response.json()
    assert body["ordered"] is True and sum(1 for e in body["events"] if e["kind"] == "model_call") == 2


# --- duty ----------------------------------------------------------------------------------------------------------

def question_id(turn_id):
    with SessionLocal() as db:
        return db.scalar(select(AgentMessage.id).where(AgentMessage.turn_id == turn_id, AgentMessage.role == "user"))


def duty_row(alert_id, *, owner=OWNER_HASH, at=None, text="NVDA 单日下跌 6%\n第二行细节", outcome="decided", decision="record", turn_id=None, **fields):
    with SessionLocal() as db:
        db.add(DutyLog(owner_hash=owner, alert_id=alert_id, created_at=at or NOW, event={"alert_id": alert_id, "symbol": "NVDA", "kind": "drop", "text": text},
                       mode=fields.pop("mode", "shadow"), outcome=outcome, decision=decision, turn_id=turn_id, **fields))
        db.commit()


def test_duty_list_item_the_mode_and_the_turn_that_opens_the_drawer(client, monkeypatch):
    monkeypatch.setenv("FINBOT_DUTY_MODE", "on")
    cid = conversation(bot())
    tid, mid = turn(cid, question="盯盘提醒 #7")
    duty_row(7, decision="tell_now", reason="跌幅大", message="NVDA 大跌，注意", delivery="queued", turn_id=tid, mode="on", ms=1200, model_calls=2)
    duty_row(8, owner=owner_hash(GUEST))
    body = get(client, "/backstage/duty").json()
    assert body["mode"] == "on" and body["next_before"] is None and len(body["items"]) == 1
    item = body["items"][0]
    assert (item["symbol"], item["kind"], item["what"]) == ("NVDA", "drop", "NVDA 单日下跌 6%")
    assert (item["decision"], item["outcome"], item["mode"], item["delivery"]) == ("tell_now", "decided", "on", "queued")
    assert (item["reason"], item["message"], item["ms"], item["model_calls"], item["alert_id"]) == ("跌幅大", "NVDA 大跌，注意", 1200, 2, 7)
    assert item["turn_id"] == str(tid) and item["message_id"] == str(question_id(tid))
    monkeypatch.setenv("FINBOT_DUTY_MODE", "junk")
    assert get(client, "/backstage/duty").json()["mode"] == "shadow"


def test_duty_row_without_a_turn_has_nothing_to_open(client):
    duty_row(1, outcome="dropped", decision=None)
    item = get(client, "/backstage/duty").json()["items"][0]
    assert item["turn_id"] is None and item["message_id"] is None and item["decision"] is None


def test_duty_filters_paging_and_validation(client):
    for index in range(5):
        duty_row(index, at=NOW - timedelta(minutes=index), decision="digest" if index % 2 else "ignore")
    duty_row(9, at=NOW - timedelta(minutes=9), outcome="failed", decision=None)
    first = get(client, "/backstage/duty", limit=2).json()
    second = get(client, "/backstage/duty", limit=2, before=first["next_before"]).json()
    third = get(client, "/backstage/duty", limit=2, before=second["next_before"]).json()
    assert [i["alert_id"] for page in (first, second, third) for i in page["items"]] == [0, 1, 2, 3, 4, 9] and third["next_before"] is None
    assert [i["alert_id"] for i in get(client, "/backstage/duty", decision="digest").json()["items"]] == [1, 3]
    assert [i["alert_id"] for i in get(client, "/backstage/duty", outcome="failed").json()["items"]] == [9]
    for bad in ({"decision": "sell"}, {"outcome": "x"}):
        response = get(client, "/backstage/duty", **bad)
        assert response.status_code == 400 and response.json() == {"detail": "invalid_filter"}
    assert get(client, "/backstage/duty", before="nonsense").status_code == 400
    assert get(client, "/backstage/duty", limit=0).status_code == 422
    assert get(client, "/backstage/duty").headers["cache-control"] == "no-store"


def test_duty_shows_no_card_button_value(client):
    duty_row(1, text="alert " + CONFIRM, decision="tell_now", message="按 " + AUTHORIZE, reason=REPLY)
    assert not any(value in get(client, "/backstage/duty").text for value in BUTTONS[:2] + (REPLY,))


def test_the_detail_names_the_companies_the_system_brought_and_skips_its_timeline_entry(client):
    cid = conversation(bot())
    entries = [*TIMELINE, {"kind": "latest_known", "at_ms": 5, "step": 0, "symbols": ["NVDA", "AMD"]}]
    record = with_timeline(entries)
    record["audit"]["latest_known"] = ["NVDA", "AMD", 7, "x\x00y"]
    tid, mid = turn(cid, record=record)
    ledger(tid, cid, ms=900, at=NOW)
    ledger(tid, cid, ms=700, at=NOW + timedelta(seconds=1))
    model_usage.flush()
    body = get(client, f"/backstage/answers/{mid}").json()
    assert body["latest_known"] == ["NVDA", "AMD", "x\x00y"]     # the non-string entry is dropped
    assert all(isinstance(s, str) for s in body["latest_known"])
    assert body["ordered"] is True and all(e["kind"] != "latest_known" for e in body["events"])
    plain = turn(cid, record=kernel_record())[1]
    assert get(client, f"/backstage/answers/{plain}").json()["latest_known"] == []


# --- memory changes (5d-2) -------------------------------------------------------------------------------------------

MEMORY_KEYS = {"id", "at", "target", "action", "by", "text", "before", "reason", "bot", "bot_deleted", "symbol", "company", "reconstructed", "quote", "examples",
               "conversation_id", "message_id", "run", "template", "from_bot", "to_bot"}


def memory_event(*, owner=OWNER_HASH, item_id=None, target="profile", action="added", by="chat", **fields):
    with SessionLocal() as db:
        row = memory_events.log(db, owner, target=target, item_id=item_id or uuid.uuid4(), action=action, by=by, **fields)
        db.commit()
        return row.id


def test_memory_changes_list_item_for_an_edit_said_in_a_bots_conversation(client):
    b = bot("研究员")
    cid = conversation(b)
    memory_event(action="edited", by=memory_events.chat(cid, None, None), text="金额用亿美元", before="金额用万元", bot_id=b, at=NOW)
    body = get(client, "/backstage/memory").json()
    assert body["next_before"] is None
    [row] = body["items"]
    assert set(row) == MEMORY_KEYS
    assert (row["target"], row["action"], row["by"], row["text"], row["before"], row["bot"]) == ("profile", "edited", "chat", "金额用亿美元", "金额用万元", "研究员")
    assert (row["conversation_id"], row["reconstructed"], row["quote"], row["examples"], row["symbol"], row["company"]) == (str(cid), False, None, [], None, None)
    assert datetime.fromisoformat(row["at"]) == NOW
    assert get(client, "/backstage/memory").headers["cache-control"] == "no-store"


def test_memory_changes_a_view_names_its_company_a_move_names_both_layers_and_a_review_its_examples(client):
    b = bot("研究员")
    memory_event(target="view", action="recorded", by="page", text="估值太高了", symbol="NVDA", basis={"quote": "估值太高了，我觉得"}, at=NOW)
    memory_event(action="moved", by="page", text="先说结论", bot_id=b, basis={"from_bot": None, "to_bot": b}, at=NOW - timedelta(minutes=1))
    examples = [{"quote": "我先看现金流", "message_id": str(uuid.uuid4()), "date": "2026-11-01"}]
    run = uuid.uuid4()
    memory_event(action="proposed", by=memory_events.review(run), text="先看现金流", basis={"examples": examples}, at=NOW - timedelta(minutes=2),
                 reconstructed=True)
    view, moved, proposed = get(client, "/backstage/memory").json()["items"]
    assert (view["target"], view["symbol"], view["company"], view["quote"]) == ("view", "NVDA", owner_views.display_name("NVDA"), "估值太高了，我觉得")
    assert (moved["from_bot"], moved["to_bot"], moved["bot"]) == ({"id": None, "name": None}, {"id": str(b), "name": "研究员"}, "研究员")
    assert view["from_bot"] is None and view["to_bot"] is None
    assert (proposed["by"], proposed["run"], proposed["examples"], proposed["reconstructed"]) == ("review", str(run), examples, True)


def test_memory_changes_filters_search_and_paging(client):
    for minute in range(5):
        memory_event(action="added", by="page", text=f"第{minute}条", at=NOW - timedelta(minutes=minute))
    memory_event(target="view", action="superseded", by="chat", text="旧看法", symbol="NVDA", at=NOW - timedelta(minutes=10))
    memory_event(action="archived", by="settle", text="老习惯", reason="很久没在你的话里出现", at=NOW - timedelta(minutes=11))
    first = get(client, "/backstage/memory", limit=3).json()
    second = get(client, "/backstage/memory", limit=3, before=first["next_before"]).json()
    third = get(client, "/backstage/memory", limit=3, before=second["next_before"]).json()
    texts = [i["text"] for page in (first, second, third) for i in page["items"]]
    assert texts == ["第0条", "第1条", "第2条", "第3条", "第4条", "旧看法", "老习惯"] and third["next_before"] is None
    assert [i["text"] for i in get(client, "/backstage/memory", target="view").json()["items"]] == ["旧看法"]
    assert [i["text"] for i in get(client, "/backstage/memory", action="superseded,archived").json()["items"]] == ["旧看法", "老习惯"]
    assert [i["text"] for i in get(client, "/backstage/memory", by="settle").json()["items"]] == ["老习惯"]
    assert [i["text"] for i in get(client, "/backstage/memory", q="很久没").json()["items"]] == ["老习惯"], "the reason is searched"
    assert [i["text"] for i in get(client, "/backstage/memory", q="第3").json()["items"]] == ["第3条"]
    assert get(client, "/backstage/memory", q="%").json()["items"] == []


@pytest.mark.parametrize("bad", [{"target": "x"}, {"target": ""}, {"action": "x"}, {"action": ""}, {"action": "added,x"}, {"by": "x"}])
def test_memory_changes_refuse_a_filter_that_is_no_value(client, bad):
    response = get(client, "/backstage/memory", **bad)
    assert response.status_code == 400 and response.json() == {"detail": "invalid_filter"}


def test_memory_changes_cursor_and_limit_validation(client):
    assert get(client, "/backstage/memory", before="nonsense").status_code == 400
    assert get(client, "/backstage/memory", limit=0).status_code == 422
    assert get(client, "/backstage/memory", limit=201).status_code == 422
    assert get(client, "/backstage/memory", q="x" * 101).status_code == 422


def test_memory_changes_are_the_owners_alone_and_show_no_card_button_value(client):
    memory_event(owner=owner_hash(GUEST), text="别人的记忆")
    memory_event(text="按 " + CONFIRM, reason=AUTHORIZE)
    response = get(client, "/backstage/memory")
    assert [i["text"] for i in response.json()["items"]] == ["按 [已移除]"]
    assert "别人的记忆" not in response.text and CONFIRM not in response.text and AUTHORIZE not in response.text
    assert get(client, "/backstage/memory", headers=G).status_code == 403


def test_a_memory_page_write_shows_up_in_the_tab_as_the_pages(client):
    response = client.post("/agent-chat/profile", headers=H, json={"kind": "instruction", "text": "先说结论"})
    assert response.status_code == 200, response.text
    item_id = response.json()["item"]["id"]
    assert client.delete(f"/agent-chat/profile/{item_id}", headers=H).status_code == 200
    items = get(client, "/backstage/memory").json()["items"]
    assert [(i["action"], i["by"], i["text"]) for i in items] == [("deleted", "page", None), ("added", "page", None)], "deleted: its words are gone"


def test_memory_changes_find_the_conversation_of_a_change_that_names_only_his_message(client):
    """A change rebuilt from its row knows only his message: the tab still links the conversation, his own and nobody else's."""
    mine, theirs = conversation(), conversation(owner="t" * 64)
    with SessionLocal() as db:
        said = AgentMessage(conversation_id=mine, turn_id=uuid.uuid4(), sequence=1, role="user", content="以后金额用亿美元")
        other = AgentMessage(conversation_id=theirs, turn_id=uuid.uuid4(), sequence=1, role="user", content="别人的话")
        db.add_all([said, other])
        db.commit()
        said_id, other_id = said.id, other.id
    memory_event(by=memory_events.chat(None, None, said_id), text="金额用亿美元", at=NOW, reconstructed=True)
    memory_event(by=memory_events.chat(None, None, other_id), text="别人的", at=NOW - timedelta(minutes=1))
    rows = get(client, "/backstage/memory").json()["items"]
    assert [(r["message_id"], r["conversation_id"]) for r in rows] == [(str(said_id), str(mine)), (str(other_id), None)]


def test_memory_changes_name_a_deleted_bot_as_deleted_not_as_the_global_layer(client):
    gone = uuid.uuid4()
    memory_event(action="archived", text="研究员只看半导体", reason="bot_deleted", bot_id=gone, at=NOW)
    memory_event(text="全局：金额用亿美元", at=NOW - timedelta(minutes=1))
    rows = get(client, "/backstage/memory").json()["items"]
    assert [(r["bot"], r["bot_deleted"], r["reason"]) for r in rows] == [(None, True, "bot_deleted"), (None, False, None)]
