"""A kernel turn's question is the last thing the model reads (2026-11-26).

In a long conversation the 10 KB layer-3 summary and the citation notes sent *after* the owner's question pulled the model away
from it: replaying one real request, 「顺便记一下：我只看美股」 called the memory tool 0 of 6 times as sent and 6 of 6 times with the
same blocks moved before the question.  Everything the system writes for the turn now comes before the question; the cache point
stays on the last message of the conversation proper, so the cached prefix is what it was."""
import json
from types import SimpleNamespace

import pytest

from app import agent_context as layers
from app.kernel import prompt

MEMORY = {"role": "user", "content": layers.MEMORY_MARKER + " of older turns...):\n1. 目标: 看半导体"}


def note(turn):
    return layers.inline_catalogue_message({"turn_id": turn, "opening": "a", "sources": []})


def ctx():
    return SimpleNamespace(identity_credential="")


def history(n):
    """n earlier turns, each answer followed by its note, then the question n+1 and the memory note the endpoint sends after it."""
    rows = []
    for i in range(1, n + 1):
        rows += [{"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": f"a{i}"}, note(f"t{i}")]
    return rows + [{"role": "user", "content": f"q{n + 1}"}, MEMORY]


def plain(messages):
    return [{k: v for k, v in m.items() if k != "cache_point"} for m in messages]


@pytest.fixture(autouse=True)
def on(monkeypatch):
    monkeypatch.delenv("FINBOT_KERNEL_QUESTION_LAST", raising=False)


def test_the_question_is_last_and_every_system_block_comes_before_it():
    built = prompt.build_messages("q4", ctx(), history(3), latest="系统最新掌握：NVDA")
    assert built[-1] == {"role": "user", "content": "q4"}
    assert built[-3]["content"] == MEMORY["content"]
    assert built[-2]["role"] == "system" and "系统最新掌握" in built[-2]["content"]
    assert sum(1 for m in built if m.get("content") == "q4") == 1


def test_the_cache_point_is_on_the_last_message_of_the_conversation_proper():
    built = prompt.build_messages("q4", ctx(), history(3), latest="系统最新掌握：NVDA")
    marked = [i for i, m in enumerate(built) if m.get("cache_point")]
    assert len(marked) == 1 and built[marked[0]]["content"] == note("t3")["content"]


def test_the_cached_prefix_holds_from_one_turn_to_the_next():
    three = prompt.build_messages("q4", ctx(), history(3), latest="块A")
    four = prompt.build_messages("q5", ctx(), history(4), latest="块B")
    end = next(i for i, m in enumerate(three) if m.get("cache_point")) + 1
    assert json.dumps(plain(four[:end]), ensure_ascii=False) == json.dumps(plain(three[:end]), ensure_ascii=False)


def test_a_card_press_still_ends_with_the_fact():
    rows = history(2)[:-2] + [{"role": "user", "content": "confirm:x"}]
    built = prompt.build_messages("confirm:x", ctx(), rows, fact="系统：已执行")
    assert built[-1] == {"role": "system", "content": "系统：已执行"}


def test_flag_off_the_blocks_stay_after_the_question(monkeypatch):
    monkeypatch.setenv("FINBOT_KERNEL_QUESTION_LAST", "off")
    built = prompt.build_messages("q4", ctx(), history(3), latest="系统最新掌握：NVDA")
    at = next(i for i, m in enumerate(built) if m.get("content") == "q4")
    assert built[at + 1]["content"] == MEMORY["content"] and "系统最新掌握" in built[-1]["content"]


def test_the_first_turn_keeps_its_blocks_after_the_question_so_none_leads_the_conversation():
    from app import anthropic_native
    built = prompt.build_messages("q1", ctx(), [], latest="系统最新掌握：NVDA")
    assert built[1] == {"role": "user", "content": "q1"} and "系统最新掌握" in built[-1]["content"]
    system, _ = anthropic_native.convert_messages(built, system_role=True)
    assert not any("系统最新掌握" in block["text"] for block in system)
