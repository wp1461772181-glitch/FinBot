// Contrast guard for the two themes (UX batch 2, P0; extended in P1.2).  Pure Node: it parses tokens.css and the
// four old sheets (plus bridge.css) in load order, resolves the theme tokens through their var() chains for light
// and dark (and for the red-up market colours), and reports
//   A1  a rule that paints a hard-coded light background while its text follows the theme (a token that
//       turns light in dark mode, or no colour at all), unless dark mode repoints that selector (theme.css);
//   A2  a rule that writes hard-coded light text over a token background that is light in light mode;
//   A3  text painted with a token that is light in light mode, with no dark token background;
//   B   token text/background pairs below WCAG contrast (4.5 body, 3 secondary);
//   D   the design's colour table (2.3): every text token against bg / surface / sunken, the soft-fill pairs, and the
//       same again with up/down swapped (data-updown="red-up"); every bot hue against the three backgrounds (3:1).
// `node scripts/theme-contrast.mjs` prints the computed numbers next to the design's.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

// Load order: the tokens, the old sheets, then the bridge that points the old names at the tokens.
export const SHEETS = ["styles/tokens.css", "styles/legacy/styles.css", "styles/legacy/chat.css", "styles/legacy/theme.css", "styles/legacy/grok.css", "styles/legacy/bridge.css"];
export const BOT_SHEET = "styles/bots.css";

/** Flat rule list: {selectors, decls, media}.  Good enough for our hand-written and minified sheets. */
export function parseCss(text) {
  const src = text.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules = [];
  const walk = (start, media) => {
    let i = start, head = "";
    while (i < src.length) {
      const ch = src[i];
      if (ch === "{") {
        const prelude = head.trim(); head = "";
        if (prelude.startsWith("@media") || prelude.startsWith("@supports")) { i = walk(i + 1, prelude); continue; }
        const end = matching(src, i);
        const body = src.slice(i + 1, end);
        if (!prelude.startsWith("@")) rules.push({ selectors: splitSelectors(prelude), decls: parseDecls(body), media });
        i = end + 1; continue;
      }
      if (ch === "}") return i + 1;
      if (ch === ";" && head.trim().startsWith("@")) { head = ""; i += 1; continue; }
      head += ch; i += 1;
    }
    return i;
  };
  walk(0, "");
  return rules;
}

function matching(src, open) {
  let depth = 0;
  for (let i = open; i < src.length; i += 1) {
    if (src[i] === "{") depth += 1;
    else if (src[i] === "}") { depth -= 1; if (depth === 0) return i; }
  }
  return src.length;
}

function splitSelectors(prelude) {
  const out = []; let depth = 0, cur = "";
  for (const ch of prelude) {
    if (ch === "(") depth += 1; if (ch === ")") depth -= 1;
    if (ch === "," && depth === 0) { out.push(normSelector(cur)); cur = ""; } else cur += ch;
  }
  if (cur.trim()) out.push(normSelector(cur));
  return out;
}

export function normSelector(sel) {
  return sel.trim().replace(/\s*([>+~])\s*/g, "$1").replace(/\s+/g, " ").replace(/"/g, "");
}

function parseDecls(body) {
  const decls = {};
  for (const part of body.split(";")) {
    const at = part.indexOf(":");
    if (at < 0) continue;
    decls[part.slice(0, at).trim().toLowerCase()] = part.slice(at + 1).replace(/!important/, "").trim();
  }
  return decls;
}

// --- colours ---------------------------------------------------------------------------------------
const NAMED = { white: "#ffffff", black: "#000000", transparent: null };

export function parseColor(value) {
  if (!value) return null;
  const v = value.trim().toLowerCase();
  if (v in NAMED) return NAMED[v] ? parseColor(NAMED[v]) : null;
  let m = v.match(/^#([0-9a-f]{3,8})$/);
  if (m) {
    let h = m[1];
    if (h.length === 3 || h.length === 4) h = [...h].map((c) => c + c).join("");
    const a = h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1;
    return { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16), a };
  }
  m = v.match(/^rgba?\(([^)]+)\)$/);
  if (m) {
    const p = m[1].split(/[\s,/]+/).filter(Boolean).map((x) => (x.endsWith("%") ? parseFloat(x) / 100 : parseFloat(x)));
    return { r: p[0], g: p[1], b: p[2], a: p[3] ?? 1 };
  }
  return null;
}

export function luminance({ r, g, b }) {
  const ch = (c) => { const s = c / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b);
}

export function contrast(a, b) {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

const isLight = (c) => Boolean(c && c.a >= 0.5 && luminance(c) > 0.55);

/** The first colour literal in a declaration value, ignoring var() fallbacks. */
function firstLiteral(value) {
  const stripped = value.replace(/var\([^()]*(\([^()]*\)[^()]*)*\)/g, " ");
  const m = stripped.match(/#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\bwhite\b/);
  return m ? parseColor(m[0]) : null;
}

function firstVar(value) {
  const m = value.match(/^\s*var\(\s*(--[\w-]+)/);
  return m ? m[1] : null;
}

// --- tokens ----------------------------------------------------------------------------------------
// The four token sets the cascade can produce on <html>.  `:root[data-updown=red-up]` and the dark one share their
// specificity with `:root[data-theme=dark]`, so (as in the browser) the dark + red-up rule is what decides there.
const SELECTORS = {
  light: ":root",
  dark: ":root[data-theme=dark]",
  lightRedUp: ":root[data-updown=red-up]",
  darkRedUp: ":root[data-theme=dark][data-updown=red-up]",
};

/** Token maps for light, dark, and both with the market colours swapped, from the `:root…` rules in load order. */
export function themeTokens(rules) {
  const sets = { light: {}, dark: {}, lightRedUp: {}, darkRedUp: {} };
  for (const rule of rules) {
    if (rule.media) continue;
    for (const sel of rule.selectors) {
      const key = Object.keys(SELECTORS).find((k) => SELECTORS[k] === sel);
      if (!key) continue;
      for (const [k, v] of Object.entries(rule.decls)) if (k.startsWith("--")) sets[key][k] = v;
    }
  }
  const dark = { ...sets.light, ...sets.dark };
  return {
    light: sets.light,
    dark,
    lightRedUp: { ...sets.light, ...sets.lightRedUp },
    darkRedUp: { ...dark, ...sets.lightRedUp, ...sets.darkRedUp },
  };
}

export function resolveToken(tokens, name, depth = 0) {
  const raw = tokens[name];
  if (raw == null || depth > 10) return null;
  const ref = firstVar(raw);
  if (ref) return resolveToken(tokens, ref, depth + 1) ?? parseColor(raw.match(/,\s*([^)]+)\)/)?.[1] ?? "");
  return parseColor(raw);
}

function resolveValue(tokens, value) {
  const ref = firstVar(value);
  return ref ? resolveToken(tokens, ref) : firstLiteral(value);
}

// --- checks ----------------------------------------------------------------------------------------
const DARK_PREFIX = ":root[data-theme=dark] ";
// Ink tokens made for a dark surface the rule sits inside (the hero card, the inverted pill).
const ON_DARK_SURFACE = /^--me-(hero|invert)-/;

export function check(rules) {
  const tokens = themeTokens(rules);
  const darkCovered = new Set();
  for (const rule of rules) for (const sel of rule.selectors) if (sel.startsWith(DARK_PREFIX)) {
    const bg = rule.decls.background ?? rule.decls["background-color"];
    if (bg && firstVar(bg)) darkCovered.add(sel.slice(DARK_PREFIX.length));
  }
  const failures = [];
  for (const rule of rules) {
    const bgValue = rule.decls.background ?? rule.decls["background-color"];
    const plain = rule.selectors.filter((s) => !s.startsWith(":root"));
    if (!plain.length) continue;
    const colorValue = rule.decls.color;
    // A3: text painted with a token that is light in light mode, without a dark token background under it.
    const colorVar = colorValue ? firstVar(colorValue) : null;
    if (colorVar && !ON_DARK_SURFACE.test(colorVar) && isLight(resolveToken(tokens.light, colorVar)) && !(bgValue && firstVar(bgValue) && !isLight(resolveValue(tokens.light, bgValue)))) {
      failures.push({ check: "A3", selector: plain.join(","), color: colorValue, background: bgValue ?? "(inherited)" });
    }
    if (!bgValue) continue;
    const bgVar = firstVar(bgValue);
    // A1: hard-coded light background, theme-following text.
    if (!bgVar && isLight(firstLiteral(bgValue))) {
      const textVar = colorValue ? firstVar(colorValue) : null;
      const textTurnsLight = colorValue ? (textVar ? isLight(resolveToken(tokens.dark, textVar)) : false) : true;
      if (textVar && isLight(resolveToken(tokens.light, textVar))) failures.push({ check: "A1", theme: "light", selector: plain.join(","), background: bgValue, color: colorValue });
      if (textTurnsLight) for (const sel of plain) if (!darkCovered.has(sel)) failures.push({ check: "A1", selector: sel, background: bgValue, color: colorValue ?? "(inherited)" });
    }
    // A2: hard-coded light text over a token background that is light in light mode.
    if (bgVar && colorValue && !firstVar(colorValue) && isLight(firstLiteral(colorValue))) {
      for (const theme of ["light", "dark"]) {
        if (isLight(resolveValue(tokens[theme], bgValue))) { failures.push({ check: "A2", theme, selector: plain.join(","), background: bgValue, color: colorValue }); break; }
      }
    }
  }
  return failures;
}

// Token pairs that carry text.  [text, background, minimum ratio]
export const PAIRS = [
  ["--me-ink", "--me-bg", 4.5], ["--me-ink", "--me-surface", 4.5], ["--me-ink", "--me-surface-2", 4.5],
  ["--me-muted", "--me-bg", 3], ["--me-muted", "--me-surface", 3], ["--me-muted", "--me-surface-2", 3],
  ["--me-rail-ink", "--me-rail", 4.5], ["--me-invert-ink", "--me-invert", 4.5],
  ["--me-hero-ink", "--me-hero", 4.5], ["--me-hero-muted", "--me-hero", 3],
  ["--me-accent", "--me-surface", 3], ["--me-accent", "--me-bg", 3],
  ["--ink", "--surface", 4.5], ["--ink", "--paper", 4.5],
];

export function checkPairs(rules, pairs = PAIRS) {
  const tokens = themeTokens(rules);
  const failures = [];
  for (const theme of ["light", "dark"]) for (const [fg, bg, min] of pairs) {
    const a = resolveToken(tokens[theme], fg), b = resolveToken(tokens[theme], bg);
    if (!a || !b) { failures.push({ check: "B", theme, pair: `${fg} on ${bg}`, ratio: "unresolved" }); continue; }
    const ratio = contrast(a, b);
    if (ratio < min) failures.push({ check: "B", theme, pair: `${fg} on ${bg}`, ratio: Number(ratio.toFixed(2)), min });
  }
  return failures;
}

export function loadRules(dir, extra = "") {
  return parseCss(SHEETS.map((name) => readFileSync(new URL(name, dir), "utf8")).join("\n") + "\n" + extra);
}

// --- design table (design 2.3) ------------------------------------------------------------------------------------
export const SETS = ["light", "dark", "lightRedUp", "darkRedUp"];
const BACKGROUNDS = ["--bg", "--surface", "--sunken"];

// Text tokens against the three backgrounds: [token, minimum ratio, the design's number for light, for dark].
export const DESIGN_TEXT = [
  ["--ink", 4.5, 14.97, 13.35], ["--ink-2", 4.5, 8.6, 9.42], ["--muted", 4.5, 4.84, 5.88],
  ["--faint", 3, 3.03, 3.72],
  ["--accent", 4.5, 5.76, 7.57], ["--opinion", 4.5, 6.03, 7.39], ["--action", 4.5, 5.44, 7.48],
  ["--up", 4.5, 4.7, 7.68], ["--down", 4.5, 4.91, 5.81],
  // Status colours default to the same values as up / down and must clear the same bar; they never swap.
  ["--success", 4.5, 4.7, 7.68], ["--danger", 4.5, 4.91, 5.81],
];
// Text on its own soft fill: [text, fill, minimum, the design's light, the design's dark].
export const DESIGN_ON_FILL = [
  ["--accent", "--accent-soft", 4.5, 5.7, 7.41], ["--opinion", "--opinion-soft", 4.5, 5.99, 7.52], ["--action", "--action-soft", 4.5, 5.6, 7.16],
  ["--on-accent", "--accent", 4.5, null, null],
  ["--ink", "--accent-soft", 4.5, null, null],
  ["--on-deep", "--deep", 4.5, null, null], ["--on-deep-2", "--deep", 3, null, null],
];

const ratioOf = (tokens, fg, bg) => {
  const a = resolveToken(tokens, fg), b = resolveToken(tokens, bg);
  return a && b ? contrast(a, b) : null;
};

/** Computed numbers for the design table: per set, the minimum over the three backgrounds. */
export function designNumbers(rules) {
  const all = themeTokens(rules);
  const rows = [];
  for (const set of SETS) {
    for (const [fg, min] of DESIGN_TEXT) {
      const ratios = BACKGROUNDS.map((bg) => ratioOf(all[set], fg, bg));
      rows.push({ set, pair: `${fg} on bg/surface/sunken`, fg, min, ratio: ratios.some((r) => r == null) ? null : Math.min(...ratios) });
    }
    for (const [fg, fill, min] of DESIGN_ON_FILL) rows.push({ set, pair: `${fg} on ${fill}`, fg, min, ratio: ratioOf(all[set], fg, fill) });
  }
  return rows;
}

export function checkDesign(rules) {
  const failures = [];
  for (const row of designNumbers(rules)) {
    if (row.ratio == null) failures.push({ check: "D", set: row.set, pair: row.pair, ratio: "unresolved" });
    else if (row.ratio < row.min) failures.push({ check: "D", set: row.set, pair: row.pair, ratio: Number(row.ratio.toFixed(2)), min: row.min });
  }
  return failures;
}

/** Bot hues (bots.css): outline colours, so 3:1 against the three backgrounds of their theme. */
export function botHues(css) {
  const light = {}, dark = {};
  for (const rule of parseCss(css)) for (const sel of rule.selectors) {
    const hue = rule.decls["--bot-hue"];
    const m = sel.match(/^(:root\[data-theme=dark\] )?\[data-bot-color=([a-z]+)\]$/);
    if (m && hue) (m[1] ? dark : light)[m[2]] = hue;
  }
  return { light, dark };
}

export function checkBots(css, rules) {
  const tokens = themeTokens(rules);
  const hues = botHues(css);
  const failures = [];
  for (const theme of ["light", "dark"]) for (const [id, hue] of Object.entries(hues[theme])) {
    const c = parseColor(hue);
    for (const bg of BACKGROUNDS) {
      const ratio = c && resolveToken(tokens[theme], bg) ? contrast(c, resolveToken(tokens[theme], bg)) : null;
      if (ratio == null || ratio < 3) failures.push({ check: "D", theme, pair: `bot ${id} (${hue}) on ${bg}`, ratio: ratio == null ? "unresolved" : Number(ratio.toFixed(2)), min: 3 });
    }
  }
  return failures;
}

export function loadBotCss(dir) {
  return readFileSync(new URL(BOT_SHEET, dir), "utf8");
}

// `node scripts/theme-contrast.mjs`: the design's numbers next to the computed ones.
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const rules = loadRules(new URL("../src/", import.meta.url));
  const f = (n) => (n == null ? "  -  " : n.toFixed(2).padStart(5));
  for (const set of SETS) {
    console.log(`\n== ${set} ==`);
    console.log("pair".padEnd(44), "min".padStart(4), "computed".padStart(9), "design".padStart(7));
    for (const row of designNumbers(rules)) {
      if (row.set !== set) continue;
      const design = DESIGN_TEXT.find(([fg]) => fg === row.fg && row.pair.endsWith("sunken"))?.[set.startsWith("dark") ? 3 : 2]
        ?? DESIGN_ON_FILL.find(([fg, fill]) => row.pair === `${fg} on ${fill}`)?.[set.startsWith("dark") ? 4 : 3];
      console.log(row.pair.padEnd(44), String(row.min).padStart(4), f(row.ratio).padStart(9), f(set.endsWith("RedUp") ? null : design ?? null).padStart(7));
    }
  }
}
