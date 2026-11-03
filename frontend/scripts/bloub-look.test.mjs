import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { BLOUB_COLORS, faceLook, BLOUB_SHAPES, bloubLook, bloubState, hashString, BLOUB_EXPRESSIONS, BLOUB_STATES, DEFAULT_LOOK,
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

test("the hash only supplies the default: it reaches every shape and colour of the full catalog, expression stays neutral", () => {
  const shapes = new Set(), colors = new Set();
  for (let i = 0; i < 400; i++) { const l = defaultLook(`bot-${i}`); shapes.add(l.shape); colors.add(l.color); assert.equal(l.expression, "neutre"); }
  assert.equal(shapes.size, BLOUB_SHAPES.length);
  assert.equal(colors.size, BLOUB_COLORS.length);
});

test("normalizeLook accepts a full catalog look and refuses anything else", () => {
  assert.deepEqual(normalizeLook({ shape: "nuage", color: "creme", expression: "hilare" }), { shape: "nuage", color: "creme", expression: "hilare" });
  for (const bad of [null, undefined, "nuage", [], {}, { shape: "nuage" }, { shape: "star", color: "bleu", expression: "fier" },
    { shape: "nuage", color: "neon", expression: "fier" }, { shape: "nuage", color: "bleu", expression: "angry" }]) assert.equal(normalizeLook(bad), null);
});

test("a stored look wins over everything; with none, an explicit legacy face, then the hash", () => {
  const stored = { shape: "triangle", color: "gris", expression: "colere" };
  assert.deepEqual(resolveLook("id-1", "bot:square-focus", stored), stored);
  assert.deepEqual(resolveLook("id-1", "", stored), stored);
  assert.deepEqual(resolveLook("id-1", "bot:square-focus", null), { ...faceLook("square", "focus"), expression: "neutre" });
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

test("selector state: picking changes one field, ignores unknown ids, and is pure", () => {
  const base = { shape: "cercle", color: "encre", expression: "neutre" };
  assert.deepEqual(pickLook(base, "shape", "goutte"), { shape: "goutte", color: "encre", expression: "neutre" });
  assert.deepEqual(pickLook(base, "color", "rose"), { shape: "cercle", color: "rose", expression: "neutre" });
  assert.deepEqual(pickLook(base, "expression", "timide"), { shape: "cercle", color: "encre", expression: "timide" });
  assert.equal(pickLook(base, "shape", "star"), base);
  assert.equal(pickLook(base, "mood", "x"), base);
  assert.deepEqual(base, { shape: "cercle", color: "encre", expression: "neutre" });
});

test("lookForSave: nothing picked sends nothing; any pick is written, even one equal to the default or to the hash", () => {
  assert.equal(lookForSave(null, null), undefined);
  assert.equal(lookForSave(undefined, { shape: "nuage", color: "bleu", expression: "fier" }), undefined);
  assert.deepEqual(lookForSave({ ...DEFAULT_LOOK }, null), DEFAULT_LOOK); // explicit default combination is a choice
  const hashed = defaultLook("some-bot");
  assert.deepEqual(lookForSave(hashed, null), hashed); // clicking the tile that already shows is a choice too
  const stored = { shape: "nuage", color: "bleu", expression: "fier" };
  assert.equal(lookForSave({ ...stored }, stored), undefined); // unchanged from what is stored
  assert.deepEqual(lookForSave({ ...stored, color: "vert" }, stored), { ...stored, color: "vert" });
  assert.equal(lookForSave({ shape: "star" }, null), undefined); // never sends something the server would refuse
});

test("randomLook covers the catalog, is calm-faced, and only ever returns valid looks", () => {
  let seed = 1; const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const shapes = new Set(), colors = new Set();
  for (let i = 0; i < 400; i++) { const l = randomLook(rand); assert.deepEqual(normalizeLook(l), l); assert.equal(l.expression, "neutre"); shapes.add(l.shape); colors.add(l.color); }
  assert.equal(shapes.size, 8); assert.equal(colors.size, 12);
  assert.ok(normalizeLook(randomLook(() => 0.999999)) && normalizeLook(randomLook(() => 0)));
});

test("the customiser labels every catalog id, and every label has an English phrase", async () => {
  const source = await readFile(new URL("../src/BloubCustomizer.tsx", import.meta.url), "utf8");
  const english = JSON.parse(await readFile(new URL("../src/locales/en-US.json", import.meta.url), "utf8"));
  const table = name => Object.fromEntries([...source.match(new RegExp(`${name}: Record<string, string> = \\{([^}]*)\\}`))[1].matchAll(/(\w+): "([^"]+)"/g)].map(m => [m[1], m[2]]));
  for (const [name, ids] of [["SHAPE_LABELS", BLOUB_SHAPES], ["COLOR_LABELS", BLOUB_COLORS], ["EXPRESSION_LABELS", BLOUB_EXPRESSIONS]]) {
    const labels = table(name);
    assert.deepEqual(Object.keys(labels).sort(), [...ids].sort(), name);
    for (const zh of Object.values(labels)) assert.ok(english[zh]?.trim(), `no English for ${zh}`);
  }
  for (const heading of ["形状", "表情", "颜色"]) assert.ok(english[heading]);
});
