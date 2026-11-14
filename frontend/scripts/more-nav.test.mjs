import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { ASSISTANT_ITEMS, GUEST_ASSISTANT_ITEMS, RESEARCH_ITEMS, SETTINGS_ITEMS, areaItems } from "../src/shell-nav.mjs";

// The secondary navigation (P2.2: the old 「更多」 menu, the rail's page rows and the section tabs became the sidebar's
// 研究 / 助手 / 设置 groups and the phone's 更多 drawer).  No component renderer here, so the wiring is checked in the
// source the build compiles.  These tests stood on the old Shell.tsx / BotRailList; each states the same fact for the new shell.
const src = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), "utf8");

test("every destination the old 「更多」 menu offered has a place: 公司 / 预测 / 资料库 under 研究, 技能 / 记忆 under 助手, 设置 as its own group", () => {
  assert.deepEqual(RESEARCH_ITEMS.map((i) => i.label), ["自选", "预测", "材料库", "证据", "模型成绩", "历史回放"]);
  assert.deepEqual(ASSISTANT_ITEMS.map((i) => i.label), ["全部 bot", "技能", "记忆", "新闻源", "知识库"]);
  assert.deepEqual(SETTINGS_ITEMS.map((i) => i.label), ["模型", "通知", "外观", "数据", "账户"]);
  const sidebar = src("app/shell/AppSidebar.tsx");
  for (const area of ["research", "assistant", "settings"]) assert.match(sidebar, new RegExp(`<NavGroupItem area="${area}"`));
});

test("例行任务 stays primary chrome: a sidebar entry with the to-do number and a tab of the phone's bar, not a More item", () => {
  const sidebar = src("app/shell/AppSidebar.tsx"), bar = src("app/shell/MobileTabBar.tsx"), more = src("app/shell/MoreDrawer.tsx");
  assert.match(sidebar, /<NavLeaf area="routines" props=\{props\} badge=\{props\.routinesCount\} \/>/);
  assert.match(bar, /\{ area: "routines", label: "任务", icon: CalendarClock \}/);
  assert.match(bar, /const badge = tab\.area === "routines" \? props\.routinesCount : 0;/);
  assert.doesNotMatch(more, /routines/);
});

test("预测 lives under 研究 on the sidebar, for guests too; the phone's bar has five items and 更多 opens the drawer", () => {
  assert.ok(areaItems("research", { personal: false }).some((i) => i.id === "forecasts"));
  assert.ok(areaItems("research", { personal: true }).some((i) => i.id === "forecasts"));
  const bar = src("app/shell/MobileTabBar.tsx");
  const tabs = bar.slice(bar.indexOf("const TABS"), bar.indexOf("];", bar.indexOf("const TABS")));
  assert.equal((tabs.match(/area: "/g) ?? []).length, 4, "four tabs plus the 更多 button");
  assert.match(bar, /aria-haspopup="dialog"/);
  assert.match(bar, /t\("更多"\)/);
  assert.match(bar, /min-h-14/);                          // 56px: every target is at least 44
  assert.match(bar, /pb-\[env\(safe-area-inset-bottom\)\]/);
});

test("a guest's navigation is what the old guest rail showed: no bots, no 持仓 / 任务 entries, skills and memory under 助手", () => {
  assert.deepEqual(GUEST_ASSISTANT_ITEMS.map((i) => i.id), ["skills", "memory"]);
  const sidebar = src("app/shell/AppSidebar.tsx");
  assert.match(sidebar, /\{props\.personal && <NavLeaf area="portfolio"/);
  assert.match(sidebar, /\{props\.personal && <NavLeaf area="routines"/);
  assert.match(sidebar, /\{props\.personal \? <>/);
});

test("the forecast group has no stock picker: the company comes from the record", () => {
  const layout = src("app/WorkspaceLayout.tsx");
  assert.match(layout, /const stockPicker = isResearchSection\(activeSection\) && navGroup\(activeSection\) !== "forecast";/);
  assert.match(layout, /research=\{stockPicker \? \{ symbol, symbols, onSelectStock: switchSymbol/);
  const shell = src("app/shell/AppShell.tsx");
  assert.match(shell, /\{research && !guarded && <Suspense fallback=\{null\}><ResearchBar \{\.\.\.research\} \/><\/Suspense>\}/);
  assert.match(src("app/shell/ResearchBar.tsx"), /role="combobox"/);
});

test("the sidebar is 260px, 56px collapsed, and remembers the choice", () => {
  const sidebar = src("components/ui/sidebar.tsx");
  assert.match(sidebar, /const SIDEBAR_WIDTH = "260px"/);
  assert.match(sidebar, /const SIDEBAR_WIDTH_ICON = "56px"/);
  assert.match(sidebar, /SIDEBAR_STORAGE_KEY = "market-evidence-agent:sidebar-open:v1"/);
  assert.match(sidebar, /SIDEBAR_BREAKPOINT = 1024/);
  assert.doesNotMatch(src("styles/legacy/styles.css"), /\.app-frame/);
});
