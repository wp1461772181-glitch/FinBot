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
import { backstageRoutes } from "./backstage.mjs";
import { OWNER_VIEWS, activeViews, viewHistory } from "./views.mjs";
import { memoryOverview } from "./overview.mjs";
import { buildWatch, patchPreset, resetPreset, watchView } from "./watch.mjs";
import { buildTemplates, templateApply, templatePreview, templatesList, templateUndo } from "./templates.mjs";
import { NEWS, SKILLS, PROFILE, RECALL, TELEGRAM, BOT_TELEGRAM, PUSHOVER, KNOWLEDGE_DOCS, DRY_RUNS, REPAIRS, KNOWLEDGE_IMPORTABLE, knowledgeChunks, readSkillFile } from "./assistant.mjs";

export function buildState() {
  return { views: structuredClone(OWNER_VIEWS), bots: botList(), queue: [...WATCHLIST], chat: buildChat(), modelRoles: { ...MODEL_ROLES.roles }, portfolio: buildPortfolio(), tasks: structuredClone(TASKS), inbox: structuredClone(INBOX), proposals: structuredClone(PROPOSALS), runs: structuredClone(RUNS), routines: { writes: [] }, assistant: buildAssistant(), templates: buildTemplates(), watch: buildWatch(), settings: buildSettings(), backstage: {} };
}

/** The 设置 pages' data as a mutable copy (P8.2): the write routes below change it and the reads answer from it.  `writes` keeps every write as the page sent it (the role table's own state is `modelRoles`).
 *  `testFail` (a refusal code) makes 测试 answer 422; `discovery` is what 服务商可用模型 answers ("ok", "unsupported", "empty" or a refusal code). */
function buildSettings() {
  return { writes: [], catalog: structuredClone(MODEL_CATALOG), analysis: structuredClone(ANALYSIS_SETTINGS), telegram: structuredClone(TELEGRAM), pushover: structuredClone(PUSHOVER), testFail: null, discovery: "ok", counter: 0 };
}

/** The 助手 pages' data as a mutable copy (P8.1): the write routes below change it and the reads answer from it, so a save shows in the list.  `writes` keeps every write as the page sent it. */
function buildAssistant() {
  return { writes: [], skills: structuredClone(SKILLS.skills), news: structuredClone(NEWS), profile: structuredClone(PROFILE.items), recall: structuredClone(RECALL), docs: structuredClone(KNOWLEDGE_DOCS), candidates: [], counter: 0 };
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
  route.get(`${A}/model-catalog`, own(({ state }) => state.settings.catalog));
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
  // P7.3: `state.forecastRootsError` makes the company's forecast-root list unreadable (the `latest` redirect page's error state).
  route.get("/v2/stocks/:symbol/forecast-roots", ({ params, state }) => (state.forecastRootsError ? reply.status(500, { detail: "forecast_roots_unavailable" }) : forecastRoots(params.symbol)));
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
  route.get("/v3/materials/analysis-settings", ({ state }) => state.settings.analysis);
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

  // --- 后台: the owner's read-only backstage (fixtures/backstage.mjs) ---------------------------------------------
  backstageRoutes(route, reply, own);

  // --- portfolio, routines, inbox ----------------------------------------------------------------------
  route.get(`${A}/portfolio`, own(({ state }) => (state.portfolio.fail ? reply.status(500, { detail: "shots: forced failure" }) : portfolioSummary(state))));
  // P7.1: the ledger's three writes.  Each keeps the request exactly as the page sent it (`state.portfolio.writes`: method, path, body) so a check reads the
  // body back; the answer is what the server answers (`ok`, `status`, the new `id`), and the state moves the way the server's does (a new row, the cash, the plan).
  const written = (state, method, path, body) => { (state.portfolio.writes ??= []).push({ method, path, body: structuredClone(body) }); };
  route.post(`${A}/portfolio/transactions`, own(({ body, state }) => {
    written(state, "POST", "/portfolio/transactions", body);
    const id = `p0000000-0000-4000-8000-${String(900 + state.portfolio.writes.length).padStart(12, "0")}`;
    state.portfolio.transactions = [{ id, symbol: body.symbol ?? "", kind: body.kind, quantity: body.quantity ?? null, price: body.price ?? null, fee: body.fee ?? null, amount: body.amount ?? null,
      ratio: body.ratio ?? null, occurred_on: body.occurred_on ?? "2026-11-13", note: body.note ?? "", created_at: "2026-11-13T02:00:00Z" }, ...state.portfolio.transactions];
    return { ok: true, status: "recorded", id, warnings: [] };
  }));
  route.put(`${A}/portfolio/cash`, own(({ body, state }) => {
    written(state, "PUT", "/portfolio/cash", body);
    state.portfolio.cash = Number(body.available_funds).toFixed(2);
    return { ok: true, status: "updated", available_funds: state.portfolio.cash };
  }));
  route.put(`${A}/portfolio/plans/:symbol`, own(({ params, body, state }) => {
    written(state, "PUT", `/portfolio/plans/${params.symbol}`, body);
    state.portfolio.plans[params.symbol] = { plan_text: body.plan_text, add_price: body.add_price, stop_price: body.stop_price, target_price: body.target_price, updated_at: "2026-11-13T02:00:00Z" };
    return { ok: true, status: "saved" };
  }));
  route.get(`${A}/tasks`, own(({ state, query }) => ({ tasks: state.tasks.filter((t) => !query.get("bot_id") || t.bot_id === query.get("bot_id")) })));
  route.get(`${A}/tasks/runs`, own(({ state, query }) => ({ runs: state.runs.filter((r) => !query.get("bot_id") || TASKS.find((t) => t.id === r.task_id)?.bot_id === query.get("bot_id")) })));
  route.get(`${A}/tasks/proposals`, own(({ state }) => ({ proposals: state.proposals })));
  // P7.2: the routine writes.  Each keeps the request exactly as the page sent it (`state.routines.writes`: method, path, body) so a check reads the body back; the state moves
  // the way the server's does: a new task is listed, a patch merges into its task, and an inbox action sets the item's status the way fin_news_engine's
  // handle_inline_confirmation_action does (confirm: done / confirmed; skip: dismissed / skipped; later: read; the status route: whatever it is told; the card: a minted card).
  const routineWritten = (state, method, path, body) => { (state.routines.writes ??= []).push({ method, path, body: structuredClone(body) }); };
  const taskDefaults = { every_value: null, every_unit: null, max_runs: null, runs_done: 0, finished: false, enabled: true, last_run_at: null, next_run_at: "2026-11-16T00:30:00Z", last_status: null, last_status_label: null, last_conversation_id: null };
  route.post(`${A}/tasks`, own(({ body, state }) => {
    routineWritten(state, "POST", "/tasks", body);
    const task = { ...taskDefaults, ...body, id: `t2000000-0000-4000-8000-${String(900 + state.routines.writes.length).padStart(12, "0")}`, max_runs: body.max_runs ? body.max_runs : null };
    state.tasks = [...state.tasks, task];
    return { task };
  }));
  route.patch(`${A}/tasks/:id`, own(({ params, body, state }) => {
    routineWritten(state, "PATCH", `/tasks/${params.id}`, body);
    const task = state.tasks.find((t) => t.id === params.id);
    if (!task) return reply.status(404, { detail: "task_not_found" });
    Object.assign(task, body, body.max_runs !== undefined ? { max_runs: body.max_runs ? body.max_runs : null } : {});
    return { task };
  }));
  route.post(`${A}/inbox/:id/confirm`, own(({ params, body, state }) => {
    routineWritten(state, "POST", `/inbox/${params.id}/confirm`, body);
    const item = state.inbox.find((i) => i.id === params.id);
    if (!item) return reply.status(404, { detail: "confirmation_not_found" });
    const next = { confirm: ["done", "confirmed"], skip: ["dismissed", "skipped"], later: ["read", item.confirmation_state] }[body.action];
    if (!next) return reply.status(400, { detail: "invalid_confirmation_action" });
    item.status = next[0]; item.confirmation_state = next[1]; item.payload = { ...item.payload, confirmation_state: next[1] };
    return { ok: true, state: next[1], item };
  }));
  route.post(`${A}/inbox/:id/status`, own(({ params, body, state }) => {
    routineWritten(state, "POST", `/inbox/${params.id}/status`, body);
    const item = state.inbox.find((i) => i.id === params.id);
    if (!item) return reply.status(404, { detail: "item_not_found" });
    item.status = body.status;
    return { item };
  }));
  route.post(`${A}/inbox/:id/card`, own(({ params, state }) => {
    routineWritten(state, "POST", `/inbox/${params.id}/card`, null);
    const item = state.inbox.find((i) => i.id === params.id);
    return { conversation_id: item?.conversation_id ?? CONVERSATION.finbot, request_id: "q0000000-0000-4000-8000-000000000001", expires_at: null };
  }));
  route.get(`${A}/inbox`, own(({ state, query }) => ({ items: state.inbox.filter((i) => (!query.get("section") || i.section === query.get("section")) && (!query.get("bot_id") || i.bot_id === query.get("bot_id"))) })));

  // --- the writes the in-app confirmations guard (P2.3): the deletes and the unbind.  Each answers ok; the portfolio one also drops the row. ---
  route.delete(`${A}/portfolio/transactions/:id`, own(({ params, state }) => { written(state, "DELETE", `/portfolio/transactions/${params.id}`, null); state.portfolio.transactions = state.portfolio.transactions.filter((t) => t.id !== params.id); return { ok: true, status: "deleted" }; }));
  route.delete(`${A}/tasks/:id`, own(({ params, state }) => { routineWritten(state, "DELETE", `/tasks/${params.id}`, null); state.tasks = state.tasks.filter((t) => t.id !== params.id); return { ok: true }; }));
  route.delete(`${A}/bots/:id`, own(() => ({ ok: true })));
  route.delete(`${A}/bots/:id/telegram`, own(() => ({ ...BOT_TELEGRAM, configured: false, has_token: false, bound: false, shared: true })));

  // --- assistant: news sources, skills, memory, settings cards -----------------------------------------
  assistantRoutes(route, reply, own);
  settingsRoutes(route, reply, own);
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
}

/** The 助手 routes (P8.1).  Reads answer from `state.assistant`; every write is kept as `{ method, path, body }` in `state.assistant.writes` and moves the state the way the server's answer says. */
function assistantRoutes(route, reply, own) {
  const A = "/agent-chat";
  const kept = (state, method, path, body) => { state.assistant.writes.push({ method, path, body: body === undefined ? null : structuredClone(body) }); };
  const id = (state, prefix) => `${prefix}-0000-4000-8000-${String(900 + ++state.assistant.counter).padStart(12, "0")}`;
  const unknownSkill = () => reply.status(404, { detail: "unknown_skill" });

  // --- skills
  route.get(`${A}/skills`, own(({ state }) => ({ skills: state.assistant.skills, tools: SKILLS.tools })));
  route.post(`${A}/skills`, own(({ body, state }) => {
    kept(state, "POST", "/skills", body);
    const skill = { id: id(state, "s3000000"), version: 1, origin: "mine", status: "active", builtin: false, updated_at: "2026-11-13T02:00:00.000Z", enabled: true, output_template: null, ...body };
    state.assistant.skills.push(skill);
    return { skill };
  }));
  // Import comes before the :id routes: "import" must not be read as a skill id.
  route.post(`${A}/skills/import/preview`, own(({ body, state }) => {
    kept(state, "POST", "/skills/import/preview", body);
    const read = readSkillFile(body?.markdown);
    return read.error ? reply.status(422, { detail: read.error }) : read;
  }));
  route.post(`${A}/skills/import`, own(({ body, state }) => {
    kept(state, "POST", "/skills/import", body);
    const read = readSkillFile(body?.markdown);
    if (read.error) return reply.status(422, { detail: read.error });
    if (state.assistant.skills.some((s) => s.name === read.skill.name)) return reply.status(422, { detail: "name_taken" });
    const skill = { id: id(state, "s3000000"), version: 1, origin: "imported", status: "active", builtin: false, updated_at: "2026-11-13T02:00:00.000Z", enabled: true, ...read.skill };
    state.assistant.skills.push(skill);
    return { skill };
  }));
  route.patch(`${A}/skills/:id`, own(({ params, body, state }) => {
    kept(state, "PATCH", `/skills/${params.id}`, body);
    const skill = state.assistant.skills.find((s) => s.id === params.id);
    if (!skill) return unknownSkill();
    const { save_draft, ...fields } = body ?? {};
    Object.assign(skill, fields, save_draft ? { status: "active" } : {}, { version: skill.version + 1 });
    return { skill };
  }));
  route.post(`${A}/skills/:id/enabled`, own(({ params, body, state }) => {
    kept(state, "POST", `/skills/${params.id}/enabled`, body);
    const skill = state.assistant.skills.find((s) => s.id === params.id);
    if (!skill) return unknownSkill();
    skill.enabled = Boolean(body?.enabled);
    return { skill };
  }));
  route.post(`${A}/skills/:id/copy`, own(({ params, state }) => {
    kept(state, "POST", `/skills/${params.id}/copy`, null);
    const from = state.assistant.skills.find((s) => s.id === params.id);
    if (!from) return unknownSkill();
    const skill = { ...structuredClone(from), id: id(state, "s3000000"), name: `${from.name} 副本`, origin: "mine", builtin: false, status: "active", version: 1 };
    state.assistant.skills.push(skill);
    return { skill };
  }));
  route.get(`${A}/skills/:id/export`, own(({ params, state }) => {
    const skill = state.assistant.skills.find((s) => s.id === params.id);
    return skill ? reply.text(`---\nname: ${skill.name}\ndescription: ${skill.description}\ntools: ${skill.allowed_tools.join(", ")}\n---\n${skill.body}\n`, "text/markdown; charset=utf-8") : unknownSkill();
  }));
  route.delete(`${A}/skills/:id`, own(({ params, state }) => { kept(state, "DELETE", `/skills/${params.id}`, null); state.assistant.skills = state.assistant.skills.filter((s) => s.id !== params.id); return { ok: true }; }));

  // --- 你的看法 (the owner's views of companies): the memory page lists the active ones, a company page reads its history, 删除 removes one version
  route.get(`${A}/views`, own(({ state }) => ({ views: activeViews(state.views) })));
  route.get(`${A}/views/:symbol/history`, own(({ params, state }) => ({ symbol: params.symbol.toUpperCase(), versions: viewHistory(state.views, params.symbol.toUpperCase()) })));
  route.post(`${A}/views/:id/restore`, own(({ params, state }) => {
    kept(state, "POST", `/views/${params.id}/restore`, null);
    const view = state.views.find((v) => v.id === params.id && v.status === "archived");
    if (!view) return reply.status(404, { detail: "view_not_found" });
    if (state.views.some((v) => v.symbol === view.symbol && v.status === "active")) return reply.status(409, { detail: "这家公司已有一条当前看法，先撤回它再恢复" });
    Object.assign(view, { status: "active", status_label: "", ended_at: null, archived_reason: null });
    return { view };
  }));
  // --- 用模板起步 (4f): the templates and what was applied; preview writes nothing, apply writes the ticked memory into the profile, undo takes it out again.  `state.templates.writes` keeps every write as the page sent it.
  route.get(`${A}/role-templates`, own(({ state }) => templatesList(state)));
  route.post(`${A}/role-templates/applications/:id/undo`, own(({ params, body, state }) => {
    state.templates.writes.push({ method: "POST", path: `/role-templates/applications/${params.id}/undo`, body: structuredClone(body ?? null) });
    return templateUndo(state, params.id, body) ?? reply.status(404, { detail: "application_not_found" });
  }));
  route.post(`${A}/role-templates/:template/preview`, own(({ params, body, state }) => templatePreview(state, params.template, body) ?? reply.status(404, { detail: "unknown_template" })));
  route.post(`${A}/role-templates/:template/apply`, own(({ params, body, state }) => {
    state.templates.writes.push({ method: "POST", path: `/role-templates/${params.template}/apply`, body: structuredClone(body ?? null) });
    return templateApply(state, params.template, body) ?? reply.status(404, { detail: "unknown_template" });
  }));
  // --- 它在帮你盯的 → 规则 (5b-2): the rules, the system defaults and the sensitivity; every write is kept in `state.watch.writes` as the page sent it.
  route.get(`${A}/watch`, own(({ state }) => watchView(state)));
  route.patch(`${A}/watch-presets/:key`, own(({ params, body, state }) => {
    state.watch.writes.push({ method: "PATCH", path: `/watch-presets/${params.key}`, body: structuredClone(body ?? null) });
    const done = patchPreset(state, params.key, body);
    return done.row ?? reply.status(done.status, { detail: done.detail });
  }));
  route.post(`${A}/watch-presets/:key/reset`, own(({ params, state }) => {
    state.watch.writes.push({ method: "POST", path: `/watch-presets/${params.key}/reset`, body: null });
    const done = resetPreset(state, params.key);
    return done.row ?? reply.status(done.status, { detail: done.detail });
  }));
  route.put(`${A}/alert-settings`, own(({ body, state }) => {
    state.watch.writes.push({ method: "PUT", path: "/alert-settings", body: structuredClone(body ?? null) });
    if (body?.sensitivity !== undefined && !["quiet", "standard", "sensitive"].includes(body.sensitivity)) return reply.status(400, { detail: { error_code: "bad_sensitivity", reason: "灵敏度只能是安静、标准或灵敏。" } });
    if (body?.sensitivity !== undefined) state.watch.settings.sensitivity = body.sensitivity;
    if (typeof body?.short_moves === "boolean") state.watch.settings.short_moves = body.short_moves;
    return watchView(state).settings;
  }));
  route.delete(`${A}/watch-rules/:id`, own(({ params, state }) => {
    state.watch.writes.push({ method: "DELETE", path: `/watch-rules/${params.id}`, body: null });
    if (!state.watch.rules.some((r) => r.id === params.id)) return reply.status(404, { detail: "没有这条规则。" });
    state.watch.rules = state.watch.rules.filter((r) => r.id !== params.id);
    return { ok: true };
  }));
  // --- 它眼中的你: the overview of everything kept, the two page writes for a view, and the two downloads
  route.get(`${A}/memory/overview`, own(({ state }) => memoryOverview(state)));
  route.get(`${A}/memory/export`, own(({ query, state }) => {
    const format = query.get("format") ?? "json";
    if (format !== "json" && format !== "md") return reply.status(422, { detail: "invalid_format" });
    return format === "md" ? reply.text("# 它眼中的你\n", "text/markdown; charset=utf-8") : reply.text(JSON.stringify({ schema: "finbot-memory-export/1", ...memoryOverview(state) }, null, 2), "application/json; charset=utf-8");
  }));
  route.post(`${A}/views/:symbol`, own(({ params, body, state }) => {
    kept(state, "POST", `/views/${params.symbol}`, body);
    const symbol = params.symbol.toUpperCase(), text = String(body?.text ?? "").trim();
    if (text.length < 4) return reply.status(422, { detail: "view_quote_too_short" });
    const now = "2026-11-25T03:00:00+00:00";
    const replaced = state.views.find((v) => v.symbol === symbol && v.status === "active");
    if (replaced) Object.assign(replaced, { status: "superseded", status_label: "已更新", ended_at: now });
    state.viewSeq = (state.viewSeq ?? 0) + 1;
    const view = { id: `d0000000-0000-4000-8000-00000000${String(100 + state.viewSeq).padStart(4, "0")}`, symbol, text, quote: text, status: "active", status_label: "", archived_reason: null, source_message_id: null, conversation_id: null, turn_id: null, created_at: now, ended_at: null };
    state.views.push(view);
    return { status: replaced ? "replaced" : "recorded", view, replaced: Boolean(replaced) };
  }));
  route.post(`${A}/views/:symbol/drop`, own(({ params, state }) => {
    kept(state, "POST", `/views/${params.symbol}/drop`, null);
    const view = state.views.find((v) => v.symbol === params.symbol.toUpperCase() && v.status === "active");
    if (!view) return reply.status(404, { detail: "view_not_found" });
    Object.assign(view, { status: "dropped", status_label: "已撤回", ended_at: "2026-11-25T03:00:00+00:00" });
    return { view };
  }));
  route.delete(`${A}/views/:id`, own(({ params, state }) => {
    const found = state.views.some((v) => v.id === params.id);
    if (!found) return reply.status(404, { detail: "view_not_found" });
    state.views = state.views.filter((v) => v.id !== params.id);
    return { deleted: true };
  }));

  // --- memory
  route.get(`${A}/profile`, own(({ state }) => ({ items: state.assistant.profile, bots: PROFILE.bots })));
  const botName = (botId) => PROFILE.bots.find((b) => b.id === botId)?.name ?? null;
  route.post(`${A}/profile`, own(({ body, state }) => {
    kept(state, "POST", "/profile", body);
    const n = state.assistant.profile.length + 1;
    const item = { id: id(state, "pf000000"), handle: `P${n}`, topic: null, origin: "manual", quote: "", status: "active", scope: body.bot_id ? "bot" : "global", bot_name: botName(body.bot_id), created_at: "2026-11-13T02:00:00.000Z", updated_at: "2026-11-13T02:00:00.000Z", last_used_at: null, ...body };
    state.assistant.profile.push(item);
    return { item };
  }));
  route.patch(`${A}/profile/:id`, own(({ params, body, state }) => {
    kept(state, "PATCH", `/profile/${params.id}`, body);
    const item = state.assistant.profile.find((i) => i.id === params.id);
    if (!item) return reply.status(404, { detail: "profile_item_not_found" });
    Object.assign(item, body);
    if ("bot_id" in body) Object.assign(item, { scope: body.bot_id ? "bot" : "global", bot_name: botName(body.bot_id) });
    return { item };
  }));
  route.post(`${A}/profile/:id/confirm`, own(({ params, state }) => {
    kept(state, "POST", `/profile/${params.id}/confirm`, null);
    const item = state.assistant.profile.find((i) => i.id === params.id);
    if (!item) return reply.status(404, { detail: "profile_item_not_found" });
    if (item.status === "proposed") item.status = "active"; else item.origin = "explicit";   // a guess he confirms stays origin pattern
    return { item };
  }));
  route.post(`${A}/profile/:id/restore`, own(({ params, state }) => {
    kept(state, "POST", `/profile/${params.id}/restore`, null);
    const item = state.assistant.profile.find((i) => i.id === params.id && i.status === "archived");
    if (!item) return reply.status(404, { detail: "profile_item_not_found" });
    item.status = item.origin === "pattern" && !item.archived_at ? "proposed" : "active";
    Object.assign(item, { archived_at: null, archived_reason: null, last_seen_at: "2026-11-25T02:00:00.000Z" });
    return { item };
  }));
  route.delete(`${A}/profile/:id`, own(({ params, state }) => { kept(state, "DELETE", `/profile/${params.id}`, null); state.assistant.profile = state.assistant.profile.filter((i) => i.id !== params.id); return { ok: true }; }));
  // The query is read for one thing only: a search for 无结果 finds nothing (the page's no-match sentence).  Which address was asked is what the checks read, from the request log.
  route.get(`${A}/recall`, own(({ state, query }) => ({ items: String(query.get("q") ?? "").includes("无结果") ? [] : state.assistant.recall })));

  // --- news sources
  route.get(`${A}/news-sources`, own(({ state }) => state.assistant.news));
  route.post(`${A}/news-sources`, own(({ body, state }) => {
    kept(state, "POST", "/news-sources", body);
    const sources = state.assistant.news.sources, at = sources.findIndex((s) => s.id === body.id);
    const source = { health: "ok", consecutive_failures: 0, last_error: null, ...(at >= 0 ? sources[at] : {}), ...body };
    if (at >= 0) sources[at] = source; else sources.push(source);
    return { ok: true, source };
  }));
  route.put(`${A}/news-sources/push-settings`, own(({ body, state }) => {
    kept(state, "PUT", "/news-sources/push-settings", body);
    state.assistant.news.push.summary_max_tokens = body.summary_max_tokens;
    return { ok: true, push: { summary_max_tokens: body.summary_max_tokens } };
  }));
  route.post(`${A}/news-sources/:id/enabled`, own(({ params, body, state }) => {
    kept(state, "POST", `/news-sources/${params.id}/enabled`, body);
    const source = state.assistant.news.sources.find((s) => s.id === params.id);
    if (source) source.enabled = Boolean(body?.enabled);
    return { ok: true, enabled: Boolean(body?.enabled) };
  }));
  route.post(`${A}/news-sources/:id/dry-run`, own(({ params, state }) => { kept(state, "POST", `/news-sources/${params.id}/dry-run`, null); return { source_id: params.id, ...(DRY_RUNS[params.id] ?? { ok: false }) }; }));
  route.post(`${A}/news-sources/:id/repair`, own(({ params, state }) => {
    kept(state, "POST", `/news-sources/${params.id}/repair`, null);
    const answer = REPAIRS[params.id] ?? { ok: false };
    const source = state.assistant.news.sources.find((s) => s.id === params.id);
    if (answer.ok && source) Object.assign(source, { health: "ok", consecutive_failures: 0, last_error: null });
    return answer;
  }));
  route.delete(`${A}/news-sources/:id`, own(({ params, state }) => { kept(state, "DELETE", `/news-sources/${params.id}`, null); state.assistant.news.sources = state.assistant.news.sources.filter((s) => s.id !== params.id); return { ok: true }; }));

  // --- the knowledge library (owner endpoints without the /agent-chat prefix; the page sends the session header)
  route.get("/knowledge/documents", ({ state }) => ({ items: state.assistant.docs }));
  route.get("/knowledge/candidates", ({ state }) => ({ items: state.assistant.candidates }));
  route.get("/knowledge/importable/:source", ({ params }) => ({ items: KNOWLEDGE_IMPORTABLE[params.source] ?? [] }));
  route.post("/knowledge/import", ({ body, state }) => {
    kept(state, "POST", "/knowledge/import", body);
    for (const sourceId of body.source_ids) {
      const row = (KNOWLEDGE_IMPORTABLE[body.source_type] ?? []).find((r) => r.id === sourceId);
      if (row) state.assistant.docs.push({ id: id(state, "kd000000"), title: row.title, symbol: row.symbol, source_type: row.source_type, observed_at: "2026-11-12T00:00:00.000Z", available_at: "2026-11-12T00:00:00.000Z", status: "pending", active: true, owner_scope: "owner", chunks: 5 });
    }
    return { ok: true, accepted_sources: body.source_ids.length, chunks: body.source_ids.length * 5, needs_review: 0 };
  });
  route.post("/knowledge/index", ({ body, state }) => { kept(state, "POST", "/knowledge/index", body); return { ok: true, indexed: 3, failed: 1, idle: 0 }; });
  route.post("/knowledge/retrieval-test", ({ body, state }) => {
    kept(state, "POST", "/knowledge/retrieval-test", body);
    return { result: { ok: true, data: [{ title: "AAPL 10-Q（2026 财年第四季度）", snippet: "Services revenue grew year over year.", score: 0.83 }] }, citations: [{ index: 1, title: "AAPL 10-Q（2026 财年第四季度）", url: "https://example.test/docs/01" }] };
  });
  route.get("/knowledge/documents/:id/chunks", ({ params, state }) => knowledgeChunks(params.id, state.assistant.docs) ?? reply.status(404, { detail: "document_not_found" }));
  route.post("/knowledge/documents/:id/retry", ({ params, state }) => { kept(state, "POST", `/knowledge/documents/${params.id}/retry`, null); return { ok: true, queued_chunks: 3 }; });
  route.post("/knowledge/documents/:id/withdraw", ({ params, state }) => {
    kept(state, "POST", `/knowledge/documents/${params.id}/withdraw`, null);
    const doc = state.assistant.docs.find((d) => d.id === params.id);
    if (doc) Object.assign(doc, { active: false, status: "withdrawn" });
    return { ok: true, status: "withdrawn" };
  });
  route.post("/knowledge/candidates/:id/review", ({ params, body, state }) => {
    kept(state, "POST", `/knowledge/candidates/${params.id}/review`, body);
    state.assistant.candidates = state.assistant.candidates.filter((c) => c.id !== params.id);
    return { ok: true };
  });
}

/** The 设置 routes (P8.2): the model catalog, the role table, the material-analysis default, Telegram and Pushover.  Reads answer from `state.settings` (and `state.modelRoles`); every write is kept as `{ method, path, body }` in `state.settings.writes` and moves the state the way the server's answer says.
 *  No answer carries a key: the entries say only whether one is configured. */
function settingsRoutes(route, reply, own) {
  const A = "/agent-chat";
  const kept = (state, method, path, body) => { state.settings.writes.push({ method, path, body: body === undefined ? null : structuredClone(body) }); };
  const find = (state, name) => state.settings.catalog.models.find((m) => m.name === name);
  const refuse = (status, detail) => reply.status(status, { detail });
  const makeDefault = (catalog, name) => { for (const m of catalog.models) m.is_default = m.name === name; catalog.default = name; };

  // --- the catalog
  route.post(`${A}/model-catalog`, own(({ body, state }) => {
    kept(state, "POST", "/model-catalog", body);
    const catalog = state.settings.catalog;
    if (find(state, body?.name)) return refuse(409, "model_exists");
    const model = { name: body.name, display_name: body.display_name ?? "", provider: body.provider, model: body.model, base_url: body.base_url ?? null, origin: "server", key_source: body.key_env ? "env" : "vault", key_env: body.key_env ?? null,
      key_status: "configured", is_default: false, migrated: false };
    catalog.models.push(model);
    if (body.is_default || !catalog.default) makeDefault(catalog, model.name);
    return { model };
  }));
  // The two fixed addresses come before the :name ones: "test", "models" and "default" must not be read as a name.
  route.post(`${A}/model-catalog/test`, own(({ body, state }) => {
    kept(state, "POST", "/model-catalog/test", body);
    return state.settings.testFail ? refuse(422, state.settings.testFail) : { ok: true };
  }));
  route.post(`${A}/model-catalog/models`, own(({ body, state }) => {
    kept(state, "POST", "/model-catalog/models", body);
    const mode = state.settings.discovery;
    if (mode === "unsupported") return { status: "unsupported", ordering: "provider", models: [] };
    if (mode === "empty") return { status: "ok", ordering: "provider", models: [] };
    if (mode !== "ok") return refuse(422, mode);
    return { status: "ok", ordering: "provider", models: ["alpha-1", "alpha-1-mini", "beta-2", "beta-2-thinking", "gamma-3", "delta-4"].map((id) => ({ id, name: id === "beta-2" ? "Beta 2" : id })) };
  }));
  route.put(`${A}/model-catalog/default`, own(({ body, state }) => {
    kept(state, "PUT", "/model-catalog/default", body);
    const model = find(state, body?.name);
    if (!model) return refuse(404, "model_not_found");
    makeDefault(state.settings.catalog, model.name);
    return { model };
  }));
  route.patch(`${A}/model-catalog/:name`, own(({ params, body, state }) => {
    kept(state, "PATCH", `/model-catalog/${params.name}`, body);
    const catalog = state.settings.catalog, model = find(state, params.name);
    if (!model) return refuse(404, "model_not_found");
    if (model.origin !== "server") return refuse(422, "model_from_file");
    const { name, is_default, api_key, key_env, ...fields } = body ?? {};
    if (name && name !== model.name) {
      if (find(state, name)) return refuse(409, "model_exists");
      // A rename follows into the roles and the bots that name the model, as the server does.
      for (const role of Object.keys(state.modelRoles)) if (state.modelRoles[role] === model.name) state.modelRoles[role] = name;
      for (const bot of state.bots) if (bot.model === model.name) bot.model = name;
      if (catalog.default === model.name) catalog.default = name;
      model.name = name;
    }
    Object.assign(model, fields);
    if (api_key) { model.key_source = "vault"; model.key_env = null; model.key_status = "configured"; }
    if (key_env) { model.key_source = "env"; model.key_env = key_env; model.key_status = "configured"; }
    if (is_default) makeDefault(catalog, model.name);
    return { model };
  }));
  route.delete(`${A}/model-catalog/:name`, own(({ params, state }) => {
    kept(state, "DELETE", `/model-catalog/${params.name}`, undefined);
    const catalog = state.settings.catalog, at = catalog.models.findIndex((m) => m.name === params.name);
    if (at < 0) return refuse(404, "model_not_found");
    catalog.models.splice(at, 1);
    if (catalog.default === params.name) catalog.default = catalog.models[0]?.name ?? null;
    return { ok: true };
  }));

  // --- the roles and the material-analysis default
  route.put(`${A}/model-roles/:role`, own(({ params, body, state }) => {
    kept(state, "PUT", `/model-roles/${params.role}`, body);
    state.modelRoles[params.role] = body?.model ?? null;
    return { roles: state.modelRoles };
  }));
  route.put("/v3/materials/analysis-settings", ({ body, state }) => {
    kept(state, "PUT", "/v3/materials/analysis-settings", body);
    const model = find(state, body?.catalog_model);
    if (!model) return refuse(404, "model_not_found");
    state.settings.analysis = { source: "settings", provider: model.provider, base_url: model.base_url, model: model.model, has_api_key: true, api_key_last4: null };
    return state.settings.analysis;
  });
  route.delete("/v3/materials/analysis-settings", ({ state }) => {
    kept(state, "DELETE", "/v3/materials/analysis-settings", undefined);
    state.settings.analysis = { source: "environment", provider: "deepseek", base_url: null, model: "deepseek-chat", has_api_key: false, api_key_last4: null };
    return state.settings.analysis;
  });

  // --- Telegram (the shared bot) and Pushover.  A check that plays the message arriving from Telegram sets `state.settings.telegram` to the bound record.
  route.get(`${A}/telegram/status`, own(({ state }) => state.settings.telegram));
  route.post(`${A}/telegram/token`, own(({ body, state }) => {
    kept(state, "POST", "/telegram/token", body);
    state.settings.telegram = { configured: true, has_token: true, bound: false, bot_username: "finbot_fixture_bot", chat_id: null, bound_at: null, bind_code_active: false };
    return state.settings.telegram;
  }));
  route.post(`${A}/telegram/bind`, own(({ state }) => {
    kept(state, "POST", "/telegram/bind", undefined);
    state.settings.telegram = { ...state.settings.telegram, bind_code_active: true };
    return { code: "482913", bot_username: state.settings.telegram.bot_username };
  }));
  route.post(`${A}/telegram/unbind`, own(({ state }) => {
    kept(state, "POST", "/telegram/unbind", undefined);
    state.settings.telegram = { ...state.settings.telegram, bound: false, chat_id: null, bound_at: null, bind_code_active: false };
    return state.settings.telegram;
  }));
  route.get(`${A}/pushover/status`, own(({ state }) => state.settings.pushover));
  route.put(`${A}/pushover`, own(({ body, state }) => {
    kept(state, "PUT", "/pushover", body);
    state.settings.pushover = { configured: true, updated_at: "2026-11-13T02:00:00.000Z" };
    return state.settings.pushover;
  }));
  route.delete(`${A}/pushover`, own(({ state }) => {
    kept(state, "DELETE", "/pushover", undefined);
    state.settings.pushover = { configured: false, updated_at: null };
    return state.settings.pushover;
  }));
}
