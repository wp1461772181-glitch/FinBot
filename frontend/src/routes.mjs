// The address book of the app (design 3.2).  Pure: no window, no React, no router library.
//
// Every in-app link and jump builds its address here, so the route map (src/app/router.tsx) and the links that point
// into it cannot drift apart.  A path is what the router takes ("/research/c/AAPL?tab=forecasts"); `hashHref(path)`
// turns it into the "#/…" an <a href> needs when it is not a router link (Markdown answers, window.open).
//
// Routes added to the design's list, each because something that exists today needs an address:
//   /research/c/:symbol/latest        resolver: the symbol's newest forecast, then redirect (#revisions → ?section=versions)
//   /research/evidence                the evidence centre without a version (the symbol comes from ?symbol=; ?upload=1 opens the upload dialog)
//   /assistant/skills/:skillId        a skill's editor (drafts link to it)

const TICKER = /^[A-Z]{1,5}(?:[.-][A-Z]{1,2})?$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const ID = /^[0-9a-f-]{8,64}$/i;

export const COMPANY_TABS = ["overview", "forecasts", "materials"];
export const ROUTINE_TABS = ["confirm", "tasks", "runs"];
export const SETTINGS_SECTIONS = ["models", "notifications", "appearance", "data", "account"];
export const ASSISTANT_SECTIONS = ["bots", "skills", "memory", "news", "knowledge"];
export const SOURCE_TYPES = ["official_filing", "uploaded_media"];

/** Route patterns in react-router syntax, one per address the app answers.  The router builds its map from these. */
export const PATTERNS = {
  login: "/login",
  chat: "/chat",
  chatBot: "/chat/:botId",
  chatBotSettings: "/chat/:botId/settings",
  chatConversation: "/chat/c/:conversationId",
  chatHistory: "/chat/history",
  research: "/research",
  company: "/research/c/:symbol",
  companyLatest: "/research/c/:symbol/latest",
  forecasts: "/research/forecasts",
  forecast: "/research/forecasts/:rootId",
  judgment: "/research/judgments/:eventId",
  evidenceIndex: "/research/evidence",
  evidence: "/research/evidence/:versionId",
  evidenceSource: "/research/evidence/:versionId/:sourceType/:sourceId",
  materials: "/research/materials",
  scores: "/research/scores",
  replay: "/research/replay",
  monitor: "/research/monitor",
  portfolio: "/portfolio",
  routines: "/routines",
  assistantBots: "/assistant/bots",
  assistantSkills: "/assistant/skills",
  assistantSkill: "/assistant/skills/:skillId",
  assistantMemory: "/assistant/memory",
  assistantNews: "/assistant/news",
  assistantKnowledge: "/assistant/knowledge",
  settings: "/settings/:section",
  devKit: "/dev/kit",
  devKitProbe: "/dev/kit/probe",
  devKitStates: "/dev/kit/states",
  devKitBots: "/dev/kit/bots",
};

const seg = (value) => encodeURIComponent(String(value));

/** "?a=1&b=2" from the entries whose value is set; "" when none is. */
function query(entries) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(entries)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** A ticker as the address carries it: trimmed and upper-case.  Anything else is returned as given (callers validate). */
export function symbolParam(value) {
  return typeof value === "string" ? value.trim().toUpperCase() : "";
}

export const paths = {
  login: () => "/login",
  chat: (botId) => (botId ? `/chat/${seg(botId)}` : "/chat"),
  chatSettings: (botId) => `/chat/${seg(botId)}/settings`,
  chatConversation: (conversationId) => `/chat/c/${seg(conversationId)}`,
  chatHistory: () => "/chat/history",
  research: () => "/research",
  company: (symbol, tab) => `/research/c/${seg(symbolParam(symbol))}${query({ tab: tab && tab !== "overview" && COMPANY_TABS.includes(tab) ? tab : "" })}`,
  /** The symbol's newest forecast, opened by a small resolver ({section: "versions"} lands on the version list). */
  companyLatest: (symbol, { section } = {}) => `/research/c/${seg(symbolParam(symbol))}/latest${query({ section })}`,
  forecasts: ({ symbol } = {}) => `/research/forecasts${query({ symbol: symbolParam(symbol) })}`,
  forecast: (rootId, { version, revise, section } = {}) => `/research/forecasts/${seg(rootId)}${query({ version, revise, section })}`,
  judgment: (eventId) => `/research/judgments/${seg(eventId)}`,
  /** One version's evidence; with a source, that material's event detail. */
  evidence: (versionId, sourceType, sourceId) => sourceType && sourceId
    ? `/research/evidence/${seg(versionId)}/${seg(sourceType)}/${seg(sourceId)}`
    : `/research/evidence/${seg(versionId)}`,
  evidenceIndex: ({ symbol, upload } = {}) => `/research/evidence${query({ symbol: symbolParam(symbol), upload: upload ? "1" : "" })}`,
  materials: ({ symbol, focus, type, analysis } = {}) => `/research/materials${query({ symbol: symbolParam(symbol), focus, type, analysis })}`,
  scores: () => "/research/scores",
  replay: () => "/research/replay",
  monitor: () => "/research/monitor",
  portfolio: () => "/portfolio",
  routines: ({ tab } = {}) => `/routines${query({ tab: ROUTINE_TABS.includes(tab) ? tab : "" })}`,
  assistant: (section = "bots") => `/assistant/${ASSISTANT_SECTIONS.includes(section) ? section : "bots"}`,
  skill: (skillId) => `/assistant/skills/${seg(skillId)}`,
  settings: (section = "models") => `/settings/${SETTINGS_SECTIONS.includes(section) ? section : "models"}`,
  devKit: ({ probe, states, bots } = {}) => (probe ? "/dev/kit/probe" : states ? "/dev/kit/states" : bots ? "/dev/kit/bots" : "/dev/kit"),
};

/** "#/research/…" for a path: the form an <a href> or the location bar holds. */
export function hashHref(path) {
  return `#${path}`;
}

/** Split "/a/b?x=1#frag" into pathname and URLSearchParams (a fragment is dropped). */
export function splitPath(path) {
  const raw = String(path ?? "").replace(/#.*$/, "");
  const at = raw.indexOf("?");
  return { pathname: at === -1 ? raw : raw.slice(0, at), params: new URLSearchParams(at === -1 ? "" : raw.slice(at + 1)) };
}

/** The tab a company address asks for; anything unknown is the overview. */
export function companyTab(params) {
  const tab = params.get("tab");
  return COMPANY_TABS.includes(tab) ? tab : "overview";
}

/** The tab of the routines address, or null when the address names none (P7.2 reads it; the address keeps it meanwhile). */
export function routinesTab(params) {
  const tab = params.get("tab");
  return ROUTINE_TABS.includes(tab) ? tab : null;
}

/** A valid ticker from ?symbol=, or null. */
export function symbolFromParams(params) {
  const symbol = symbolParam(params.get("symbol") ?? "");
  return TICKER.test(symbol) ? symbol : null;
}

/** The material a ?symbol=&focus=&type= address points at: {symbol, source_type, source_id, analysis_id}, or null without a ticker.
 *  A focus that is not an id is dropped (the library still opens on the symbol).  `analysis` is the brief citation's analysis. */
export function materialFocusFromParams(params) {
  const symbol = symbolFromParams(params);
  if (!symbol) return null;
  const focus = String(params.get("focus") ?? "").trim();
  const analysis = String(params.get("analysis") ?? "").trim();
  return {
    symbol,
    source_type: params.get("type") === "official_filing" ? "official_filing" : "uploaded_media",
    source_id: ID.test(focus) ? focus : null,
    analysis_id: ID.test(analysis) ? analysis : null,
  };
}

/** True for a well-formed record id (the forecast / judgment / version ids are UUIDs). */
export function isRecordId(value) {
  return typeof value === "string" && UUID.test(value);
}

/** A source type the evidence address may carry, or null. */
export function sourceTypeParam(value) {
  return SOURCE_TYPES.includes(value) ? value : null;
}

/**
 * Which part of the chrome an address belongs to: the old section names the shell's highlight and tabs were written
 * against ("agent", "bot", "overview", "forecast", "revisions", "evaluation", "replay", "evidence", "materials",
 * "routines", "portfolio", "news", "skills", "memory", "me", "knowledge", "admin").  Unknown paths are "agent".
 */
export function sectionOfPath(path) {
  const { pathname, params } = splitPath(path);
  const parts = pathname.split("/").filter(Boolean);
  const [head, second, , fourth] = parts;
  if (!head || head === "chat") {
    if (!second || second === "history" || second === "c") return "agent";
    return "bot";
  }
  if (head === "portfolio") return "portfolio";
  if (head === "routines") return "routines";
  if (head === "settings") return "admin";
  if (head === "assistant") {
    return second === "skills" ? "skills" : second === "memory" ? "memory" : second === "news" ? "news" : second === "knowledge" ? "knowledge" : "me";
  }
  if (head === "research") {
    if (!second) return "overview";
    if (second === "c") {
      if (fourth === "latest") return "revisions";
      const tab = companyTab(params);
      return tab === "forecasts" ? "forecast" : tab === "materials" ? "materials" : "overview";
    }
    if (second === "forecasts" || second === "judgments" || second === "monitor") return "forecast";
    if (second === "scores") return "evaluation";
    if (second === "replay") return "replay";
    if (second === "evidence") return "evidence";
    if (second === "materials") return "materials";
  }
  return "agent";
}

/**
 * Where the old section names lead (what SectionTabs, the rail and the pages' own buttons ask for), for a reader
 * looking at `symbol`.  The address of a company's page carries the company; the pages that have no company of
 * their own (scores, replay, the forecast home) do not.
 */
export function pathForSection(section, symbol) {
  const ticker = symbolParam(symbol ?? "");
  const known = TICKER.test(ticker) ? ticker : null;
  switch (section) {
    case "overview": return known ? paths.company(known) : paths.research();
    case "forecast": return paths.forecasts();
    case "revisions": return known ? paths.companyLatest(known, { section: "versions" }) : paths.forecasts();
    case "evaluation": return paths.scores();
    case "replay": return paths.replay();
    case "materials": return paths.materials({ symbol: known });
    case "evidence": return paths.evidenceIndex({ symbol: known });
    case "routines": return paths.routines();
    case "portfolio": return paths.portfolio();
    case "news": return paths.assistant("news");
    case "skills": return paths.assistant("skills");
    case "memory": return paths.assistant("memory");
    case "me": return paths.assistant("bots");
    case "knowledge": return paths.assistant("knowledge");
    case "admin": return paths.settings();
    default: return paths.chat();
  }
}
