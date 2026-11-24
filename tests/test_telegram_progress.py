"""The Telegram progress message: old-engine steps as before, the kernel's sentences and checklist stacked in it."""
import asyncio
import types

from scripts import run_telegram_bridge as bridge

ACK, DONE = bridge.ACK_TEXT, bridge.DONE_TEXT


class _Rig:
    def __init__(self, monkeypatch):
        self.edits, self.now = [], 1000.0

        async def send_text(client, token, chat_id, text, inline_keyboard=None, *, markdown=True):
            return 7

        async def edit_text(client, token, chat_id, message_id, text):
            self.edits.append(text)

        monkeypatch.setattr(bridge, "_send_text", send_text)
        monkeypatch.setattr(bridge, "_edit_text", edit_text)
        # Only the bridge's own clock is faked; the event loop keeps the real one, so a trailing edit can really sleep.
        monkeypatch.setattr(bridge, "time", types.SimpleNamespace(monotonic=lambda: self.now))
        self.progress = bridge._Progress(None, "tok", 1)
        asyncio.run(self.progress.start())

    def ev(self, kind, data, wait=bridge.PROGRESS_MIN_INTERVAL + 1):
        self.now += wait
        asyncio.run(self.progress.on_event(kind, data))

    def finish(self):
        asyncio.run(self.progress.finish())


def _items(*pairs):
    return {"items": [{"text": t, "status": s} for t, s in pairs]}


def test_sentences_stack_in_one_message(monkeypatch):
    r = _Rig(monkeypatch)
    r.ev("narration", {"text": "先看财报"})
    r.ev("narration", {"text": "再比同行"})
    assert r.edits[-1] == f"{ACK}\n先看财报\n再比同行"


def test_checklist_marks_and_replacement(monkeypatch):
    r = _Rig(monkeypatch)
    r.ev("checklist", _items(("查财报", "done"), ("比同行", "doing"), ("写结论", "pending"), ("查传闻", "failed")))
    assert r.edits[-1] == f"{ACK}\n☑ 1 查财报\n◐ 2 比同行\n☐ 3 写结论\n☒ 4 查传闻"
    r.ev("checklist", _items(("查财报", "done")))
    assert r.edits[-1] == f"{ACK}\n☑ 1 查财报"


def test_checklist_comes_before_sentences(monkeypatch):
    r = _Rig(monkeypatch)
    r.ev("narration", {"text": "开始"})
    r.ev("checklist", _items(("a", "doing")))
    assert r.edits[-1] == f"{ACK}\n◐ 1 a\n开始"


def test_kernel_tool_names_never_shown(monkeypatch):
    r = _Rig(monkeypatch)
    r.ev("tool_start", {"name": "escalate"})
    r.ev("tool_start", {"name": "plan"})
    assert r.edits == []


def test_tool_start_does_not_edit_after_narration_or_checklist(monkeypatch):
    r = _Rig(monkeypatch)
    r.ev("narration", {"text": "一句"})
    n = len(r.edits)
    r.ev("tool_start", {"name": "query_financials"})
    r.ev("status", {"step": "x"})
    assert len(r.edits) == n
    r2 = _Rig(monkeypatch)
    r2.ev("checklist", _items(("a", "doing")))
    n = len(r2.edits)
    r2.ev("tool_start", {"name": "query_financials"})
    assert len(r2.edits) == n


def test_old_engine_sequence_unchanged(monkeypatch):
    r = _Rig(monkeypatch)
    r.ev("tool_start", {"name": "query_financials"})
    r.ev("status", {"step": "整理"})
    r.ev("tool_start", {"name": "query_financials"}, wait=0.1)     # inside the window: dropped, as today
    r.ev("tool_start", {"name": "search_news"})
    assert r.edits == [f"{ACK}\n正在调用：query_financials", f"{ACK}\n进展：整理", f"{ACK}\n正在调用：search_news"]
    r.finish()
    assert r.edits[-1] == DONE


def test_update_inside_throttle_window_shows_with_next_edit(monkeypatch):
    r = _Rig(monkeypatch)
    r.ev("narration", {"text": "甲"})
    r.ev("narration", {"text": "乙"}, wait=0.1)
    assert r.edits == [f"{ACK}\n甲"]
    r.ev("narration", {"text": "丙"})
    assert r.edits[-1] == f"{ACK}\n甲\n乙\n丙"


def test_finish_with_and_without_checklist(monkeypatch):
    r = _Rig(monkeypatch)
    r.ev("checklist", _items(("a", "done"), ("b", "doing")))
    r.ev("narration", {"text": "句子"})
    r.finish()
    assert r.edits[-1] == f"☑ 1 a\n◐ 2 b\n{DONE}"
    r2 = _Rig(monkeypatch)
    r2.ev("narration", {"text": "句子"})
    r2.finish()
    assert r2.edits[-1] == DONE


def test_last_six_sentences_only(monkeypatch):
    r = _Rig(monkeypatch)
    for i in range(9):
        r.ev("narration", {"text": f"s{i}"})
    assert r.edits[-1] == ACK + "\n" + "\n".join(f"s{i}" for i in range(3, 9))


def test_body_under_3500_chars_drops_oldest_sentences(monkeypatch):
    r = _Rig(monkeypatch)
    for i in range(6):
        r.ev("narration", {"text": f"{i}" + "字" * 1000})
    body = r.edits[-1]
    assert len(body) <= 3500
    assert body.endswith("5" + "字" * 1000)
    assert "\n0" + "字" not in body


def _in_one_loop(rig, monkeypatch, script):
    """Run ``script(progress)`` inside a single event loop, so a pending trailing edit can fire; a short interval stands in for the real one."""
    monkeypatch.setattr(bridge, "PROGRESS_MIN_INTERVAL", 0.02)

    async def main():
        rig.now += 100
        await script(rig.progress)

    asyncio.run(main())


def test_trailing_edit_shows_checklist_that_followed_a_narration_closely(monkeypatch):
    r = _Rig(monkeypatch)

    async def script(progress):
        await progress.on_event("narration", {"text": "先看财报"})
        await progress.on_event("checklist", _items(("查财报", "doing")))     # 1 ms later, inside the window
        assert r.edits == [f"{ACK}\n先看财报"]
        await asyncio.sleep(0.1)

    _in_one_loop(r, monkeypatch, script)
    assert r.edits == [f"{ACK}\n先看财报", f"{ACK}\n◐ 1 查财报\n先看财报"]


def test_throttled_updates_make_exactly_one_trailing_edit(monkeypatch):
    r = _Rig(monkeypatch)

    async def script(progress):
        await progress.on_event("narration", {"text": "甲"})
        await progress.on_event("narration", {"text": "乙"})
        await progress.on_event("checklist", _items(("a", "doing")))
        await progress.on_event("narration", {"text": "丙"})
        await asyncio.sleep(0.15)

    _in_one_loop(r, monkeypatch, script)
    assert r.edits == [f"{ACK}\n甲", f"{ACK}\n◐ 1 a\n甲\n乙\n丙"]


def test_finish_cancels_the_trailing_edit(monkeypatch):
    r = _Rig(monkeypatch)

    async def script(progress):
        await progress.on_event("narration", {"text": "甲"})
        await progress.on_event("narration", {"text": "乙"})
        await progress.finish()
        await asyncio.sleep(0.15)

    _in_one_loop(r, monkeypatch, script)
    assert r.edits == [f"{ACK}\n甲", DONE]


def test_trailing_edit_failure_does_not_raise(monkeypatch):
    r = _Rig(monkeypatch)

    async def broken(client, token, chat_id, message_id, text):
        if "乙" in text:
            raise RuntimeError("telegram down")
        r.edits.append(text)

    async def script(progress):
        await progress.on_event("narration", {"text": "甲"})
        monkeypatch.setattr(bridge, "_edit_text", broken)
        await progress.on_event("narration", {"text": "乙"})
        await asyncio.sleep(0.1)
        await progress.finish()

    _in_one_loop(r, monkeypatch, script)
    assert r.edits[-1] == DONE


def test_old_engine_update_inside_the_window_is_still_dropped(monkeypatch):
    r = _Rig(monkeypatch)

    async def script(progress):
        await progress.on_event("tool_start", {"name": "query_financials"})
        await progress.on_event("tool_start", {"name": "search_news"})
        await asyncio.sleep(0.1)

    _in_one_loop(r, monkeypatch, script)
    assert r.edits == [f"{ACK}\n正在调用：query_financials"]
