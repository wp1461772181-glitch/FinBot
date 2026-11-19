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

test("the sidebar entry, the phone's tab and the page say 任务, not 待你确认", () => {
  // P2.2: the rail row became the sidebar's 任务 entry (lucide icon) and the phone bar's tab.  P7.2: the page is app/routines/ (its title is 任务, as the sidebar says;
  // the drawn RoutineIcon of the old title went with the old page).
  const sidebar = src("app/shell/AppSidebar.tsx"), bar = src("app/shell/MobileTabBar.tsx"), page = src("app/routines/RoutinesPage.tsx"), icons = src("BotPages.tsx");
  assert.match(sidebar, /routines: "任务"/);
  assert.match(sidebar, /routines: CalendarClock/);
  assert.match(bar, /\{ area: "routines", label: "任务", icon: CalendarClock \}/);
  assert.match(page, /<h1 id="routines-title" className="[^"]*">\{t\("任务"\)\}<\/h1>/);
  for (const text of [sidebar, bar, page]) assert.doesNotMatch(text, /t\("待你确认"\)\}<\/h1>/);
  assert.doesNotMatch(icons, />✉</);
});

test("#briefs still opens the page, which lists every routine, the proposals and the run suggestions", () => {
  assert.match(src("legacy-routes.mjs"), /case "briefs":/);
  assert.equal(legacyHashToPath("#briefs"), "/routines");
  const data = src("app/routines/use-routines.ts");
  assert.match(data, /listTaskProposals\(signal\)/);
  assert.match(data, /listInbox\("confirm", signal\)/);
  assert.match(data, /listAgentTasks\(signal, botId \|\| undefined\)/);   // no botId: every bot's routines
  assert.match(src("app/routines/RoutinesPage.tsx"), /useRoutinesData\(\{ runsBotId: filter \}\)/);   // the page asks for no bot's tasks in particular
  assert.match(src("routine-form.mjs"), /bot_id: lockedBotId \?\? draft\.botId/);       // the page's form picks the bot, a bot's own page fixes it
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
  const router = src("app/router.tsx"), page = src("app/assistant/news/NewsPage.tsx"), more = src("app/shell/MoreDrawer.tsx");
  assert.ok(ASSISTANT_ITEMS.some((item) => item.id === "news" && item.label === "新闻源"));
  assert.equal(areaPath("assistant", "AAPL", "news"), "/assistant/news");
  assert.match(more, /areaItems\("assistant"/);
  assert.match(router, /path: PATTERNS\.assistantNews, \.\.\.page\(\(\) => import\("\.\/pages\/personal"\), "NewsRoute"\)/);
  assert.match(src("app/pages/personal.tsx"), /export function NewsRoute\(\) \{ return <NewsPage \/>; \}/);
  assert.equal(legacyHashToPath("#news"), "/assistant/news");   // was: "news" in App.tsx's list of known hash sections
  assert.doesNotMatch(src("app/routines/RoutinesPage.tsx"), /NewsSourcesPanel|getNewsSourcesConfig/);
  // The page that holds them is app/assistant/news/ (P8.1): the table of sources and the drawer, not the task page.
  assert.match(page, /getNewsSourcesConfig/);
  assert.match(page, /<NewsRow /);
});

test("the routine form has no token caps; the frequency offers intervals and run counts", () => {
  const form = src("app/routines/TaskDrawer.tsx"), model = src("routine-form.mjs");
  assert.doesNotMatch(form, /token|Cap/);
  assert.doesNotMatch(model, /token|Cap/);
  assert.match(form, /\{ value: "every", label: t\("每隔一段时间"\) \}/);
  assert.match(model, /max_runs: draft\.countMode === "once" \? 1 : draft\.countMode === "count" \? Number\(draft\.runs\) : 0/);
});
