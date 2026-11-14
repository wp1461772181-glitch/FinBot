// Design 3.3: every row of the old-address table has at least one case here; the table never shrinks (R3).
import assert from "node:assert/strict";
import test from "node:test";
import { isNewHash, legacyHashToPath, normalizeHash } from "../src/legacy-routes.mjs";
import { forecastHash, judgmentHash, reviseHash, forecastHomeHash } from "../src/forecast-routes.mjs";
import { materialHref } from "../src/material-focus.mjs";
import { dispatchAgentAction } from "../src/agent-client-actions.mjs";

const ROOT = "6f1c2d3e-0000-4000-8000-000000000001";
const VERSION = "6f1c2d3e-0000-4000-8000-000000000002";
const SOURCE = "6f1c2d3e-0000-4000-8000-0000000000aa";
const BOT = "6f1c2d3e-0000-4000-8000-0000000000bb";
const CONVERSATION = "6f1c2d3e-0000-4000-8000-0000000000cc";
const LAST = { lastSymbol: "TSLA" };

const row = (name, hash, expected, options = {}) => test(name, () => assert.equal(legacyHashToPath(hash, options), expected));

// [row 1] 空、#agent、#chat -> #/chat
row("row 1: empty hash", "", "/chat");
row("row 1: bare #", "#", "/chat");
row("row 1: #agent", "#agent", "/chat");
row("row 1: #chat alias", "#chat", "/chat");
row("row 1: case and slashes (#AGENT/, #//agent)", "#AGENT/", "/chat");
row("row 1: #//agent", "#//agent", "/chat");
// [row 2] #agent/<对话id>
row("row 2: #agent/<conversation id>", `#agent/${CONVERSATION}`, `/chat/c/${CONVERSATION}`);
row("row 2: upper-case id is lower-cased", `#agent/${CONVERSATION.toUpperCase()}`, `/chat/c/${CONVERSATION}`);
row("row 2: a malformed conversation id falls back to the chat", "#agent/not-an-id", "/chat");
// [row 3] #bot/<botId>
row("row 3: #bot/<id>", `#bot/${BOT}`, `/chat/${BOT}`);
row("row 3: malformed bot id falls back to the chat", "#bot/zzz", "/chat");
row("row 3: #bot alone", "#bot", "/chat");
// [row 4] #overview、#company
row("row 4: #overview with a last symbol", "#overview", "/research/c/TSLA", LAST);
row("row 4: #company with a last symbol", "#company", "/research/c/TSLA", LAST);
row("row 4: #overview without one", "#overview", "/research");
row("row 4: #company with an unusable last symbol", "#company", "/research", { lastSymbol: "<script>" });
row("row 4: last symbol is upper-cased", "#overview", "/research/c/BRK.B", { lastSymbol: "brk.b" });
// [row 5] #forecast
row("row 5: #forecast", "#forecast", "/research/forecasts");
row("row 5: #Forecast/ (case, trailing slash)", "#Forecast/", "/research/forecasts");
// [row 6] #forecast?symbol=AMD
row("row 6: #forecast?symbol=AMD", "#forecast?symbol=AMD", "/research/forecasts?symbol=AMD");
row("row 6: lower-case symbol", "#forecast?symbol=amd", "/research/forecasts?symbol=AMD");
row("row 6: a bad symbol is ignored", "#forecast?symbol=%3Cb%3E", "/research/forecasts");
// [row 7] #forecast/<rootId>（含 ?version=、?revise=）
row("row 7: #forecast/<rootId>", `#forecast/${ROOT}`, `/research/forecasts/${ROOT}`);
row("row 7: with ?version=", `#forecast/${ROOT}?version=${VERSION}`, `/research/forecasts/${ROOT}?version=${VERSION}`);
row("row 7: with ?revise=", `#forecast/${ROOT}?revise=${SOURCE}`, `/research/forecasts/${ROOT}?revise=${SOURCE}`);
row("row 7: with both", `#forecast/${ROOT}?version=${VERSION}&revise=${SOURCE}`, `/research/forecasts/${ROOT}?version=${VERSION}&revise=${SOURCE}`);
row("row 7: an unreadable ?revise= is dropped, the page still opens", `#forecast/${ROOT}?revise=nope`, `/research/forecasts/${ROOT}`);
row("row 7: an unreadable ?version= is the forecast home, never a guess", `#forecast/${ROOT}?version=nope`, "/research/forecasts");
row("row 7: a malformed forecast id is the forecast home", "#forecast/12345", "/research/forecasts");
row("row 7: extra segments are the forecast home", `#forecast/${ROOT}/extra`, "/research/forecasts");
// [row 8] #forecast/judgment/<eventId>
row("row 8: #forecast/judgment/<eventId>", `#forecast/judgment/${ROOT}`, `/research/judgments/${ROOT}`);
row("row 8: malformed judgment id is the forecast home", "#forecast/judgment/x", "/research/forecasts");
// [row 9] #forecast/monitor
row("row 9: #forecast/monitor", "#forecast/monitor", "/research/monitor");
// [row 10] #revisions
row("row 10: #revisions with a last symbol resolves the newest forecast's versions", "#revisions", "/research/c/TSLA/latest?section=versions", LAST);
row("row 10: #revisions without one is the forecast home", "#revisions", "/research/forecasts");
// [row 11] #evaluation  [row 12] #replay
row("row 11: #evaluation", "#evaluation", "/research/scores");
row("row 12: #replay", "#replay", "/research/replay");
// [row 13] #materials、#library
row("row 13: #materials", "#materials", "/research/materials");
row("row 13: #library alias", "#library", "/research/materials");
// [row 14] #materials?symbol=AAPL&focus=<id>&type=…
row("row 14: symbol only", "#materials?symbol=AAPL", "/research/materials?symbol=AAPL");
row("row 14: symbol and focus", `#materials?symbol=AAPL&focus=${SOURCE}`, `/research/materials?symbol=AAPL&focus=${SOURCE}`);
row("row 14: symbol, focus and type", `#materials?symbol=AAPL&focus=${SOURCE}&type=official_filing`, `/research/materials?symbol=AAPL&focus=${SOURCE}&type=official_filing`);
row("row 14: an unknown type is dropped", `#materials?symbol=AAPL&focus=${SOURCE}&type=web`, `/research/materials?symbol=AAPL&focus=${SOURCE}`);
row("row 14: lower-case symbol", `#materials?symbol=aapl&focus=${SOURCE}`, `/research/materials?symbol=AAPL&focus=${SOURCE}`);
row("row 14: an unreadable focus is dropped, the symbol stays", "#materials?symbol=AAPL&focus=<x>", "/research/materials?symbol=AAPL");
row("row 14: a bad symbol drops the whole link", `#materials?symbol=<script>&focus=${SOURCE}`, "/research/materials");
// [row 15] #evidence  [row 16] #evidence/<versionId>/<类型>/<材料id>
row("row 15: #evidence with a last symbol", "#evidence", "/research/evidence?symbol=TSLA", LAST);
row("row 15: #evidence without one", "#evidence", "/research/evidence");
row("row 15: #evidence/upload keeps the dialog open", "#evidence/upload", "/research/evidence?symbol=TSLA&upload=1", LAST);
row("row 16: #evidence/<versionId>", `#evidence/${VERSION}`, `/research/evidence/${VERSION}`);
row("row 16: #evidence/<versionId>/<type>/<id>", `#evidence/${VERSION}/official_filing/${SOURCE}`, `/research/evidence/${VERSION}/official_filing/${SOURCE}`);
row("row 16: an uploaded-media source", `#evidence/${VERSION}/uploaded_media/${SOURCE}`, `/research/evidence/${VERSION}/uploaded_media/${SOURCE}`);
row("row 16: a percent-encoded source id round-trips", `#evidence/${VERSION}/official_filing/${encodeURIComponent("a/b")}`, `/research/evidence/${VERSION}/official_filing/a%2Fb`);
row("row 16: an unknown source type keeps the version", `#evidence/${VERSION}/web/${SOURCE}`, `/research/evidence/${VERSION}`);
// [row 17] #routines、#briefs  [row 18] #portfolio
row("row 17: #routines", "#routines", "/routines");
row("row 17: #briefs alias", "#briefs", "/routines");
row("row 17: ?tab= is kept when it is one of the three", "#routines?tab=runs", "/routines?tab=runs");
row("row 17: an unknown ?tab= is dropped", "#routines?tab=x", "/routines");
row("row 18: #portfolio", "#portfolio", "/portfolio");
// [row 19-22] #news #skills #memory #me
row("row 19: #news", "#news", "/assistant/news");
row("row 20: #skills", "#skills", "/assistant/skills");
row("row 20: #skills/<id> opens that skill", "#skills/draft_12-ab", "/assistant/skills/draft_12-ab");
row("row 20: a malformed skill id is the skills page", "#skills/a b", "/assistant/skills");
row("row 21: #memory", "#memory", "/assistant/memory");
row("row 22: #me", "#me", "/assistant/bots");
// [row 23] #admin、#settings
row("row 23: #admin", "#admin", "/settings/models");
row("row 23: #settings alias", "#settings", "/settings/models");
// developer sample page (kept for the smoke checks)
row("dev kit: #dev-kit", "#dev-kit", "/dev/kit");
row("dev kit: #dev-kit/probe", "#dev-kit/probe", "/dev/kit/probe");

test("new-form and unknown addresses are not this table's business (null)", () => {
  for (const hash of ["#/chat", "#/research/c/AAPL?tab=forecasts", "#/", "#/whatever", "#nonsense", "#portfolio-x", "#x/y/z"]) {
    assert.equal(legacyHashToPath(hash, LAST), null, hash);
  }
  assert.equal(isNewHash("#/chat"), true);
  assert.equal(isNewHash("#chat"), false);
  assert.equal(isNewHash(""), false);
});

test("malformed input never throws and lands on a safe page", () => {
  for (const hash of [undefined, null, 42, {}, [], "#%", "#%E0%A4%A", "#evidence/%E0%A4%A/x/y", "#forecast/%", "####", "#?", "#?=&&", "#/", "# agent", "#agent/%00"]) {
    assert.doesNotThrow(() => legacyHashToPath(hash, LAST), String(hash));
    assert.doesNotThrow(() => normalizeHash(hash, LAST), String(hash));
  }
  assert.equal(legacyHashToPath("#evidence/%E0%A4%A/x/y", LAST), "/research/evidence?symbol=TSLA");
  assert.equal(legacyHashToPath(undefined), "/chat");
  assert.equal(legacyHashToPath("#?"), "/chat");
});

test("normalizeHash: new addresses stay, old ones convert, unknown ones become the chat", () => {
  assert.equal(normalizeHash("#/portfolio"), null);
  assert.equal(normalizeHash("#portfolio"), "/portfolio");
  assert.equal(normalizeHash("#nonsense"), "/chat");
  assert.equal(normalizeHash(""), "/chat");
});

test("every hash the app's own helpers write converts to the matching new page", () => {
  assert.equal(legacyHashToPath(forecastHash(ROOT)), `/research/forecasts/${ROOT}`);
  assert.equal(legacyHashToPath(forecastHash(ROOT, VERSION)), `/research/forecasts/${ROOT}?version=${VERSION}`);
  assert.equal(legacyHashToPath(reviseHash(ROOT, SOURCE)), `/research/forecasts/${ROOT}?revise=${SOURCE}`);
  assert.equal(legacyHashToPath(judgmentHash(ROOT)), `/research/judgments/${ROOT}`);
  assert.equal(legacyHashToPath(forecastHomeHash("AMD")), "/research/forecasts?symbol=AMD");
  assert.equal(legacyHashToPath(forecastHomeHash()), "/research/forecasts");
  assert.equal(legacyHashToPath(materialHref("AAPL", { source_id: SOURCE, source_type: "official_filing" })), `/research/materials?symbol=AAPL&focus=${SOURCE}&type=official_filing`);
  assert.equal(legacyHashToPath(materialHref("AAPL", { source_id: SOURCE, source_type: "uploaded_media" })), `/research/materials?symbol=AAPL&focus=${SOURCE}&type=uploaded_media`);
});

// The agent's open_page names (agent-client-actions.mjs), after the page-name map App has always applied
// (predictions -> forecast, sec -> evidence, knowledge -> admin), as #<name>.
test("agent open_page names all land on a page", () => {
  const rename = { predictions: "forecast", sec: "evidence", knowledge: "admin" };
  const expected = {
    overview: "/research/c/TSLA", predictions: "/research/forecasts", materials: "/research/materials", sec: "/research/evidence?symbol=TSLA",
    revisions: "/research/c/TSLA/latest?section=versions", evaluation: "/research/scores", agent: "/chat", knowledge: "/settings/models",
  };
  for (const [page, path] of Object.entries(expected)) {
    assert.equal(legacyHashToPath(`#${rename[page] ?? page}`, LAST), path, page);
  }
  // the event's own validation is unchanged: an unknown page is not dispatched at all
  const host = new EventTarget();
  host.CustomEvent = CustomEvent; host.sessionStorage = { getItem: () => null, setItem() {} };
  assert.equal(dispatchAgentAction({ id: "6f1c2d3e-0000-4000-8000-0000000000dd", action: "open_page", page: "nowhere" }, host), false);
});

test("appHref turns the pure modules' old-form hash fields into links the router answers", async () => {
  const { appHref } = await import("../src/legacy-routes.mjs");
  assert.equal(appHref(`#forecast/${ROOT}`), `#/research/forecasts/${ROOT}`);
  assert.equal(appHref("#/portfolio"), "#/portfolio");
  assert.equal(appHref("#nonsense"), "#/chat");
  assert.equal(appHref(undefined), "#/chat");
});
