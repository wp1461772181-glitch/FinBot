import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// 「更多」 folds 公司、预测、资料库、技能、记忆、设置 into one control.  No component renderer here, so the
// wiring is checked in the source the build compiles.  例行任务 stays a bot-rail row and a mobile tab.
const src = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), "utf8");

test("the six secondary labels live in 更多, and the rail lists one More control", () => {
  const app = src("App.tsx");
  const more = app.slice(app.indexOf("const moreItems"), app.indexOf("const mobileTabs"));
  for (const label of ["公司", "预测", "资料库", "技能", "记忆", "设置"]) {
    assert.match(more, new RegExp(`label: t\\("${label}"\\)`));
  }
  assert.doesNotMatch(more, /例行任务|新闻源/);
  assert.match(app, /<MoreMenu items=\{railMoreItems\}[\s\S]*placement="rail" drop=\{botRail \? "up" : "down"\}/);
  assert.match(app, /<MoreMenu items=\{moreItems\}[\s\S]*placement="sheet"/);
  assert.match(app, /aria-haspopup="menu"/);
  assert.match(app, /t\("更多"\)/);
  assert.match(app, /active \? active\.label : t\("公司、预测与其它"\)/);
  assert.doesNotMatch(app, /label: t\("我"\)/);
  assert.doesNotMatch(app, /nav\.filter\(item => !botRail/);
});

test("例行任务 stays primary chrome: a rail row and a mobile tab, not a More item", () => {
  const app = src("App.tsx"), rail = src("BotPages.tsx");
  assert.match(app, /\{ id: "routines", label: t\("例行任务"\), icon: <RoutineIcon \/>/);
  assert.match(rail, /<strong>\{t\("例行任务"\)\}<\/strong>/);
  assert.match(app, /例行任务 is not one of them/);
});

test("预测 is a bot-rail row on the owner's desktop rail, and stays in 更多 on the mobile tab bar and for guests", () => {
  const app = src("App.tsx"), rail = src("BotPages.tsx");
  // The rail's 更多 drops 预测 only when the rail has the row (botRail is the owner's rail); the sheet keeps all six.
  assert.match(app, /const railMoreItems = botRail \? moreItems\.filter\(item => item\.id !== "forecast"\) : moreItems;/);
  assert.match(app, /<MoreMenu items=\{moreItems\}[^>]*placement="sheet"/);
  assert.match(app, /forecastActive=\{navGroup\(activeSection\) === "forecast"\} onForecast=\{\(\) => \{ close\(\); navigate\("forecast"\); \}\}/);
  assert.match(rail, /onClick=\{onForecast\}[\s\S]*<ForecastIcon \/>[\s\S]*<strong>\{t\("预测"\)\}<\/strong>/);
  // The three mobile tabs are unchanged.
  const tabs = app.slice(app.indexOf("const mobileTabs"), app.indexOf("const research ="));
  assert.doesNotMatch(tabs, /id: "forecast"/);
});

test("the forecast group has no stock picker: the company comes from the record", () => {
  const app = src("App.tsx");
  assert.match(app, /const stockPicker = research && navGroup\(activeSection\) !== "forecast";/);
  assert.match(app, /\{stockPicker && <div className="symbol-form">/);
  assert.match(app, /\{stockPicker && <form className="watchlist-add"/);
});

test("the pinned bot rail is 288px, a modest step up from 240px", () => {
  const css = src("styles/legacy/styles.css");
  assert.match(css, /\.app-frame\.is-nav-pinned\{grid-template-columns:288px minmax\(0,1fr\)!important\}/);
  assert.match(css, /\.app-frame\.is-nav-pinned \.app-rail\{[^}]*width:288px/);
  assert.doesNotMatch(css, /240px|276px/);
  assert.match(src("styles/legacy/theme.css"), /grid-template-columns: repeat\(3, 1fr\)/);
});
