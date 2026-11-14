import assert from "node:assert/strict";
import test from "node:test";
import {
  PATTERNS, paths, hashHref, splitPath, companyTab, routinesTab, symbolFromParams, materialFocusFromParams, sectionOfPath, isRecordId, pathForSection,
} from "../src/routes.mjs";

const ID = "6f1c2d3e-0000-4000-8000-000000000001";
const q = (text) => new URLSearchParams(text);

test("paths: one generator per address of the route map", () => {
  assert.equal(paths.login(), "/login");
  assert.equal(paths.chat(), "/chat");
  assert.equal(paths.chat(null), "/chat");
  assert.equal(paths.chat(ID), `/chat/${ID}`);
  assert.equal(paths.chatSettings(ID), `/chat/${ID}/settings`);
  assert.equal(paths.chatConversation(ID), `/chat/c/${ID}`);
  assert.equal(paths.chatHistory(), "/chat/history");
  assert.equal(paths.research(), "/research");
  assert.equal(paths.company("aapl"), "/research/c/AAPL");
  assert.equal(paths.company("AAPL", "overview"), "/research/c/AAPL");
  assert.equal(paths.company("AAPL", "forecasts"), "/research/c/AAPL?tab=forecasts");
  assert.equal(paths.company("AAPL", "materials"), "/research/c/AAPL?tab=materials");
  assert.equal(paths.company("AAPL", "nonsense"), "/research/c/AAPL");
  assert.equal(paths.company("BRK.B"), "/research/c/BRK.B");
  assert.equal(paths.companyLatest("amd", { section: "versions" }), "/research/c/AMD/latest?section=versions");
  assert.equal(paths.companyLatest("amd"), "/research/c/AMD/latest");
  assert.equal(paths.forecasts(), "/research/forecasts");
  assert.equal(paths.forecasts({ symbol: "amd" }), "/research/forecasts?symbol=AMD");
  assert.equal(paths.forecast(ID), `/research/forecasts/${ID}`);
  assert.equal(paths.forecast(ID, { version: "v1" }), `/research/forecasts/${ID}?version=v1`);
  assert.equal(paths.forecast(ID, { revise: "s1" }), `/research/forecasts/${ID}?revise=s1`);
  assert.equal(paths.forecast(ID, { version: "v1", revise: "s1", section: "versions" }), `/research/forecasts/${ID}?version=v1&revise=s1&section=versions`);
  assert.equal(paths.judgment(ID), `/research/judgments/${ID}`);
  assert.equal(paths.evidence("v1"), "/research/evidence/v1");
  assert.equal(paths.evidence("v1", "official_filing", "s1"), "/research/evidence/v1/official_filing/s1");
  assert.equal(paths.evidence("v1", "official_filing", "a/b"), "/research/evidence/v1/official_filing/a%2Fb");
  assert.equal(paths.evidenceIndex(), "/research/evidence");
  assert.equal(paths.evidenceIndex({ symbol: "aapl", upload: true }), "/research/evidence?symbol=AAPL&upload=1");
  assert.equal(paths.materials(), "/research/materials");
  assert.equal(paths.materials({ symbol: "aapl" }), "/research/materials?symbol=AAPL");
  assert.equal(paths.materials({ symbol: "AAPL", focus: "f1", type: "official_filing", analysis: "a1" }), "/research/materials?symbol=AAPL&focus=f1&type=official_filing&analysis=a1");
  assert.equal(paths.scores(), "/research/scores");
  assert.equal(paths.replay(), "/research/replay");
  assert.equal(paths.monitor(), "/research/monitor");
  assert.equal(paths.portfolio(), "/portfolio");
  assert.equal(paths.routines(), "/routines");
  assert.equal(paths.routines({ tab: "runs" }), "/routines?tab=runs");
  assert.equal(paths.routines({ tab: "x" }), "/routines");
  assert.equal(paths.assistant(), "/assistant/bots");
  for (const section of ["bots", "skills", "memory", "news", "knowledge"]) assert.equal(paths.assistant(section), `/assistant/${section}`);
  assert.equal(paths.assistant("nope"), "/assistant/bots");
  assert.equal(paths.skill("draft_1"), "/assistant/skills/draft_1");
  assert.equal(paths.settings(), "/settings/models");
  for (const section of ["models", "notifications", "appearance", "data", "account"]) assert.equal(paths.settings(section), `/settings/${section}`);
  assert.equal(paths.settings("nope"), "/settings/models");
  assert.equal(paths.devKit(), "/dev/kit");
  assert.equal(paths.devKit({ probe: true }), "/dev/kit/probe");
  assert.equal(paths.devKit({ states: true }), "/dev/kit/states");
});

test("paths escape what must not reach the address raw", () => {
  assert.equal(paths.chat("a b/c"), "/chat/a%20b%2Fc");
  assert.equal(paths.materials({ symbol: "AAPL", focus: "x&y=1" }), "/research/materials?symbol=AAPL&focus=x%26y%3D1");
});

test("every generated path matches a pattern of the route map", () => {
  const matches = (pattern, path) => {
    const re = new RegExp(`^${pattern.replace(/:[A-Za-z]+/g, "[^/]+")}$`);
    return re.test(splitPath(path).pathname);
  };
  const samples = [
    paths.login(), paths.chat(), paths.chat(ID), paths.chatSettings(ID), paths.chatConversation(ID), paths.chatHistory(), paths.research(),
    paths.company("AAPL"), paths.companyLatest("AAPL"), paths.forecasts(), paths.forecast(ID), paths.judgment(ID), paths.evidenceIndex(), paths.evidence("v"),
    paths.evidence("v", "official_filing", "s"), paths.materials(), paths.scores(), paths.replay(), paths.monitor(), paths.portfolio(), paths.routines(),
    paths.assistant("bots"), paths.assistant("skills"), paths.skill("x"), paths.assistant("memory"), paths.assistant("news"), paths.assistant("knowledge"),
    paths.settings("data"), paths.devKit(), paths.devKit({ probe: true }), paths.devKit({ states: true }),
  ];
  const patterns = Object.values(PATTERNS);
  for (const sample of samples) assert.ok(patterns.some((pattern) => matches(pattern, sample)), sample);
});

test("hashHref and splitPath", () => {
  assert.equal(hashHref("/chat"), "#/chat");
  assert.deepEqual({ ...splitPath("/a/b?x=1&y=2#f"), params: splitPath("/a/b?x=1&y=2#f").params.get("y") }, { pathname: "/a/b", params: "2" });
  assert.equal(splitPath("/a").pathname, "/a");
  assert.equal(splitPath(undefined).pathname, "");
});

test("search-parameter readers", () => {
  assert.equal(companyTab(q("")), "overview");
  assert.equal(companyTab(q("tab=forecasts")), "forecasts");
  assert.equal(companyTab(q("tab=materials")), "materials");
  assert.equal(companyTab(q("tab=zzz")), "overview");
  assert.equal(routinesTab(q("")), null);
  assert.equal(routinesTab(q("tab=tasks")), "tasks");
  assert.equal(routinesTab(q("tab=bogus")), null);
  assert.equal(symbolFromParams(q("symbol=amd")), "AMD");
  assert.equal(symbolFromParams(q("symbol=<x>")), null);
  assert.equal(symbolFromParams(q("")), null);
  assert.deepEqual(materialFocusFromParams(q(`symbol=aapl&focus=${ID}&type=official_filing&analysis=${ID}`)), { symbol: "AAPL", source_type: "official_filing", source_id: ID, analysis_id: ID });
  assert.deepEqual(materialFocusFromParams(q("symbol=AAPL")), { symbol: "AAPL", source_type: "uploaded_media", source_id: null, analysis_id: null });
  assert.equal(materialFocusFromParams(q(`focus=${ID}`)), null);
  assert.equal(materialFocusFromParams(q("symbol=AAPL&focus=<x>")).source_id, null);
  assert.equal(isRecordId(ID), true);
  assert.equal(isRecordId("nope"), false);
});

test("sectionOfPath names the old section the shell highlights", () => {
  const cases = {
    "/chat": "agent", "/chat/history": "agent", [`/chat/c/${ID}`]: "agent", [`/chat/${ID}`]: "bot", [`/chat/${ID}/settings`]: "bot",
    "/research": "overview", "/research/c/AAPL": "overview", "/research/c/AAPL?tab=forecasts": "forecast", "/research/c/AAPL?tab=materials": "materials",
    "/research/c/AAPL/latest?section=versions": "revisions", "/research/forecasts": "forecast", [`/research/forecasts/${ID}`]: "forecast",
    [`/research/judgments/${ID}`]: "forecast", "/research/monitor": "forecast", "/research/scores": "evaluation", "/research/replay": "replay",
    "/research/evidence": "evidence", [`/research/evidence/${ID}`]: "evidence", "/research/materials?symbol=AAPL": "materials",
    "/portfolio": "portfolio", "/routines?tab=runs": "routines", "/assistant/bots": "me", "/assistant/skills": "skills", "/assistant/skills/x": "skills",
    "/assistant/memory": "memory", "/assistant/news": "news", "/assistant/knowledge": "knowledge", "/settings/models": "admin", "/settings/account": "admin",
    "/login": "agent", "/nonsense": "agent", "": "agent",
  };
  for (const [path, section] of Object.entries(cases)) assert.equal(sectionOfPath(path), section, path);
});

test("pathForSection: every old section name leads somewhere, with the company when the page has one", () => {
  const cases = [
    ["agent", "/chat"], ["bot", "/chat"], ["nonsense", "/chat"], ["overview", "/research/c/TSLA"], ["forecast", "/research/forecasts"],
    ["revisions", "/research/c/TSLA/latest?section=versions"], ["evaluation", "/research/scores"], ["replay", "/research/replay"],
    ["materials", "/research/materials?symbol=TSLA"], ["evidence", "/research/evidence?symbol=TSLA"], ["routines", "/routines"], ["portfolio", "/portfolio"],
    ["news", "/assistant/news"], ["skills", "/assistant/skills"], ["memory", "/assistant/memory"], ["me", "/assistant/bots"], ["knowledge", "/assistant/knowledge"], ["admin", "/settings/models"],
  ];
  for (const [section, path] of cases) assert.equal(pathForSection(section, "tsla"), path, section);
  assert.equal(pathForSection("overview", null), "/research");
  assert.equal(pathForSection("overview", "<x>"), "/research");
  assert.equal(pathForSection("materials"), "/research/materials");
  assert.equal(pathForSection("revisions", ""), "/research/forecasts");
});
