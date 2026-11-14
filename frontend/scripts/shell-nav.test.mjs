import assert from "node:assert/strict";
import test from "node:test";
import { AREAS, ASSISTANT_ITEMS, GUEST_ASSISTANT_ITEMS, RESEARCH_ITEMS, SETTINGS_ITEMS, activeArea, activeItem, areaItems, areaPath, needsLogin } from "../src/shell-nav.mjs";
import { PATTERNS, paths } from "../src/routes.mjs";
import { isResearchSection, navGroup } from "../src/workspace-sections.mjs";

const ROOT = "6f1c2d3e-0000-4000-8000-0000000000aa";

test("the six areas, and the sub-pages three of them carry", () => {
  assert.deepEqual(AREAS, ["chat", "research", "portfolio", "routines", "assistant", "settings"]);
  assert.deepEqual(RESEARCH_ITEMS.map((i) => i.id), ["watchlist", "forecasts", "materials", "evidence", "scores", "replay"]);
  assert.deepEqual(ASSISTANT_ITEMS.map((i) => i.id), ["bots", "skills", "memory", "news", "knowledge"]);
  assert.deepEqual(SETTINGS_ITEMS.map((i) => i.id), ["models", "notifications", "appearance", "data", "account"]);
  assert.deepEqual(areaItems("portfolio"), []);
  assert.deepEqual(areaItems("assistant", { personal: false }).map((i) => i.id), ["skills", "memory"], "a guest keeps the two the old 「更多」 menu showed");
  assert.equal(GUEST_ASSISTANT_ITEMS.length, 2);
});

test("every entry leads to an address the router answers", () => {
  const patterns = Object.values(PATTERNS).filter((p) => !p.includes("dev") && !p.includes("*"));
  const matches = (path) => patterns.some((pattern) => new RegExp(`^${pattern.replace(/:[A-Za-z]+/g, "[^/]+")}$`).test(path.split("?")[0]));
  for (const area of AREAS) {
    assert.ok(matches(areaPath(area, "AAPL")), `${area}: ${areaPath(area, "AAPL")}`);
    for (const item of areaItems(area)) assert.ok(matches(areaPath(area, "AAPL", item.id)), `${area}/${item.id}: ${areaPath(area, "AAPL", item.id)}`);
  }
  assert.ok(matches(areaPath("chat", null, "history")));
});

test("research sub-pages carry the company where the old tabs did", () => {
  assert.equal(areaPath("research", "TSLA", "watchlist"), "/research");
  assert.equal(areaPath("research", "TSLA", "forecasts"), "/research/forecasts");
  assert.equal(areaPath("research", "TSLA", "materials"), "/research/materials?symbol=TSLA");
  assert.equal(areaPath("research", "TSLA", "evidence"), "/research/evidence?symbol=TSLA");
  assert.equal(areaPath("research", "TSLA", "scores"), "/research/scores");
  assert.equal(areaPath("research", "TSLA", "replay"), "/research/replay");
  assert.equal(areaPath("research", null, "materials"), "/research/materials");
});

test("where an address sits in the sidebar", () => {
  const at = (path) => [activeArea(path), activeItem(path)];
  assert.deepEqual(at("/chat"), ["chat", null]);
  assert.deepEqual(at("/chat/history"), ["chat", "history"]);
  assert.deepEqual(at("/chat/b0000000-0000-4000-8000-000000000001"), ["chat", null]);
  assert.deepEqual(at("/chat/c/abc"), ["chat", null]);
  assert.deepEqual(at("/research"), ["research", "watchlist"]);
  assert.deepEqual(at("/research/c/AAPL"), ["research", "watchlist"]);
  assert.deepEqual(at("/research/c/AAPL?tab=forecasts"), ["research", "forecasts"]);
  assert.deepEqual(at("/research/c/AAPL?tab=materials"), ["research", "materials"]);
  assert.deepEqual(at("/research/forecasts"), ["research", "forecasts"]);
  assert.deepEqual(at(`/research/forecasts/${ROOT}?version=x`), ["research", "forecasts"]);
  assert.deepEqual(at(`/research/judgments/${ROOT}`), ["research", "forecasts"]);
  assert.deepEqual(at("/research/monitor"), ["research", "forecasts"]);
  assert.deepEqual(at("/research/materials?symbol=AAPL"), ["research", "materials"]);
  assert.deepEqual(at("/research/evidence"), ["research", "evidence"]);
  assert.deepEqual(at(`/research/evidence/${ROOT}/official_filing/x`), ["research", "evidence"]);
  assert.deepEqual(at("/research/scores"), ["research", "scores"]);
  assert.deepEqual(at("/research/replay"), ["research", "replay"]);
  assert.deepEqual(at("/portfolio"), ["portfolio", null]);
  assert.deepEqual(at("/routines?tab=runs"), ["routines", null]);
  assert.deepEqual(at("/assistant/bots"), ["assistant", "bots"]);
  assert.deepEqual(at("/assistant/skills"), ["assistant", "skills"]);
  assert.deepEqual(at("/assistant/skills/abc"), ["assistant", "skills"]);
  assert.deepEqual(at("/assistant/memory"), ["assistant", "memory"]);
  assert.deepEqual(at("/assistant/news"), ["assistant", "news"]);
  assert.deepEqual(at("/assistant/knowledge"), ["assistant", "knowledge"]);
  assert.deepEqual(at("/settings/models"), ["settings", "models"]);
  assert.deepEqual(at("/settings/appearance"), ["settings", "appearance"]);
  assert.deepEqual(at("/settings/account"), ["settings", "account"]);
  assert.deepEqual(at("/nowhere"), ["chat", null], "an unknown address is the chat, as sectionOfPath says");
});

test("a research address of any kind highlights a sub-page (none is left without one)", () => {
  for (const path of ["/research", "/research/c/AAPL", "/research/forecasts", "/research/judgments/x", "/research/monitor", "/research/materials", "/research/evidence", "/research/scores", "/research/replay", "/research/c/AAPL/latest?section=versions"]) {
    assert.equal(activeArea(path), "research", path);
    assert.ok(activeItem(path), `${path} has a highlighted sub-page`);
  }
});

test("only the owner's pages are guarded", () => {
  for (const path of ["/portfolio", "/routines", "/routines?tab=runs", "/assistant/bots", "/assistant/skills", "/assistant/skills/x", "/assistant/memory", "/assistant/news", "/assistant/knowledge", "/chat/b0000000-0000-4000-8000-000000000001", "/chat/b0000000-0000-4000-8000-000000000001/settings"]) assert.equal(needsLogin(path), true, path);
  for (const path of ["/chat", "/chat/history", "/chat/c/abc", "/research", "/research/c/AAPL", "/research/forecasts", "/research/materials", "/research/evidence", "/research/scores", "/research/replay", "/settings/models", "/settings/appearance", "/login"]) assert.equal(needsLogin(path), false, path);
});

test("workspace sections keep the groups the old shell gave them", () => {
  assert.equal(navGroup("agent"), "chat"); assert.equal(navGroup("bot"), "chat");
  assert.equal(navGroup("overview"), "company"); assert.equal(navGroup("revisions"), "forecast"); assert.equal(navGroup("evidence"), "library");
  assert.equal(navGroup("me"), "memory"); assert.equal(navGroup("knowledge"), "settings"); assert.equal(navGroup("admin"), "settings");
  assert.equal(isResearchSection("replay"), true); assert.equal(isResearchSection("portfolio"), false);
  assert.equal(paths.assistant("bots"), "/assistant/bots");
});
