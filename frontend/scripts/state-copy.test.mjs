import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { pageItems } from "../src/command-items.mjs";

// P2.3: the copy of the state components, the command palette and the replaced confirmations is in the English catalog
// (a phrase missing there would show the Chinese text in the English interface).
const english = JSON.parse(await readFile(new URL("../src/locales/en-US.json", import.meta.url), "utf8"));
const root = new URL("../src/", import.meta.url).pathname;

async function files(dir) {
  const out = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...await files(full));
    else if (/\.(tsx?|mjs)$/.test(entry.name)) out.push(full);
  }
  return out;
}

const CONFIRM_SITES = ["BotRoutines.tsx", "BotSidePanel.tsx", "app/settings/ModelCatalogCard.tsx", "SkillsPage.tsx", "PersonalPages.tsx", "PortfolioPage.tsx", "app/settings/TelegramBindCard.tsx"].map((name) => path.join(root, name));

// P3.1 moved the old chat page and settings page (legacy markup, copy untouched) into src/app/.  Their copy has gaps in the
// English catalog that were always there (they were in the old-pages group this test never read), so the moved files stay out
// of this scan, exactly as they were.  Each P3.2-P3.4 / P8.2 package takes its files off this list when it restyles them.
const LEGACY_MOVED = new Set(["ChatSessionProvider", "ClarificationCard"].map((name) => `app/chat/${name}.tsx`)
  .concat(["AppearanceCard", "ChatArchiveSettings", "MaterialAnalysisDefaultCard", "ModelCatalogCard", "PushoverCard", "SettingsPage", "TelegramBindCard"].map((name) => `app/settings/${name}.tsx`)));

test("every t(\"…\") literal in the state components, the palette and the shell is in the English catalog", async () => {
  const scanned = [...await files(path.join(root, "components/state")), ...await files(path.join(root, "components/command")), ...await files(path.join(root, "app"))]
    .filter((file) => !LEGACY_MOVED.has(path.relative(root, file)));
  const missing = [];
  const phrases = (source) => [...source.matchAll(/\bt\(\s*"([^"\n]*[\u4e00-\u9fff][^"\n]*)"\s*\)/g)].map((match) => match[1]);
  for (const file of scanned) for (const phrase of phrases(await readFile(file, "utf8"))) if (!(phrase in english)) missing.push(`${path.relative(root, file)}: ${phrase}`);
  // The old pages hold other copy this package did not touch; only the text inside the replaced confirmations is this package's.
  for (const file of CONFIRM_SITES) for (const call of (await readFile(file, "utf8")).matchAll(/await confirm\(\{([^}]*)\}\)/g)) for (const phrase of phrases(call[1])) if (!(phrase in english)) missing.push(`${path.basename(file)}: ${phrase}`);
  assert.deepEqual(missing, []);
});

test("the pages the palette lists, and the areas it names them by, are all translated", () => {
  const missing = new Set();
  const t = (text) => { if (!(text in english)) missing.add(text); return english[text] ?? text; };
  pageItems({ personal: true, t });
  assert.deepEqual([...missing], []);
});

test("no window.confirm is left, and the nine replaced places ask through the in-app confirm", async () => {
  let asks = 0;
  for (const file of await files(root)) {
    const source = await readFile(file, "utf8");
    assert.ok(!/window\.confirm/.test(source), `${path.relative(root, file)} still calls window.confirm`);
  }
  for (const file of CONFIRM_SITES) asks += [...(await readFile(file, "utf8")).matchAll(/await confirm\(\{/g)].length;
  assert.equal(asks, 9);
});

test("every confirmation that deletes or unbinds is press-and-hold and says what follows", async () => {
  for (const file of CONFIRM_SITES) {
    const source = await readFile(file, "utf8");
    for (const match of source.matchAll(/await confirm\(\{([^}]*)\}\)/g)) {
      assert.match(match[1], /tone: "danger"/, `${path.basename(file)}: tone`);
      assert.match(match[1], /hold: true/, `${path.basename(file)}: hold`);
      assert.match(match[1], /description:/, `${path.basename(file)}: description`);
    }
  }
});
