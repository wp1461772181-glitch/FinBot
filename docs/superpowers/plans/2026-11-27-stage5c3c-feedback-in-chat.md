# 5c-3c 「有用／没用」 said in a conversation (WeChat, and every other channel)

**Goal:** The owner says 「刚才英特尔那条没用」「今天的简报挺有用」 in any conversation (WeChat has no buttons) and it is recorded as the same verdict a button press records. Owner's decision 11-27: 「对话里说一句」.

**Spec:** 5c-3b (`docs/superpowers/plans/2026-11-27-stage5c3b-feedback.md`, merged): the `alert_feedback` store, `describe`, the wake reading the verdicts. Design §7.2 「每条提醒带『有用／没用』」.

**Why this shape (CLAUDE.md 准则 3):** the model only says *what* he meant (which stock, an alert or the brief, which verdict); **code** finds the message he means — the newest one that fits within 48 hours — and the tool result says exactly which one it matched, so he sees at once if it is the wrong one. The model does not have to read a list first, so the write stays a tier-1 direct operation (a read would put it on a card, and a card cannot be pressed in WeChat). No new format for the owner.

## Task 1 — resolve what he means (`app/alert_feedback.py`)

`resolve(owner, *, about: str = "alert", symbol: str | None = None, now: datetime | None = None) -> dict | None`, within `RESOLVE_WINDOW = timedelta(hours=48)`:

- `about == "brief"`: the newest `duty_brief` row of the owner with `outcome == "done"` and a `delivery_group` → `{"target": "outbox", "target_id": str(group), "kind": "brief", "symbol": None, "text": first line of its message, "at": created_at}`.
- `about == "alert"`: the newest of
  - sentinel alerts (`data/sentinel.db` `alerts`, read-only `mode=ro`, `created_at` in the window; with `symbol`, only rows whose `symbol.split("+")` contains it, upper-cased) → `target "sentinel"`, `target_id str(id)`, `kind` the alert kind, `text` its first line;
  - duty messages that reached him (`duty_log` rows with `decision == "tell_now"`, `mode == "on"`, `delivery in ("queued", "briefed")`, `delivery_group` set, in the window; with `symbol`, `event.symbol` or one of `event.members`) → `target "outbox"`, `target_id str(delivery_group)`, `kind "duty"`, `text` first line of `message`.
- None when nothing fits. A sentinel database that cannot be read leaves only the duty messages (logged, not raised).

`CHANNELS` (or wherever `record` checks the channel) gains `"chat"`.

## Task 2 — the operation `rate_alert` (tier 1)

Follow `record_view` end to end (it is the closest: tier 1, kernel-only, the owner's own words):

- `app/agent_tool_catalog.py`: args model `RateAlertArgs` — `verdict: Literal["useful", "not_useful"]`, `about: Literal["alert", "brief"] = "alert"`, `symbol: str | None` (1–12 chars, upper-cased, letters/digits/`.`/`-`), `quote: str` (1–200 chars: his words from this turn); kind `reversible`; description (English, like its neighbours): record the owner's verdict on an alert, a duty message or the morning brief that he states in this turn; `symbol` is the stock he names, left out when he names none (the newest one is meant); `about` is `brief` only when he speaks of the morning brief; the result names the message it matched — tell him which one in one line, and if he says it is the wrong one, call again with the symbol. Add to `OWNER_ONLY` and `KERNEL_ONLY`.
- `app/agent_bots.py`: add `rate_alert` wherever `record_view` is listed for the default scope.
- `app/kernel/act.py`: `TIER1` gains `rate_alert`; the summary line (Chinese, like the others): 「记下用户对某条提醒、值班消息或早间简报的『有用／没用』（他这轮亲口说的；不写股票就是最近一条）。记下后照工具返回的那句告诉他对上的是哪一条。」; the undo hint: 「说错了就说『那条改成有用／没用』。」; the card display (if it ever goes on a card): title 「记下提醒反馈」, target = what `resolve` matched.
- `app/agent_workflow/tools.py` (where `record_view` executes): `rate_alert` → `resolve(...)`; nothing found → a refusal whose message is 「最近 48 小时里没找到{symbol 或 空}{的提醒 / 的早间简报}。」; found → `record(owner, target, target_id, verdict, "chat", symbol=..., kind=..., text=...)`; when the target is a sentinel alert also acknowledge it (`sentinel.store.Store(db_path()).ack_alert(int(id))`; a failure is logged and does not fail the verdict); returns `{"recorded": f"{symbol or ''} {北京 时间 %m-%d %H:%M}「{text}」——{有用|没用}", "target": ..., "target_id": ...}`.
- `app/kernel/operation_registry.py`: `("POST", "/backstage/feedback")` becomes `_op("rate_alert")` (was a gap); `tests/test_operation_registry.py` `test_gaps_stay_visible` drops it again.

## Tests

- `tests/test_alert_feedback.py`: `resolve` — newest sentinel alert vs newer duty message (the newest wins); symbol match on a merged `A+B` alert; symbol on a duty message's members; `about="brief"` picks the newest done brief with a group; outside 48 h → None; an unreadable sentinel database still finds duty messages; the `chat` channel is accepted.
- Kernel act tests (follow the existing `record_view` tests, e.g. `tests/test_kernel_act*.py`): `rate_alert` with no read this turn runs at once and records with channel `chat`; after a read it goes onto the card (unchanged tier-1 rule); nothing found → the refusal sentence; a sentinel target is acknowledged; the result carries `recorded`.
- `tests/test_operation_registry.py`: the route maps to `rate_alert`; gaps list back to three.
- Ruler: unchanged suite (no new case needed); one shadow chat check by hand (`python -m ruler.run ask`): 「刚才英特尔那条提醒没用」 then 「不对，是特斯拉那条」 on the shadow database with a sentinel alert row written for both.
