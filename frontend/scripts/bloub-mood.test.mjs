import assert from "node:assert/strict";
import test from "node:test";
import { CALM, HOLD, MOOD_MORPH, MOODS, moodAt } from "../src/bloub-mood.mjs";
import { BLOUB_EXPRESSIONS } from "../src/bloub-look.mjs";
import { createDirector, T } from "../src/bloub-director.mjs";

// Click-only / comic faces never enter a thinking sequence.
const BANNED = ["hilare", "excite", "colere", "triste", "effraye", "timide", "blase", "somnolent", "heureux"];

test("calm is the catalogue's neutral face", () => { assert.equal(CALM, "neutre"); assert.ok(BLOUB_EXPRESSIONS.includes(CALM)); });

test("work sequences: real catalogue ids, calm-adjacent only, no repeats back to back, no comic faces", () => {
  assert.deepEqual(Object.keys(MOODS).sort(), ["answer", "tool", "waiting"]);
  for (const [phase, seq] of Object.entries(MOODS)) {
    assert.ok(seq.length >= 2, phase);
    for (const id of seq) { assert.ok(BLOUB_EXPRESSIONS.includes(id), id); assert.ok(!BANNED.includes(id), id); assert.notEqual(id, CALM); }
    seq.forEach((id, i) => assert.notEqual(id, seq[(i + 1) % seq.length], `${phase} repeats ${id}`));
  }
});

test("smooth parameters: a morph is real (>= 0.5 s), shorter than the hold, so a face settles before the next", () => {
  assert.ok(MOOD_MORPH >= 0.5 && MOOD_MORPH <= 1.2);
  assert.ok(HOLD >= MOOD_MORPH * 2);
});

test("moodAt walks the phase sequence by hold time, looping, and is deterministic", () => {
  const seq = MOODS.waiting;
  assert.equal(moodAt("waiting", 0), seq[0]);
  assert.equal(moodAt("waiting", HOLD - 0.01), seq[0]);
  assert.equal(moodAt("waiting", HOLD + 0.01), seq[1]);
  assert.equal(moodAt("waiting", HOLD * seq.length + 0.01), seq[0]);
  assert.equal(moodAt("waiting", 3.3), moodAt("waiting", 3.3));
  assert.equal(moodAt("nope", 1), CALM); assert.equal(moodAt(null, 1), CALM); assert.equal(moodAt("waiting", -5), seq[0]);
});

const read = (d, t) => d.read(t);

test("idle base is always calm: idle, hovered, sleeping, unread, reduced motion", () => {
  const d = createDirector({ now: 0 });
  assert.equal(read(d, 0).expression, CALM);
  d.send({ type: "hover", value: true }, 1); assert.equal(read(d, 1.1).expression, CALM);
  d.send({ type: "click" }, 2); assert.equal(read(d, 2.1).expression, CALM);
  assert.equal(read(d, 200).expression, CALM);
  d.send({ type: "unread", value: true }, 201); assert.equal(read(d, 202).expression, CALM);
  const r = createDirector({ now: 0, reducedMotion: true });
  r.send({ type: "turn-start" }, 1); assert.equal(read(r, 3).expression, CALM);
});

test("while working (orbit) the face walks the sequence; it follows the phase and returns to calm after the turn", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "turn-start" }, 10);
  assert.equal(read(d, 10.5).expression, CALM);  // attention beat (wide): the state's own face
  const v = read(d, 11.2);
  assert.equal(v.state, "orbit"); assert.equal(v.expression, MOODS.waiting[0]); assert.equal(v.moodMorph, MOOD_MORPH);
  assert.equal(read(d, 10 + HOLD + 0.1).expression, MOODS.waiting[1]);
  d.send({ type: "phase", phase: "tool" }, 14);
  assert.equal(read(d, 14.1).expression, MOODS.tool[0]);
  assert.equal(read(d, 14 + HOLD + 0.1).expression, MOODS.tool[1]);
  d.send({ type: "turn-end", outcome: "done" }, 20);
  assert.equal(read(d, 20.5).expression, CALM); // wink's own face
  assert.equal(read(d, 20 + T.SUCCESS + 1).expression, CALM);
});

test("answer phase keeps the thinking body and still reports its sequence", () => {
  const d = createDirector({ now: 0 });
  d.send({ type: "turn-start" }, 0); d.send({ type: "phase", phase: "answer" }, 3);
  const v = read(d, 4); assert.equal(v.state, "thinking"); assert.equal(v.expression, MOODS.answer[0]);
});

// A1: one sequence set per archetype.
import { MOODS_BY_ARCHETYPE } from "../src/bloub-mood.mjs";
const PHASES = ["answer", "hold", "listen", "tool", "verify", "waiting"];

test("per archetype: five sets, each covering every phase, with catalogue ids, calm-adjacent, no repeat back to back", () => {
  assert.deepEqual(Object.keys(MOODS_BY_ARCHETYPE).sort(), ["generalist", "lead", "reader", "sentinel", "tracker"]);
  for (const [archetype, set] of Object.entries(MOODS_BY_ARCHETYPE)) {
    assert.deepEqual(Object.keys(set).sort(), PHASES, archetype);
    for (const [phase, seq] of Object.entries(set)) {
      assert.ok(seq.length >= 1, `${archetype}/${phase}`);
      for (const id of seq) { assert.ok(BLOUB_EXPRESSIONS.includes(id), id); assert.ok(!BANNED.includes(id), `${archetype}/${phase}: ${id}`); assert.notEqual(id, CALM); }
      if (seq.length > 1) seq.forEach((id, i) => assert.notEqual(id, seq[(i + 1) % seq.length], `${archetype}/${phase} repeats ${id}`));
    }
  }
});

test("per archetype: the lead's set is the global one; characters differ where the design says they do", () => {
  for (const phase of Object.keys(MOODS)) assert.deepEqual(MOODS_BY_ARCHETYPE.lead[phase], MOODS[phase]);
  assert.notDeepEqual(MOODS_BY_ARCHETYPE.tracker.tool, MOODS_BY_ARCHETYPE.lead.tool);
  assert.notDeepEqual(MOODS_BY_ARCHETYPE.sentinel.tool, MOODS_BY_ARCHETYPE.lead.tool);
  assert.notDeepEqual(MOODS_BY_ARCHETYPE.reader.verify, MOODS_BY_ARCHETYPE.lead.verify, "the reader's checking is its high moment: it alternates squint and focus");
  const sets = new Set(Object.values(MOODS_BY_ARCHETYPE).map(set => JSON.stringify(set)));
  assert.ok(sets.size >= 4, "at least four distinct sets (the generalist may share the lead's)");
});

test("moodAt(phase, elapsed, archetype): walks that archetype's sequence; a single face holds; unknown archetype or phase fall back", () => {
  const tool = MOODS_BY_ARCHETYPE.sentinel.tool;
  assert.equal(moodAt("tool", 0, "sentinel"), tool[0]);
  assert.equal(moodAt("tool", HOLD + 0.01, "sentinel"), tool[1]);
  assert.equal(moodAt("tool", HOLD * tool.length + 0.01, "sentinel"), tool[0], "loops");
  assert.equal(moodAt("listen", 0, "reader"), "attentif");
  assert.equal(moodAt("listen", 99, "reader"), "attentif");
  assert.equal(moodAt("tool", 0, "no-such-archetype"), MOODS.tool[0]);
  assert.equal(moodAt("tool", 0), MOODS.tool[0], "without an archetype: unchanged");
  assert.equal(moodAt("sleep", 0, "reader"), CALM);
});
