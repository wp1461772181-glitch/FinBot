// Fixture entry: buildState() makes a fresh mutable state per browser context; registerRoutes() wires the handlers.
import { BOT, CONVERSATION, HOLD_MARKER, LOGIN_CODE, WATCHLIST } from "./ids.mjs";
import { prices } from "./common.mjs";
import { botList, BOT_TEMPLATES, MODEL_CATALOG, MODEL_ROLES } from "./bots.mjs";
import { buildChat, conversationSummaries, CONTEXT_USAGE, streamEvents } from "./chat.mjs";
import { filingInventory } from "./filings.mjs";
import { MATERIALS, materialList, analysisVersion, materialOriginal, ANALYSIS_SETTINGS } from "./materials.mjs";
import { forecastList, forecastRoots, timeline, versionDetail, evaluations, MONITOR, workspace, job, revisionCandidates, JUDGMENTS } from "./forecasts.mjs";
import { portfolioSummary, buildPortfolio } from "./portfolio.mjs";
import { TASKS, RUNS, PROPOSALS, INBOX } from "./routines.mjs";
import { NEWS, SKILLS, PROFILE, RECALL, TELEGRAM, BOT_TELEGRAM, PUSHOVER, KNOWLEDGE_DOCS } from "./assistant.mjs";

export function buildState() {
  return { bots: botList(), queue: [...WATCHLIST], chat: buildChat(), modelRoles: { ...MODEL_ROLES.roles }, portfolio: buildPortfolio(), tasks: structuredClone(TASKS), inbox: structuredClone(INBOX) };
}

/** Owner-only endpoints answer 403 without the fake credential, like the real server. */
const owner = (handler, reply) => (ctx) => (ctx.authed ? handler(ctx) : reply.status(403, { detail: "owner_only" }));

export function registerRoutes(route, reply) {
  const own = (handler) => owner(handler, reply);
  const A = "/agent-chat";

  // --- login (the code is a fixture, not a real one; any other code is refused like the real server does) -----------
  route.post(`${A}/personal-login`, async ({ body }) => {
    if (body?.code !== LOGIN_CODE) return reply.status(401, { detail: "invalid_login" });
    const { FAKE_CREDENTIAL } = await import("../mock-api.mjs");
    return { credential: FAKE_CREDENTIAL };
  });

  // --- bots, models, queue -----------------------------------------------------------------------------
  route.get(`${A}/bots`, own(({ state }) => ({ bots: state.bots, default_bot_id: BOT.finbot })));
  route.get(`${A}/bot-templates`, own(() => BOT_TEMPLATES));
  route.get(`${A}/model-catalog`, own(() => MODEL_CATALOG));
  route.get(`${A}/model-roles`, own(({ state }) => ({ roles: state.modelRoles })));
  route.post(`${A}/bots/:id/read`, own(({ params, state }) => { const b = state.bots.find((x) => x.id === params.id); const read = b?.unread ?? 0; if (b) b.unread = 0; return { read }; }));
  route.get(`${A}/research-queue`, own(({ state }) => ({ symbols: state.queue })));
  route.put(`${A}/research-queue`, own(({ body, state }) => { state.queue = body.symbols; return { ok: true }; }));

  // --- conversations -----------------------------------------------------------------------------------
  route.get(`${A}/conversations`, own(({ state }) => ({ conversations: conversationSummaries(state), has_more: false })));
  route.get(`${A}/conversations/:id/messages`, own(({ params, state }) => ({ messages: state.chat.conversations.get(params.id) ?? [], has_more: false, next_before: null, compactions: [] })));
  route.get(`${A}/conversations/:id/context`, own(() => CONTEXT_USAGE));
  route.get(`${A}/context`, own(() => CONTEXT_USAGE));
  route.post(`${A}/stream`, own(({ body, state }) => {
    // A message containing the hold marker is never answered: that bot's line stays "answering" (the sidebar's 回答中 mark).
    if (String(body.message).includes(HOLD_MARKER)) return new Promise(() => {});
    const bot = body.bot_id ? state.bots.find((b) => b.id === body.bot_id) : null;
    const conversationId = bot?.conversation_id ?? body.conversation_id ?? CONVERSATION.finbot;
    const events = streamEvents({ conversationId, message: body.message, botId: bot?.id });
    const list = state.chat.conversations.get(conversationId) ?? [];
    state.chat.conversations.set(conversationId, list);
    const text = events.filter((e) => e.event === "delta").map((e) => e.data.text).join("");
    list.push({ role: "user", content: body.display_message || body.message }, { role: "assistant", status: "complete", turn_id: events[0].data.turn_id, content: text, thinking_ms: 900 });
    return reply.sse(events);
  }));

  // --- market data -------------------------------------------------------------------------------------
  route.get("/v2/stocks/:symbol/prices", ({ params }) => prices(params.symbol));
  route.get("/filing-inventories/:symbol", ({ params }) => filingInventory(params.symbol));

  // --- forecasts (V2) ----------------------------------------------------------------------------------
  const found = (value) => (value ?? reply.status(404, { detail: "not_found" }));
  route.get("/v2/forecasts", ({ query }) => forecastList(query));
  route.get("/v2/stocks/:symbol/forecast-roots", ({ params }) => forecastRoots(params.symbol));
  route.get("/v2/stocks/:symbol/workspace", ({ params }) => workspace(params.symbol));
  route.get("/v2/forecast-roots/:id/timeline", ({ params }) => found(timeline(params.id)));
  route.get("/v2/forecast-versions/:id", ({ params }) => found(versionDetail(params.id)));
  route.get("/v2/forecast-versions/:id/revision-candidates", ({ params }) => revisionCandidates(params.id));
  route.get("/v2/jobs/:id", ({ params }) => job(params.id));
  route.get("/v2/monitor/status", () => MONITOR);
  route.get("/v2/evaluations", ({ query }) => evaluations(query.get("symbol")));
  route.get(`${A}/earnings-judgments`, own(({ query }) => ({ judgments: JUDGMENTS.filter((j) => !query.get("symbol") || j.symbol === query.get("symbol")) })));
  route.get(`${A}/earnings-judgments/:id`, own(({ params }) => { const j = JUDGMENTS.find((x) => x.id === params.id); return j ? { judgment: j } : reply.status(404, { detail: "not_found" }); }));

  // --- materials (V3) ----------------------------------------------------------------------------------
  route.get("/v3/materials", ({ query }) => materialList(query));
  route.get("/v3/materials/analysis-settings", () => ANALYSIS_SETTINGS);
  route.get("/v3/materials/:type/:id/analyses", ({ params }) => { const m = MATERIALS.find((x) => x.source_id === params.id); const no = m?.latest_analysis_id ? Number(m.latest_analysis_id.slice(-12)) : null;
    return { source_type: params.type, source_id: params.id, items: no ? [analysisVersion(no, { symbol: m.symbol })] : [] }; });
  route.get("/v3/materials/:type/:id/original", ({ params }) => materialOriginal(params.type, params.id));
  route.get("/v3/material-analyses/:id", ({ params }) => { const m = MATERIALS.find((x) => x.latest_analysis_id === params.id); return analysisVersion(Number(params.id.slice(-12)), { symbol: m?.symbol ?? "AAPL" }); });
  route.get("/v3/material-analysis-jobs/:id", ({ params }) => ({ job_id: params.id, status: "succeeded", analysis_id: null, cache_hit: false }));
  route.get("/uploaded-evidence/:symbol", ({ params }) => ({ symbol: params.symbol, items: [] }));
  route.get("/evidence-revisions/:symbol", ({ params }) => ({ symbol: params.symbol, revisions: [] }));

  // --- portfolio, routines, inbox ----------------------------------------------------------------------
  route.get(`${A}/portfolio`, own(({ state }) => portfolioSummary(state)));
  route.get(`${A}/tasks`, own(({ state, query }) => ({ tasks: state.tasks.filter((t) => !query.get("bot_id") || t.bot_id === query.get("bot_id")) })));
  route.get(`${A}/tasks/runs`, own(({ query }) => ({ runs: RUNS.filter((r) => !query.get("bot_id") || TASKS.find((t) => t.id === r.task_id)?.bot_id === query.get("bot_id")) })));
  route.get(`${A}/tasks/proposals`, own(() => ({ proposals: PROPOSALS })));
  route.get(`${A}/inbox`, own(({ state, query }) => ({ items: state.inbox.filter((i) => (!query.get("section") || i.section === query.get("section")) && (!query.get("bot_id") || i.bot_id === query.get("bot_id"))) })));

  // --- assistant: news sources, skills, memory, settings cards -----------------------------------------
  route.get(`${A}/news-sources`, own(() => NEWS));
  route.get(`${A}/skills`, own(() => SKILLS));
  route.get(`${A}/profile`, own(() => PROFILE));
  route.get(`${A}/recall`, own(() => ({ items: RECALL })));
  route.get(`${A}/telegram/status`, own(() => TELEGRAM));
  route.get(`${A}/pushover/status`, own(() => PUSHOVER));
  route.get(`${A}/bots/:id/telegram`, own(() => BOT_TELEGRAM));
  route.get(`${A}/background-model`, own(() => ({ configured: true, has_key: true, provider: "siliconflow", model: "deepseek-ai/DeepSeek-V4-Flash", base_url: null, updated_at: null })));
  route.get("/knowledge/documents", () => ({ items: KNOWLEDGE_DOCS }));
  route.get("/knowledge/candidates", () => ({ items: [] }));
}
