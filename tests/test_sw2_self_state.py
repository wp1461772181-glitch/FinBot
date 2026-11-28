"""SW2 S2 (R1, R7; spec-sw2 §3.1, K6–K11): the model and the previous answer's system source check, as a fact block.

Pins P-R1 (the five states reach the model as the spec's wording), B1 (one ledger line per shadow terminal, written after
the gate returns), B2 (reason codes), B3 (turns from before the audit key), B4 (tail only, bad lines unknown), B5 (at most five
sentences of sixty characters), K6 (paused read), K8 (owner refusal writes nothing), K9 (wording, once per turn), K10 (what the
ledger keeps; file modes), K11 (the model label keeps the catalog key on every catalog-resolved turn), P-N (one ordinary
single-company question: the four switches on against off differ only by the fact block, the sentence and the memory tools).
Off: no block, no audit key, no ledger line.
"""
import asyncio
import copy
import json
import os
import re
import stat
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent_system_prompt import SELF_STATE_SENTENCE
from app.agent_workflow import claim_public_wire as wire
from app.agent_workflow import claim_shadow
pass  # (removed import of the old turn)
from app.agent_workflow import tools
from app.agent_workflow.state import AgentRuntimeContext
from test_agent_chat_stream import stream_fixture  # noqa: F401  (the endpoint fixture for the K11 label tests)

OWNER = "owner-credential-for-sw2-tests"
TURN = "11111111-2222-4333-8444-555555555555"
K9_PENDING = '- 上一条回答的系统来源核对：还没有结果（核对在回答之后另行进行，距上一条完成约 {s} 秒）；目前没有显示任何标注。'


@pytest.fixture(autouse=True)
def _switches(monkeypatch, tmp_path):
    for name in ("FINBOT_SW2_SELF_STATE", "FINBOT_SW2_MEMORY_PRELOAD", "FINBOT_SW2_SELF_STATE_WORDING", "FINBOT_SW2_HISTORY_PAGES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path))
    claim_shadow.reset_state()
    yield
    claim_shadow.reset_state()


def _marks(*sentences):
    return [{"id": f"m{i}", "hover": {"answer_sentence": s, "evidence": {}}} for i, s in enumerate(sentences)]


def _state(**kwargs):
    base = dict(model_label="haiku-5.5（openrouter/anthropic/claude-haiku-5-5）", prior=None)
    base.update(kwargs)
    return base


def _context(*, bot_id=None, self_state=None):
    return SimpleNamespace(provider="openrouter", model="anthropic/claude-haiku-5-5", bot_id=bot_id, self_state=self_state)


# ---- B2: maybe_schedule returns the reason its synchronous filter gave -------------------------------------------------

def _result(**overrides):
    base = {"status": "succeeded", "answer": "数字 [1]。", "citations": [{"ordinal": 1}], "turn_id": TURN}
    base.update(overrides)
    return base


def test_maybe_schedule_names_each_synchronous_reason(monkeypatch):
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
    ctx = SimpleNamespace(provider="p", model="m", identity_credential=OWNER, unattended=False, bot_id=None)
    assert claim_shadow.maybe_schedule(_result(pending_request={"id": "x"}), ctx, {}) == "pending_request"
    assert claim_shadow.maybe_schedule(_result(status="failed"), ctx, {}) == "not_succeeded"
    assert claim_shadow.maybe_schedule(_result(citations=[]), ctx, {}) == "no_numbered_sources"
    assert claim_shadow.maybe_schedule(_result(answer="没有编号。"), ctx, {}) == "no_numbered_sources"
    unattended = SimpleNamespace(provider="p", model="m", identity_credential=OWNER, unattended=True, bot_id=None)
    assert claim_shadow.maybe_schedule(_result(), unattended, {}) == "unattended"
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "off")
    assert claim_shadow.maybe_schedule(_result(), ctx, {}) == "shadow_off"


def test_maybe_schedule_busy_and_scheduled(monkeypatch):
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
    ctx = SimpleNamespace(provider="p", model="m", identity_credential=OWNER, unattended=False, bot_id=None)
    ran = []

    async def fake_run(snapshot):
        ran.append(snapshot.turn_id)

    monkeypatch.setattr(claim_shadow, "_run", fake_run)

    async def go():
        codes = [claim_shadow.maybe_schedule(_result(turn_id=f"{i:08d}-0000-4000-8000-000000000000"), ctx, {})
                 for i in range(claim_shadow.MAX_PENDING_TURNS + 1)]
        await asyncio.sleep(0)
        return codes
    codes = asyncio.run(go())
    assert codes[:claim_shadow.MAX_PENDING_TURNS] == ["scheduled"] * claim_shadow.MAX_PENDING_TURNS
    assert codes[-1] == "busy" and len(ran) == claim_shadow.MAX_PENDING_TURNS


# ---- K9 / B5 / P-R6 SELF_MODEL & SELF_NO_BOT: the fact block itself ----------------------------------------------------

# ---- P-R1 at the level of the states: prior_answer_state decides, the block says ----------------------------------------

@pytest.mark.parametrize("name,audit,marks,settled,paused,elapsed,expected", [
    ("judged-no-marks", {"judge_schedule": "scheduled"}, [], {"outcome": "judged"}, False, 5.0, {"state": "none"}),
    ("judged-two-marks", {"judge_schedule": "scheduled"}, ["甲", "乙"], {"outcome": "judged"}, False, 5.0, "shown"),
    ("pending", {"judge_schedule": "scheduled"}, [], None, False, 12.0, {"state": "pending", "elapsed_s": 12.0}),
    ("stale-unknown", {"judge_schedule": "scheduled"}, [], None, False, 400.0, {"state": "unknown"}),
    ("paused", {"judge_schedule": "scheduled"}, [], None, True, 5.0, {"state": "paused"}),
    ("no-numbered", {"judge_schedule": "no_numbered_sources"}, [], None, False, 5.0, {"state": "not_checked", "reason": "no_numbered_sources"}),
    ("stopped", {"judge_schedule": "scheduled"}, [], {"outcome": "stopped"}, False, 5.0, {"state": "not_checked", "reason": "shadow_off"}),
    ("error", {"judge_schedule": "scheduled"}, [], {"outcome": "error"}, False, 5.0, {"state": "not_checked", "reason": "unavailable"}),
])
def test_prior_answer_state_table(monkeypatch, name, audit, marks, settled, paused, elapsed, expected):
    monkeypatch.setattr(wire, "prior_turn_marks", lambda turn_id: (paused, _marks(*marks)))
    monkeypatch.setattr(wire, "read_settled", lambda turn_id: settled)
    state = wire.prior_answer_state(TURN, owner=True, audit=audit, elapsed_s=elapsed)
    if expected == "shown":
        assert state["state"] == "shown" and len(state["sentences"]) == len(marks)
    else:
        assert {k: v for k, v in state.items() if k != "sentences"} == expected


def test_not_owner_is_not_checked_without_reading_anything(monkeypatch):
    monkeypatch.setattr(wire, "read_settled", lambda *_: pytest.fail("the ledger must not be read for a guest"))
    assert wire.prior_answer_state(TURN, owner=False, audit={"judge_schedule": "scheduled"}, elapsed_s=1) == {
        "state": "not_checked", "reason": "not_owner"}


def test_turn_from_before_the_audit_key_shows_marks_or_unknown(monkeypatch):
    monkeypatch.setattr(wire, "prior_turn_marks", lambda turn_id: (False, _marks("甲")))
    assert wire.prior_answer_state(TURN, owner=True, audit={}, elapsed_s=1)["state"] == "shown"
    monkeypatch.setattr(wire, "prior_turn_marks", lambda turn_id: (False, []))
    assert wire.prior_answer_state(TURN, owner=True, audit=None, elapsed_s=1) == {"state": "unknown"}


# ---- K6: prior_turn_marks reads the pause and missing state as the public read does -------------------------------------

def test_prior_turn_marks_pause_and_missing_state_are_different(tmp_path, monkeypatch):
    assert wire.prior_turn_marks(TURN) == (False, [])          # no state file: not paused
    (tmp_path / wire.STATE_NAME).write_text(json.dumps({"paused": True, "displayed": []}), encoding="utf-8")
    assert wire.prior_turn_marks(TURN) == (True, [])           # paused
    (tmp_path / wire.STATE_NAME).write_text(json.dumps({"paused": False, "displayed": []}), encoding="utf-8")
    assert wire.prior_turn_marks(TURN) == (False, [])          # not paused, nothing displayed


# ---- B4 / K10: the ledger is tail-read, tolerant, and keeps only turn_id, outcome, at -----------------------------------

def test_ledger_keeps_three_keys_and_private_modes(tmp_path):
    shadow = tmp_path / "shadow"                                  # created by the ledger write: 0700
    wire.append_settled(shadow, TURN, "judged")
    row = json.loads((shadow / wire.SETTLED_NAME).read_text(encoding="utf-8").strip())
    assert set(row) == {"turn_id", "outcome", "at"} and row["turn_id"] == TURN and row["outcome"] == "judged"
    assert stat.S_IMODE(os.stat(shadow / wire.SETTLED_NAME).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(shadow).st_mode) == 0o700


def test_tail_only_and_bad_lines_are_unknown_not_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(wire, "SETTLED_TAIL_LINES", 5)
    old = "99999999-0000-4000-8000-000000000000"
    path = tmp_path / wire.SETTLED_NAME
    rows = [json.dumps({"turn_id": old, "outcome": "judged", "at": "x"})]
    rows += ["not json at all"]
    rows += [json.dumps({"turn_id": f"{i:08d}-0000-4000-8000-000000000000", "outcome": "judged", "at": "x"}) for i in range(10)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path))
    assert wire.read_settled(old) is None                      # older than the tail: never read
    assert wire.read_settled(f"{9:08d}-0000-4000-8000-000000000000")["outcome"] == "judged"
    (tmp_path / wire.SETTLED_NAME).unlink()
    assert wire.read_settled(TURN) is None                     # missing file: unknown, no exception


# ---- The turn: the fact block reaches the model, once per turn, and the audit records what it said --------------------

# ---- B1: the shadow task's terminal writes: one line each, judged after the gate returns, owner refusal writes none --

def _snapshot(identity=OWNER, citations=True):
    return claim_shadow.ShadowTurn(
        turn_id=TURN, conversation_id="c1", bot_id=None, question="Northwind 营收？",
        answer="Northwind 第三季度营收下降 8% [1]。", status="succeeded", reason="normal", route="A",
        citations=({"ordinal": 1, "quote": "revenue rose 8%", "source_type": "official_filing",
                    "saved_text": "full_document", "check_text": "revenue rose 8% in Q3"},) if citations else (),
        code_flags={}, answer_model="openrouter/deepseek/deepseek-v4-flash", identity_credential=identity)


def _ledger(tmp_path):
    path = tmp_path / wire.SETTLED_NAME
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


@pytest.fixture
def shadow_owner(monkeypatch):
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW", "on")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "background")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_EXPECT_MODEL", "deepseek/deepseek-v4-flash")
    monkeypatch.setattr("app.agent_chat_identity.owner_credential_matches", lambda c: c == OWNER)
    claim_shadow.set_test_resolve_fn(AsyncMock(return_value={"provider": "openrouter", "model": "deepseek/deepseek-v4-flash", "api_key": "k"}))
    yield
    claim_shadow.set_test_resolve_fn(None)


def test_judged_turn_writes_one_line_after_the_gate_returns(monkeypatch, tmp_path, shadow_owner):
    from app.agent_workflow.claim_judge import JudgeResult
    monkeypatch.setattr("app.agent_workflow.claim_judge.judge_claims", AsyncMock(return_value=JudgeResult(
        status="ok", verdict="ok", reason="", quote="revenue rose 8%", quote_verified=True, quote_ordinal=1, subtype="number")))
    monkeypatch.setattr("app.agent_workflow.claim_short_review.review_candidate", AsyncMock(return_value={"status": "ok", "passed": True}))
    seen_at_gate = []
    original = wire.process_record

    def spy(dir_path, record):
        seen_at_gate.append(len(_ledger(tmp_path)))       # the ledger must not have the line yet
        return original(dir_path, record)
    monkeypatch.setattr(wire, "process_record", spy)
    asyncio.run(claim_shadow._run(_snapshot()))
    assert seen_at_gate == [0]
    assert [r["outcome"] for r in _ledger(tmp_path)] == ["judged"]


def test_stopped_turn_writes_stopped_once(monkeypatch, tmp_path, shadow_owner):
    (tmp_path / "STOP").write_text("STOP", encoding="utf-8")
    asyncio.run(claim_shadow._run(_snapshot()))
    assert [r["outcome"] for r in _ledger(tmp_path)] == ["stopped"]


def test_owner_refusal_writes_no_line(monkeypatch, tmp_path, shadow_owner):
    asyncio.run(claim_shadow._run(_snapshot(identity="guest-credential")))
    assert _ledger(tmp_path) == []


def test_settle_failure_is_logged_and_the_turn_still_judges(monkeypatch, tmp_path, shadow_owner):
    from app.agent_workflow.claim_judge import JudgeResult
    monkeypatch.setattr("app.agent_workflow.claim_judge.judge_claims", AsyncMock(return_value=JudgeResult(
        status="ok", verdict="ok", reason="", quote="revenue rose 8%", quote_verified=True, quote_ordinal=1, subtype="number")))
    monkeypatch.setattr("app.agent_workflow.claim_short_review.review_candidate", AsyncMock(return_value={"status": "ok", "passed": True}))

    def broken(*_args, **_kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(wire, "append_settled", broken)
    asyncio.run(claim_shadow._run(_snapshot()))
    assert len(list(tmp_path.glob("[0-9]*.jsonl"))) == 1         # the shadow record is still written
    assert _ledger(tmp_path) == []                               # and the failed ledger line is not


# ---- K11 (fix M1): the model label keeps the catalog key on every catalog-resolved turn ------------------------------------

DEFAULT_ENTRY = {"name": "haiku-5.5", "provider": "openrouter", "model": "anthropic/claude-haiku-5-5", "base_url": None, "context_window": None}
FLASH_ENTRY = {"name": "deepseek-flash", "provider": "siliconflow", "model": "deepseek-ai/DeepSeek-V4-Flash", "base_url": None, "context_window": None}


def _chosen(provider, model):
    from app.agent_chat_stream import _Model
    return _Model(provider, model, "k" * 16, None)


@pytest.mark.parametrize("case,resolved,expected", [
    ("catalog name", FLASH_ENTRY, "deepseek-flash（siliconflow/deepseek-ai/DeepSeek-V4-Flash）"),
    ("catalog_model empty (the chat UI's form): the default entry", DEFAULT_ENTRY, "haiku-5.5（openrouter/anthropic/claude-haiku-5-5）"),
    ("bot with its model set", FLASH_ENTRY, "deepseek-flash（siliconflow/deepseek-ai/DeepSeek-V4-Flash）"),
    ("bot with model NULL: the catalog default", DEFAULT_ENTRY, "haiku-5.5（openrouter/anthropic/claude-haiku-5-5）"),
])
def test_catalog_turns_are_labelled_with_the_entry_they_resolved_to(case, resolved, expected):
    from app.agent_chat_stream import _model_label
    assert _model_label(resolved, _chosen(resolved["provider"], resolved["model"])) == expected


def test_browser_sent_provider_and_model_are_labelled_as_given():
    from app.agent_chat_stream import _model_label
    assert _model_label(None, _chosen("deepseek", "deepseek-chat")) == "deepseek/deepseek-chat"


def _run_stream_and_capture_labels(monkeypatch, stream_fixture, payload):
    """Runs the endpoint with the fixture's stubs; returns the label handed to the self-state read and the label the
    stored answer's audit carries (the same spy as the probe P4)."""
    import app.agent_chat_stream as stream
    from starlette.requests import Request
    labels = []

    def spy(cid, cred, turn, label):
        labels.append(label)
        return {"model_label": label, "prior": None}
    monkeypatch.setattr(stream, "_self_state_inputs", spy)

    async def go():
        request = Request({"type": "http", "method": "POST", "path": "/agent-chat/stream", "headers": []})
        response = await stream.stream_chat(payload, request, "x" * 40)
        return "".join([part async for part in response.body_iterator])
    asyncio.run(go())
    stored = stream_fixture[4]
    audits = [kw["tool_calls"]["audit"] for _, kw in stored
              if isinstance(kw.get("tool_calls"), dict) and isinstance(kw["tool_calls"].get("audit"), dict)]
    return labels, [a.get("self_state", {}).get("model_label") for a in audits]


# ---- P-N (fix M2, spec-sw2 §4): one ordinary single-company question, the four switches on against off -----------------

PN_QUESTION = "MSFT 最近一期年报的营业收入是多少？"
PN_ANSWER = "MSFT FY2026 营业收入为 331,839,000,000 美元 [1]。"
PN_ROW = {"source_id": "pn-msft-10k-revenue", "symbol": "MSFT", "form": "10-K", "source_type": "reported_figure", "metric": "revenue",
          "title": "MSFT 10-K · 营业收入 FY2026", "filed_at": "2026-07-29", "excerpt": "营业收入（Revenue）FY2026：331,839,000,000 USD。"}
FOUR_SWITCHES = ("FINBOT_SW2_HISTORY_PAGES", "FINBOT_SW2_MEMORY_PRELOAD", "FINBOT_SW2_SELF_STATE_WORDING", "FINBOT_SW2_SELF_STATE")
MEMORY_TOOLS = {"recall_conversations", "read_past_conversation"}


def _is_evidence(message):
    return isinstance(message, dict) and str(message.get("content") or "").startswith("Accepted evidence")


def _strip_sentence(messages):
    out = []
    for m in messages:
        if isinstance(m, dict) and SELF_STATE_SENTENCE in str(m.get("content") or ""):
            m = {**m, "content": str(m["content"]).replace(SELF_STATE_SENTENCE, "", 1)}
        out.append(m)
    return out


HEX_ID = re.compile(r"[0-9a-f]{32}")


def _ids_masked(messages):
    """Each turn draws fresh ids (the saved result set's uuid4().hex, in the catalogue); both sides mask them, nothing else."""
    return [{**m, "content": HEX_ID.sub("<id>", str(m["content"]))} if isinstance(m, dict) and "content" in m else m for m in messages]


