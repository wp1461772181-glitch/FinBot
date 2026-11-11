"""FP2: the earlier conversation the answering model sees follows its window, and a long answer is cut head+tail."""
import asyncio
from app.agent_workflow import direct, truncation
from app.agent_workflow.state import AgentRuntimeContext
from app import agent_context as layers


async def emit(_):
    pass


def _ctx(**kwargs):
    return AgentRuntimeContext('custom', 'test', 'dummy', context_window=kwargs.pop('context_window', 128000), **kwargs)


# --- group 6: truncation.cut_head_tail -------------------------------------------------------------

def test_cut_head_tail_returns_short_text_unchanged():
    text = '短文本' * 10
    assert truncation.cut_head_tail(text, 10_000) == text
    assert truncation.cut_head_tail(text, len(text.encode())) == text


def test_cut_head_tail_returns_empty_when_the_budget_is_too_small():
    assert truncation.cut_head_tail('汉' * 20000, 500) == ''


def test_cut_head_tail_keeps_the_result_within_budget_for_four_byte_characters():
    text = '😀' * 2000                       # 8000 bytes; the 3-byte formula overshoots, the 4-byte one fits
    cut = truncation.cut_head_tail(text, 4000)
    assert cut and len(cut.encode()) <= 4000
    assert cut.startswith('😀') and cut.endswith('😀') and '中间省略' in cut


def test_cut_head_tail_keeps_the_real_end_of_the_text_not_the_whole_text():
    text = 'H' * 10000 + 'T' * 10000          # ASCII: 20000 bytes, budget 3000 -> keep 970, head 485, tail 485
    cut = truncation.cut_head_tail(text, 3000)
    assert cut != text and len(cut.encode()) <= 3000
    head, marker, tail = cut.split('\n')
    assert head == 'H' * 485 and tail == 'T' * 485
    assert marker == '…（中间省略 19030 字）…'
