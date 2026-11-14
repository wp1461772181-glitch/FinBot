// Class names the built `utilities` layer defines versus class names the old UI uses.
//
// Tailwind scans src/app, src/components and src/dev, and turns every word there that happens to be a utility name
// (a comment saying "table", a string saying "contents") into a rule in the `utilities` layer.  That layer is above
// `legacy`, so such a rule silently overrides an old page's element of the same class.  The scan cannot tell a word in a
// comment from a class, so this check compares the two name sets from the build output instead of trusting reviewers.
//
//   utilities: the class each selector inside an `@layer utilities { … }` block of the built CSS (dist/assets/*.css) defines
//              (its leading class; see selectorClasses)
//   legacy:    every class selector in src/styles/legacy/*.css, plus every class token in a `className` string of the old
//              .tsx files (the ones in the src/ root; the new code is under src/app, src/components, src/dev)
//   collision: the names in both, minus ALLOWED
import fs from "node:fs";
import path from "node:path";

/** Names that are in both sets on purpose.  Every entry needs the reason it is harmless. */
export const ALLOWED = new Map([
  ["sr-only", "same visually-hidden box either way; the old rule is scoped to data-legacy by P1.1 (styles.css)"],
]);

const unescapeClass = (raw) => raw.replace(/\\(.)/g, "$1");

/** The text of every `@layer utilities{…}` block (balanced braces). */
function utilityBlocks(css) {
  const blocks = [];
  const marker = /@layer\s+utilities\s*\{/g;
  let m;
  while ((m = marker.exec(css))) {
    let depth = 1, i = marker.lastIndex;
    while (i < css.length && depth) { const c = css[i++]; if (c === "{") depth += 1; else if (c === "}") depth -= 1; }
    blocks.push(css.slice(marker.lastIndex, i - 1));
    marker.lastIndex = i;
  }
  return blocks;
}

/** Split a selector list at its top-level commas. */
function splitSelectors(text) {
  const out = []; let depth = 0, start = 0;
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (c === "(" || c === "[") depth += 1; else if (c === ")" || c === "]") depth -= 1;
    else if (c === "," && !depth) { out.push(text.slice(start, i)); start = i + 1; }
  }
  out.push(text.slice(start));
  return out;
}

/**
 * Class names in the selectors of a CSS text (declarations and url() values are skipped).
 * `leadingOnly`: take just the first class of each selector, the one a utility rule defines.  `.material-fact .num`
 * defines `material-fact`; `.num` there is only a descendant it styles inside that box, so it is not a utility named num.
 */
export function selectorClasses(css, { leadingOnly = false } = {}) {
  const names = new Set();
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");
  // selector text = whatever stands before a "{", back to the previous "{", "}" or ";"
  const re = /([^{}]*?)\{/g;
  let m;
  while ((m = re.exec(stripped))) {
    const text = m[1].slice(m[1].lastIndexOf(";") + 1);
    if (text.trim().startsWith("@")) continue;
    for (const selector of splitSelectors(text)) {
      for (const c of selector.matchAll(/\.((?:\\.|[A-Za-z0-9_-])+)/g)) {
        const name = unescapeClass(c[1]);
        if (/^[A-Za-z_]/.test(name)) names.add(name);
        if (leadingOnly) break;
      }
    }
  }
  return names;
}

/** Class tokens in the string literals of every `className=…` in a tsx source. */
export function classNameTokens(source) {
  const tokens = new Set();
  const take = (text) => { for (const t of text.split(/\s+/)) if (/^[A-Za-z_][\w-]*$/.test(t)) tokens.add(t); };
  for (const m of source.matchAll(/className=/g)) {
    let i = m.index + m[0].length;
    if (source[i] === '"' || source[i] === "'") { const end = source.indexOf(source[i], i + 1); take(source.slice(i + 1, end)); continue; }
    if (source[i] !== "{") continue;
    let depth = 0, j = i;
    for (; j < source.length; j += 1) { const c = source[j]; if (c === "{") depth += 1; else if (c === "}") { depth -= 1; if (!depth) break; } }
    const expr = source.slice(i + 1, j);
    for (const s of expr.matchAll(/"([^"\n]*)"|'([^'\n]*)'|`([^`]*)`/g)) take((s[1] ?? s[2] ?? (s[3] ?? "").replace(/\$\{[^}]*\}/g, " ")));
  }
  return tokens;
}

export function findCollisions({ distDir, srcDir }) {
  const assets = path.join(distDir, "assets");
  const utilities = new Set();
  const cssFiles = fs.readdirSync(assets).filter((f) => f.endsWith(".css"));
  if (!cssFiles.length) throw new Error(`no CSS in ${assets}`);
  for (const f of cssFiles) for (const block of utilityBlocks(fs.readFileSync(path.join(assets, f), "utf8"))) for (const n of selectorClasses(block, { leadingOnly: true })) utilities.add(n);
  const legacy = new Set();
  const legacyDir = path.join(srcDir, "styles", "legacy");
  for (const f of fs.readdirSync(legacyDir).filter((x) => x.endsWith(".css"))) for (const n of selectorClasses(fs.readFileSync(path.join(legacyDir, f), "utf8"))) legacy.add(n);
  const oldTsx = fs.readdirSync(srcDir).filter((f) => f.endsWith(".tsx"));
  for (const f of oldTsx) for (const n of classNameTokens(fs.readFileSync(path.join(srcDir, f), "utf8"))) legacy.add(n);
  // P3.1: old markup that moved under src/app/ keeps the header line `legacy markup, moved as-is in P3.1`; its class names are old names too.
  const moved = [];
  const walk = (dir) => { for (const entry of fs.readdirSync(dir, { withFileTypes: true })) { const full = path.join(dir, entry.name); if (entry.isDirectory()) walk(full); else if (entry.name.endsWith(".tsx") && /^\/\/ legacy markup, moved as-is in P3\.1/.test(fs.readFileSync(full, "utf8"))) moved.push(full); } };
  walk(path.join(srcDir, "app"));
  for (const f of moved) for (const n of classNameTokens(fs.readFileSync(f, "utf8"))) legacy.add(n);
  const both = [...utilities].filter((n) => legacy.has(n)).sort();
  return { utilities, legacy, oldTsx: oldTsx.length + moved.length, collisions: both.filter((n) => !ALLOWED.has(n)), allowed: both.filter((n) => ALLOWED.has(n)) };
}
