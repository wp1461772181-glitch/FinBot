// Hash routes of the 预测 section.  Pure: no window, no React.
//
//   #forecast                         home
//   #forecast?symbol=AMD              home, filtered to one symbol
//   #forecast/<rootId>                one forecast
//   #forecast/<rootId>?version=<id>   one forecast, that version selected
//   #forecast/<rootId>?revise=<id>    one forecast, its revision form open on that library filing
//   #forecast/judgment/<eventId>      one earnings judgment
//   #forecast/monitor                 monitor status
//
// Anything under #forecast that does not match one of these exactly is malformed and goes to home; it never
// guesses at a record.  The older hashes (#revisions, #evaluation, #replay) are not forecast routes: App still
// routes them itself, and `legacyForecastSection` names them.

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TICKER = /^[A-Z]{1,5}(?:[.-][A-Z]{1,2})?$/;

function splitHash(hash) {
  const raw = typeof hash === "string" ? hash.replace(/^#/, "") : "";
  const at = raw.indexOf("?");
  const path = at === -1 ? raw : raw.slice(0, at);
  const query = at === -1 ? "" : raw.slice(at + 1);
  return { segments: path.split("/"), params: new URLSearchParams(query) };
}

function uuid(value) {
  return typeof value === "string" && UUID.test(value) ? value.toLowerCase() : null;
}

/** @returns {{view: "home" | "forecast" | "judgment" | "monitor", rootId?: string, versionId?: string, reviseSourceId?: string, judgmentId?: string, symbol?: string}} */
export function parseForecastHash(hash) {
  const { segments, params } = splitHash(hash);
  const home = { view: "home" };
  if (segments[0] !== "forecast") return home;
  if (segments.length === 1) {
    if (!params.has("symbol")) return home;
    const symbol = (params.get("symbol") ?? "").trim().toUpperCase();
    return TICKER.test(symbol) ? { view: "home", symbol } : home;
  }
  if (segments.length === 2 && segments[1] === "monitor") return { view: "monitor" };
  if (segments.length === 3 && segments[1] === "judgment") {
    const judgmentId = uuid(segments[2]);
    return judgmentId ? { view: "judgment", judgmentId } : home;
  }
  if (segments.length === 2) {
    const rootId = uuid(segments[1]);
    if (!rootId) return home;
    const route = { view: "forecast", rootId };
    if (params.has("version")) {
      const versionId = uuid(params.get("version"));
      if (!versionId) return home;
      route.versionId = versionId;
    }
    // A library filing the reader asked to revise this forecast with; an unreadable one is ignored, the page still opens.
    const reviseSourceId = uuid(params.get("revise"));
    if (reviseSourceId) route.reviseSourceId = reviseSourceId;
    return route;
  }
  return home;
}

/** The older sections that now live inside the forecast group, by hash; null for any other hash. */
export function legacyForecastSection(hash) {
  const name = splitHash(hash).segments[0];
  return name === "revisions" || name === "evaluation" || name === "replay" ? name : null;
}

export function forecastHash(rootId, versionId) {
  return versionId ? `#forecast/${rootId}?version=${versionId}` : `#forecast/${rootId}`;
}

/** One forecast, with its revision form opened on a library filing (the judgment page's 用这份财报修订). */
export function reviseHash(rootId, sourceId) {
  return `#forecast/${rootId}?revise=${sourceId}`;
}

export function judgmentHash(judgmentId) {
  return `#forecast/judgment/${judgmentId}`;
}

export function forecastHomeHash(symbol) {
  return symbol ? `#forecast?symbol=${encodeURIComponent(symbol)}` : "#forecast";
}
