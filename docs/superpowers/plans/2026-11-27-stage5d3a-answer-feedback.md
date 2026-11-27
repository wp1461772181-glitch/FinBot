# 5d-3a The owner's 「好／不好」 on an answer, kept on the server

**Goal:** The thumbs under an answer stop being a note in one browser (`localStorage`, `frontend/src/app/chat/Message.tsx` `giveFeedback`) and become the owner's verdict on the server, with an optional reason for 「不好」. He can also say it in a conversation on any channel (「刚才那个回答不好，数据太旧了」). The backstage 回答 tab shows it and filters 「被点不好的」. This is the data the 质量 tab (5d-3b) and the weekly self-check (5d-3c) read.

**Spec:** `docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md` §10.2 (「每条回答可以点『好／不好』，点『不好』时可以说一句原因」), §9.2 (筛选「被点了不好的」; 质量栏).

## Task 1 — the record (`app/answer_feedback.py`, new; pattern: `app/alert_feedback.py`)

- Table `answer_feedback`: `id`, `owner_hash`, `message_id` (the stored assistant answer row), `conversation_id`, `turn_id`, `verdict` (`good` | `bad`), `reason` (≤200, optional, only with `bad`), `channel` (`web` | `chat`), `created_at`, `updated_at`; unique (`owner_hash`, `message_id`). Pressing again with the other verdict changes it; the same verdict again changes nothing (a new reason replaces the old); `clear` removes his verdict (the web's second press on the same thumb).
- `record(owner_hash, conversation_id, turn_id, verdict, channel, reason=None)`: the turn's final answer (the last assistant row of that turn with text) in one of his conversations, stored by its `message_id`; else `None` (a turn with no answer, not his, a tool round). The web knows the turn id of every answer, also one it has just streamed and has no message id for yet, and the browser's old votes are keyed by turn id. `clear(owner_hash, conversation_id, turn_id)`. `of(owner_hash, message_ids) -> {id: {verdict, reason}}`. `resolve_last(owner_hash, conversation_id, before_turn)`: the newest answer of that conversation before the current turn.

## Task 2 — the web

- `PUT /agent-chat/conversations/{conversation_id}/turns/{turn_id}/feedback` `{verdict, reason?}` and `DELETE` on the same path (owner only; a guest keeps the local note as today). The history API passes `feedback` on each assistant message (next to where it passes `reconciliation`, `app/agent_chat_stream.py`).
- `Message.tsx`: the thumbs call the API and show the server's state; 「不好」 opens one small inline field 「哪里不好？（可不填）」 with 发送 / 跳过. A failed call says so and leaves the thumb as it was.
- The votes already in this browser's `localStorage` are sent once for the answers shown that have none on the server, then the local key is removed.
- Locale entries.

## Task 3 — saying it in a conversation (kernel, tier 1)

- `act` operation `rate_answer` {verdict, reason?}: the previous answer of this conversation (not the one being written). Tier 1 like `rate_alert` (it only touches his own feedback; reversible: 「那条改成好的」). The tool result names which answer it matched (its first line and time) so the model can say it.
- `operation_registry`: PUT and DELETE map to `rate_answer`.
- The old pipeline's bots do not get it (stage 6 retires that pipeline); said there, nothing is recorded — named in the report.

## Task 4 — the backstage 回答 tab

- List rows gain `feedback` (`good` | `bad` | null) and the filter `feedback=bad` (「被点不好的」); the detail shows the verdict and the reason.

## Every request format (collaboration rules §4.5)

- Web: PUT / DELETE above. Telegram: no button on answers (a row of buttons under every answer is noise); the sentence through the kernel. WeChat: the sentence through the kernel. Each gets a test.

## Tests

- `tests/test_answer_feedback.py`: record / change / same twice / clear / not his / a guest / a tool round / reason only with bad; `resolve_last`.
- API: PUT/DELETE, owner-only, history carries it.
- Kernel: `rate_answer` on the previous answer, the result names it, Telegram and WeChat sentence.
- Backstage: the row field, the filter, the detail.
- Frontend: thumbs call the API, the reason field, the one-time upload of local votes, a failed call.
