import assert from "node:assert/strict";
import test from "node:test";
import {
  ARCHETYPES, AURA_VARIANTS, EASINGS, PERSONA_PRESETS, REST_GAZES, TEMPO_MAX, TEMPO_MIN, VOL_HIGH, VOL_LOW,
  annualizedVolatility, archetypeOf, clearOverrides, derivePersona, presetFor, presetLook, readOverrides, readVolatility,
  trackedSymbol, volatilityBand, writeOverrides, writeVolatility
} from "../src/bot-persona.mjs";

// The five bots as the box has them (D6, 2026-11-13).
const BOTS = {
  finbot: { id: "ecc4d493-1e26-435d-99e9-cb5699ab7cc6", name: "FinBot", template: "blank", is_default: true, focus: { companies: [] }, default_company: null },
  news: { id: "ca3c9be3-97ea-4ce0-a624-ae6bfeb723e9", name: "NewsBot", template: "news_monitor", is_default: false, focus: { companies: [] }, default_company: null },
  apple: { id: "3694c439-f29e-49dd-9875-51b6c8a4f7fd", name: "AppleBot", template: "blank", is_default: false, focus: { companies: [{ symbol: "AAPL" }] }, default_company: null },
  report: { id: "67441a6d-b24a-4efc-a57c-bb9391313ece", name: "ReportBot", template: "earnings_reader", is_default: false, focus: { companies: [] }, default_company: null },
  tesla: { id: "c20935c6-c9f9-417c-a900-0afd5dcb5566", name: "TeslaBot", template: "company_researcher", is_default: false, focus: { companies: [] }, default_company: null }
};
const custom = (extra = {}) => ({ id: "11111111-aaaa-bbbb-cccc-000000000001", name: "我的 bot", template: "blank", is_default: false, focus: { companies: [] }, default_company: null, ...extra });
const memoryStorage = () => { const map = new Map(); return { getItem: k => map.has(k) ? map.get(k) : null, setItem: (k, v) => void map.set(k, String(v)), removeItem: k => void map.delete(k), map }; };

test("rules (6.4), first hit wins: default > news_monitor > earnings_reader > company > generalist", () => {
  assert.equal(archetypeOf(custom({ is_default: true, template: "news_monitor", default_company: { symbol: "AAPL" } })), "lead");
  assert.equal(archetypeOf(custom({ template: "news_monitor", default_company: { symbol: "AAPL" } })), "sentinel");
  assert.equal(archetypeOf(custom({ template: "earnings_reader", default_company: { symbol: "AAPL" } })), "reader");
  assert.equal(archetypeOf(custom({ default_company: { symbol: "AAPL" } })), "tracker");
  assert.equal(archetypeOf(custom({ template: "company_researcher" })), "tracker");
  assert.equal(archetypeOf(custom()), "generalist");
  assert.equal(archetypeOf(null), "generalist");
  // emoji / text avatars carry no extra weight: the record decides
  assert.equal(derivePersona({ ...custom(), avatar: "🐻" }).archetype, "generalist");
});

test("the five existing bots are pinned (D6): each gets its whole preset, source preset", () => {
  const expect = {
    finbot: ["lead", 1, "smooth", "follow", "ticks"], tesla: ["tracker", 1.25, "spring", "ahead-right", "speed-lines"],
    news: ["sentinel", 1.1, "step", "scan", "bulletin"], apple: ["tracker", 0.9, "smooth", "front", "halo"], report: ["reader", 0.8, "smooth", "down", "page-lines"]
  };
  for (const [key, [archetype, tempo, easing, restGaze, auraVariant]] of Object.entries(expect)) {
    assert.deepEqual(derivePersona(BOTS[key]), { archetype, tempo, easing, restGaze, auraVariant, source: "preset" }, key);
  }
  // TeslaBot has no focus company on the box: the pin is what makes it fast, not a volatility it cannot get
  assert.equal(trackedSymbol(BOTS.tesla), null);
  assert.equal(derivePersona(BOTS.tesla, { volatility: 0.1 }).tempo, 1.25, "a preset never goes through the derivation");
});

test("preset hit: by id, by name (whitespace and case ignored), and a renamed bot whose id is not in the table falls back to derivation", () => {
  assert.equal(presetFor({ id: BOTS.news.id, name: "something else" })?.name, "NewsBot", "by id, whatever the name says");
  assert.equal(presetFor({ id: "unknown", name: "  tesla bot " })?.name, "TeslaBot");
  assert.equal(presetFor({ id: "unknown", name: "APPLEBOT" })?.name, "AppleBot");
  assert.equal(presetFor({ id: "unknown", name: "Tesla" }), null);
  assert.equal(presetFor(null), null);
  const renamed = custom({ name: "市场哨兵", template: "news_monitor" });
  const persona = derivePersona(renamed);
  assert.equal(persona.source, "derived");
  assert.equal(persona.archetype, "sentinel");
  assert.equal(persona.easing, "step");
  assert.equal(persona.restGaze, "scan");
});

test("recommended looks: only presets have one; TeslaBot is capsule / rouge", () => {
  assert.deepEqual(presetLook(BOTS.tesla), { shape: "capsule", color: "rouge" });
  assert.deepEqual(presetLook({ name: "NewsBot" }), { shape: "triangle", color: "orange" });
  assert.equal(presetLook(custom()), null);
  assert.notEqual(presetLook(BOTS.tesla), PERSONA_PRESETS[1].look, "a copy: callers cannot edit the table");
});

test("volatility bands: above 45% fast (+ spring + speed-lines), below 25% calm (+ smooth + halo), in between standard (+ reticle)", () => {
  assert.equal(volatilityBand(0.7), "fast");
  assert.equal(volatilityBand(VOL_HIGH), "standard", "above 45%, strictly");
  assert.equal(volatilityBand(0.3), "standard");
  assert.equal(volatilityBand(VOL_LOW), "standard");
  assert.equal(volatilityBand(0.12), "calm");
  assert.equal(volatilityBand(NaN), null);
  assert.equal(volatilityBand(null), null);
  const tracker = custom({ id: "tracker-1", default_company: { symbol: "XYZ" } });
  const fast = derivePersona(tracker, { volatility: 0.6 });
  assert.deepEqual([fast.archetype, fast.tempo, fast.easing, fast.auraVariant], ["tracker", 1.25, "spring", "speed-lines"]);
  const standard = derivePersona(tracker, { volatility: 0.35 });
  assert.deepEqual([standard.tempo, standard.easing, standard.auraVariant], [1, "smooth", "reticle"]);
  const calm = derivePersona(tracker, { volatility: 0.18 });
  assert.deepEqual([calm.tempo, calm.easing, calm.auraVariant], [0.9, "smooth", "halo"]);
  assert.equal(fast.source, "derived");
});

test("without market data or a tracked company the id hash decides, inside the archetype's range, and the same id gives the same answer in any order", () => {
  const ids = Array.from({ length: 40 }, (_, i) => `bot-${i * 7919}`);
  const first = ids.map(id => derivePersona(custom({ id, default_company: { symbol: "XYZ" } })));
  const again = [...ids].reverse().map(id => derivePersona(custom({ id, default_company: { symbol: "XYZ" } }))).reverse();
  assert.deepEqual(first, again, "order of calls changes nothing");
  assert.deepEqual(derivePersona(custom({ id: "bot-1", default_company: { symbol: "XYZ" } })), derivePersona(custom({ id: "bot-1", default_company: { symbol: "XYZ" } })));
  // all three bands show up over 40 ids, and nothing leaves the allowed values
  assert.equal(new Set(first.map(p => p.auraVariant)).size, 3);
  for (const p of first) { assert.ok(["speed-lines", "halo", "reticle"].includes(p.auraVariant)); assert.ok(p.tempo >= TEMPO_MIN && p.tempo <= TEMPO_MAX); }
  // a tracker with a company but no stored volatility yet uses the hash too (not "standard" by default)
  assert.notDeepEqual(new Set(first.map(p => p.tempo)).size, 1);
  // other archetypes stay in their range
  for (const id of ids) {
    const g = derivePersona(custom({ id }));
    assert.equal(g.archetype, "generalist");
    assert.ok([0.9, 1, 1.1].includes(g.tempo)); assert.equal(g.easing, "smooth"); assert.ok(AURA_VARIANTS.generalist.includes(g.auraVariant));
    const s = derivePersona(custom({ id, template: "news_monitor" }));
    assert.equal(s.easing, "step"); assert.equal(s.restGaze, "scan"); assert.ok(AURA_VARIANTS.sentinel.includes(s.auraVariant));
    const r = derivePersona(custom({ id, template: "earnings_reader" }));
    assert.equal(r.restGaze, "down"); assert.ok(r.tempo <= 0.9 && r.tempo >= TEMPO_MIN);
  }
});

test("every persona is made of known values", () => {
  const all = [...Object.values(BOTS), custom(), custom({ template: "news_monitor" }), custom({ template: "company_researcher" })].map(bot => derivePersona(bot));
  for (const p of all) {
    assert.ok(ARCHETYPES.includes(p.archetype)); assert.ok(EASINGS.includes(p.easing)); assert.ok(REST_GAZES.includes(p.restGaze));
    assert.ok(AURA_VARIANTS[p.archetype].includes(p.auraVariant), `${p.archetype}/${p.auraVariant}`);
    assert.ok(p.tempo >= TEMPO_MIN && p.tempo <= TEMPO_MAX);
  }
});

test("overrides: a saved choice wins over a preset and a derivation; a new archetype brings its own gaze; bad values are ignored", () => {
  const tempo = derivePersona(BOTS.tesla, { overrides: { tempo: 0.9 } });
  assert.deepEqual([tempo.tempo, tempo.easing, tempo.archetype, tempo.source], [0.9, "spring", "tracker", "override"]);
  const swapped = derivePersona(BOTS.finbot, { overrides: { archetype: "sentinel", easing: "smooth" } });
  assert.deepEqual([swapped.archetype, swapped.restGaze, swapped.easing, swapped.source], ["sentinel", "scan", "smooth", "override"]);
  assert.ok(AURA_VARIANTS.sentinel.includes(swapped.auraVariant));
  assert.equal(derivePersona(BOTS.finbot, { overrides: { archetype: "wizard", tempo: 9, easing: "bounce" } }).source, "preset", "nothing valid, nothing overridden");
  assert.equal(derivePersona(BOTS.finbot, { overrides: "junk" }).source, "preset");
});

test("override storage: round trip, versioned key, clear, bad JSON and bad fields ignored, no storage is fine", () => {
  const storage = memoryStorage();
  assert.deepEqual(readOverrides(storage, "bot-1"), {});
  assert.deepEqual(writeOverrides(storage, "bot-1", { archetype: "reader", tempo: 1.1, easing: "spring", extra: 1 }), { archetype: "reader", tempo: 1.1, easing: "spring" });
  assert.deepEqual(readOverrides(storage, "bot-1"), { archetype: "reader", tempo: 1.1, easing: "spring" });
  assert.deepEqual(readOverrides(storage, "bot-2"), {}, "per bot");
  assert.ok([...storage.map.keys()].every(key => /:v1:/.test(key)), "the key carries a version");
  storage.setItem([...storage.map.keys()][0], "{not json");
  assert.deepEqual(readOverrides(storage, "bot-1"), {});
  storage.setItem([...storage.map.keys()][0], JSON.stringify({ archetype: "nope", tempo: "fast", easing: "step" }));
  assert.deepEqual(readOverrides(storage, "bot-1"), { easing: "step" });
  writeOverrides(storage, "bot-1", { tempo: 2 }); // out of range: nothing valid left, the entry goes away
  assert.equal(storage.map.size, 0);
  writeOverrides(storage, "bot-1", { tempo: 0.8 });
  assert.deepEqual(clearOverrides(storage, "bot-1"), {});
  assert.equal(storage.map.size, 0);
  assert.deepEqual(readOverrides(null, "bot-1"), {});
  assert.deepEqual(writeOverrides(undefined, "bot-1", { tempo: 1 }), { tempo: 1 });
  const broken = { getItem() { throw new Error("denied"); }, setItem() { throw new Error("denied"); }, removeItem() { throw new Error("denied"); } };
  assert.deepEqual(readOverrides(broken, "bot-1"), {});
  assert.doesNotThrow(() => writeOverrides(broken, "bot-1", { tempo: 1 }));
});

test("annualizedVolatility: stdev of the last 60 daily returns x sqrt(252)", () => {
  // returns alternate +2% / -2% (mean 0): sample stdev = 0.02 * sqrt(60 / 59)
  const closes = [100];
  for (let i = 0; i < 60; i++) closes.push(closes[i] * (i % 2 === 0 ? 1.02 : 0.98));
  const expected = 0.02 * Math.sqrt(60 / 59) * Math.sqrt(252);
  assert.ok(Math.abs(annualizedVolatility(closes) - expected) < 1e-9, `${annualizedVolatility(closes)} vs ${expected}`);
  assert.ok(Math.abs(expected - 0.3202) < 1e-3, "about 32%");
  // only the last 60 returns count: a wild older stretch changes nothing
  const noisy = [10, 40, 5, 90, ...closes];
  assert.ok(Math.abs(annualizedVolatility(noisy) - expected) < 1e-9);
  // a straight line of identical closes has no volatility
  assert.equal(annualizedVolatility(Array(30).fill(50)), 0);
  // too little data, junk, non-positive closes
  assert.equal(annualizedVolatility(closes.slice(0, 15)), null);
  assert.equal(annualizedVolatility(null), null);
  assert.equal(annualizedVolatility([100, "x", NaN, -1, 0]), null);
  assert.equal(volatilityBand(annualizedVolatility(closes)), "standard");
});

test("a computed volatility is stored per bot and symbol and kept (identity does not drift with the market)", () => {
  const storage = memoryStorage();
  assert.equal(readVolatility(storage, "bot-1", "TSLA"), null);
  assert.equal(writeVolatility(storage, "bot-1", "TSLA", 0.58), true);
  assert.equal(readVolatility(storage, "bot-1", "TSLA"), 0.58);
  assert.equal(readVolatility(storage, "bot-1", "AAPL"), null, "another symbol is a first time again");
  assert.equal(readVolatility(storage, "bot-2", "TSLA"), null);
  assert.equal(writeVolatility(storage, "bot-1", "TSLA", NaN), false);
  assert.equal(readVolatility(storage, "bot-1", "TSLA"), 0.58);
  storage.setItem([...storage.map.keys()][0], "garbage");
  assert.equal(readVolatility(storage, "bot-1", "TSLA"), null);
  assert.equal(readVolatility(null, "bot-1", "TSLA"), null);
});
