"""Telegram: a single-choice clarification card (「请确认这次指代的公司」) gets one inline button per choice.

Before this, only the write cards (同意 / 取消) got buttons; a selection card went out as its question plus
「（这一步需要在网页里选择后确认。）」, and the user had to go to the web page or retype the question.  A press
now sends the choice's own ``reply:`` value to the card it belongs to, as the web page does
(frontend/src/chat-clarification.mjs ``selectedClarification``).  A card with ``options`` (the forecast
revision's ticked sources) still has no Telegram form and keeps the web note.
"""
import asyncio
import uuid

from scripts import run_telegram_bridge as bridge

OWNER_ID = 4343
OWNER_HASH = "p" * 64
CHOICES = ["特斯拉（TSLA）", "Tesla 电动车业务", "特斯拉能源业务"]
WEB_NOTE = "（这一步需要在网页里选择后确认。）"


class _Telegram:
    def __init__(self):
        self.replies = []

    def record_reply(self, owner, bot_id, text, message_id):
        self.replies.append((bot_id, text))


def _selection_card(choices=CHOICES, request_id=None):
    """The clarification frame as agent_chat_stream puts it on the wire (the keys the bridge reads)."""
    return {"request_id": request_id or str(uuid.uuid4()), "reason": "missing_information",
            "question": "请确认这次指代的公司。", "display": None,
            "choices": [{"label": label, "value": "reply:" + label} for label in choices]}


def _stream_with(card, conversation):
    events = [("conversation", {"conversation_id": conversation, "turn_id": "t-1"}),
              ("delta", {"text": "这次「它」指的是哪家公司？"}),
              ("clarification", card)]

    async def stream(client, credential, bot_id, text, **press):
        return bridge.format_turn(events)
    return stream


def _patch_telegram(monkeypatch, sent):
    async def send_text(client, bot_token, chat_id, text, inline_keyboard=None, *, markdown=True):
        sent.append((text, inline_keyboard))
        return 4000 + len(sent)

    async def answer_callback(*_):
        pass

    monkeypatch.setattr(bridge, "_send_text", send_text)
    monkeypatch.setattr(bridge, "_answer_callback", answer_callback)
    monkeypatch.setattr(bridge, "_bot_token_for_send", lambda owner_hash, tg: "123:x")


def _press(data):
    return {"id": "cb-sel", "from": {"id": OWNER_ID}, "data": data,
            "message": {"chat": {"id": OWNER_ID, "type": "private"}}}


def test_a_streamed_selection_card_gets_one_button_per_choice(monkeypatch):
    conversation = "tg-line-" + uuid.uuid4().hex[:8]
    card = _selection_card()
    sent, pending = [], {}
    _patch_telegram(monkeypatch, sent)
    monkeypatch.setattr(bridge, "_ask_agent", _stream_with(card, conversation))

    asyncio.run(bridge._bot_turn(None, "owner", OWNER_HASH, OWNER_ID, pending, _Telegram(), "b-1", "助理",
                                 "它是哪家公司"))

    text, keyboard = sent[-1]
    assert WEB_NOTE not in text and "网页" not in text
    assert len(keyboard) == len(CHOICES)
    assert [row[0]["text"] for row in keyboard] == CHOICES
    for row in keyboard:
        data = row[0]["callback_data"]
        assert len(data.encode()) <= 64
        # Telegram sees only the short id, never the choice's value or the card id.
        assert card["request_id"] not in data and "reply:" not in data
        entry = pending[data.split(":", 1)[1]]
        assert entry["card_id"] == card["request_id"] and entry["conversation_id"] == conversation
    assert sorted(entry["value"] for entry in pending.values()) == sorted("reply:" + c for c in CHOICES)


def test_a_long_choice_label_is_cut_to_twenty_characters_on_its_button(monkeypatch):
    conversation = "tg-line-" + uuid.uuid4().hex[:8]
    card = _selection_card(choices=["这是一个非常非常长的候选公司名称用于测试截断"])
    sent, pending = [], {}
    _patch_telegram(monkeypatch, sent)
    monkeypatch.setattr(bridge, "_ask_agent", _stream_with(card, conversation))

    asyncio.run(bridge._bot_turn(None, "owner", OWNER_HASH, OWNER_ID, pending, _Telegram(), "b-1", "助理", "哪个"))

    _, keyboard = sent[-1]
    assert keyboard[0][0]["text"] == "这是一个非常非常长的候选公司名称用于测试截断"[:20]


def test_pressing_a_selection_button_sends_that_choice_to_its_card(monkeypatch):
    conversation = "tg-line-" + uuid.uuid4().hex[:8]
    card = _selection_card()
    sent, asked, pending = [], [], {}
    _patch_telegram(monkeypatch, sent)
    monkeypatch.setattr(bridge, "_ask_agent", _stream_with(card, conversation))
    asyncio.run(bridge._bot_turn(None, "owner", OWNER_HASH, OWNER_ID, pending, _Telegram(), "b-1", "助理", "哪个"))
    _, keyboard = sent[-1]
    second = keyboard[1][0]["callback_data"]

    async def ask_agent(client, credential, bot_id, text, *, conversation_id=None, pending_request_id=None,
                        display_message=None, on_event=None):
        asked.append({"bot_id": bot_id, "text": text, "conversation_id": conversation_id,
                      "pending_request_id": pending_request_id, "display_message": display_message})
        return "好的，按 Tesla 电动车业务来查。", [], conversation

    monkeypatch.setattr(bridge, "_ask_agent", ask_agent)
    asyncio.run(bridge._handle_callback(None, _press(second), pending, OWNER_HASH, "owner", OWNER_ID, OWNER_ID,
                                        _Telegram()))

    # The press reaches the bot's line as the choice's own value, against the same card and conversation.
    assert asked == [{"bot_id": "b-1", "text": "reply:Tesla 电动车业务", "conversation_id": conversation,
                      "pending_request_id": card["request_id"], "display_message": "Tesla 电动车业务"}]
    # The card is used up: the other buttons of the card are gone, so a second press runs nothing.
    asyncio.run(bridge._handle_callback(None, _press(keyboard[0][0]["callback_data"]), pending, OWNER_HASH, "owner",
                                        OWNER_ID, OWNER_ID, _Telegram()))
    assert len(asked) == 1 and pending == {}


def test_a_multi_select_card_gets_no_buttons_and_keeps_the_web_note(monkeypatch):
    """The forecast revision card: ticked materials on the web, no Telegram form."""
    conversation = "tg-line-" + uuid.uuid4().hex[:8]
    card = {"request_id": str(uuid.uuid4()), "reason": "choose_revision_sources",
            "question": "选择用于修订的材料", "display": None,
            "options": [{"value": "1", "label": "材料甲"}, {"value": "2", "label": "材料乙"}],
            "choices": [{"label": "用所选材料修订", "value": "confirm:" + "t" * 40}]}
    sent, pending = [], {}
    _patch_telegram(monkeypatch, sent)
    monkeypatch.setattr(bridge, "_ask_agent", _stream_with(card, conversation))

    asyncio.run(bridge._bot_turn(None, "owner", OWNER_HASH, OWNER_ID, pending, _Telegram(), "b-1", "助理", "修订"))

    text, keyboard = sent[-1]
    assert keyboard is None and pending == {}
    assert text.endswith(WEB_NOTE)


def test_a_selection_card_with_no_choices_gets_no_buttons_and_keeps_the_web_note(monkeypatch):
    """A card the backend built with an empty choice list has nothing to render; the note stays."""
    conversation = "tg-line-" + uuid.uuid4().hex[:8]
    card = _selection_card(choices=[])
    sent, pending = [], {}
    _patch_telegram(monkeypatch, sent)
    monkeypatch.setattr(bridge, "_ask_agent", _stream_with(card, conversation))

    asyncio.run(bridge._bot_turn(None, "owner", OWNER_HASH, OWNER_ID, pending, _Telegram(), "b-1", "助理", "哪个"))

    text, keyboard = sent[-1]
    assert keyboard is None
    assert text.endswith(WEB_NOTE)
