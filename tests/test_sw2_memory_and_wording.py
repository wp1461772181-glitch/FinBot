"""SW2 S3 (R3, R4, R6; spec §3.3, §3.4, K4, K5): the owner's memory tools are in reach on every turn, the recall notes say
what a memory may carry, and the self-state sentence sits in the instruction behind its switch.

Pins P-R3/R4 (tool block and wording, on and off), P-R6 (instruction half), B10 (bot scope), B12 (structural exclusion).
Switches default on; the import-time texts (tool descriptions) are checked in a subprocess for the off state.
"""
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.agent_recall import note
from app.agent_system_prompt import INSTRUCTION, SELF_STATE_SENTENCE
from app.agent_workflow import direct, tools
from app.agent_workflow.claim_shadow_extract import select_sentences
from app.agent_workflow.state import AgentRuntimeContext
from test_sw1b_closing_complete import text

ROOT = Path(__file__).resolve().parents[1]
OWNER = "owner-credential"
MEMORY_TOOLS = {"recall_conversations", "read_past_conversation"}
# K4 and K5 wording, copied verbatim from accept-sw2-spec.md §1.
NOTE_ON = ("这些是以前对话的摘要和用户当时的提问，只用来知道聊过什么、在哪个对话。它们不是证据，不编号，不能引用；"
           "转述当时说过的话可以，注明是哪天的说法、不标 [n]；要把数字当作现在的事实写出，仍要在本轮重新读取并引用本轮的 [n]。")
NOTE_OFF = ("这些是以前对话的摘要和用户当时的提问，只用来知道聊过什么、在哪个对话。它们不是证据，不编号，不能引用；"
            "回答里的数字和事实仍要在本轮重新读取并引用本轮的 [n]。")
SELF_STATE_TEXT = ('关于你自己和本产品的状态（当前模型、bot 设定、研究队列、上一条回答的系统核对结果）、对过去对话的转述（注明哪一天），'
                   '以及标明为一般知识的句子，自成一句，不标 [n]，也不必说"没有证据编号"；这几类句子不能当作现在的事实来支撑财务结论，'
                   '要把数字当作现在的事实写出，照旧只用本轮工具结果并标 [n]。')


@pytest.fixture(autouse=True)
def _switches(monkeypatch):
    for name in ("FINBOT_SW2_HISTORY_PAGES", "FINBOT_SW2_MEMORY_PRELOAD", "FINBOT_SW2_SELF_STATE_WORDING", "FINBOT_SW2_SELF_STATE"):
        monkeypatch.delenv(name, raising=False)


def _rag_scope():
    return {"category": "A", "mode": "rag", "symbol": None, "symbols": [], "days_back": None}


def _run(monkeypatch, *, owner, tool_scope=None):
    """One rag turn whose model answers at once; returns the turn and the first request's offered tools and messages."""
    from app.agent_workflow.direct import Turn
    seen_tools, seen_messages = [], []
    monkeypatch.setattr(direct, "owner_credential_matches", lambda c: c == OWNER)
    monkeypatch.setattr(tools, "owner_credential_matches", lambda c: c == OWNER)
    turns = []
    original = Turn.finish

    def spy(self, *args, **kwargs):
        turns.append(self)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Turn, "finish", spy)

    def decide(messages, offered):
        seen_tools.append({t["function"]["name"] for t in offered})
        seen_messages.append(messages)
        return text("这是一个没有编号的简短回答。")

    async def emit(_event):
        pass
    ctx = AgentRuntimeContext("custom", "test", "dummy", identity_credential=OWNER if owner else "guest",
                              classifier=lambda _: _rag_scope(), decider=decide, tool_scope=tool_scope)
    asyncio.run(direct.run_direct_turn("上次聊 Intel 你说毛利率多少？现在还这么看吗？", ctx, emit=emit))
    return turns[-1], seen_tools[0], seen_messages[0]


def test_owner_turn_offers_the_memory_tools_from_the_first_request(monkeypatch, disposable_database):
    turn, offered, _ = _run(monkeypatch, owner=True)
    assert MEMORY_TOOLS <= offered
    assert "记忆与技能" in turn.audit["preloaded_categories"]


def test_switch_off_keeps_the_memory_tools_out_of_the_preload(monkeypatch, disposable_database):
    monkeypatch.setenv("FINBOT_SW2_MEMORY_PRELOAD", "off")
    turn, offered, _ = _run(monkeypatch, owner=True)
    assert not (MEMORY_TOOLS & offered)
    assert "记忆与技能" not in turn.audit["preloaded_categories"]


def test_guest_turn_never_gets_the_memory_tools(monkeypatch, disposable_database):
    turn, offered, _ = _run(monkeypatch, owner=False)
    assert not (MEMORY_TOOLS & offered)


def test_bot_scope_without_the_memory_tools_neither_preloads_nor_offers_them(monkeypatch, disposable_database):
    """B10: the visible filter keeps a bot's own scope, whatever the owner preload says."""
    turn, offered, _ = _run(monkeypatch, owner=True, tool_scope=frozenset({"search_knowledge", "calculate", "query_financials"}))
    assert not (MEMORY_TOOLS & offered)
    assert "记忆与技能" not in turn.audit["preloaded_categories"]


def test_self_state_sentence_is_in_the_instruction_the_model_sees(monkeypatch, disposable_database):
    _, _, messages = _run(monkeypatch, owner=False)
    system = "\n".join(str(m.get("content") or "") for m in messages if isinstance(m, dict) and m.get("role") == "system")
    assert SELF_STATE_SENTENCE in system


def test_recall_note_reads_the_switch_and_says_what_a_memory_may_carry(monkeypatch):
    assert note() == NOTE_ON
    monkeypatch.setenv("FINBOT_SW2_MEMORY_PRELOAD", "off")
    assert note() == NOTE_OFF


def test_self_state_sentence_text_is_the_accepted_wording():
    assert SELF_STATE_SENTENCE == SELF_STATE_TEXT and len(SELF_STATE_SENTENCE) == 151


def _instruction(monkeypatch, *, existence, wording):
    monkeypatch.setenv("FINBOT_SW1_EXISTENCE_KNOWLEDGE", "on" if existence else "off")
    monkeypatch.setenv("FINBOT_SW2_SELF_STATE_WORDING", "on" if wording else "off")
    return direct.evidence_instruction("\n".join(INSTRUCTION))


def test_self_state_sentence_follows_the_existence_sentence_when_that_is_in(monkeypatch):
    body = _instruction(monkeypatch, existence=True, wording=True)
    after = body.index(direct.EXISTENCE_INSTRUCTION) + len(direct.EXISTENCE_INSTRUCTION)
    assert body[after:].startswith(SELF_STATE_SENTENCE)


def test_self_state_sentence_follows_the_anchor_when_existence_is_off(monkeypatch):
    body = _instruction(monkeypatch, existence=False, wording=True)
    after = body.index(direct.EXISTENCE_ANCHOR) + len(direct.EXISTENCE_ANCHOR)
    assert body[after:].startswith(SELF_STATE_SENTENCE)
    assert direct.EXISTENCE_INSTRUCTION not in body


def test_wording_off_is_the_same_text_without_the_sentence(monkeypatch):
    on = _instruction(monkeypatch, existence=True, wording=True)
    off = _instruction(monkeypatch, existence=True, wording=False)
    assert SELF_STATE_SENTENCE not in off
    assert on.replace(SELF_STATE_SENTENCE, "", 1) == off
    assert len(on) - len(off) == len(SELF_STATE_SENTENCE)


@pytest.mark.parametrize("value,memory_tools_present,note_is_new", [("on", True, True), ("off", False, False)])
def test_tool_descriptions_follow_the_memory_switch_at_import(value, memory_tools_present, note_is_new):
    env = {**os.environ, "FINBOT_SW2_MEMORY_PRELOAD": value}
    code = ("from app.agent_tool_catalog import definitions;"
            "r=definitions()['recall_conversations'].description;"
            "p=definitions()['read_past_conversation'].description;"
            "print('retell it as what was said then' in r, 'Retelling what was said then is fine' in p)")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.split() == [str(note_is_new), str(note_is_new)]


def test_unnumbered_self_state_memory_and_general_knowledge_sentences_are_never_selected():
    """B12: a numbered fact is judged; an unnumbered self-state, memory retelling or general-knowledge sentence is not."""
    answer = ("当前回答模型是 haiku-5.5，不带编号。"
              "上次（五月十二日）说毛利率约 43%。"
              "按一般知识，公司通常每季度披露一次财报。"
              "Intel 第三季度毛利率为 42.97% [1]，营收为 129 亿美元 [1]。")
    citations = [{"ordinal": 1, "title": "10-Q", "source_type": "official_filing",
                  "quote": "毛利率 42.97%，营收 129 亿美元", "check_text": "毛利率 42.97%，营收 129 亿美元"}]
    candidates = select_sentences(answer, citations)[0]
    assert candidates, "the numbered fact sentences are selected"
    assert all("[1]" in c.text for c in candidates)
    assert not any("haiku" in c.text or "五月十二日" in c.text or "一般知识" in c.text for c in candidates)
