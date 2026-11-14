import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), "utf8");
const shellSources = () => ["app/shell/AppShell.tsx", "app/shell/AppSidebar.tsx", "app/shell/MobileTabBar.tsx", "app/shell/MoreDrawer.tsx", "app/shell/account.tsx"].map(read).join("\n");

test("the shell carries no theme or language select (P2.2: no top bar any more; the sidebar's light / dark switch is a button)", () => {
  const shell = shellSources();
  assert.doesNotMatch(shell, /id="theme"/);
  assert.doesNotMatch(shell, /id="locale"/);
  assert.doesNotMatch(shell, /<select|setLocale/);
  // The quick switch uses the same persistence as the settings page.
  assert.match(read("app/shell/account.tsx"), /saveTheme\(next\); applyTheme\(next\)/);
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
