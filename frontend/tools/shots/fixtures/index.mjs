// Fixture entry: buildState() makes a fresh mutable state per browser context; registerRoutes() wires the handlers.
import { ASK_MARKER, BOT, CONVERSATION, HOLD_MARKER, LOGIN_CODE, WATCHLIST } from "./ids.mjs";
import { prices } from "./common.mjs";
import { botList, BOT_TEMPLATES, MODEL_CATALOG, MODEL_ROLES } from "./bots.mjs";
import { buildChat, CITATION_DETAILS, clarificationEvents, compactionNotice, conversationSummaries, CONTEXT_USAGE, streamEvents } from "./chat.mjs";
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
  // A save (P5.1): the fields it names replace the bot's, as the server does; the answer is the bot as it now stands.  The bodies are what the smoke checks read from view.mock.requests.
  route.patch(`${A}/bots/:id`, own(({ params, body, state }) => {
    const found = state.bots.find((x) => x.id === params.id);
    if (!found) return reply.status(404, { detail: "bot_not_found" });
    Object.assign(found, body, { updated_at: "2026-11-13T02:00:01.000Z" });
    return { bot: found };
  }));
  route.post(`${A}/bots/:id/read`,own(({ params, state }) => { const b = state.bots.find((x) => x.id === params.id); const read = b?.unread ?? 0; if (b) b.unread = 0; return { read }; }));
  route.get(`${A}/research-queue`, own(({ state }) => ({ symbols: state.queue })));
  route.put(`${A}/research-queue`, own(({ body, state }) => { state.queue = body.symbols; return { ok: true }; }));

  // --- conversations -----------------------------------------------------------------------------------
  route.get(`${A}/conversations`, own(({ state }) => ({ conversations: conversationSummaries(state), has_more: false })));
  // state.chat.older[id] = { messages, cursor } (a check sets it) makes the newest page say "there are earlier turns" until they are asked for with ?before=.
  route.get(`${A}/conversations/:id/messages`, own(({ params, query, state }) => {
    const compactions = state.chat.compactions?.[params.id] ?? [];
    const older = state.chat.older?.[params.id];
    if (older && query.get("before") !== null) return { messages: older.messages, has_more: false, next_before: null, compactions };
    return { messages: state.chat.conversations.get(params.id) ?? [], has_more: Boolean(older), next_before: older ? older.cursor : null, compactions };
  }));
  route.post(`${A}/conversations/:id/compact`, own(({ params, body, state }) => {
    const turns = state.chat.conversations.get(params.id) ?? [];
    const after = turns.filter((m) => m.role === "assistant" && m.turn_id)[1]?.turn_id ?? turns.find((m) => m.turn_id)?.turn_id ?? "t0000000-0000-4000-8000-000000000001";
    state.chat.compactions = { ...(state.chat.compactions ?? {}), [params.id]: [compactionNotice(after, body?.focus)] };
    return { compacted: 2, message: "已压缩 2 轮。" };
  }));
  route.get(`${A}/conversations/:id/context`, own(() => CONTEXT_USAGE));
  route.get(`${A}/context`, own(() => CONTEXT_USAGE));
  route.post(`${A}/stream`, own(({ body, state }) => {
    // A message containing the hold marker is never answered: that bot's line stays "answering" (the sidebar's 回答中 mark).
    if (String(body.message).includes(HOLD_MARKER)) return new Promise(() => {});
    const bot = body.bot_id ? state.bots.find((b) => b.id === body.bot_id) : null;
    const conversationId = bot?.conversation_id ?? body.conversation_id ?? CONVERSATION.finbot;
    const asking = String(body.message).includes(ASK_MARKER);
    const events = asking ? clarificationEvents({ conversationId, botId: bot?.id }) : streamEvents({ conversationId, message: body.message, botId: bot?.id });
    const list = state.chat.conversations.get(conversationId) ?? [];
    state.chat.conversations.set(conversationId, list);
    if (asking) {
      list.push({ role: "user", content: body.display_message || body.message }, { role: "assistant", status: "waiting_for_input", turn_id: events[0].data.turn_id,
        content: events[1].data.text, clarification: events[2].data });
      return reply.sse(events);
    }
    const text = events.filter((e) => e.event === "delta").map((e) => e.data.text).join("");
    list.push({ role: "user", content: body.display_message || body.message }, { role: "assistant", status: "complete", turn_id: events[0].data.turn_id, content: text, thinking_ms: 900 });
    return reply.sse(events);
  }));

  // A citation's chunk (the 来源 tab and the hover card read it).  An id with no entry is a withdrawn source.
  route.get("/knowledge/citations/:id", own(({ params }) => CITATION_DETAILS[params.id] ?? reply.status(404, { detail: "citation_not_found" })));

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

  // --- the writes the in-app confirmations guard (P2.3): the deletes and the unbind.  Each answers ok; the portfolio one also drops the row. ---
  route.delete(`${A}/portfolio/transactions/:id`, own(({ params, state }) => { state.portfolio.transactions = state.portfolio.transactions.filter((t) => t.id !== params.id); return { ok: true, status: "deleted" }; }));
  route.delete(`${A}/skills/:id`, own(() => ({ ok: true })));
  route.delete(`${A}/profile/:id`, own(() => ({ ok: true })));
  route.delete(`${A}/news-sources/:id`, own(() => ({ ok: true })));
  route.delete(`${A}/tasks/:id`, own(() => ({ ok: true })));
  route.delete(`${A}/bots/:id`, own(() => ({ ok: true })));
  route.delete(`${A}/bots/:id/telegram`, own(() => ({ ...BOT_TELEGRAM, configured: false, has_token: false, bound: false, shared: true })));
  route.delete(`${A}/model-catalog/:name`, own(() => ({ ok: true })));
  route.post(`${A}/telegram/unbind`, own(() => ({ ...TELEGRAM, bound: false, chat_id: null })));

  // --- assistant: news sources, skills, memory, settings cards -----------------------------------------
  route.get(`${A}/news-sources`, own(() => NEWS));
  route.get(`${A}/skills`, own(() => SKILLS));
  route.get(`${A}/profile`, own(() => PROFILE));
  route.get(`${A}/recall`, own(() => ({ items: RECALL })));
  route.get(`${A}/telegram/status`, own(() => TELEGRAM));
  route.get(`${A}/pushover/status`, own(() => PUSHOVER));
  // A bot's own Telegram: answered as bound and running unless a check set state.botTelegram[id] (the P5.1 steps check does: no token yet).  Saving a token, making a binding
  // code and the bind itself move that record on; `state.botTelegramBound[id] = true` is the message arriving from Telegram.
  route.get(`${A}/bots/:id/telegram`, own(({ params, state }) => {
    const mine = state.botTelegram?.[params.id];
    if (!mine) return BOT_TELEGRAM;
    return state.botTelegramBound?.[params.id] ? { ...mine, bound: true, bind_code_active: false, status: "running" } : mine;
  }));
  route.post(`${A}/bots/:id/telegram/token`, own(({ params, state }) => {
    state.botTelegram = { ...(state.botTelegram ?? {}), [params.id]: { ...BOT_TELEGRAM, has_token: true, bound: false, status: "unbound", chat_id: null, bound_at: null, shared: false, token_tail: "7f3a" } };
    return state.botTelegram[params.id];
  }));
  route.post(`${A}/bots/:id/telegram/bind`, own(({ params, state }) => {
    state.botTelegram = { ...(state.botTelegram ?? {}), [params.id]: { ...state.botTelegram?.[params.id], bind_code_active: true } };
    return { code: "482913", bot_username: "finbot_fixture_bot", link: null, expires_at: "2026-11-13T02:30:00.000Z" };
  }));
  route.get(`${A}/background-model`, own(() => ({ configured: true, has_key: true, provider: "siliconflow", model: "deepseek-ai/DeepSeek-V4-Flash", base_url: null, updated_at: null })));
  route.get("/knowledge/documents", () => ({ items: KNOWLEDGE_DOCS }));
  route.get("/knowledge/candidates", () => ({ items: [] }));
}
