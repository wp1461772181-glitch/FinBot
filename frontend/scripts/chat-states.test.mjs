import test from "node:test";
import assert from "node:assert/strict";
import { botIdOfLine, externalSource, failureNeedsSettings, firstOfTurns, newTurnIds, newlyListed, retryPlan } from "../src/chat-states.mjs";

test("a routine's result names the task and its time; everything else is just an outside message", () => {
  assert.deepEqual(externalSource("【例行任务结果】「盘前新闻速览」2026-11-13 08:30"), { kind: "routine", name: "盘前新闻速览", time: "2026-11-13 08:30" });
  assert.deepEqual(externalSource("【例行任务结果】「盘前新闻速览」"), { kind: "routine", name: "盘前新闻速览", time: null });
  assert.deepEqual(externalSource("【例行任务结果】没有名字"), { kind: "external", name: null, time: null });
  assert.deepEqual(externalSource("帮我看一下 TSLA"), { kind: "external", name: null, time: null });
  assert.deepEqual(externalSource(undefined), { kind: "external", name: null, time: null });
});

test("a poll's new turns, and the message each starts at", () => {
  const before = [{ role: "user", content: "a", turn_id: "t1" }, { role: "assistant", content: "b", turn_id: "t1" }];
  const after = [...before, { role: "user", content: "c", turn_id: "t2" }, { role: "assistant", content: "d", turn_id: "t2" }, { role: "assistant", content: "e" }];
  assert.deepEqual(newTurnIds(before, after), ["t2"]);
  assert.deepEqual(newTurnIds(after, after), []);
  assert.deepEqual([...firstOfTurns(after, ["t2"])], [[2, "t2"]]);
  assert.deepEqual([...firstOfTurns(after, [])], []);
});

test("only a missing model, key or access sends the reader to the settings", () => {
  for (const code of ["model_not_configured", "model_key_missing", "model_not_found", "provider_invalid_key", "provider_model_access_denied", '"provider_invalid_key"']) assert.equal(failureNeedsSettings(code), true, code);
  for (const code of ["provider_timeout", "provider_rate_or_quota_error", "chat_capacity_reached", "Failed to fetch", "", undefined]) assert.equal(failureNeedsSettings(code), false, String(code));
});

test("retry takes the failed turn off and resends the user line it answered, as the same request", () => {
  const thread = [{ role: "user", content: "早一点的问题" }, { role: "assistant", content: "答", status: "complete" }, { role: "user", content: "最后的问题" }, { role: "assistant", content: "写了一半", status: "failed" }];
  const plan = retryPlan(thread, { content: "最后的问题" });
  assert.deepEqual([plan.base.length, plan.content, plan.pendingRequestId, plan.label], [2, "最后的问题", undefined, undefined]);
  // A card's answer keeps its request id and the label it shows.
  const card = [{ role: "user", content: "用所选的 2 份材料修订" }, { role: "assistant", content: "", status: "failed" }];
  const again = retryPlan(card, { content: "confirm:revise:1.3", pendingRequestId: "d0", label: "用所选的 2 份材料修订" });
  assert.deepEqual([again.content, again.pendingRequestId, again.label], ["confirm:revise:1.3", "d0", "用所选的 2 份材料修订"]);
  // The remembered request is not the last user line (the thread was reloaded): the line itself goes out, plain.
  const stale = retryPlan(thread, { content: "别的问题" });
  assert.deepEqual([stale.content, stale.pendingRequestId], ["最后的问题", undefined]);
});

test("nothing to retry unless the thread ends in a failed answer to a user line", () => {
  assert.equal(retryPlan([], null), null);
  assert.equal(retryPlan([{ role: "user", content: "q" }], null), null);
  assert.equal(retryPlan([{ role: "user", content: "q" }, { role: "assistant", content: "a", status: "complete" }], null), null);
  assert.equal(retryPlan([{ role: "user", content: "q" }, { role: "assistant", content: "a", status: "cancelled" }], null), null);
  assert.equal(retryPlan([{ role: "assistant", content: "", status: "failed" }], null), null);
});

test("lines that are new since the last look, and the bot a line names", () => {
  assert.deepEqual(newlyListed(["bot:a"], ["bot:a", "bot:b"]), ["bot:b"]);
  assert.deepEqual(newlyListed(undefined, ["bot:a"]), ["bot:a"]);
  assert.deepEqual(newlyListed(["bot:a"], []), []);
  assert.equal(botIdOfLine("bot:b0000000"), "b0000000");
  assert.equal(botIdOfLine("local"), null);
  assert.equal(botIdOfLine("conv:abc"), null);
});
