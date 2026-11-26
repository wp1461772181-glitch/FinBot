"""Stage 4a, task 1: the owner's own view of each company (「你的看法」): the table, ``record_view`` / ``drop_view``, the line in the
「系统最新掌握」 block and the owner-only routes.  Disposable Postgres; no network, no model."""
import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app import agent_bots as bots
from app import latest_known as lk
from app import owner_views
from app.agent_chat_models import AgentBot, AgentConversation, AgentMessage, OwnerView, ViewReview
from app.agent_chat_store import owner_hash
from app.agent_tool_catalog import KERNEL_ONLY, OWNER_ONLY, definitions, legacy_definitions, schemas, write_tool_names
from app.agent_workflow import consent
from app.agent_workflow.models import AgentConsent
from app.database import Base, SessionLocal, engine
from app.kernel import act
from app.kernel.operation_registry import KERNEL_ONLY_OPERATIONS, OPERATION_REGISTRY

OWNER = "owner"
OWNER_HASH = owner_hash(OWNER)
OTHER_HASH = owner_hash("somebody-else")
CONVERSATION = "aaaaaaaa-1111-2222-3333-444444444444"
TURN = "bbbbbbbb-1111-2222-3333-444444444444"
FIRST = "我觉得英伟达今年数据中心还会翻倍"
SECOND = "我改主意了，英伟达估值太高"


def run(coro):
    return asyncio.run(coro)


def make_run(question="", credential=OWNER, read_results=0, inbox=None, turn_id=TURN, conversation_id=CONVERSATION):
    context = SimpleNamespace(identity_credential=credential, owner_hash=OWNER_HASH, conversation_id=conversation_id, bot_id=None, bot_name="",
                              tool_scope=None, default_company=None, watchlist=(), executor=None)
    return SimpleNamespace(context=context, user_text="", question=question, turn_id=turn_id, web_rows={}, citations=[], proposals=[],
                           question_card=None, carried_sets=[], writes=[], audit={}, read_results=read_results, inbox=inbox)


def wipe():
    with SessionLocal() as db:
        for model in (ViewReview, OwnerView, AgentConsent, AgentMessage):
            db.query(model).delete()
        db.commit()


@pytest.fixture
def owner(monkeypatch, disposable_database):
    Base.metadata.create_all(engine, tables=[OwnerView.__table__, ViewReview.__table__, AgentConsent.__table__, AgentBot.__table__, AgentConversation.__table__,
                                             AgentMessage.__table__])
    wipe()
    import app.agent_chat_identity as identity
    import app.agent_chat_stream as stream
    from app.agent_workflow import direct, tools
    for module in (consent, direct, tools, identity, act, stream):
        monkeypatch.setattr(module, "owner_credential_matches", lambda c: c == OWNER, raising=False)
    yield
    wipe()


def record(question, symbol="英伟达", text=None, quote=None, **kwargs):
    run_ = make_run(question, **kwargs)
    out = run(act.handle(run_, {"operation": "record_view", "arguments": {"symbol": symbol, "text": text or question, "quote": quote or question}}))
    return out, run_


def rows(symbol="NVDA"):
    with SessionLocal() as db:
        found = db.query(OwnerView).filter_by(owner_hash=OWNER_HASH, symbol=symbol).order_by(OwnerView.created_at).all()
        return [(r.text, r.status, r.ended_at is not None) for r in found]


# ---- Review Focus 1: a view, a changed mind, the history --------------------------------------------------------------

def test_a_view_is_recorded_then_superseded_and_both_are_kept(owner, client):
    out, run_ = record(FIRST, text="今年英伟达数据中心还会翻倍")
    assert out["ok"] and run_.writes == [{"operation": "record_view", "tier": 1, "outcome": "done"}]
    first = owner_views.current(OWNER_HASH, ["NVDA"])["NVDA"]
    assert first["quote"] == FIRST and first["status"] == "active" and first["turn_id"] == TURN and first["conversation_id"] == CONVERSATION
    # a week later
    with SessionLocal() as db:
        row = db.get(OwnerView, __import__("uuid").UUID(first["id"]))
        row.created_at = datetime.now(UTC) - timedelta(days=7)
        db.commit()
    out, _ = record(SECOND, text="英伟达估值太高了")
    assert out["ok"]
    assert rows() == [("今年英伟达数据中心还会翻倍", "superseded", True), ("英伟达估值太高了", "active", False)]
    versions = owner_views.history(OWNER_HASH, "NVDA")
    assert [v["text"] for v in versions] == ["英伟达估值太高了", "今年英伟达数据中心还会翻倍"]       # newest first
    assert versions[1]["ended_at"] and versions[1]["status_label"] == "已更新" and versions[0]["ended_at"] is None
    assert owner_views.current(OWNER_HASH, ["NVDA", "AMD"]).keys() == {"NVDA"}
    # the routes (owner only)
    owner_headers, guest = {"X-Chat-Session": OWNER}, {"X-Chat-Session": "g" * 64}
    assert client.get("/agent-chat/views?symbol=NVDA", headers=guest).status_code == 403
    assert client.get("/agent-chat/views/NVDA/history", headers=guest).status_code == 403
    assert client.get("/agent-chat/views?symbol=NVDA", headers=owner_headers).json()["view"]["text"] == "英伟达估值太高了"
    assert client.get("/agent-chat/views", headers=owner_headers).json()["views"][0]["symbol"] == "NVDA"
    listed = client.get("/agent-chat/views/英伟达/history", headers=owner_headers).json()
    assert listed["symbol"] == "NVDA" and [v["status"] for v in listed["versions"]] == ["active", "superseded"]
    assert client.get("/agent-chat/views?symbol=没这家公司", headers=owner_headers).status_code == 422


def test_the_same_view_again_changes_nothing(owner):
    assert record(FIRST, text="数据中心还会翻倍")[0]["ok"]
    assert record(FIRST, text="数据中心还会翻倍")[0]["ok"]
    assert rows() == [("数据中心还会翻倍", "active", False)]


def test_dropping_a_view_keeps_it_marked_withdrawn(owner):
    record(FIRST, text="数据中心还会翻倍")
    out = run(act.handle(make_run("撤回我对英伟达的看法"), {"operation": "drop_view", "arguments": {"symbol": "NVDA"}}))
    assert out["ok"] and out["data"][0]["status"] == "done"
    assert rows() == [("数据中心还会翻倍", "dropped", True)]
    assert owner_views.current(OWNER_HASH, ["NVDA"]) == {} and owner_views.history(OWNER_HASH, "NVDA")[0]["status_label"] == "已撤回"
    nothing = run(act.handle(make_run("撤回"), {"operation": "drop_view", "arguments": {"symbol": "NVDA"}}))
    assert nothing["ok"] is False and nothing["error_code"] == "no_view_to_drop" and nothing["hint"]


def test_what_was_recorded_and_the_one_sentence_that_undoes_it(owner):
    out, _ = record(FIRST, text="数据中心还会翻倍")
    row = out["data"][0]
    assert row["recorded"] == "数据中心还会翻倍" and row["symbol"] == "NVDA" and row["status"] == "done"
    assert row["undo"] == "要撤回，说『撤回我对 英伟达 的看法』。"


def test_the_owner_may_delete_one_version_and_only_his_own(owner, client):
    record(FIRST, text="数据中心还会翻倍")
    mine = owner_views.history(OWNER_HASH, "NVDA")[0]["id"]
    headers = {"X-Chat-Session": OWNER}
    assert client.delete(f"/agent-chat/views/{mine}", headers={"X-Chat-Session": "g" * 64}).status_code == 403
    assert owner_views.delete_version(OTHER_HASH, mine) is False and len(rows()) == 1
    assert client.delete("/agent-chat/views/not-an-id", headers=headers).status_code == 404
    assert client.delete(f"/agent-chat/views/{mine}", headers=headers).json() == {"deleted": True}
    assert rows() == [] and client.delete(f"/agent-chat/views/{mine}", headers=headers).status_code == 404


def test_another_owners_views_are_never_read(owner):
    owner_views.record(OTHER_HASH, "NVDA", "别人的看法", "别人的话")
    assert owner_views.current(OWNER_HASH, ["NVDA"]) == {} and owner_views.history(OWNER_HASH, "NVDA") == []
    assert owner_views.drop(OWNER_HASH, "NVDA") is None


# ---- Review Focus 2: a card after a read, the owner's own words --------------------------------------------------------

def test_after_a_read_the_view_goes_on_a_card_and_is_written_only_on_the_press(owner):
    out, run_ = record(FIRST, text="数据中心还会翻倍", read_results=1)
    assert out["data"][0]["status"] == "awaiting_confirmation" and len(run_.proposals) == 1 and rows() == []
    prepared = run_.proposals[0]
    assert prepared.tier == 1 and prepared.display["targets"][0]["quote"] == FIRST and "不是证据" in prepared.display["alternative"]
    conversation = str(bots.ensure_default_bot(OWNER_HASH).conversation_id)
    card = consent.propose(OWNER, conversation, [prepared.operation], prepared.display)
    context = SimpleNamespace(identity_credential=OWNER, owner_hash=OWNER_HASH, conversation_id=conversation, bot_id=None, executor=None)
    consent.execute(OWNER, conversation, card["choices"][0]["value"].split(":", 1)[1], [prepared.operation], act.execute_handler(context))
    view = owner_views.current(OWNER_HASH, ["NVDA"])["NVDA"]
    assert view["text"] == "数据中心还会翻倍" and view["quote"] == FIRST and view["turn_id"] == TURN and view["conversation_id"] == CONVERSATION


def test_a_quote_that_is_not_in_the_owners_message_is_refused_before_a_card(owner):
    for read in (0, 1):
        out, run_ = record("英伟达怎么样", text="数据中心还会翻倍", quote="英伟达今年数据中心还会翻倍，目标价 200", read_results=read)
        assert out["ok"] is False and out["error_code"] == "view_quote_not_owners" and out["hint"]
        assert run_.proposals == [] and rows() == []


def test_a_trivial_quote_is_refused_even_when_it_is_in_the_message(owner):
    for quote in ("英伟", "英 伟 达", "估值"):
        out, run_ = record("我觉得英伟达估值太高", text="英伟达今年会翻倍，目标价 200", quote=quote)
        assert out["ok"] is False and out["error_code"] == "view_quote_too_short" and out["hint"] == "引用要是用户原话里完整的一句或半句"
        assert run_.proposals == [] and rows() == []
    assert record("我觉得英伟达估值太高", text="估值太高", quote="估值太高")[0]["ok"]
    with pytest.raises(owner_views.ViewError, match="view_quote_too_short"):
        owner_views.record(OWNER_HASH, "NVDA", "x", "估值")
    assert owner_views.QUOTE_MIN_CHARS == 4


def test_a_quote_may_come_from_a_message_he_sent_while_the_turn_ran(owner):
    inbox = SimpleNamespace(messages=[SimpleNamespace(text="对了，我觉得英伟达今年还会翻倍", shown=True),
                                      SimpleNamespace(text="另外我觉得AMD会涨", shown=False)])
    out, _ = record("英伟达怎么样", text="今年还会翻倍", quote="我觉得英伟达今年还会翻倍", inbox=inbox)
    assert out["ok"] and rows() == [("今年还会翻倍", "active", False)]
    out, _ = record("英伟达怎么样", symbol="AMD", text="会涨", quote="我觉得AMD会涨", inbox=inbox)       # not shown to the model yet: not his words of this turn
    assert out["error_code"] == "view_quote_not_owners"


def test_an_earlier_turns_words_are_not_this_turns(owner):
    run_ = make_run("英伟达怎么样")
    run_.user_text = FIRST + "\n英伟达怎么样"            # the run also carries his earlier turns
    out = run(act.handle(run_, {"operation": "record_view", "arguments": {"symbol": "NVDA", "text": "翻倍", "quote": FIRST}}))
    assert out["error_code"] == "view_quote_not_owners"


def test_an_unrecognized_company_is_refused_with_a_hint_and_nothing_runs(owner):
    for operation in ("record_view", "drop_view"):
        arguments = {"symbol": "那家公司", "text": "看好", "quote": "我看好那家公司"} if operation == "record_view" else {"symbol": "那家公司"}
        out = run(act.handle(make_run("我看好那家公司"), {"operation": operation, "arguments": arguments}))
        assert out["ok"] is False and out["error_code"] == "company_not_recognized" and "用代码再说一次" in out["hint"]
    assert rows() == [] and owner_views.history(OWNER_HASH, "那家公司") == []


def test_company_names_and_tickers_resolve_alike(owner):
    assert {owner_views.resolve_symbol(v) for v in ("NVDA", "nvda", "英伟达", "Nvidia", " 英伟达 ")} == {"NVDA"}
    assert owner_views.resolve_symbol("brk-b") == "BRK.B" and owner_views.resolve_symbol("两个 词") is None and owner_views.resolve_symbol("") is None


def test_a_guest_cannot_record_or_drop(owner):
    for operation in ("record_view", "drop_view"):
        out = run(act.handle(make_run(FIRST, credential="g" * 64), {"operation": operation, "arguments": {"symbol": "NVDA", "text": "x", "quote": FIRST}
                                                                    if operation == "record_view" else {"symbol": "NVDA"}}))
        assert out["error_code"] == "owner_login_required"
    assert rows() == []


def test_the_text_and_quote_limits(owner):
    long_text = "很" * 201
    out = run(act.handle(make_run(FIRST), {"operation": "record_view", "arguments": {"symbol": "NVDA", "text": long_text, "quote": FIRST}}))
    assert out["error_code"] == "invalid_arguments"
    out = run(act.handle(make_run(FIRST), {"operation": "record_view", "arguments": {"symbol": "NVDA", "text": "x", "quote": FIRST * 40}}))
    assert out["error_code"] == "invalid_arguments" and rows() == []


# ---- the operation directory and the old engine ------------------------------------------------------------------------

def test_the_directory_lists_both_in_tier_one_with_their_wording():
    assert act.TIER1[-2:] == ("record_view", "drop_view") and act.tier_of("record_view") == act.tier_of("drop_view") == 1
    for name in ("record_view", "drop_view"):
        assert name in act.OPERATIONS and act.SUMMARIES[name] and f"\n{name}：" in act.ACT_SCHEMA["function"]["description"]
        assert definitions()[name].level == "reversible" and name in OWNER_ONLY and name in KERNEL_ONLY
    assert "我记下了：……" in act.SUMMARIES["record_view"] and "不是证据" in act.SUMMARIES["record_view"]
    assert act.describe("record_view")["arguments"]["required"] == ["symbol", "text", "quote"]


def test_the_old_engine_does_not_know_them():
    from app.agent_workflow.routing import parse_route
    for name in ("record_view", "drop_view"):
        assert name not in legacy_definitions() and name not in write_tool_names()
        assert name not in {s["function"]["name"] for s in schemas(owner=True, granted=set(definitions()))}
        assert name not in {s["function"]["name"] for s in schemas(owner=False, kernel=True)}
        assert name in {s["function"]["name"] for s in schemas(owner=True, kernel=True, granted=set(definitions()))}
    route = parse_route(json.dumps({"category": "D", "days_back": None, "requested_actions": ["record_view", "drop_view", "record_trade"]}))
    assert route.requested_actions == ["record_trade"]


def test_the_registry_knows_where_they_are_and_that_a_web_delete_is_not_theirs():
    assert not ({"record_view", "drop_view"} & KERNEL_ONLY_OPERATIONS)       # since 4e the memory page writes and withdraws a view: they have routes
    row = OPERATION_REGISTRY[("DELETE", "/agent-chat/views/{view_id}")]
    assert row == {"exempt": "网页上本人删除一条历史，不开放给助手"}


# ---- 4d: the review under each version ----------------------------------------------------------------------------------------

def _review(view_id, *, age_days=1, verdict="held", text="成立。", stray=(), snapshot=None, owner=OWNER_HASH):
    import uuid
    with SessionLocal() as db:
        db.add(ViewReview(owner_hash=owner, view_id=uuid.UUID(view_id), symbol="NVDA", verdict=verdict, text=text, unmatched_figures=list(stray),
                          input_snapshot=snapshot if snapshot is not None else {}, created_at=datetime.now(UTC) - timedelta(days=age_days)))
        db.commit()


def test_history_carries_the_latest_review_with_a_basis_built_from_the_snapshot(owner, client):
    record(FIRST, text="数据中心还会翻倍")
    first = owner_views.history(OWNER_HASH, "NVDA")[0]["id"]
    record(SECOND, text="估值太高")
    snapshot = {"price": {"then": {"date": "2026-09-01", "close": 100.0}, "now": {"date": "2026-11-24", "close": 150.0}, "change_pct": 50.0},
                "quarter": {"label": "FY2026 Q3", "period_end": "2026-10-26"}}
    _review(first, age_days=100, verdict="unclear", text="旧的复盘")
    _review(first, age_days=2, verdict="mixed", text="部分成立，收入翻了但估值也涨了。", stray=["37%"], snapshot=snapshot)
    newest, older = owner_views.history(OWNER_HASH, "NVDA")
    assert newest["review"] is None
    review = older["review"]
    assert (review["verdict"], review["verdict_label"], review["text"], review["unmatched_figures"]) == ("mixed", "部分成立", "部分成立，收入翻了但估值也涨了。", ["37%"])
    assert review["basis"] == {"price_then": {"date": "2026-09-01", "close": 100.0}, "price_now": {"date": "2026-11-24", "close": 150.0},
                               "change_pct": 50.0, "quarter_label": "FY2026 Q3"}
    assert review["created_at"] is not None
    over_the_wire = client.get("/agent-chat/views/NVDA/history", headers={"X-Chat-Session": OWNER}).json()["versions"]
    assert over_the_wire[0]["review"] is None and over_the_wire[1]["review"]["verdict_label"] == "部分成立"
    assert client.get("/agent-chat/views/NVDA/history", headers={"X-Chat-Session": "g" * 64}).status_code == 403


def test_a_review_with_no_price_and_no_quarter_has_no_basis(owner):
    record(FIRST, text="数据中心还会翻倍")
    only = owner_views.history(OWNER_HASH, "NVDA")[0]["id"]
    _review(only, snapshot={"price": {"then": None, "now": None, "change_pct": None}, "quarter": None})
    assert owner_views.history(OWNER_HASH, "NVDA")[0]["review"]["basis"] is None
    _review(only, age_days=0, snapshot={"price": {"then": None, "now": {"date": "2026-11-24", "close": 150.0}, "change_pct": None}, "quarter": None})
    assert owner_views.history(OWNER_HASH, "NVDA")[0]["review"]["basis"]["price_now"]["close"] == 150.0


def test_another_owners_review_is_never_attached(owner):
    record(FIRST, text="数据中心还会翻倍")
    mine = owner_views.history(OWNER_HASH, "NVDA")[0]["id"]
    _review(mine, owner=OTHER_HASH)
    assert owner_views.history(OWNER_HASH, "NVDA")[0]["review"] is None


def test_deleting_a_version_deletes_its_reviews_and_only_its_own(owner):
    record(FIRST, text="数据中心还会翻倍")
    first = owner_views.history(OWNER_HASH, "NVDA")[0]["id"]
    record(SECOND, text="估值太高")
    second = owner_views.history(OWNER_HASH, "NVDA")[0]["id"]
    _review(first)
    _review(first, age_days=50)
    _review(second)
    assert owner_views.delete_version(OTHER_HASH, first) is False
    with SessionLocal() as db:
        assert db.query(ViewReview).count() == 3
    assert owner_views.delete_version(OWNER_HASH, first) is True
    with SessionLocal() as db:
        left = db.query(ViewReview).all()
        assert [str(r.view_id) for r in left] == [second]


# ---- Review Focus 3: the line in the 「系统最新掌握」 block --------------------------------------------------------------

NOW = datetime(2026, 11, 25, 14, 43, tzinfo=UTC)
SAID = datetime(2026, 11, 24, 18, 0, tzinfo=UTC)         # 11-25 02:00 Beijing


def _item(symbol="NVDA", view=True, n=3, **over):
    item = {"symbol": symbol, "name": "", "filings": [{"form": "8-K", "accepted_at": NOW, "observed_at": NOW, "kind": None, "head": "头" * 80}] * n,
            "news": [{"title": "标题" * 60, "source": "s", "published_at": NOW - timedelta(hours=1)}] * n,
            "price": {"kind": "close", "value": 1.0, "change_pct": None, "at": NOW, "date": NOW.date()}}
    if view:
        item["view"] = {"text": f"{symbol} 的看法：估值太高", "created_at": SAID.isoformat()}
    return {**item, **over}


def test_the_view_line_is_first_in_the_section_with_its_date_and_the_fixed_wording():
    text = lk.render([_item("NVDA")], now=NOW)
    lines = text.splitlines()
    assert lines[1] == "关于 NVDA：" and lines[2] == "  你的看法（11-25 说的）：NVDA 的看法：估值太高"
    assert lk.VIEW_NOTE in lines and "你的看法，不是证据" in lk.VIEW_NOTE and lines[-1] == lk.CLOSING_LINE
    assert "你的看法" not in lk.render([_item("NVDA", view=False)], now=NOW)         # no view, no line, no note


def test_a_view_alone_makes_a_section_and_a_notice_keeps_its_place():
    alone = lk.render([{"symbol": "AMD", "name": "", "view": {"text": "再等等", "created_at": SAID.isoformat()}}], now=NOW)
    assert alone.splitlines()[1:3] == ["关于 AMD：", "  你的看法（11-25 说的）：再等等"]
    noticed = lk.render([{"symbol": "AMD", "name": "", "notice": "系统里还没有 AMD 的资料：正在取。", "view": {"text": "再等等", "created_at": SAID.isoformat()}}], now=NOW)
    assert noticed.splitlines()[1:4] == ["系统里还没有 AMD 的资料：正在取。", "关于 AMD：", "  你的看法（11-25 说的）：再等等"]


def test_with_a_tight_block_the_facts_go_before_the_view_does():
    items = [_item(s, facts=None) for s in ("NVDA", "AMD", "AAPL")]
    for item in items:
        item["view"]["text"] = f"{item['symbol']} 我的看法" + "。很长" * 50                  # near the line cap
    text = lk.render(items, now=NOW, extra=["另提到：特斯拉（TSLA）（没有展开）"])
    assert len(text) <= lk.BLOCK_LIMIT
    for symbol in ("NVDA", "AMD", "AAPL"):
        assert f"  你的看法（11-25 说的）：{symbol} 我的看法" in text
    assert text.count("  新闻 ") < 9 and text.count("  官方公告 ") < 9
    # still tighter: the figures and pages go, the three views stay
    tight = [_item(s, facts=None) for s in ("NVDA", "AMD", "AAPL")]
    for item in tight:
        item["view"]["text"] = "看法" * 100
    text = lk.render(tight, now=NOW)
    assert len(text) <= lk.BLOCK_LIMIT and text.count("  你的看法（11-25 说的）：") == 3 and text.endswith(lk.CLOSING_LINE)


@pytest.fixture
def block(monkeypatch):
    """``_build`` as the owner's (or a guest's) turn runs it, with the database of companies and the SEC list out of the way."""
    from app import archive_subjects as archive
    monkeypatch.setattr(archive, "warm_ticker_list", lambda: None)
    monkeypatch.setattr(archive, "note_asked", lambda symbol: "ok")
    monkeypatch.setattr(lk, "_known_symbols", lambda: {"NVDA", "AMD"})
    monkeypatch.setattr(lk, "_owned_symbols", lambda owner: set())
    held = {"NVDA": {"symbol": "NVDA", "name": "英伟达", "filings": [{"form": "8-K", "accepted_at": NOW, "observed_at": NOW, "kind": None, "head": "业绩"}],
                     "news": [], "price": None}}
    monkeypatch.setattr(lk, "gather", lambda symbols, **k: [held[s] for s in symbols if s in held])
    return lambda text, owner_hash_: lk._build(text, None, None, owner_hash_, NOW)


def test_the_owners_block_opens_each_company_with_his_view_and_a_guests_never_has_it(owner, block):
    record(FIRST, text="今年数据中心还会翻倍")
    text, symbols = block("英伟达怎么样", OWNER_HASH)
    assert symbols == ["NVDA"]
    lines = text.splitlines()
    start = lines.index("关于 英伟达（NVDA）：")
    assert lines[start + 1].startswith("  你的看法（") and lines[start + 1].endswith("）：今年数据中心还会翻倍") and "官方公告" in lines[start + 2]
    guest, _ = block("英伟达怎么样", "")
    assert "你的看法" not in guest
    other, _ = block("英伟达怎么样", OTHER_HASH)
    assert "你的看法" not in other
    # a company the system holds nothing for still shows what he thinks of it
    owner_views.record(OWNER_HASH, "AMD", "先观望", "我想先观望 AMD")
    text, symbols = block("AMD 呢", OWNER_HASH)
    assert symbols == ["AMD"] and "  你的看法（" in text and "先观望" in text


def test_a_dropped_or_superseded_view_is_not_in_the_block(owner, block):
    record(FIRST, text="数据中心还会翻倍")
    record(SECOND, text="估值太高")
    text, _ = block("英伟达怎么样", OWNER_HASH)
    assert "估值太高" in text and "数据中心还会翻倍" not in text
    run(act.handle(make_run("撤回"), {"operation": "drop_view", "arguments": {"symbol": "NVDA"}}))
    assert "你的看法" not in block("英伟达怎么样", OWNER_HASH)[0]


def test_a_failure_reading_views_costs_the_line_not_the_block(owner, block, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(owner_views, "current", broken)
    text, symbols = block("英伟达怎么样", OWNER_HASH)
    assert symbols == ["NVDA"] and "你的看法" not in text and "关于 英伟达" in text


# ---- 4e Task 2, Review Focus 3: the owner writes and withdraws a view on the memory page -------------------------------------

PAGE_TEXT = "估值太高，先不加仓"


def test_a_view_typed_on_the_page_supersedes_the_old_one_and_is_its_own_quote(owner, client, block):
    record(FIRST, text="今年英伟达数据中心还会翻倍")
    headers = {"X-Chat-Session": OWNER}
    answer = client.post("/agent-chat/views/NVDA", json={"text": PAGE_TEXT}, headers=headers)
    assert answer.status_code == 200
    body = answer.json()
    assert body["status"] == "recorded" and body["view"]["text"] == PAGE_TEXT and body["replaced"]["status"] == "superseded"
    assert rows() == [("今年英伟达数据中心还会翻倍", "superseded", True), (PAGE_TEXT, "active", False)]
    new = owner_views.current(OWNER_HASH, ["NVDA"])["NVDA"]
    assert new["quote"] == PAGE_TEXT and new["conversation_id"] is None and new["turn_id"] is None and new["source_message_id"] is None
    # the model reads it back in the 「系统最新掌握」 block exactly as one said in chat
    text, _ = block("英伟达怎么样", OWNER_HASH)
    assert f"）：{PAGE_TEXT}" in text and "今年英伟达数据中心还会翻倍" not in text
    # the same text again changes nothing
    assert client.post("/agent-chat/views/NVDA", json={"text": PAGE_TEXT}, headers=headers).json()["status"] == "unchanged"
    assert len(rows()) == 2
    # a company named in words routes like the ticker
    assert client.post("/agent-chat/views/英伟达", json={"text": "还是先观望"}, headers=headers).json()["view"]["symbol"] == "NVDA"


def test_withdrawing_a_view_on_the_page_keeps_it_as_dropped(owner, client, block):
    owner_views.record(OWNER_HASH, "NVDA", PAGE_TEXT, PAGE_TEXT)
    headers = {"X-Chat-Session": OWNER}
    answer = client.post("/agent-chat/views/NVDA/drop", headers=headers)
    assert answer.status_code == 200 and answer.json()["view"]["status"] == "dropped" and answer.json()["view"]["ended_at"]
    assert rows() == [(PAGE_TEXT, "dropped", True)]
    assert "你的看法" not in block("英伟达怎么样", OWNER_HASH)[0]
    again = client.post("/agent-chat/views/NVDA/drop", headers=headers)
    assert again.status_code == 404 and again.json()["detail"] == "view_not_found"
    assert client.post("/agent-chat/views/没这家公司/drop", headers=headers).status_code == 404


def test_the_page_write_refuses_with_the_services_own_code(owner, client):
    headers = {"X-Chat-Session": OWNER}
    short = client.post("/agent-chat/views/NVDA", json={"text": "太高了"}, headers=headers)
    assert short.status_code == 422 and short.json()["detail"] == "view_quote_too_short"
    assert client.post("/agent-chat/views/NVDA", json={"text": "   "}, headers=headers).json()["detail"] == "invalid_view_text"
    assert client.post("/agent-chat/views/NVDA", json={"text": "估" * 201}, headers=headers).json()["detail"] == "invalid_view_text"
    assert client.post("/agent-chat/views/没这家公司", json={"text": PAGE_TEXT}, headers=headers).json()["detail"] == "company_not_recognized"
    for body in ({}, {"text": PAGE_TEXT, "quote": "他说的"}, {"text": PAGE_TEXT, "conversation_id": CONVERSATION}, {"text": "估" * 401}, {"text": None}):
        assert client.post("/agent-chat/views/NVDA", json=body, headers=headers).status_code == 422
    assert rows() == []


def test_a_guest_cannot_write_or_withdraw_a_view_and_another_owners_view_is_untouched(owner, client):
    owner_views.record(OTHER_HASH, "NVDA", "别人的看法", "别人的看法在这里")
    guest = {"X-Chat-Session": "g" * 64}
    for headers in (guest, {}):
        write = client.post("/agent-chat/views/NVDA", json={"text": PAGE_TEXT}, headers=headers)
        assert write.status_code == 403 and write.json()["detail"] == "owner_only"
        assert client.post("/agent-chat/views/NVDA/drop", headers=headers).status_code == 403
    assert client.post("/agent-chat/views/NVDA/drop", headers={"X-Chat-Session": OWNER}).status_code == 404       # his own: nothing to drop
    assert owner_views.current(OTHER_HASH, ["NVDA"])["NVDA"]["status"] == "active" and rows() == []


def test_the_new_page_routes_do_not_shadow_the_history_and_restore_routes(owner, client):
    headers = {"X-Chat-Session": OWNER}
    owner_views.record(OWNER_HASH, "NVDA", "先看看", "我想先看看英伟达")
    archived = owner_views.history(OWNER_HASH, "NVDA")[0]["id"]
    assert owner_views.archive(OWNER_HASH, archived, "很久没提了")["status"] == "archived"
    owner_views.record(OWNER_HASH, "NVDA", PAGE_TEXT, PAGE_TEXT)
    history = client.get("/agent-chat/views/NVDA/history", headers=headers)
    assert history.status_code == 200 and [v["status"] for v in history.json()["versions"]] == ["active", "archived"]
    # restore is ``POST /views/{view_id}/restore``: refused (409) while another view is current; not read as a symbol
    blocked = client.post(f"/agent-chat/views/{archived}/restore", headers=headers)
    assert blocked.status_code == 409 and blocked.json()["detail"] == owner_views.RESTORE_BLOCKED
    assert client.post("/agent-chat/views/NVDA/drop", headers=headers).status_code == 200
    restored = client.post(f"/agent-chat/views/{archived}/restore", headers=headers)
    assert restored.status_code == 200 and restored.json()["view"]["status"] == "active"
    assert client.post("/agent-chat/views/not-an-id/restore", headers=headers).status_code == 404
    assert client.delete(f"/agent-chat/views/{archived}", headers=headers).json() == {"deleted": True}


# ---- 4e Task 2, Review Focus 7: the registry -----------------------------------------------------------------------------------

def test_the_page_writes_are_mapped_to_the_view_operations_and_nothing_is_kernel_only_any_more():
    assert OPERATION_REGISTRY[("POST", "/agent-chat/views/{symbol}")] == {"operation": "record_view"}
    assert OPERATION_REGISTRY[("POST", "/agent-chat/views/{symbol}/drop")] == {"operation": "drop_view"}
    assert not ({"record_view", "drop_view"} & KERNEL_ONLY_OPERATIONS)
    assert {"record_view", "drop_view"} <= set(act.OPERATIONS)
