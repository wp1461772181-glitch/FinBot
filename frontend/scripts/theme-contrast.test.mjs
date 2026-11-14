import assert from "node:assert/strict";
import test from "node:test";
import { botHues, check, checkBots, checkDesign, checkPairs, designNumbers, loadBotCss, loadRules, parseCss, resolveToken, themeTokens } from "./theme-contrast.mjs";

const SRC = new URL("../src/", import.meta.url);
const show = (failures) => failures.map((f) => JSON.stringify(f)).join("\n");

test("no hard-coded light surface carries theme-following text, and no light text sits on a light token", () => {
  const failures = check(loadRules(SRC));
  assert.equal(failures.length, 0, show(failures));
});

test("theme token text/background pairs meet WCAG contrast in light and dark", () => {
  const failures = checkPairs(loadRules(SRC));
  assert.equal(failures.length, 0, show(failures));
});

test("--navy stays a dark brand colour in both themes (white text is written on it)", () => {
  const tokens = themeTokens(loadRules(SRC));
  for (const theme of ["light", "dark"]) {
    const navy = resolveToken(tokens[theme], "--navy");
    assert.ok(navy && navy.r + navy.g + navy.b < 3 * 60, `${theme}: --navy resolves to ${JSON.stringify(navy)}`);
  }
});

test("a new light card with token text fails the guard", () => {
  const rules = loadRules(SRC, ".zz-new-card{background:#fff;color:var(--ink)}");
  assert.ok(check(rules).some((f) => f.check === "A1" && f.selector === ".zz-new-card"));
  const onLight = loadRules(SRC, ".zz-hero{background:var(--me-surface);color:#fff}");
  assert.ok(check(onLight).some((f) => f.check === "A2" && f.selector === ".zz-hero"));
});

test("the parser reads minified rules and media blocks", () => {
  const rules = parseCss("@media (max-width:1px){.a,.b>c{background:#fff;color:red}}.d{color:#000}");
  assert.deepEqual(rules.map((r) => r.selectors), [[".a", ".b>c"], [".d"]]);
  assert.equal(rules[0].decls.background, "#fff");
});

test("the design's colour table holds: text tokens on bg / surface / sunken, soft fills, on-accent, in light and dark", () => {
  const failures = checkDesign(loadRules(SRC)).filter((f) => f.set === "light" || f.set === "dark");
  assert.equal(failures.length, 0, show(failures));
});

test("with up and down swapped (data-updown=red-up) every pair still holds, in both themes", () => {
  const rules = loadRules(SRC);
  const failures = checkDesign(rules).filter((f) => f.set === "lightRedUp" || f.set === "darkRedUp");
  assert.equal(failures.length, 0, show(failures));
  const tokens = themeTokens(rules);
  for (const theme of ["light", "dark"]) {
    const plain = tokens[theme], swapped = tokens[`${theme}RedUp`];
    assert.deepEqual(resolveToken(swapped, "--up"), resolveToken(plain, "--down"), `${theme}: up takes down's value`);
    assert.deepEqual(resolveToken(swapped, "--down"), resolveToken(plain, "--up"), `${theme}: down takes up's value`);
  }
});

test("success and danger never follow the up/down switch, and equal up / down by default", () => {
  const tokens = themeTokens(loadRules(SRC));
  for (const theme of ["light", "dark"]) {
    for (const name of ["--success", "--danger"]) {
      assert.deepEqual(resolveToken(tokens[`${theme}RedUp`], name), resolveToken(tokens[theme], name), `${theme} ${name} moved with the switch`);
    }
    assert.deepEqual(resolveToken(tokens[theme], "--success"), resolveToken(tokens[theme], "--up"), `${theme}: success defaults to up`);
    assert.deepEqual(resolveToken(tokens[theme], "--danger"), resolveToken(tokens[theme], "--down"), `${theme}: danger defaults to down`);
  }
});

test("the contrast guard really reads tokens.css and follows var() chains (a broken token is caught)", () => {
  const rules = loadRules(SRC);
  assert.ok(designNumbers(rules).length >= 40, "design table rows");
  const broken = loadRules(SRC, ":root{--muted:var(--stone-300)}");
  assert.ok(checkDesign(broken).some((f) => f.pair.startsWith("--muted") && f.set === "light"), "a pale --muted must fail the table");
  const noDarkSwap = loadRules(SRC).filter((r) => !r.selectors.includes(":root[data-theme=dark][data-updown=red-up]"));
  assert.ok(checkDesign(noDarkSwap).some((f) => f.set === "darkRedUp"), "dropping the dark red-up rule must fail");
  const viaBridge = loadRules(SRC, ":root{--me-ink:#eeeeee}");
  assert.ok(checkPairs(viaBridge).some((f) => f.pair.startsWith("--me-ink") && f.theme === "light"), "the --me-* names are resolved through the bridge");
});

test("every bot hue has 3:1 against the page backgrounds of its theme", () => {
  const css = loadBotCss(SRC);
  const hues = botHues(css);
  assert.equal(Object.keys(hues.light).length, 12);
  assert.equal(Object.keys(hues.dark).length, 12);
  const failures = checkBots(css, loadRules(SRC));
  assert.equal(failures.length, 0, show(failures));
});
