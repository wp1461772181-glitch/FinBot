import assert from "node:assert/strict";
import test from "node:test";
import { APPROVAL_TTL_MS } from "../src/approval-card.mjs";
import { turnPhase } from "../src/bloub-director.mjs";
import { awaiting, isOffline, turnSignal, unitsOf } from "../src/turn-signals.mjs";

const user = { role: "user", content: "hi" };
const asst = (extra = {}) => ({ role: "assistant", content: "", ...extra });
const call = (status, result = { data: [{ a: 1 }] }) => ({ name: "query_stock_prices", status, result });

test("phases of a running turn: thinking > tool > answer, read off the streaming message", () => {
  const sending = messages => turnSignal({ chatState: "sending", messages }).phase;
  assert.equal(sending([user]), "thinking");
  assert.equal(sending([user, asst()]), "thinking");
  assert.equal(sending([user, asst({ tool_trace: [call("running", null)] })]), "tool");
  assert.equal(sending([user, asst({ tool_trace: [call("complete")], content: "partial" })]), "answer");
  assert.equal(sending([user, asst({ tool_trace: [call("complete")] })]), "tool", "tools done, no text yet: still the tool beat");
  assert.equal(sending([user, asst({ content: "  " })]), "thinking");
});

test("verify: the last running node of the trace is verify or repair; it beats a running tool", () => {
  const trace = (...nodes) => nodes.map((n, i) => ({ id: `n${i}`, ...n }));
  const sending = m => turnSignal({ chatState: "sending", messages: [user, asst(m)] }).phase;
  assert.equal(sending({ trace: trace({ kind: "decide", status: "done" }, { kind: "verify", status: "running" }) }), "verify");
  assert.equal(sending({ trace: trace({ kind: "repair", status: "running" }) }), "verify");
  assert.equal(sending({ trace: trace({ kind: "tool", status: "running" }, { kind: "verify", status: "running" }), tool_trace: [call("running", null)] }), "verify", "verify beats tool");
  assert.equal(sending({ trace: trace({ kind: "verify", status: "running" }, { kind: "tool", status: "running" }), tool_trace: [call("running", null)] }), "tool", "only the LAST running node counts");
  assert.equal(sending({ trace: trace({ kind: "verify", status: "done" }), content: "text" }), "answer", "a finished check is not a phase");
  assert.equal(sending({ trace: trace({ kind: "verify", status: "failed" }) }), "thinking");
});

test("listening: the composer has focus and text and no turn runs; otherwise idle", () => {
  const base = { chatState: "ready", messages: [] };
  assert.equal(turnSignal({ ...base, draft: "hel", composerFocused: true }).phase, "listening");
  assert.equal(turnSignal({ ...base, draft: "hel", composerFocused: false }).phase, "idle");
  assert.equal(turnSignal({ ...base, draft: "   ", composerFocused: true }).phase, "idle");
  assert.equal(turnSignal({ ...base, draft: "", composerFocused: true }).phase, "idle");
  assert.equal(turnSignal({ chatState: "sending", messages: [user], draft: "next", composerFocused: true }).phase, "thinking", "a running turn is not interrupted by typing");
  assert.equal(turnSignal({ ...base, draft: "hel", composerFocused: true, offline: true }).phase, "idle", "offline does not listen");
  assert.equal(turnSignal().phase, "idle");
});

test("turnPhase (the old reading) keeps its answers: waiting / tool / answer / null", () => {
  assert.equal(turnPhase("ready", [user]), null);
  assert.equal(turnPhase("sending", [user]), "waiting");
  assert.equal(turnPhase("sending", [user, asst({ tool_trace: [call("running", null)] })]), "tool");
  assert.equal(turnPhase("sending", [user, asst({ content: "x" })]), "answer");
});

test("units: finished tool calls that brought something back; empty results and failures do not count", () => {
  assert.equal(unitsOf(asst({ tool_trace: [call("complete"), call("complete"), call("running", null)] })), 2);
  assert.equal(unitsOf(asst({ tool_trace: [call("complete", { data: [] })] })), 0, "an empty list is an empty result");
  assert.equal(unitsOf(asst({ tool_trace: [call("not_found", { data: [] }), call("failed", null), call("cancelled", null)] })), 0);
  assert.equal(unitsOf(asst({ tool_trace: [call("complete", { count: 0 }), call("complete", { error_code: "tool_timeout" }), call("complete", null)] })), 0);
  assert.equal(unitsOf(asst({ tool_trace: [call("complete", { job_status: "queued" }), call("complete", { count: 3 })] })), 2, "a card or job result is something");
  assert.equal(unitsOf(user), 0);
  assert.equal(unitsOf(asst()), 0);
  assert.equal(unitsOf(null), 0);
  assert.equal(turnSignal({ chatState: "sending", messages: [user, asst({ tool_trace: [call("complete"), call("running", null)] })] }).units, 1);
  assert.equal(turnSignal({ chatState: "ready", messages: [user, asst({ tool_trace: [call("complete")] })] }).units, 1, "still readable after the turn, for the closing motion");
});

test("offline: the connectivity flag, or a failed turn whose request never got an answer; nothing else", () => {
  assert.equal(isOffline({ backendDown: true, chatState: "ready", messages: [] }), true);
  assert.equal(isOffline({ chatState: "error", messages: [user, asst({ status: "failed", failure: { code: "x", message: "m", network: true } })] }), true);
  assert.equal(isOffline({ chatState: "error", messages: [user, asst({ status: "failed", failure: { code: "x", message: "m", network: false } })] }), false, "the server answered: it is there");
  assert.equal(isOffline({ chatState: "ready", messages: [user, asst({ failure: { network: true } })] }), false, "an old failure does not count once the chat recovered");
  assert.equal(isOffline(), false);
  assert.equal(turnSignal({ chatState: "ready", messages: [], offline: true }).offline, true);
});

test("awaiting: a waiting status or a card, until it expires (10 minutes from its arrival) or the user moves on", () => {
  const card = { request_id: "00000000-0000-4000-8000-000000000000", reason: "write_confirmation", choices: [] };
  const t0 = 1_000_000;
  assert.deepEqual(awaiting([user, asst({ status: "waiting_for_input" })], t0), { waiting: true, expiresAt: null });
  assert.deepEqual(awaiting([user, asst({ status: "waiting_for_user", clarification: card, card_at: t0 })], t0 + 1000), { waiting: true, expiresAt: t0 + APPROVAL_TTL_MS });
  assert.equal(awaiting([user, asst({ clarification: card, card_at: t0 })], t0 + APPROVAL_TTL_MS - 1).waiting, true);
  assert.equal(awaiting([user, asst({ clarification: card, card_at: t0 })], t0 + APPROVAL_TTL_MS).waiting, false, "expired");
  assert.equal(awaiting([user, asst({ clarification: card })], t0).waiting, true, "a card read back from the server has no clock");
  assert.equal(awaiting([user, asst({ clarification: card, card_at: t0 }), user], t0).waiting, false, "answered: a later message exists");
  assert.equal(awaiting([user, asst({ status: "complete" })], t0).waiting, false);
  assert.equal(awaiting([], t0).waiting, false);
  assert.equal(awaiting(undefined, t0).waiting, false);
});

import { announcement, runningTool } from "../src/turn-signals.mjs";
test("announcement: one sentence per phase, nothing for idle and listening, offline and waiting-for-you included", () => {
  assert.equal(announcement({ phase: "idle" }), null);
  assert.equal(announcement({ phase: "listening" }), null);
  assert.equal(announcement(), null);
  assert.deepEqual(announcement({ phase: "thinking" }), { phrase: "正在思考", detail: null });
  assert.deepEqual(announcement({ phase: "tool", tool: "query_stock_prices" }), { phrase: "正在调用工具", detail: "query_stock_prices" });
  assert.deepEqual(announcement({ phase: "tool" }), { phrase: "正在调用工具", detail: null });
  assert.deepEqual(announcement({ phase: "verify" }), { phrase: "正在核对证据", detail: null });
  assert.deepEqual(announcement({ phase: "answer" }), { phrase: "正在作答", detail: null });
  assert.deepEqual(announcement({ phase: "idle", waiting: true }), { phrase: "在等你确认", detail: null });
  assert.deepEqual(announcement({ phase: "thinking", waiting: true }), { phrase: "正在思考", detail: null }, "a running turn outranks the old card");
  assert.deepEqual(announcement({ phase: "tool", offline: true }), { phrase: "连接不上服务器", detail: null });
});

test("runningTool: the last tool still running in the streaming message", () => {
  assert.equal(runningTool([user, asst({ tool_trace: [{ name: "a", status: "complete" }, { name: "b", status: "running" }, { name: "c", status: "running" }] })]), "c");
  assert.equal(runningTool([user, asst({ tool_trace: [{ name: "a", status: "complete" }] })]), null);
  assert.equal(runningTool([user]), null);
  assert.equal(runningTool(undefined), null);
});
