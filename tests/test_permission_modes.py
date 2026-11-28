"""The permission modes (11-28, owner: 「把选择权交到用户身上」): 每步都问 / 默认 / 完全放行, his 「这次直接做」 for one turn, and what
stays in every mode (after outside material a write waits; a card that asks him to pick always waits).  ``app.permission_mode``,
``kernel.act._runs_at_once``, the route ``/agent-chat/permission-mode``."""
import json

import pytest
from fastapi.testclient import TestClient

from app import permission_mode
from app.kernel import act
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
        assert tool_results(fake)[0]["data"][0]["undo"] == act.UNDO_OTHER and result["pending_request"] is None


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
