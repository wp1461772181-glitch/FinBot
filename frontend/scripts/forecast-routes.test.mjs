import assert from "node:assert/strict";
import test from "node:test";
import { forecastHash, forecastHomeHash, judgmentHash, legacyForecastSection, parseForecastHash, reviseHash } from "../src/forecast-routes.mjs";

const ROOT = "3f2b8c1e-9d4a-4e6b-8a57-1c0d2e3f4a5b";
const VERSION = "a1b2c3d4-0000-4000-8000-123456789abc";

test("bare #forecast and its filter form go to home", () => {
  assert.deepEqual(parseForecastHash("#forecast"), { view: "home" });
  assert.deepEqual(parseForecastHash("forecast"), { view: "home" });
  assert.deepEqual(parseForecastHash("#forecast?symbol=AMD"), { view: "home", symbol: "AMD" });
  assert.deepEqual(parseForecastHash("#forecast?symbol=brk.b"), { view: "home", symbol: "BRK.B" });
});

test("a symbol that is not a ticker is dropped, not guessed", () => {
  assert.deepEqual(parseForecastHash("#forecast?symbol=%3Cscript%3E"), { view: "home" });
  assert.deepEqual(parseForecastHash("#forecast?symbol="), { view: "home" });
  assert.deepEqual(parseForecastHash("#forecast?symbol=TOOLONGSYMBOL"), { view: "home" });
});

test("#forecast/<rootId> opens one forecast, with an optional version", () => {
  assert.deepEqual(parseForecastHash(`#forecast/${ROOT}`), { view: "forecast", rootId: ROOT });
  assert.deepEqual(parseForecastHash(`#forecast/${ROOT}?version=${VERSION}`), { view: "forecast", rootId: ROOT, versionId: VERSION });
  assert.deepEqual(parseForecastHash(`#forecast/${ROOT.toUpperCase()}`), { view: "forecast", rootId: ROOT });
});

test("?revise=<filing id> opens one forecast on a library filing; an unreadable id is ignored, not guessed at", () => {
  const FILING = "0b9d7e52-6c41-4f08-9a3e-5d2f1c8b7a64";
  assert.deepEqual(parseForecastHash(reviseHash(ROOT, FILING)), { view: "forecast", rootId: ROOT, reviseSourceId: FILING });
  assert.deepEqual(parseForecastHash(`#forecast/${ROOT}?version=${VERSION}&revise=${FILING}`),
    { view: "forecast", rootId: ROOT, versionId: VERSION, reviseSourceId: FILING });
  assert.deepEqual(parseForecastHash(`#forecast/${ROOT}?revise=nope`), { view: "forecast", rootId: ROOT });
  assert.deepEqual(parseForecastHash(`#forecast/not-a-uuid?revise=${FILING}`), { view: "home" });
});

test("judgment and monitor routes", () => {
  assert.deepEqual(parseForecastHash(`#forecast/judgment/${ROOT}`), { view: "judgment", judgmentId: ROOT });
  assert.deepEqual(parseForecastHash("#forecast/monitor"), { view: "monitor" });
});

test("malformed forecast hashes go to home", () => {
  for (const hash of [
    "#forecast/not-a-uuid",
    `#forecast/${ROOT}/extra`,
    `#forecast/${ROOT.slice(0, -1)}`,
    `#forecast/${ROOT}?version=nope`,
    "#forecast/judgment",
    "#forecast/judgment/",
    "#forecast/judgment/123",
    `#forecast/judgment/${ROOT}/x`,
    "#forecast/monitor/x",
    `#forecast//${ROOT}`,
    "#forecast/",
  ]) assert.deepEqual(parseForecastHash(hash), { view: "home" }, hash);
});

test("a hash that is not a forecast route is home, and non-strings do not throw", () => {
  assert.deepEqual(parseForecastHash("#agent"), { view: "home" });
  assert.deepEqual(parseForecastHash(""), { view: "home" });
  assert.deepEqual(parseForecastHash(undefined), { view: "home" });
});

test("old hashes still name their section", () => {
  assert.equal(legacyForecastSection("#revisions"), "revisions");
  assert.equal(legacyForecastSection("#evaluation"), "evaluation");
  assert.equal(legacyForecastSection("#replay"), "replay");
  assert.equal(legacyForecastSection("#replay?symbol=AMD"), "replay");
  assert.equal(legacyForecastSection("#forecast"), null);
  assert.equal(legacyForecastSection("#materials"), null);
  // The old hashes are not forecast routes, so they never open a record by accident.
  assert.deepEqual(parseForecastHash("#revisions"), { view: "home" });
});

test("builders round-trip through the parser", () => {
  assert.deepEqual(parseForecastHash(forecastHash(ROOT)), { view: "forecast", rootId: ROOT });
  assert.deepEqual(parseForecastHash(forecastHash(ROOT, VERSION)), { view: "forecast", rootId: ROOT, versionId: VERSION });
  assert.deepEqual(parseForecastHash(judgmentHash(ROOT)), { view: "judgment", judgmentId: ROOT });
  assert.deepEqual(parseForecastHash(forecastHomeHash("AMD")), { view: "home", symbol: "AMD" });
  assert.equal(forecastHomeHash(), "#forecast");
});
