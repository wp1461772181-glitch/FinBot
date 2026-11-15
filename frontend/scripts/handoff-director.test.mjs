// The handoff in the director (design 6.7): the order and the times of a normal switch, a quick run of switches, landing in a working bot, in a bot
// that waits for you, in one with unread messages, and under reduced motion.
import test from "node:test";
import assert from "node:assert/strict";
import { T, createDirector, shouldArrive } from "../src/bloub-director.mjs";
import { HANDOFF } from "../src/handoff.mjs";
import { auraPhaseOf, createTracker } from "../src/aura/track.mjs";
import { derivePersona } from "../src/bot-persona.mjs";

const FIN = derivePersona({ id: "f", name: "FinBot", is_default: true });
const TESLA = derivePersona({ id: "t", name: "TeslaBot", template: "company_researcher", default_company: { symbol: "TSLA" } });
const NEWS = derivePersona({ id: "n", name: "NewsBot", template: "news_monitor" });
const APPLE = derivePersona({ id: "a", name: "AppleBot", template: "company_researcher", default_company: { symbol: "AAPL" } });
const walk = (d, from, to, step = 0.02) => { const out = []; for (let t = from; t <= to + 1e-9; t += step) out.push([Math.round(t * 1000) / 1000, d.read(t)]); return out; };
const phases = rows => rows.map(([, v]) => v.handoff?.phase ?? "none");
const firstAt = (rows, pick) => rows.find(([, v]) => pick(v))?.[0];

test("a normal switch: leave (old persona) -> swap (new persona, swirl) -> enter -> settle -> the new bot's rest; at the times of the table", () => {
  const d = createDirector({ now: 0, persona: FIN });
  d.send({ type: "handoff", persona: TESLA, at: 10 }, 10.01);
  const rows = walk(d, 10.02, 11.6);
  const order = [...new Set(phases(rows))];
  assert.deepEqual(order, ["leave", "swap", "enter", "settle", "none"]);
  assert.equal(rows[0][1].aura, "ticks", "the old aura variant while it leaves");
  assert.equal(rows[0][1].archetype, "lead");
  assert.equal(rows[0][1].handoff.from, "ticks");
  const swap = firstAt(rows, v => v.handoff?.phase === "swap"), enter = firstAt(rows, v => v.handoff?.phase === "enter"), done = firstAt(rows, v => !v.handoff);
  assert.ok(Math.abs(swap - 10 - HANDOFF.SWAP) < 0.03 && Math.abs(enter - 10 - HANDOFF.ENTER_AT) < 0.03 && Math.abs(done - 10 - HANDOFF.SWIRL_END) < 0.03, `${swap} ${enter} ${done}`);
  const after = rows.find(([, v]) => v.handoff?.phase === "swap")[1];
  assert.equal(after.aura, "speed-lines"); assert.equal(after.archetype, "tracker"); assert.equal(after.tempo, TESLA.tempo);
  assert.equal(after.state, "swirl", "the swirl rings carry the change");
  assert.equal(after.handoff.to, "speed-lines");
  const swirl = rows.filter(([, v]) => v.state === "swirl");
  assert.ok(swirl.at(-1)[0] - swirl[0][0] <= 1.2, "the swirl is gone by 1.3 s after the click");
  assert.equal(rows.at(-1)[1].state, "idle");
  assert.equal(rows.at(-1)[1].handoff, null);
});

test("the swirl waits for its time and takes the body for the rest of the handoff; the entrance plays inside it, not longer than 400 ms", () => {
  const d = createDirector({ now: 0, persona: FIN });
  d.send({ type: "handoff", persona: NEWS, at: 0 }, 0);
  assert.notEqual(d.read(0.05).state, "swirl", "the old bot is still leaving");
  assert.equal(d.read(0.2).state, "swirl");
  assert.equal(d.read(HANDOFF.SWIRL_END - 0.05).state, "swirl");
  const enter = walk(createDirectorFrom(NEWS), 0, 1.4).filter(([, v]) => v.handoff?.phase === "enter");
  assert.ok(enter.length > 0 && enter.at(-1)[0] - enter[0][0] <= HANDOFF.ENTER + 0.03);
  function createDirectorFrom(persona) { const x = createDirector({ now: 0, persona: FIN }); x.send({ type: "handoff", persona, at: 0 }, 0); return x; }
});

test("a quick run of switches goes to the last target; the one in between is never shown, and no aura of it is asked for", () => {
  const d = createDirector({ now: 0, persona: FIN });
  d.send({ type: "handoff", persona: TESLA, at: 5 }, 5);
  d.send({ type: "handoff", persona: NEWS, at: 5.08 }, 5.08);   // inside the exit: the target is replaced
  d.send({ type: "handoff", persona: APPLE, at: 5.2 }, 5.2);    // the second one is on screen: leave it for the last
  const rows = walk(d, 5.2, 6.8);
  assert.ok(!rows.some(([, v]) => v.aura === "ticker"), "NewsBot, in between, is never shown");
  assert.equal(rows.at(-1)[1].aura, "halo");
  assert.equal(rows.at(-1)[1].archetype, "tracker");
  assert.equal(rows.at(-1)[1].handoff, null);
  // the aura never sees the middle one's enter phase: only the persona that is current is ever asked to enter
  const tracker = createTracker(), variantsAtEnter = new Set();
  for (const [t, v] of rows) { const input = tracker.step({ clock: t, now: t, view: v, units: 0 }); if (input.phase === "enter") variantsAtEnter.add(v.aura); }
  assert.deepEqual([...variantsAtEnter], ["halo"]);
});

test("a redirect on a switch that has swapped carries the body pose over (no jump) and restarts the swap at once", () => {
  const d = createDirector({ now: 0, persona: FIN });
  d.send({ type: "handoff", persona: TESLA, at: 0 }, 0);
  const before = d.read(0.3);
  assert.equal(before.handoff.phase, "swap");
  d.send({ type: "handoff", persona: NEWS, at: 0.3 }, 0.3);
  const after = d.read(0.3);
  assert.equal(after.aura, "ticker", "the last target is the persona now");
  assert.equal(after.handoff.phase, "swap");
  assert.ok(after.handoff.carry && typeof after.handoff.carry.dx === "number", "the pose of the one in between is carried");
  assert.equal(after.state, "swirl", "the swirl goes on, it is not restarted");
});

test("landing in a working bot: no swirl, no entrance; the work pose at once, and the old aura still leaves", () => {
  const d = createDirector({ now: 0, persona: FIN });
  d.send({ type: "handoff", persona: TESLA, at: 0, quiet: true }, 0);
  d.send({ type: "turn-start", quiet: true }, 0);
  d.send({ type: "phase", phase: "tool" }, 0);
  const rows = walk(d, 0.02, 1.4);
  assert.ok(!rows.some(([, v]) => v.state === "swirl"), "no swirl");
  assert.ok(!rows.some(([, v]) => v.handoff?.phase === "enter"), "no entrance");
  assert.ok(rows.some(([, v]) => v.handoff?.phase === "leave"), "the old aura leaves");
  assert.equal(rows.at(-1)[1].pose, "tool");
  assert.equal(rows.at(-1)[1].aura, "speed-lines", "and it is the new bot that works");
  assert.equal(auraPhaseOf(rows.at(-1)[1]), "tool");
  assert.equal(rows.at(-1)[1].handoff, null, "the body is back at rest by 0.42 s");
});

test("landing in a bot that waits for you: the amber dot is there from the swap, the swirl plays around it, then the hold pose", () => {
  const d = createDirector({ now: 0, persona: FIN });
  d.send({ type: "handoff", persona: NEWS, at: 0 }, 0);
  d.send({ type: "hold" }, 0);
  assert.equal(d.read(0.05).waitingForUser, false, "the old body that is still leaving does not wear the new line's dot");
  const swap = d.read(0.25);
  assert.equal(swap.waitingForUser, true);
  assert.equal(swap.state, "swirl");
  const end = d.read(HANDOFF.SWIRL_END + 0.05);
  assert.equal(end.pose, "hold"); assert.equal(end.waitingForUser, true); assert.equal(end.handoff, null);
});

test("landing in a bot with unread messages: the eyes glance at the divider for 0.8 s after the handoff, then the unread dot", () => {
  const d = createDirector({ now: 0, persona: FIN });
  d.send({ type: "handoff", persona: NEWS, at: 0, unread: true }, 0);
  d.send({ type: "unread", value: true }, 0);
  assert.equal(d.read(0.5).pose, "handoff");
  const g = d.read(HANDOFF.SWIRL_END + 0.1);
  assert.equal(g.pose, "glance"); assert.equal(g.gaze, "below"); assert.equal(g.state, "idle");
  assert.equal(d.read(HANDOFF.SWIRL_END + HANDOFF.GLANCE + 0.1).pose, "notify");
  // without unread there is no glance
  const e = createDirector({ now: 0, persona: FIN });
  e.send({ type: "handoff", persona: NEWS, at: 0 }, 0);
  assert.equal(e.read(HANDOFF.SWIRL_END + 0.1).pose, "idle");
});

test("a turn that starts while the swirl plays takes the body (work outranks the handoff); what belonged to the old line is gone at the switch", () => {
  const d = createDirector({ now: 0, persona: FIN });
  d.send({ type: "turn-start" }, 0);
  d.send({ type: "phase", phase: "tool" }, 1);
  d.send({ type: "handoff", persona: NEWS, at: 2 }, 2);
  assert.notEqual(d.read(2.3).pose, "tool", "the old line's turn does not carry over");
  d.send({ type: "turn-start" }, 2.5);
  assert.equal(d.read(3.2).layer, "work");   // (the swirl is kept 0.6 s, the engine's morph floor, then the work pose takes over)
  assert.notEqual(d.read(3.2).state, "swirl");
});

test("reduced motion: the persona is swapped at once; there is no handoff, no swirl, no phase", () => {
  const d = createDirector({ now: 0, reducedMotion: true, persona: FIN });
  d.send({ type: "handoff", persona: TESLA, at: 0 }, 0);
  const v = d.read(0.01);
  assert.equal(v.handoff, null); assert.equal(v.aura, "speed-lines"); assert.equal(v.state, "idle");
  for (const [, view] of walk(d, 0, 1.5)) assert.equal(view.handoff, null);
});

test("the persona event swaps the personality silently (a volatility that arrived late); during an exit it changes the target", () => {
  const d = createDirector({ now: 0, persona: TESLA });
  d.send({ type: "persona", persona: APPLE }, 1);
  assert.equal(d.read(1.1).aura, "halo");
  d.send({ type: "handoff", persona: FIN, at: 2 }, 2);
  d.send({ type: "persona", persona: NEWS }, 2.05);
  assert.equal(d.read(2.3).aura, "ticker");
});

test("the arrival does not play on a switch: the bot is marked as met and nothing plays; the first bot of a page and the hero avatar still arrive", () => {
  const seen = new Set();
  assert.equal(shouldArrive(seen, "a", false), true, "first bot of the page");
  assert.equal(shouldArrive(seen, "b", false, true), false, "switching to a new bot: the handoff plays instead");
  assert.equal(shouldArrive(seen, "b", false), false, "and it is met now");
  assert.equal(shouldArrive(seen, "c", false), true, "an empty-state hero avatar (its own instance) still arrives");
  assert.equal(shouldArrive(seen, "d", true, true), false);
  assert.equal(shouldArrive(seen, "d", false), true, "reduced motion consumed nothing");
});

test("the aura phase of the view: leave then enter around the swap; the swirl and the rest are the state's own", () => {
  const d = createDirector({ now: 0, persona: FIN });
  d.send({ type: "handoff", persona: NEWS, at: 0 }, 0);
  assert.equal(auraPhaseOf(d.read(0.05)), "leave");
  assert.equal(auraPhaseOf(d.read(0.25)), "leave", "stays gone while the swirl takes the body");
  assert.equal(auraPhaseOf(d.read(0.5)), "enter");
  assert.equal(auraPhaseOf(d.read(1.0)), "idle");
  assert.equal(auraPhaseOf(d.read(0.05), { still: true }), "idle");
  const tracker = createTracker();
  const leave = tracker.step({ clock: 3, now: 0, view: d.read(0.05), units: 0 });
  assert.equal(leave.phase, "leave"); assert.ok(Math.abs(leave.t - 0.05 * d.read(0.05).tempo) < 1e-6, "the aura's time is the handoff's, not the avatar clock");
  assert.ok(T.DWELL > 0);
});

test("the click is heard before the page changes: the old aura leaves at once, the persona arrives later; a late arrival still plays the whole swap, the swirl and the entrance", () => {
  const d = createDirector({ now: 0, persona: FIN });
  d.send({ type: "handoff-begin", at: 10 }, 10.0);
  assert.equal(d.read(10.05).handoff.phase, "leave");
  assert.equal(d.read(10.05).handoff.to, null);
  const waiting = d.read(10.3);                       // the page has not changed yet: still the old bot, the exit pose held, no new aura, no swirl
  assert.equal(waiting.handoff.phase, "leave"); assert.equal(waiting.aura, "ticks"); assert.notEqual(waiting.state, "swirl");
  d.send({ type: "handoff", persona: TESLA, at: 10 }, 10.35); // 350 ms after the click
  const rows = walk(d, 10.36, 12.0);
  assert.deepEqual([...new Set(phases(rows))], ["swap", "enter", "settle", "none"].filter(p => phases(rows).includes(p)));
  assert.ok(rows.filter(([, v]) => v.state === "swirl").length > 40, "the swirl plays (about a second)");
  assert.ok(firstAt(rows, v => v.handoff?.phase === "enter") - 10.35 < HANDOFF.ENTER_AT, "the entrance follows the swap by the normal time");
  assert.equal(rows.at(-1)[1].aura, "speed-lines");
});

test("a switch that was asked for and never came is forgotten: the avatar stays what it was", () => {
  const d = createDirector({ now: 0, persona: FIN });
  d.send({ type: "handoff-begin", at: 1 }, 1);
  assert.ok(d.read(1.1).handoff);
  assert.equal(d.read(1 + HANDOFF.NEVER + 0.05).handoff, null);
  assert.equal(d.read(1 + HANDOFF.NEVER + 0.05).aura, "ticks");
  const r = createDirector({ now: 0, reducedMotion: true, persona: FIN });
  r.send({ type: "handoff-begin", at: 1 }, 1);
  assert.equal(r.read(1.05).handoff, null, "reduced motion: nothing plays");
});
