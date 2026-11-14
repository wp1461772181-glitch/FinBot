import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), "utf8");
const topbar = (source) => source.slice(source.indexOf('<header className="topbar">'), source.indexOf("</header>", source.indexOf('<header className="topbar">')));

test("the topbar no longer carries the theme and language selects", () => {
  const bar = topbar(read("Shell.tsx"));   // P2.1: the shell moved from App.tsx
  assert.ok(bar.includes("toolbar-controls"), "topbar still present");
  assert.doesNotMatch(bar, /id="theme"/);
  assert.doesNotMatch(bar, /id="locale"/);
  assert.doesNotMatch(bar, /setLocale|saveTheme/);
});

test("the settings page owns the appearance and language sections, with the same persistence", () => {
  const settings = read("AgentChatPanel.tsx");
  assert.match(settings, /id="theme"/);
  assert.match(settings, /id="locale"/);
  assert.match(settings, /saveTheme\(/);
  assert.match(settings, /applyTheme\(/);
  assert.match(settings, /setLocale\(/);
  assert.match(settings, /<AppearanceCard\/>/);
});
