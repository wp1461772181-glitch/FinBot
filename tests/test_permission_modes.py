"""The permission modes (11-28, owner: 「把选择权交到用户身上」): 每步都问 / 默认 / 完全放行, his 「这次直接做」 for one turn, and what
stays in every mode (after outside material a write waits; a card that asks him to pick always waits).  ``app.permission_mode``,
``kernel.act._runs_at_once``, the route ``/agent-chat/permission-mode``."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import permission_mode
from app.kernel import act, loop
from app.kernel.operation_registry import OPERATION_REGISTRY
from tests.test_kernel_loop import (TOKEN, act_call, call, ctx, env, fake_consent, run, script, step, tool_results)  # noqa: F401  (fixtures)


@pytest.fixture
def mode(env):
    def choose(value):
        env.monkeypatch.setattr(permission_mode, "get", lambda owner: value)
    return choose


def statuses(fake):
    return [r["data"][0].get("status") for r in tool_results(fake) if r.get("data")]


@pytest.mark.parametrize("chosen,runs", [("ask", False), ("default", True), ("full", True)])
def test_tier_one_runs_at_once_unless_every_step_is_asked(env, fake_consent, mode, chosen, runs):
    mode(chosen)
    fake = script(env, [step(calls=[act_call("c1", "add_to_research_queue", {"symbol": "NVDA"})]), step(text="好")])
    result, _ = run(context=ctx())
    assert (len(fake_consent.executed) == 1) is runs and statuses(fake) == (["done"] if runs else ["awaiting_confirmation"])
    assert result["status"] == ("succeeded" if runs else "waiting_for_input")


@pytest.mark.parametrize("chosen,runs", [("ask", False), ("default", False), ("full", True)])
def test_a_forecast_waits_except_in_the_full_mode(env, fake_consent, mode, chosen, runs):
    mode(chosen)
    fake = script(env, [step(calls=[act_call("c1", "forecast", {"symbol": "AAPL"})]), step(text="好")])
    result, _ = run(context=ctx())
    assert (len(fake_consent.costly) == 1) is runs and statuses(fake) == (["done"] if runs else ["awaiting_confirmation"])
    if runs:      # done at once: the answer says what was done and how to undo it
        assert tool_results(fake)[0]["data"][0]["undo"] == act.UNDO["forecast"] and "退不回来" in act.UNDO["forecast"] and result["pending_request"] is None


def test_after_outside_material_a_write_waits_even_in_the_full_mode(env, fake_consent, mode):
    mode("full")
    fake = script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]),
                        step(calls=[act_call("c2", "forecast", {"symbol": "AAPL"})]), step(text="请核对卡片")])
    result, _ = run(context=ctx())
    assert fake_consent.costly == [] and statuses(fake)[-1] == "awaiting_confirmation" and result["status"] == "waiting_for_input"


def test_fetching_public_material_runs_after_a_read_but_not_when_every_step_is_asked(env, fake_consent, mode, monkeypatch):
    from app.agent_workflow import sec_sources
    monkeypatch.setattr(sec_sources, "prepare_filing", lambda name, args, financial_only=False: {
        "name": "fetch_sec", "arguments": {"symbol": "QBTS", "accession_number": "A-1"},
        "discovery": {"form": "10-Q", "filed_at": "2026-11-10", "source_url": "https://sec.gov/q"}})
    for chosen, runs in (("default", True), ("full", True), ("ask", False)):
        mode(chosen)
        before = len(fake_consent.costly)
        script(env, [step(calls=[call("c1", "web_research", {"query": "量子计算"})]),
                     step(calls=[act_call("c2", "fetch_sec", {"symbol": "QBTS"})]), step(text="好")])
        run(context=ctx())
        assert (len(fake_consent.costly) - before == 1) is runs, chosen


def test_his_go_ahead_this_turn_runs_it_and_a_made_up_one_does_not(env, fake_consent, mode):
    mode("default")
    said = "帮我做一份 AAPL 的预测，不用确认，直接做"
    script(env, [step(calls=[act_call("c1", "forecast", {"symbol": "AAPL"}, go_ahead="不用确认，直接做")]), step(text="好")])
    run(said, context=ctx())
    assert len(fake_consent.costly) == 1
    fake = script(env, [step(calls=[act_call("c1", "forecast", {"symbol": "AAPL"}, go_ahead="不用确认，直接做")]), step(text="好")])
    run("帮我做一份 AAPL 的预测", context=ctx())                  # not his words this turn: a card
    assert len(fake_consent.costly) == 1 and statuses(fake) == ["awaiting_confirmation"]


def test_his_go_ahead_does_not_reach_past_outside_material(env, fake_consent, mode):
    mode("default")
    fake = script(env, [step(calls=[call("c1", "query_financials", {"symbol": "AAPL"})]),
                        step(calls=[act_call("c2", "forecast", {"symbol": "AAPL"}, go_ahead="直接做")]), step(text="好")])
    run("直接做 AAPL 的预测", context=ctx())
    assert fake_consent.costly == [] and statuses(fake)[-1] == "awaiting_confirmation"


def test_the_mode_is_read_once_a_turn(env, fake_consent, monkeypatch):
    reads = []
    monkeypatch.setattr(permission_mode, "get", lambda owner: reads.append(owner) or "default")
    script(env, [step(calls=[act_call("c1", "add_to_research_queue", {"symbol": "NVDA"}), act_call("c2", "add_to_research_queue", {"symbol": "AMD"})]),
                 step(text="好")])
    run(context=ctx())
    assert len(reads) == 1


def test_the_route_is_his_and_the_assistant_cannot_change_it(monkeypatch):
    from app import permission_api
    from app.main import app as api
    stored = {}
    monkeypatch.setattr(permission_api, "_owner_only", lambda credential: credential if credential == "x" * 40 else (_ for _ in ()).throw(
        __import__("fastapi").HTTPException(403, "owner_only")))
    monkeypatch.setattr(permission_api, "owner_hash", lambda credential: "owner")
    monkeypatch.setattr(permission_mode, "get", lambda owner: stored.get(owner, "default"))
    monkeypatch.setattr(permission_mode, "set_mode", lambda owner, value: stored.__setitem__(owner, value) or permission_mode.view(value))
    client = TestClient(api)
    mine, guest = {"X-Chat-Session": "x" * 40}, {"X-Chat-Session": "g" * 40}
    assert client.get("/agent-chat/permission-mode", headers=guest).status_code == 403
    assert client.put("/agent-chat/permission-mode", json={"mode": "full"}, headers=guest).status_code == 403
    assert client.get("/agent-chat/permission-mode", headers=mine).json()["mode"] == "default"
    assert client.put("/agent-chat/permission-mode", json={"mode": "everything"}, headers=mine).status_code == 422
    changed = client.put("/agent-chat/permission-mode", json={"mode": "full"}, headers=mine).json()
    assert changed["mode"] == "full" and changed["label"] == "完全放行" and [m["mode"] for m in changed["modes"]] == ["ask", "default", "full"]
    assert "exempt" in OPERATION_REGISTRY[("PUT", "/agent-chat/permission-mode")]        # no act operation changes it


def test_the_store_defaults_to_the_middle(disposable_database):
    from app.database import Base, SessionLocal, engine
    Base.metadata.create_all(engine, tables=[permission_mode.PermissionSetting.__table__])
    with SessionLocal() as db:
        db.query(permission_mode.PermissionSetting).delete()
        db.commit()
    assert permission_mode.get("o" * 64) == "default" and permission_mode.get(None) == "default"
    assert permission_mode.set_mode("o" * 64, "ask")["mode"] == "ask" and permission_mode.get("o" * 64) == "ask"
    with pytest.raises(ValueError):
        permission_mode.set_mode("o" * 64, "everything")


def test_a_go_ahead_from_an_earlier_turn_does_not_count(env, fake_consent, mode):
    """11-28 review: 「直接做」 holds for the turn he said it in; an earlier message in the history is not this turn's word."""
    mode("default")
    history = [{"role": "system", "content": "endpoint"}, {"role": "user", "content": "不用确认，直接做"}, {"role": "assistant", "content": "好"},
               {"role": "user", "content": "帮我做一份 AAPL 的预测"}]
    fake = script(env, [step(calls=[act_call("c1", "forecast", {"symbol": "AAPL"}, go_ahead="不用确认，直接做")]), step(text="好")])
    run("帮我做一份 AAPL 的预测", context=ctx(), messages=history)
    assert fake_consent.costly == [] and statuses(fake) == ["awaiting_confirmation"]


def test_saving_a_page_waits_after_the_search_in_every_mode(env, fake_consent, mode, monkeypatch):
    """A page could steer what goes into his 资料库: after the search it waits, unlike the official fetches."""
    from tests.test_kernel_loop import PAGE, web_env
    web_env(env, monkeypatch)
    for chosen in ("default", "full"):
        mode(chosen)
        script(env, [step(calls=[call("c1", "web_research", {"query": "量子计算"})]),
                     step(calls=[act_call("c2", "ingest_web_source", {"url": PAGE["url"], "symbol": "IONQ"})]), step(text="好")])
        run(context=ctx())
        assert fake_consent.executed == [] and fake_consent.costly == [], chosen


def test_an_empty_sec_library_says_how_to_fetch_in_his_turn(env, fake_consent, monkeypatch):
    """11-28 shadow: the library was empty, the read said only no_source, and the answer offered to fetch the 10-Q instead of fetching it."""
    from app.agent_workflow import tools
    from app.kernel import toolrun
    async def invoke(name, args, context, *, emit=None, page_chars=None):
        return {"ok": True, "data": [], "source": "sec_filing_inventory (saved inventory)", "as_of": None, "error_code": "no_source"}
    monkeypatch.setattr(tools, "invoke", invoke)
    fake = script(env, [step(calls=[call("c1", "query_sec_filings", {"symbol": "IONQ"})]), step(text="好")])
    run(context=ctx())
    assert tool_results(fake)[0]["hint"] == toolrun.FETCH_HINT and "fetch_sec" in toolrun.FETCH_HINT


def test_a_guest_turn_is_not_told_to_fetch(env, monkeypatch):
    from app.agent_workflow import tools
    from app.kernel import toolrun
    from tests.test_kernel_helper import guest_context
    async def invoke(name, args, context, *, emit=None, page_chars=None):
        return {"ok": True, "data": [], "error_code": "no_reported_figures"}
    monkeypatch.setattr(tools, "invoke", invoke)
    fake = script(env, [step(calls=[call("c1", "query_financials", {"symbol": "IONQ"})]), step(text="好")])
    run(context=guest_context())
    assert "hint" not in tool_results(fake)[0]


# --- 11-28 Fable review: the gaps it listed -------------------------------------------------------------------------------------------

ROUTINE = "11111111-2222-3333-4444-555555555555"


def test_a_deletion_waits_in_the_full_mode_and_after_his_go_ahead(env, fake_consent, mode):
    for chosen, said, go in (("full", "删掉那个例行任务", None), ("default", "删掉那个例行任务，直接做", "直接做"), ("ask", "删掉，直接做", "直接做")):
        mode(chosen)
        before = len(fake_consent.executed)
        fake = script(env, [step(calls=[act_call("c1", "delete_routine", {"routine_id": ROUTINE}, **({"go_ahead": go} if go else {}))]), step(text="请核对卡片")])
        run(said, context=ctx())
        assert len(fake_consent.executed) == before and statuses(fake) == ["awaiting_confirmation"], chosen


def test_in_the_full_mode_news_in_the_latest_block_keeps_tier_two_and_three_on_the_card(env, fake_consent, mode, monkeypatch):
    """A news title attached before the first step is third-party text, as a page is: a forecast waits, tier 1 still runs."""
    async def latest(run, *a, **k):
        run.outside_in_prompt = True
        return "系统最新掌握：……"
    monkeypatch.setattr(loop, "_latest_block", latest)
    mode("full")
    fake = script(env, [step(calls=[act_call("c1", "forecast", {"symbol": "AAPL"}), act_call("c2", "add_to_research_queue", {"symbol": "AAPL"})]), step(text="好")])
    run(context=ctx())
    assert fake_consent.costly == [] and statuses(fake) == ["awaiting_confirmation", "done"]


def test_the_latest_block_marks_outside_text_only_for_news(env, monkeypatch):
    from app import latest_known
    seen = {}
    for kind, outside in (("market_data", False), ("official_filing", False), ("configured_news", True)):
        async def block_for(text, previous=None, focus=None, rows=None, owner_hash=None, conversation_id=None, kind=kind):
            rows.append({"id": "r1", "source_type": kind, "title": "t"})
            return "最新：t", ["AAPL"]
        monkeypatch.setattr(latest_known, "block_for", block_for)
        monkeypatch.setattr(loop, "number_attached", lambda run, text, rows: text)
        holder = type("R", (), {"outside_in_prompt": False, "context": ctx(), "audit": {}, "timeline": []})()
        monkeypatch.setattr(loop, "note_latest", lambda run, symbols: None)
        asyncio.run(loop._latest_block(holder, "AAPL 怎么样", None, None, True))
        seen[kind] = holder.outside_in_prompt
        assert holder.outside_in_prompt is outside, kind


def test_the_same_operation_twice_in_a_turn_runs_once(env, fake_consent, mode):
    mode("full")
    fake = script(env, [step(calls=[act_call("c1", "forecast", {"symbol": "AAPL"})]), step(calls=[act_call("c2", "forecast", {"symbol": "AAPL"})]), step(text="好")])
    run(context=ctx())
    assert len(fake_consent.costly) == 1
    assert [r["data"][0]["status"] for r in tool_results(fake)] == ["done", "done"] and tool_results(fake)[1]["note"] == act.DONE_AGAIN


def test_the_full_mode_does_not_reach_a_scheduled_run_or_a_guest(env, fake_consent, mode):
    from tests.test_kernel_helper import guest_context
    mode("full")
    sink = []
    fake = script(env, [step(calls=[act_call("c1", "forecast", {"symbol": "AAPL"})]), step(text="建议")])
    run(context=ctx(unattended=True, action_sink=sink, bot_id=None))
    assert fake_consent.costly == [] and fake_consent.executed == [] and len(sink) == 1
    fake = script(env, [step(text="好")])
    run(context=guest_context())
    assert "act" not in fake.calls[0]["tools"]


def test_his_go_ahead_counts_in_the_ask_mode_and_in_a_message_sent_mid_turn(env, fake_consent, mode):
    mode("ask")
    script(env, [step(calls=[act_call("c1", "add_to_research_queue", {"symbol": "NVDA"}, go_ahead="直接加，不用确认")]), step(text="好")])
    run("把 NVDA 加进研究队列，直接加，不用确认", context=ctx())
    assert len(fake_consent.executed) == 1
    holder = type("R", (), {"question": "做一份 AAPL 预测", "typed_this_turn": "\n不用确认，直接做"})()
    assert act._said_go_ahead(holder, "不用确认，直接做") and not act._said_go_ahead(holder, "全部删掉")


def test_a_mode_that_cannot_be_read_asks_every_step(monkeypatch):
    class Broken:
        def __enter__(self):
            raise RuntimeError("database down")
        def __exit__(self, *a):
            return False
    monkeypatch.setattr(permission_mode, "SessionLocal", lambda: Broken())
    assert permission_mode.get("owner") == "ask" and permission_mode.get(None) == "default"
