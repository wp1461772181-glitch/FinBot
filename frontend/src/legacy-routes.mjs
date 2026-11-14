// The old hash addresses (#agent, #forecast/<id>, #materials?symbol=…) and where they live now (design 3.3).
// Pure: no window, no React.  The table never shrinks: past answers, routine run records, bookmarks and the agent's
// open_page action all carry these.  `legacyHashToPath` is the one function; the app calls it at start-up and on
// every jump to an old-form address, and replaces the address with its result.
//
// Returns the new path, or null when the hash is already a new address ("#/…") or is not one this table knows.
// Never throws: malformed input lands on the same safe page the old router chose (an unreadable forecast address is
// the forecast home, an unknown name is the chat; it never guesses at a record).
//
// A few old addresses need a record before they have a place.  They map to a *resolver* path instead:
//   #revisions   -> /research/c/<last symbol>/latest?section=versions   (the symbol's newest forecast, version list)
// With no last symbol, #overview / #company map to /research and #revisions to the forecast home.
// #evidence needs no lookup: the evidence centre picks the symbol's newest version itself, as it always did.

import { parseForecastHash } from "./forecast-routes.mjs";
import { paths, symbolParam, SOURCE_TYPES, ROUTINE_TABS } from "./routes.mjs";

const TICKER = /^[A-Z]{1,5}(?:[.-][A-Z]{1,2})?$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ID = /^[0-9a-f-]{8,64}$/i;
const SKILL_ID = /^[A-Za-z0-9_-]{1,64}$/;

/** True for an address in the new form ("#/chat", "#/research/c/AAPL"). */
export function isNewHash(hash) {
  return typeof hash === "string" && /^#\/(?!\/)/.test(hash);
}

function lastSymbolOf(options) {
  const symbol = symbolParam(options?.lastSymbol ?? "");
  return TICKER.test(symbol) ? symbol : null;
}

/** "#Forecast//ABC/?x=1" -> {head: "forecast", rest: ["ABC"], query: "x=1", tail: "/ABC?x=1"}: case-folded name, no empty segments. */
function parse(hash) {
  const raw = String(hash ?? "").replace(/^#+/, "");
  const at = raw.indexOf("?");
  const pathPart = at === -1 ? raw : raw.slice(0, at);
  const query = at === -1 ? "" : raw.slice(at + 1);
  const segments = pathPart.split("/").filter(Boolean);
  const head = (segments[0] ?? "").toLowerCase();
  const rest = segments.slice(1);
  return { head, rest, query, params: new URLSearchParams(query) };
}

function decode(value) {
  try { return decodeURIComponent(value); } catch { return null; }
}

function materialsPath(params) {
  const symbol = symbolParam(params.get("symbol") ?? "");
  if (!TICKER.test(symbol)) return paths.materials();
  const focus = String(params.get("focus") ?? "").trim();
  const analysis = String(params.get("analysis") ?? "").trim();
  const type = params.get("type");
  return paths.materials({
    symbol,
    focus: ID.test(focus) ? focus : undefined,
    type: SOURCE_TYPES.includes(type) ? type : undefined,
    analysis: ID.test(analysis) ? analysis : undefined,
  });
}

function forecastPath(head, rest, query) {
  // parseForecastHash reads the exact old shape, so hand it the normalised address (name in lower case, no empty segments).
  const normalised = `#${["forecast", ...rest].join("/")}${query ? `?${query}` : ""}`;
  const route = parseForecastHash(normalised);
  if (route.view === "forecast") return paths.forecast(route.rootId, { version: route.versionId, revise: route.reviseSourceId });
  if (route.view === "judgment") return paths.judgment(route.judgmentId);
  if (route.view === "monitor") return paths.monitor();
  return paths.forecasts({ symbol: route.symbol });
}

function evidencePath(rest, options) {
  const symbol = lastSymbolOf(options);
  if (rest.length === 0) return paths.evidenceIndex({ symbol });
  if (rest.length === 1 && rest[0].toLowerCase() === "upload") return paths.evidenceIndex({ symbol, upload: true });
  const versionId = decode(rest[0]);
  if (!versionId) return paths.evidenceIndex({ symbol });
  const [, sourceType, ...sourceParts] = rest;
  const sourceId = sourceParts.length ? decode(sourceParts.join("/")) : null;
  if (SOURCE_TYPES.includes(sourceType) && sourceId) return paths.evidence(versionId, sourceType, sourceId);
  return paths.evidence(versionId);
}

/**
 * @param {string} hash  location.hash as the browser holds it ("#agent", "#forecast/<id>?version=<id>", "")
 * @param {{lastSymbol?: string | null}} [options]  the stock the reader last had open (a preference, not state)
 * @returns {string | null}
 */
export function legacyHashToPath(hash, options = {}) {
  try {
    if (isNewHash(hash)) return null;
    const { head, rest, query, params } = parse(hash);
    const symbol = lastSymbolOf(options);
    switch (head) {
      case "":
      case "agent":
      case "chat": {
        if (head === "agent" && rest.length === 1 && UUID.test(rest[0])) return paths.chatConversation(rest[0].toLowerCase());
        return paths.chat();
      }
      case "bot":
        return rest.length === 1 && UUID.test(rest[0]) ? paths.chat(rest[0].toLowerCase()) : paths.chat();
      case "overview":
      case "company":
        return symbol ? paths.company(symbol) : paths.research();
      case "forecast":
        return forecastPath(head, rest, query);
      case "revisions":
        return symbol ? paths.companyLatest(symbol, { section: "versions" }) : paths.forecasts();
      case "evaluation":
        return paths.scores();
      case "replay":
        return paths.replay();
      case "materials":
      case "library":
        return materialsPath(params);
      case "evidence":
        return evidencePath(rest, options);
      case "routines":
      case "briefs": {
        const tab = params.get("tab");
        return paths.routines({ tab: ROUTINE_TABS.includes(tab) ? tab : undefined });
      }
      case "portfolio":
        return paths.portfolio();
      case "news":
        return paths.assistant("news");
      case "skills":
        return rest.length === 1 && SKILL_ID.test(rest[0]) ? paths.skill(rest[0]) : paths.assistant("skills");
      case "memory":
        return paths.assistant("memory");
      case "me":
        return paths.assistant("bots");
      case "admin":
      case "settings":
        return paths.settings("models");
      case "dev-kit":
        return rest[0] === "probe" ? paths.devKit({ probe: true }) : rest[0] === "states" ? paths.devKit({ states: true }) : paths.devKit();
      default:
        return null;
    }
  } catch {
    return null;
  }
}

/** The path an address should be replaced with at start-up or when the hash changes: null when it is already fine. */
export function normalizeHash(hash, options = {}) {
  if (isNewHash(hash)) return null;
  return legacyHashToPath(hash, options) ?? paths.chat();
}

/** The "#/…" an <a href> should hold for an address that may still be in the old form (a `.hash` field the pure
 *  modules build, such as forecast-home's row hash).  New addresses pass through; unknown ones open the chat. */
export function appHref(hash, options = {}) {
  if (isNewHash(hash)) return hash;
  return `#${legacyHashToPath(hash, options) ?? paths.chat()}`;
}
