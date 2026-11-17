// Fixture entry: buildState() makes a fresh mutable state per browser context; registerRoutes() wires the handlers.
import { ASK_MARKER, BOT, BUSY_MARKER, CONVERSATION, HOLD_MARKER, LOGIN_CODE, WATCHLIST } from "./ids.mjs";
import { NO_PRICES, emptyPrices, prices } from "./common.mjs";
import { botList, BOT_TEMPLATES, MODEL_CATALOG, MODEL_ROLES } from "./bots.mjs";
import { buildChat, CITATION_DETAILS, clarificationEvents, compactionNotice, conversationSummaries, CONTEXT_USAGE, streamEvents } from "./chat.mjs";
import { filingInventory } from "./filings.mjs";
import { MATERIALS, materialList, analysisVersion, materialOriginal, ANALYSIS_SETTINGS } from "./materials.mjs";
import { forecastList, forecastRoots, timeline, versionDetail, evaluations, monitorStatus, replayJob, REPLAY_JOB, workspace, job, revisionCandidates, JUDGMENTS } from "./forecasts.mjs";
import { portfolioSummary, buildPortfolio } from "./portfolio.mjs";
import { TASKS, RUNS, PROPOSALS, INBOX } from "./routines.mjs";
import { NEWS, SKILLS, PROFILE, RECALL, TELEGRAM, BOT_TELEGRAM, PUSHOVER, KNOWLEDGE_DOCS } from "./assistant.mjs";

export function buildState() {
  return { bots: botList(), queue: [...WATCHLIST], chat: buildChat(), modelRoles: { ...MODEL_ROLES.roles }, portfolio: buildPortfolio(), tasks: structuredClone(TASKS), inbox: structuredClone(INBOX) };
}

/** The fields of a multipart/form-data body as the page sent them; a file part is described by its name, type and size. */
export function multipartFields(raw, contentType) {
  const boundary = /boundary=(?:"([^"]+)"|([^;]+))/.exec(contentType ?? "");
  const fields = {};
  if (!boundary || typeof raw !== "string") return fields;
  for (const part of raw.split(`--${boundary[1] ?? boundary[2]}`)) {
    const split = part.indexOf("\r\n\r\n");
    if (split < 0) continue;
    const head = part.slice(0, split), value = part.slice(split + 4).replace(/\r\n$/, "");
    const name = /name="([^"]*)"/.exec(head)?.[1];
    if (!name) continue;
    const file = /filename="([^"]*)"/.exec(head);
    fields[name] = file ? { filename: file[1], type: /Content-Type:\s*(\S+)/i.exec(head)?.[1] ?? "", size: value.length } : value;
  }
  return fields;
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
  // A create (P5.2): the server's own refusals first (a name must be 1–40 characters and unused among the owner's bots, else 422 with the detail code), then the bot
  // with the defaults of a fresh record under the fields the request named.  `state.createdBots` collects the new ones so a check can read them back.
  route.post(`${A}/bots`, own(({ body, state }) => {
    const name = typeof body?.name === "string" ? body.name.trim() : "";
    if (!name || name.length > 40) return reply.status(422, { detail: "invalid_name" });
    if (state.bots.some((x) => x.name === name)) return reply.status(422, { detail: "name_taken" });
    const n = state.bots.length + 1, hex = String(n).padStart(12, "0");
    const created = { description: "", tool_scope: null, model: null, reasoning_effort: null, skills: [], avatar: "", look: null, group: "", pinned: false, hidden: false, template: "blank",
      daily_notify_cap: 5, default_company: null, last_message: null, last_at: null, unread: 0, pending: 0, focus: { companies: [], theme: null }, title: "",
      ...body, name, id: `b0000000-0000-4000-8000-${hex}`, conversation_id: `c0000000-0000-4000-8000-${hex}`, is_default: false, created_at: "2026-11-13T02:00:00.000Z", updated_at: "2026-11-13T02:00:00.000Z" };
    state.bots.push(created);
    state.createdBots = [...(state.createdBots ?? []), created.id];
    return { bot: created };
  }));
  route.post(`${A}/bots/:id/read`,own(({ params, state }) => { const b = state.bots.find((x) => x.id === params.id); const read = b?.unread ?? 0; if (b) b.unread = 0; return { read }; }));
  route.get(`${A}/research-queue`, own(({ state }) => ({ symbols: state.queue })));
  // Every save is kept as the browser sent it (the raw text): the watchlist checks compare it with the body the old page sent.
  route.put(`${A}/research-queue`, own(({ body, rawBody, state }) => { state.queue = body.symbols; state.queuePuts = [...(state.queuePuts ?? []), rawBody]; return { ok: true }; }));

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
    // FP13-c: the line is answering somewhere else; nothing is written (the server refuses before the turn starts).
    if (String(body.message).includes(BUSY_MARKER)) return reply.status(409, { detail: "conversation_busy" });
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

  // FP13-c: the stop of a turn.  state.chat.cancels keeps every request body; state.chat.cancelReply picks the answer (500 = unreachable, an object = that answer).
  route.post(`${A}/conversations/:id/cancel`, own(({ body, state }) => {
    state.chat.cancels = [...(state.chat.cancels ?? []), body ?? {}];
    const picked = state.chat.cancelReply;
    if (picked === 500) return reply.status(500, { detail: "cancel_failed" });
    if (picked && typeof picked === "object") return picked;
    return { cancelled: true, turn_id: body?.turn_id ?? null };
  }));

  // A citation's chunk (the 来源 tab and the hover card read it).  An id with no entry is a withdrawn source.
  route.get("/knowledge/citations/:id", own(({ params }) => CITATION_DETAILS[params.id] ?? reply.status(404, { detail: "citation_not_found" })));

  // --- market data -------------------------------------------------------------------------------------
  // A symbol in NO_PRICES has no candles until the initialise request (below) has been made for it.
  route.get("/v2/stocks/:symbol/prices", ({ params, state }) => (NO_PRICES.has(params.symbol) && !state.pricesInitialized?.has(params.symbol) ? emptyPrices(params.symbol) : prices(params.symbol)));
  route.post("/market-data/:symbol/initialize", own(({ params, state }) => {
    state.pricesInitialized = new Set([...(state.pricesInitialized ?? []), params.symbol]);
    state.initializations = [...(state.initializations ?? []), params.symbol];
    return { symbol: params.symbol, inserted_count: 252, skipped_count: 0 };
  }));
  route.get("/filing-inventories/:symbol", ({ params }) => filingInventory(params.symbol));

  // --- forecasts (V2) ----------------------------------------------------------------------------------
  const found = (value) => (value ?? reply.status(404, { detail: "not_found" }));
  route.get("/v2/forecasts", ({ query, state }) => forecastList(query, state));
  route.get("/v2/stocks/:symbol/forecast-roots", ({ params }) => forecastRoots(params.symbol));
  route.get("/v2/stocks/:symbol/workspace", ({ params }) => workspace(params.symbol));
  route.get("/v2/forecast-roots/:id/timeline", ({ params, state }) => found(timeline(params.id, state)));
  route.get("/v2/forecast-versions/:id", ({ params }) => found(versionDetail(params.id)));
  route.get("/v2/forecast-versions/:id/revision-candidates", ({ params, state }) => revisionCandidates(params.id, state));
  route.get("/v2/jobs/:id", ({ params, state }) => (params.id === REPLAY_JOB ? (replayJob(state) ?? reply.status(404, { detail: "not_found" })) : job(params.id, state)));
  // The two writes of the forecast pages.  The raw body of every request is kept in state.forecastPosts (what the body checks compare to the baseline); the job they answer with
  // is the one `job()` describes, so `state.jobStatus` ("running" keeps it on the task bar) decides what the page sees next.
  route.post("/v2/forecast-jobs", ({ rawBody, body, state }) => {
    state.forecastPosts = [...(state.forecastPosts ?? []), { path: "/v2/forecast-jobs", body: rawBody }];
    return job("j2000000-0000-4000-8000-000000000001", { ...state, jobKind: "new", jobSymbol: body?.symbol ?? "AAPL" });
  });
  route.post("/v2/forecast-versions/:id/revision-jobs", ({ params, rawBody, state }) => {
    state.forecastPosts = [...(state.forecastPosts ?? []), { path: `/v2/forecast-versions/${params.id}/revision-jobs`, body: rawBody }];
    return job("j2000000-0000-4000-8000-000000000002", state);
  });
  route.get("/v2/monitor/status", ({ state }) => (state.monitorError ? reply.status(500, { detail: "monitor_unavailable" }) : monitorStatus(state)));
  route.get("/v2/evaluations", ({ query, state }) => (state.scoresError && !query.get("symbol") ? reply.status(500, { detail: "evaluations_unavailable" }) : evaluations(query.get("symbol"), state)));
  // P6.4: the historical replay write.  The raw body and the presence of the Idempotency-Key header are kept in state.replayPosts (what the body check compares with the baseline recorded from the old UI).
  route.post("/v2/historical-replays", ({ rawBody, body, headers, state }) => {
    state.replayPosts = [...(state.replayPosts ?? []), { path: "/v2/historical-replays", body: rawBody, idempotencyKey: Boolean(headers["idempotency-key"]) }];
    state.replayMade = { symbol: body?.symbol ?? "AAPL", date: body?.decision_date ?? "2026-10-12", polls: 0 };
    return { id: REPLAY_JOB, symbol: state.replayMade.symbol, kind: "new", root_version_id: null, parent_version_id: null, source_refs: [], time_mode: "historical_research", requested_decision_at: `${state.replayMade.date}T00:00:00Z`, status: "queued", current_stage: "queued", attempts: 0, error: null, result_version_id: null, created_at: "2026-11-13T01:00:00Z", started_at: null, completed_at: null };
  });
  route.get(`${A}/earnings-judgments`, own(({ query, state }) => ({ judgments: state.noForecasts ? [] : JUDGMENTS.filter((j) => !query.get("symbol") || j.symbol === query.get("symbol")) })));
  route.get(`${A}/earnings-judgments/:id`, own(({ params }) => { const j = JUDGMENTS.find((x) => x.id === params.id); return j ? { judgment: j } : reply.status(404, { detail: "not_found" }); }));

  // --- materials (V3) ----------------------------------------------------------------------------------
  route.get("/v3/materials", ({ query }) => materialList(query));
  route.get("/v3/materials/analysis-settings", () => ANALYSIS_SETTINGS);
  route.get("/v3/materials/:type/:id/analyses", ({ params }) => { const m = MATERIALS.find((x) => x.source_id === params.id); const no = m?.latest_analysis_id ? Number(m.latest_analysis_id.slice(-12)) : null;
    return { source_type: params.type, source_id: params.id, items: no ? [analysisVersion(no, { symbol: m.symbol })] : [] }; });
  route.get("/v3/materials/:type/:id/original", ({ params }) => materialOriginal(params.type, params.id));
  route.get("/v3/material-analyses/:id", ({ params }) => { const m = MATERIALS.find((x) => x.latest_analysis_id === params.id); return analysisVersion(Number(params.id.slice(-12)), { symbol: m?.symbol ?? "AAPL" }); });
  // A job this fake backend created (the POST below) answers "running" for `state.jobRunningPolls` reads (default 2) and then "succeeded" with an analysis; `state.jobHold` keeps every
  // job running (a page that shows the task bar).  A job id nobody created is "succeeded" with no analysis, as before.
  route.get("/v3/material-analysis-jobs/:id", ({ params, state }) => {
    if (state.jobHold) return { job_id: params.id, status: "running", analysis_id: null, cache_hit: false, current_stage: "analyzing" };
    const made = state.analysisJobs?.[params.id];
    if (!made) return { job_id: params.id, status: "succeeded", analysis_id: null, cache_hit: false };
    made.polls += 1;
    return made.polls < (state.jobRunningPolls ?? 2) ? { job_id: params.id, status: "running", analysis_id: null, cache_hit: false, current_stage: "analyzing" }
      : { job_id: params.id, status: "succeeded", analysis_id: made.analysisId, cache_hit: false, current_stage: "done" };
  });
  // P6.3 writes.  Every request is kept as the browser sent it in state.materialPosts (what the body checks compare with the baseline recorded from the old UI):
  // a scan, an analysis job (the Idempotency-Key header is random, so only its presence is kept) and an upload (the form fields; the file by name, type and size).
  const post = (state, entry) => { state.materialPosts = [...(state.materialPosts ?? []), entry]; };
  route.post("/filing-inventories/:symbol/scan", ({ params, state }) => {
    post(state, { kind: "scan", path: `/filing-inventories/${params.symbol}/scan` });
    return { ...filingInventory(params.symbol), cik: "0000000000", discovered_count: state.scanDiscovered ?? 7, created_count: state.scanCreated ?? 3, skipped_count: 4, observed_at: "2026-11-13T02:00:00.000Z" };
  });
  route.post("/v3/materials/:type/:id/analysis-jobs", ({ params, rawBody, headers, state }) => {
    post(state, { kind: "analysis-job", path: `/v3/materials/${params.type}/${params.id}/analysis-jobs`, body: rawBody, idempotencyKey: Boolean(headers["idempotency-key"]) });
    const jobId = `j9000000-0000-4000-8000-${String(Object.keys(state.analysisJobs ?? {}).length + 1).padStart(12, "0")}`;
    const row = MATERIALS.find((m) => m.source_id === params.id);
    state.analysisJobs = { ...(state.analysisJobs ?? {}), [jobId]: { polls: 0, analysisId: row?.latest_analysis_id ?? analysisVersion(1).analysis_id } };
    return { job_id: jobId, status: "queued", analysis_id: null, cache_hit: false, current_stage: "queued", attempts: 0 };
  });
  route.get("/uploaded-evidence/:symbol", ({ params, state }) => ({ symbol: params.symbol, items: state.uploaded?.[params.symbol] ?? [] }));
  route.post("/uploaded-evidence/:symbol", ({ params, rawBody, headers, state }) => {
    const fields = multipartFields(rawBody, headers["content-type"]);
    post(state, { kind: "upload", path: `/uploaded-evidence/${params.symbol}`, fields, session: Boolean(headers["x-chat-session"]) });
    const item = { id: `u0000000-0000-4000-8000-${String((state.uploaded?.[params.symbol]?.length ?? 0) + 1).padStart(12, "0")}`, symbol: params.symbol, title: fields.title, source_url: fields.source_url, published_at: fields.published_at,
      uploaded_at: "2026-11-13T02:00:00.000Z", credibility_stars: Number(fields.credibility_stars), credibility_reason: fields.credibility_reason, impact_severity: fields.impact_severity, status: "unconfirmed" };
    state.uploaded = { ...(state.uploaded ?? {}), [params.symbol]: [item, ...(state.uploaded?.[params.symbol] ?? [])] };
    return item;
  });
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
  // 解绑: the bot's own Telegram is a token without a chat again (the binding steps start over from the code); `state.botTelegramBound[id]` goes back to false.
  route.post(`${A}/bots/:id/telegram/unbind`, own(({ params, state }) => {
    const mine = { ...BOT_TELEGRAM, ...(state.botTelegram?.[params.id] ?? {}), bound: false, bind_code_active: false, status: "unbound", chat_id: null, bound_at: null };
    state.botTelegram = { ...(state.botTelegram ?? {}), [params.id]: mine };
    state.botTelegramBound = { ...(state.botTelegramBound ?? {}), [params.id]: false };
    return mine;
  }));
  route.post(`${A}/bots/:id/telegram/bind`, own(({ params, state }) => {
    state.botTelegram = { ...(state.botTelegram ?? {}), [params.id]: { ...state.botTelegram?.[params.id], bind_code_active: true } };
    return { code: "482913", bot_username: "finbot_fixture_bot", link: null, expires_at: "2026-11-13T02:30:00.000Z" };
  }));
  route.get(`${A}/background-model`, own(() => ({ configured: true, has_key: true, provider: "siliconflow", model: "deepseek-ai/DeepSeek-V4-Flash", base_url: null, updated_at: null })));
  route.get("/knowledge/documents", () => ({ items: KNOWLEDGE_DOCS }));
  route.get("/knowledge/candidates", () => ({ items: [] }));
}
