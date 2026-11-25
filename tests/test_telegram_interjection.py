"""3c: a second message sent while the bot is answering goes to the API at once; the bridge says what became of it."""
import asyncio

from scripts import run_telegram_bridge as bridge
from tests.test_telegram_bridge_flow import OWNER_ID, TOKEN, _Telegram, _Wire


def _msg(text):
    return {"chat": {"id": OWNER_ID, "type": "private"}, "from": {"id": OWNER_ID}, "text": text}


class _Rig:
    """The first message blocks on a gate; the second is answered by ``second(on_event)`` (events, then the answer)."""

    def __init__(self, monkeypatch, second):
        self.wire = _Wire(monkeypatch)
        self.gate = asyncio.Event()
        self.calls = []
        self.second = second
        self.runner = bridge.TurnRunner()
        monkeypatch.setattr(bridge, "_RUNNER", self.runner)
        monkeypatch.setattr(bridge, "BUSY_RETRY_DELAY", 0.01)

        async def ask_agent(client, credential, bot_id, text, on_event=None, **kw):
            self.calls.append(text)
            if text == "第一条":
                await self.gate.wait()
                return "答:第一条", [], "c-1"
            return await self.second(text, on_event, len(self.calls))

        monkeypatch.setattr(bridge, "_ask_agent", ask_agent)

    async def run(self, release_before_idle=True):
        telegram = _Telegram()
        for text in ("第一条", "第二条"):
            await bridge._handle_message(None, "cred", "owner", _msg(text), OWNER_ID, OWNER_ID, {}, telegram)
            await asyncio.sleep(0.02)
        return self

    async def finish(self):
        self.gate.set()
        await self.runner.wait_idle()
        return [t for _, t in self.wire.sends]


async def _emit(on_event, *events):
    for kind, data in events:
        await on_event(kind, data)


def test_a_second_message_is_posted_at_once_and_acknowledged_not_queued(monkeypatch):
    async def second(text, on_event, n):
        await _emit(on_event, ("received", {"message_id": "m2"}), ("merged", {"into_turn": "t1"}))
        return "", [], None

    async def go():
        rig = _Rig(monkeypatch, second)
        await rig.run()
        assert rig.calls == ["第一条", "第二条"]                      # posted while the first still runs
        texts = [t for _, t in rig.wire.sends]
        assert bridge.QUEUED_TEXT not in texts
        assert bridge.RECEIVED_TEXT in texts and bridge.MERGED_TEXT in texts
        return await rig.finish()

    texts = asyncio.run(go())
    assert texts.index(bridge.RECEIVED_TEXT) < texts.index(bridge.MERGED_TEXT)
    assert any(t.startswith("【助理】\n答:第一条") for t in texts)      # the first answer still arrives


def test_stopped_says_stopped(monkeypatch):
    async def second(text, on_event, n):
        await _emit(on_event, ("received", {"message_id": "m2"}), ("stopped", {}))
        return "", [], None

    texts = asyncio.run(_stop_scenario(monkeypatch, second))
    assert bridge.STOPPED_TEXT in texts and bridge.MERGED_TEXT not in texts


async def _stop_scenario(monkeypatch, second):
    rig = _Rig(monkeypatch, second)
    await rig.run()
    return await rig.finish()


def test_the_stopped_turns_own_partial_text_is_its_answer(monkeypatch):
    wire = _Wire(monkeypatch)

    async def ask_agent(client, credential, bot_id, text, on_event=None, **kw):
        await on_event("stopped", {})
        return "NVDA 的营收是 100\n\n好的，不做了。", [], "c-1"

    monkeypatch.setattr(bridge, "_ask_agent", ask_agent)
    asyncio.run(bridge._bot_turn(None, "cred", "owner", OWNER_ID, {}, _Telegram(), "b-default", "助理", "第一条", feedback=True))
    assert wire.sends[-1][1] == "【助理】\nNVDA 的营收是 100\n\n好的，不做了。"


def test_a_separate_answer_is_its_own_message_that_quotes_the_question(monkeypatch):
    async def second(text, on_event, n):
        await _emit(on_event, ("received", {"message_id": "m2"}), ("separate", {"turn_id": "t2"}))
        return "已记下 10 股 TSLA。", [], "c-1"

    texts = asyncio.run(_stop_scenario(monkeypatch, second))
    assert "【助理】\n回复：第二条\n\n已记下 10 股 TSLA。" in texts
    assert texts.index(bridge.RECEIVED_TEXT) < texts.index("【助理】\n回复：第二条\n\n已记下 10 股 TSLA。")


def test_a_long_quote_is_cut_to_one_short_line(monkeypatch):
    long_text = "另外帮我记一下\n我买了 10 股 TSLA " + "很长" * 40

    async def second(text, on_event, n):
        await _emit(on_event, ("received", {}), ("separate", {}))
        return "好。", [], "c-1"

    async def go():
        rig = _Rig(monkeypatch, second)
        telegram = _Telegram()
        await bridge._handle_message(None, "cred", "owner", _msg("第一条"), OWNER_ID, OWNER_ID, {}, telegram)
        await asyncio.sleep(0.02)
        await bridge._handle_message(None, "cred", "owner", _msg(long_text), OWNER_ID, OWNER_ID, {}, telegram)
        return await rig.finish()

    texts = asyncio.run(go())
    quote = next(t for t in texts if "回复：" in t).split("\n\n")[0].split("\n")[1]
    assert quote.startswith("回复：另外帮我记一下 我买了") and quote.endswith("…") and len(quote) <= 3 + bridge.QUOTE_CHARS + 1


def test_a_queued_message_is_told_how_many_are_ahead_then_answered(monkeypatch):
    async def second(text, on_event, n):
        await _emit(on_event, ("received", {}), ("separate", {}), ("queued", {"ahead": 3}))
        await asyncio.sleep(0.02)
        return "排到了。", [], "c-1"

    texts = asyncio.run(_stop_scenario(monkeypatch, second))
    assert "排队中（前面 3 件）" in texts
    assert texts.index("排队中（前面 3 件）") < texts.index("【助理】\n回复：第二条\n\n排到了。")


def test_the_first_answers_progress_message_keeps_working_while_the_second_runs(monkeypatch):
    async def second(text, on_event, n):
        await _emit(on_event, ("received", {}), ("merged", {}))
        return "", [], None

    async def go():
        rig = _Rig(monkeypatch, second)
        telegram = _Telegram()
        await bridge._handle_message(None, "cred", "owner", _msg("第一条"), OWNER_ID, OWNER_ID, {}, telegram)
        await asyncio.sleep(0.02)
        await bridge._handle_message(None, "cred", "owner", _msg("第二条"), OWNER_ID, OWNER_ID, {}, telegram)
        await asyncio.sleep(0.02)
        assert len(rig.wire.actions) == 1                   # the second has no typing indicator of its own
        await rig.finish()
        return rig.wire

    wire = asyncio.run(go())
    assert wire.edits[-1][1] == bridge.DONE_TEXT            # the first turn's placeholder is finished by the first turn
    assert wire.edits[-1][0] == 501                         # (the placeholder is the first message sent)


def test_the_second_answer_is_still_split_by_length(monkeypatch):
    big = "\n\n".join(f"第{i}段：" + "字" * 900 for i in range(8))

    async def second(text, on_event, n):
        await _emit(on_event, ("received", {}), ("separate", {}))
        return big, [], "c-1"

    texts = asyncio.run(_stop_scenario(monkeypatch, second))
    parts = [t for t in texts if t.startswith("【助理】") and "第0段" in t or "第7段" in t]
    assert len(parts) >= 2 and all(len(t) <= bridge.ANSWER_MAX_CHARS + 60 for t in texts)
    assert any("回复：第二条" in t for t in texts)


def test_an_engine_that_answers_409_still_queues_the_message_the_old_way(monkeypatch):
    async def second(text, on_event, n):
        if n == 2:
            raise bridge.ConversationBusy()
        return "答:第二条", [], "c-1"

    async def go():
        rig = _Rig(monkeypatch, second)
        await rig.run()
        assert bridge.QUEUED_TEXT in [t for _, t in rig.wire.sends]
        assert rig.calls == ["第一条", "第二条"]                  # tried once, refused
        texts = await rig.finish()
        assert rig.calls == ["第一条", "第二条", "第二条"]        # then waited its turn
        return texts

    texts = asyncio.run(go())
    assert bridge.RECEIVED_TEXT not in texts and "【助理】\n答:第二条" in texts
