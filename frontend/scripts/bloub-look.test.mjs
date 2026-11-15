import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { BLOUB_COLORS, CALM_EXPRESSION, faceLook, BLOUB_SHAPES, bloubLook, bloubState, hashString, BLOUB_EXPRESSIONS, BLOUB_STATES, DEFAULT_LOOK,
  defaultLook, normalizeLook, resolveLook, pickLook, sameLook, lookForSave, randomLook } from "../src/bloub-look.mjs";

const vendored = file => readFile(new URL(`../src/bloub/${file}`, import.meta.url), "utf8");
const ids = (source, from, to) => [...source.slice(source.indexOf(from), source.indexOf(to)).matchAll(/id: '([a-z]+)'/g)].map(m => m[1]);

test("hashString is stable and non-negative", () => {
  assert.equal(hashString("bot-1"), hashString("bot-1"));
  assert.ok(hashString("x") >= 0);
  assert.notEqual(hashString("a"), hashString("b"));
});

test("the catalog is the whole vendored bloub catalog: 8 shapes, 12 colours, 16 expressions, 14 states (+ swirl)", async () => {
  const skins = await vendored("skins.ts"), expressions = await vendored("expressions.ts"), states = await vendored("states.ts");
  assert.deepEqual(BLOUB_SHAPES, ids(skins, "export const SHAPES", "export const SHAPE_BY_ID"));
  assert.deepEqual(BLOUB_COLORS, ids(skins, "export const COLORS", "export const COLOR_BY_ID"));
  assert.deepEqual(BLOUB_EXPRESSIONS, ids(expressions, "export const EXPRESSIONS", "export const EXPRESSION_BY_ID"));
  const listed = [...states.slice(states.indexOf("export const SEQUENCE")).matchAll(/'([a-z]+)'/g)].map(m => m[1]);
  assert.deepEqual([...BLOUB_STATES].sort(), [...new Set([...listed, "swirl"])].sort());
  assert.equal(BLOUB_SHAPES.length, 8); assert.equal(BLOUB_COLORS.length, 12); assert.equal(BLOUB_EXPRESSIONS.length, 16);
  assert.equal(BLOUB_STATES.filter(s => s !== "swirl").length, 14);
});

test("a bot's look is stable and drawn from the known shapes/colours", () => {
  const a = bloubLook("bot-123", "bot:kline-idle");
  assert.deepEqual(a, bloubLook("bot-123", "bot:kline-idle"));
  assert.ok(BLOUB_SHAPES.includes(a.shape));
  assert.ok(BLOUB_COLORS.includes(a.color));
});

test("different bots look different (shape+colour pairs spread out)", () => {
  const seen = new Set();
  for (let i = 0; i < 24; i++) { const l = bloubLook(`bot-${i}`, "bot:kline-idle"); seen.add(`${l.shape}/${l.color}`); }
  assert.ok(seen.size >= 12, `only ${seen.size} distinct looks`);
});

test("an explicit non-default face choice maps to a fixed look; legacy/default use the hash", () => {
  const picked = bloubLook("any-id", "bot:square-focus");
  assert.deepEqual(picked, bloubLook("other-id", "bot:square-focus"));
  assert.notDeepEqual(bloubLook("a", "orb:green"), bloubLook("zzzz-b", "orb:green"));
  assert.notDeepEqual(bloubLook("a", ""), bloubLook("zzzz-b", ""));
});

test("state: idle by default, orbit while running, notify when unread and not busy", () => {
  assert.equal(bloubState({}), "idle");
  assert.equal(bloubState({ running: true }), "orbit");
  assert.equal(bloubState({ unread: true }), "notify");
  assert.equal(bloubState({ running: true, unread: true }), "orbit");
});

test("faceLook matches an explicit avatar's look", () => {
  assert.deepEqual(faceLook("square", "focus"), bloubLook("x", "bot:square-focus"));
});

test("the hash only supplies the default: it reaches every shape and colour of the full catalog, looks carry no expression", () => {
  const shapes = new Set(), colors = new Set();
  for (let i = 0; i < 400; i++) { const l = defaultLook(`bot-${i}`); shapes.add(l.shape); colors.add(l.color); assert.deepEqual(Object.keys(l).sort(), ["color", "shape"]); }
  assert.equal(shapes.size, BLOUB_SHAPES.length);
  assert.equal(colors.size, BLOUB_COLORS.length);
});

test("normalizeLook keeps shape + colour only and ignores any stored expression; anything else is refused", () => {
  assert.deepEqual(normalizeLook({ shape: "nuage", color: "creme" }), { shape: "nuage", color: "creme" });
  assert.deepEqual(normalizeLook({ shape: "nuage", color: "creme", expression: "hilare" }), { shape: "nuage", color: "creme" });
  assert.deepEqual(normalizeLook({ shape: "nuage", color: "creme", expression: "angry" }), { shape: "nuage", color: "creme" });
  for (const bad of [null, undefined, "nuage", [], {}, { shape: "nuage" }, { shape: "star", color: "bleu" }, { shape: "nuage", color: "neon" }]) assert.equal(normalizeLook(bad), null);
});

test("an old stored look with a non-calm expression still renders the calm base (expression ignored, shape + colour kept)", () => {
  for (const old of ["colere", "hilare", "somnolent", "effraye"]) {
    const look = resolveLook("id-1", "bot:square-focus", { shape: "triangle", color: "gris", expression: old });
    assert.deepEqual(look, { shape: "triangle", color: "gris" });
    assert.equal(look.expression, undefined);
  }
  assert.equal(CALM_EXPRESSION, "neutre");
});

test("a stored look wins over everything; with none, an explicit legacy face, then the hash", () => {
  const stored = { shape: "triangle", color: "gris" };
  assert.deepEqual(resolveLook("id-1", "bot:square-focus", stored), stored);
  assert.deepEqual(resolveLook("id-1", "", stored), stored);
  assert.deepEqual(resolveLook("id-1", "bot:square-focus", null), faceLook("square", "focus"));
  assert.deepEqual(resolveLook("id-1", "bot:kline-idle", null), defaultLook("id-1"));
  assert.deepEqual(resolveLook("id-1", "bot:kline-idle", { shape: "star" }), defaultLook("id-1")); // a broken stored value never blanks the avatar
});

test("choosing the default combination explicitly counts as chosen (the ux3 quirk)", () => {
  const chosen = { ...DEFAULT_LOOK };
  // The hash of this id is not the default look, yet the stored default combination is what shows.
  const id = Array.from({ length: 50 }, (_, i) => `q-${i}`).find(x => !sameLook(defaultLook(x), DEFAULT_LOOK));
  assert.ok(id);
  assert.deepEqual(resolveLook(id, "bot:kline-idle", chosen), DEFAULT_LOOK);
  assert.notDeepEqual(resolveLook(id, "bot:kline-idle", null), DEFAULT_LOOK);
});

test("selector state: picking changes shape or colour only; an expression pick is refused; pure", () => {
  const base = { shape: "cercle", color: "encre" };
  assert.deepEqual(pickLook(base, "shape", "goutte"), { shape: "goutte", color: "encre" });
  assert.deepEqual(pickLook(base, "color", "rose"), { shape: "cercle", color: "rose" });
  assert.equal(pickLook(base, "expression", "timide"), base);
  assert.equal(pickLook(base, "shape", "star"), base);
  assert.equal(pickLook(base, "mood", "x"), base);
  assert.deepEqual(base, { shape: "cercle", color: "encre" });
});

test("lookForSave: nothing picked sends nothing; any pick is written without an expression", () => {
  assert.equal(lookForSave(null, null), undefined);
  assert.equal(lookForSave(undefined, { shape: "nuage", color: "bleu" }), undefined);
  assert.deepEqual(lookForSave({ ...DEFAULT_LOOK }, null), DEFAULT_LOOK); // explicit default combination is a choice
  const hashed = defaultLook("some-bot");
  assert.deepEqual(lookForSave(hashed, null), hashed);
  const stored = { shape: "nuage", color: "bleu" };
  assert.equal(lookForSave({ ...stored }, stored), undefined);
  assert.equal(lookForSave({ ...stored, expression: "colere" }, { ...stored, expression: "fier" }), undefined); // expression never counts as a change
  assert.deepEqual(lookForSave({ ...stored, color: "vert", expression: "colere" }, stored), { shape: "nuage", color: "vert" });
  assert.equal(lookForSave({ shape: "star" }, null), undefined);
});

test("randomLook covers the catalog, has no expression, and only ever returns valid looks", () => {
  let seed = 1; const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const shapes = new Set(), colors = new Set();
  for (let i = 0; i < 400; i++) { const l = randomLook(rand); assert.deepEqual(normalizeLook(l), l); assert.equal(l.expression, undefined); shapes.add(l.shape); colors.add(l.color); }
  assert.equal(shapes.size, 8); assert.equal(colors.size, 12);
  assert.ok(normalizeLook(randomLook(() => 0.999999)) && normalizeLook(randomLook(() => 0)));
});

test("the customiser labels every catalog id, and every label has an English phrase", async () => {
  const source = await readFile(new URL("../src/BloubCustomizer.tsx", import.meta.url), "utf8");
  const english = JSON.parse(await readFile(new URL("../src/locales/en-US.json", import.meta.url), "utf8"));
  const table = name => Object.fromEntries([...source.match(new RegExp(`${name}: Record<string, string> = \\{([^}]*)\\}`))[1].matchAll(/(\w+): "([^"]+)"/g)].map(m => [m[1], m[2]]));
  for (const [name, ids] of [["SHAPE_LABELS", BLOUB_SHAPES], ["COLOR_LABELS", BLOUB_COLORS]]) {
    const labels = table(name);
    assert.deepEqual(Object.keys(labels).sort(), [...ids].sort(), name);
    for (const zh of Object.values(labels)) assert.ok(english[zh]?.trim(), `no English for ${zh}`);
  }
  for (const heading of ["形状", "颜色"]) assert.ok(english[heading]);
});

test("the customiser has no expression picker", async () => {
  const source = await readFile(new URL("../src/BloubCustomizer.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /expression|EXPRESSION|BLOUB_EXPRESSIONS/i);
});

// A1: the look of a bot resolves in four steps — stored, a preset bot's recommended look, an explicit old face pick, the id hash.
const TESLA_ID = "c20935c6-c9f9-417c-a900-0afd5dcb5566";
test("resolveLook, four levels in order (A1)", () => {
  const stored = { shape: "nuage", color: "gris" };
  // 1. a stored look beats everything, even for a preset bot
  assert.deepEqual(resolveLook(TESLA_ID, "bot:kline-focus", stored, "TeslaBot"), stored);
  // 2. a preset bot with nothing stored takes the recommended look (TeslaBot: capsule / rouge) and not the old face pick or the hash
  assert.deepEqual(resolveLook(TESLA_ID, "bot:kline-focus", null, "TeslaBot"), { shape: "capsule", color: "rouge" });
  assert.deepEqual(resolveLook(TESLA_ID, "bot:kline-focus", undefined, "whatever name"), { shape: "capsule", color: "rouge" }, "by id");
  assert.deepEqual(resolveLook("not-the-id", "bot:kline-focus", null, " tesla bot "), { shape: "capsule", color: "rouge" }, "by name");
  // a broken stored value falls through to level 2
  assert.deepEqual(resolveLook(TESLA_ID, "", { shape: "star" }, "TeslaBot"), { shape: "capsule", color: "rouge" });
  // 3. any other bot: the explicit old face pick, 4. else the hash (unchanged)
  assert.deepEqual(resolveLook("id-1", "bot:square-focus", null, "My bot"), faceLook("square", "focus"));
  assert.deepEqual(resolveLook("id-1", "bot:kline-idle", null, "My bot"), defaultLook("id-1"));
  // no name passed (older call sites): a preset bot is still hit by id
  assert.deepEqual(resolveLook(TESLA_ID, "bot:kline-focus", null), { shape: "capsule", color: "rouge" });
  // the four bots that already carry a stored look keep it (colours: NewsBot gris, AppleBot orange, ReportBot violet, FinBot encre)
  assert.deepEqual(resolveLook("ca3c9be3-97ea-4ce0-a624-ae6bfeb723e9", "bot:square-idle", { shape: "nuage", color: "gris" }, "NewsBot"), { shape: "nuage", color: "gris" });
  assert.deepEqual(resolveLook("3694c439-f29e-49dd-9875-51b6c8a4f7fd", "bot:bull-bull", { shape: "hexagone", color: "orange" }, "AppleBot"), { shape: "hexagone", color: "orange" });
});
