import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { waitingCount } from "../src/inbox-items.mjs";
import { CARDS, cleanLayout } from "../src/workspace-cards.mjs";
import { legacyHashToPath } from "../src/legacy-routes.mjs";
import { ASSISTANT_ITEMS, areaPath } from "../src/shell-nav.mjs";

// The 例行任务 hub (2026-10-28, Levi: 「待你确认」没有图标，改成例行任务).  No component renderer here, so the wiring
// is checked in the source the build compiles.  (P2.1: the page switch moved to app/router.tsx and #briefs' alias to
// legacy-routes.mjs; P2.2: the rail became the sidebar and the phone's tab bar, app/shell/.  The assertions say the same things.)
const src = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), "utf8");

test("the sidebar entry, the phone's tab and the page say 任务 / 例行任务 with a drawn icon, not 待你确认", () => {
  // P2.2: the rail row became the sidebar's 任务 entry (lucide icon) and the phone bar's tab; the page keeps its drawn RoutineIcon.
  const sidebar = src("app/shell/AppSidebar.tsx"), bar = src("app/shell/MobileTabBar.tsx"), page = src("PersonalPages.tsx"), icons = src("BotPages.tsx");
  assert.match(sidebar, /routines: "任务"/);
  assert.match(sidebar, /routines: CalendarClock/);
  assert.match(bar, /\{ area: "routines", label: "任务", icon: CalendarClock \}/);
  assert.match(icons, /export function RoutineIcon\(\)[\s\S]*?<svg/);
  assert.match(page, /<h1 id="routines-title"><RoutineIcon \/> \{t\("例行任务"\)\}<\/h1>/);
  for (const text of [sidebar, bar, page]) assert.doesNotMatch(text, /t\("待你确认"\)/);
  assert.doesNotMatch(icons, />✉</);
});

test("#briefs still opens the page, which lists every routine, the proposals and the run suggestions", () => {
  assert.match(src("legacy-routes.mjs"), /case "briefs":/);
  assert.equal(legacyHashToPath("#briefs"), "/routines");
  const page = src("PersonalPages.tsx");
  assert.match(page, /listTaskProposals\(signal\)/);
  assert.match(page, /<TaskManager bots=\{bots\}/);          // every bot's routines: no botId
  assert.match(page, /listInbox\("confirm", signal\)/);
  const manager = src("BotRoutines.tsx");
  assert.match(manager, /botId\?: string/);
  assert.match(manager, /bot_id: botId \?\? draftBot/);       // the hub's form picks the bot
});

test("one 例行任务 workspace card; a saved 待你确认 card becomes it", () => {
  assert.ok(!CARDS.some((c) => c.id === "confirm") && CARDS.some((c) => c.id === "routines" && c.title === "例行任务"));
  assert.deepEqual(cleanLayout([{ card: "confirm" }]), [{ card: "routines" }]);
});

test("the card counts this bot's live proposals and open suggestions", () => {
  const proposals = [{ bot_id: "b1", expired: false }, { bot_id: "b1", expired: true }, { bot_id: "b2", expired: false }];
  const confirms = [{ status: "unread" }, { status: "dismissed" }, { status: "done" }, { status: "read" }];
  assert.equal(waitingCount("b1", proposals, confirms), 3);
  assert.equal(waitingCount("b3", [], []), 0);
});

test("新闻源 is a page under 助手, opens its own page, and the 例行任务 page no longer carries it", () => {
  // P2.2: it was a rail row under 例行任务; it is now one of the 助手 sub-pages (the sidebar's group, the phone's 更多 drawer).
  const router = src("app/router.tsx"), page = src("PersonalPages.tsx"), more = src("app/shell/MoreDrawer.tsx");
  assert.ok(ASSISTANT_ITEMS.some((item) => item.id === "news" && item.label === "新闻源"));
  assert.equal(areaPath("assistant", "AAPL", "news"), "/assistant/news");
  assert.match(more, /areaItems\("assistant"/);
  assert.match(router, /path: PATTERNS\.assistantNews, \.\.\.page\(\(\) => import\("\.\/pages\/personal"\), "NewsRoute"\)/);
  assert.match(src("app/pages/personal.tsx"), /export function NewsRoute\(\) \{ return <NewsSourcesPage \/>; \}/);
  assert.equal(legacyHashToPath("#news"), "/assistant/news");   // was: "news" in App.tsx's list of known hash sections
  const routines = page.slice(page.indexOf("export function RoutinesPage"), page.indexOf("const HEALTH_LABELS"));
  assert.doesNotMatch(routines, /NewsSourcesPanel|getNewsSourcesConfig/);
  const newsPage = page.slice(page.indexOf("export function NewsSourcesPage"), page.indexOf("const KIND_LABELS"));
  assert.match(newsPage, /<NewsSourcesPanel /);
});

test("the routine form has no token caps; the frequency offers intervals and run counts", () => {
  const form = src("BotRoutines.tsx");
  assert.doesNotMatch(form, /token|Cap/);
  assert.match(form, /<option value="every">\{t\("每隔一段时间"\)\}<\/option>/);
  assert.match(form, /max_runs: draftCount === "once" \? 1 : draftCount === "count" \? draftRuns : 0/);
});
