import assert from "node:assert/strict";
import test from "node:test";
import { CURSORS, TRACES, doneLineState, periodFor, signatureOf, turnEndOutcome } from "../src/signature.mjs";
import { turnTransition } from "../src/bloub-director.mjs";
import { derivePersona } from "../src/bot-persona.mjs";

test("every persona archetype has a trace and a caret from the tables", () => {
  const samples = [
    { archetype: "lead", auraVariant: "ticks" }, { archetype: "tracker", auraVariant: "speed-lines" }, { archetype: "tracker", auraVariant: "halo" },
    { archetype: "tracker", auraVariant: "reticle" }, { archetype: "sentinel", auraVariant: "ticker" }, { archetype: "reader", auraVariant: "page-lines" },
    { archetype: "generalist", auraVariant: "orbit-dots" }, {}, null, undefined
  ];
  for (const persona of samples) { const s = signatureOf(persona); assert.ok(TRACES.includes(s.trace), JSON.stringify(persona)); assert.ok(CURSORS.includes(s.cursor), JSON.stringify(persona)); }
});

test("the five existing bots get the six-way table of 6.5 (traces) and 6.6 (carets)", () => {
  const bots = [
    [{ id: "default", name: "FinBot", is_default: true }, "candles", "bar"],
    [{ id: "tesla", name: "TeslaBot", template: "company_researcher", default_company: { symbol: "TSLA" } }, "streaks", "slant"],
    [{ id: "news", name: "NewsBot", template: "news_monitor" }, "steps", "underline"],
    [{ id: "apple", name: "AppleBot", template: "company_researcher", default_company: { symbol: "AAPL" } }, "arc", "hairline"],
    [{ id: "report", name: "ReportBot", template: "earnings_reader" }, "lines", "bar-block"]
  ];
  const seen = new Set();
  for (const [bot, trace, cursor] of bots) {
    const persona = derivePersona(bot);
    const s = signatureOf(persona);
    assert.deepEqual(s, { trace, cursor }, `${bot.name} -> ${persona.archetype}/${persona.auraVariant}`);
    seen.add(s.trace);
  }
  assert.equal(seen.size, 5, "five different traces");
});

test("a custom bot with no template is the generalist: three orbiting dots and the lead's bar; a standard tracker drifts", () => {
  assert.deepEqual(signatureOf(derivePersona({ id: "x1", name: "Mine" })), { trace: "orbit", cursor: "bar" });
  assert.deepEqual(signatureOf({ archetype: "tracker", auraVariant: "reticle" }), { trace: "drift", cursor: "slant" });
});

test("period = base / tempo: the quick bot's loop is shorter, the calm one's longer", () => {
  assert.equal(periodFor(1.2, 1), 1.2);
  assert.ok(Math.abs(periodFor(1.2, 1.25) - 0.96) < 1e-9);
  assert.ok(Math.abs(periodFor(1.2, 0.8) - 1.5) < 1e-9);
  assert.equal(periodFor(1.2, 0), 1.2); assert.equal(periodFor(1.2, NaN), 1.2); assert.equal(periodFor(1.2, "fast"), 1.2); assert.equal(periodFor(1.2, -1), 1.2);
});

const answer = (extra = {}) => [{ role: "user", content: "q" }, { role: "assistant", content: "a", status: "complete", ...extra }];

test("how a turn ended: error > cancel > waiting > partial > done", () => {
  assert.equal(turnEndOutcome("sending", "idle", answer()), "done");
  assert.equal(turnEndOutcome("sending", "idle", answer({ status: "partially_succeeded" })), "partial");
  assert.equal(turnEndOutcome("sending", "idle", answer({ status: "cancelled" })), "cancel");
  assert.equal(turnEndOutcome("sending", "idle", answer({ status: "waiting_for_user" })), "waiting");
  assert.equal(turnEndOutcome("sending", "idle", answer({ clarification: { request_id: "r" } })), "waiting");
  assert.equal(turnEndOutcome("sending", "idle", answer({ status: "failed" })), "error");
  assert.equal(turnEndOutcome("sending", "error", answer()), "error");
  assert.equal(turnEndOutcome("sending", "idle", [{ role: "user", content: "q" }]), "cancel");
  assert.equal(turnEndOutcome("sending", "idle", []), "cancel");
  assert.equal(turnEndOutcome("sending", "error", answer({ status: "partially_succeeded" })), "error", "error outranks partial");
});

test("no end without a running turn before it", () => {
  assert.equal(turnEndOutcome("idle", "idle", answer()), null);
  assert.equal(turnEndOutcome("idle", "sending", answer()), null);
  assert.equal(turnEndOutcome("sending", "sending", answer()), null);
  assert.equal(turnEndOutcome(undefined, "idle", answer()), null);
});

test("it agrees with the director's own reading of the same turn, so the line and the avatar never tell two stories", () => {
  const cases = [answer(), answer({ status: "partially_succeeded" }), answer({ status: "cancelled" }), answer({ status: "waiting_for_user" }), answer({ status: "waiting_for_input" }),
    answer({ clarification: { request_id: "r" } }), answer({ status: "failed" }), [{ role: "user", content: "q" }], [], answer({ status: undefined })];
  for (const next of ["idle", "error"]) for (const messages of cases) {
    const director = turnTransition("sending", next, messages);
    assert.equal(turnEndOutcome("sending", next, messages), director.outcome, `${next} / ${JSON.stringify(messages.at(-1))}`);
  }
});

test("the closing line: only a turn this tab has just seen end sweeps; history is a plain hairline", () => {
  const done = answer()[1];
  assert.equal(doneLineState(done), "plain");
  assert.equal(doneLineState(done, { ended: "done" }), "done");
  assert.equal(doneLineState(answer({ status: "partially_succeeded" })[1], { ended: "partial" }), "partial");
  assert.equal(doneLineState(answer({ status: "partially_succeeded" })[1]), "plain");
  assert.equal(doneLineState(done, { ended: "waiting" }), "plain", "a turn that waits for you does not sweep");
});

test("the closing line: a failure is its own colour and never sweeps; a stop or a running turn has none", () => {
  assert.equal(doneLineState(answer({ status: "failed" })[1]), "failed");
  assert.equal(doneLineState(answer({ status: "failed" })[1], { ended: "error" }), "failed");
  assert.equal(doneLineState(answer({ status: "failed", content: "" })[1]), "failed");
  assert.equal(doneLineState(answer({ status: "cancelled" })[1], { ended: "cancel" }), null);
  assert.equal(doneLineState(done(), { streaming: true }), null);
  assert.equal(doneLineState(answer({ status: "running" })[1]), null);
  assert.equal(doneLineState(answer({ status: "waiting_for_user" })[1]), null);
  assert.equal(doneLineState(answer({ content: "" })[1]), null);
  assert.equal(doneLineState(answer({ status: undefined })[1]), "plain", "an answer from before statuses existed");
  assert.equal(doneLineState(null), null);
  assert.equal(doneLineState({ role: "user", content: "q" }), null);
  function done() { return answer()[1]; }
});
