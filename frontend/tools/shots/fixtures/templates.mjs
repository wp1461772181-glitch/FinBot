// 用模板起步 (stage 4f): the three templates as the plan's appendix words them, and the answers of the four routes.  The fake backend keeps the applications in its state; an apply writes the ticked
// memory items into the profile (with `template` set), so the profile list and the badge show it, and an undo removes them again.  Invented ids; the shapes are the ones src/api/role-templates.ts documents.
import { BOT } from "./ids.mjs";

const NOTES_ALWAYS = ["盯防类的几条会在每次回答和值班判断时读到。"];
const NOTES_SHADOW = ["值班现在只记录、不主动发消息（要打开请告诉我），所以这几条暂时只影响回答。"];
const NOTES_REST = ["价格异动的默认提醒（哨兵）这一版不随模板改变。", "每条简报每次运行会调用一次模型，记在用量里；不想要可以不勾，或之后在例行任务里暂停。", "持仓、计划价位和你对公司的看法，还要在对话里慢慢告诉它。"];
export const NOTES = [...NOTES_ALWAYS, ...NOTES_SHADOW, ...NOTES_REST];

const mem = (key, kind, text) => ({ key, kind, text });
const skill = (key, name, description, body, output_template, allowed_tools) => ({ key, name, description, body, output_template, allowed_tools });

export const TEMPLATES = [
  {
    id: "short_term", label: "短线", blurb: "看日内和几天内的走势：回答先给结论和价位，急涨急跌也告诉你，开盘前给一份速览。",
    memory: [
      mem("st_about", "about_me", "我主要做短线，关注日内和几天内的走势，持有时间短。"),
      mem("st_conclusion_first", "instruction", "回答先给结论和关键价位，再讲原因；提到价格都写明是几点的数据。"),
      mem("st_fast_moves", "instruction", "我的持仓盘中出现急涨急跌（5 分钟、15 分钟这种），也算值得告诉我的事。"),
      mem("st_why_moving", "instruction", "说异动时先讲是它自己的事，还是大盘、板块一起动，再讲原因；查不到原因就直说没查到。"),
      mem("st_news_impact", "preference", "新闻和公告先说对股价的直接影响，背景放后面。"),
    ],
    briefs: [{ key: "st_premarket", name: "盘前速览", schedule_kind: "weekdays", schedule_time: "09:00", timezone: "America/New_York", every_value: null, every_unit: null, skill_key: "st_skill_premarket",
      instruction: "开盘前给我一份速览：持仓和研究队列里，隔夜有公告、新闻或盘前涨跌明显的，每只一句话——发生了什么、盘前涨跌多少、离我设的补仓价/止损价/目标价还有多远。没有值得说的，就只回一句『今天盘前没有要特别注意的』。" }],
    skills: [
      skill("st_skill_premarket", "盘前速览", "开盘前把持仓和研究队列过一遍：隔夜公告、新闻、盘前涨跌和离计划价位的距离。",
        "1. 用 query_portfolio 读持仓和计划价位，用 query_research_queue 读研究队列。\n2. 用 query_market_quote / query_stock_prices 看每只的最新价和相对昨收的涨跌，写明数据时间。\n3. 用 query_sec_filings 和 search_configured_news 找隔夜的公告和新闻；不够再用 web_research。\n4. 离计划价位的距离用 calculate 算。\n5. 只写有事的那几只，每只一句；都没事就说没事。",
        "**今天要注意的**（每只：公司 · 发生了什么 · 盘前涨跌（时间）· 离计划价位）\n**没事的**（一行列出）",
        ["query_portfolio", "query_research_queue", "query_market_quote", "query_stock_prices", "query_sec_filings", "search_configured_news", "web_research", "calculate"]),
      skill("st_skill_why", "异动归因", "一只股票为什么大涨大跌：先看公告和新闻，再看大盘和同行。",
        "1. 用 query_market_quote / query_stock_prices 确认涨跌幅和时间。\n2. 用 query_sec_filings 看最近的官方公告，用 search_configured_news 看新闻；不够再用 web_research，必要时 search_x（标明是社交平台内容）。\n3. 用 query_stock_prices 看大盘和一两家同行同一时间的涨跌，分清是它自己的事还是一起动。\n4. 写原因时带出处；查不到就直说没查到。",
        "**涨跌**（多少，几点）\n**原因**（带出处；没查到就写没查到）\n**是它自己还是一起动**",
        ["query_market_quote", "query_stock_prices", "query_sec_filings", "search_configured_news", "web_research", "search_x", "query_alerts"]),
    ],
    usual: ["st_skill_premarket", "st_skill_why", "新闻摘要"], notes: NOTES,
  },
  {
    id: "dca", label: "定投", blurb: "长期按节奏买入、不择时：日常涨跌不打扰你，每月复盘一次持仓和你的判断。",
    memory: [
      mem("dca_about", "about_me", "我做长期定投，按固定节奏买入，不做择时。"),
      mem("dca_quiet", "instruction", "日常涨跌不用特意告诉我；持仓公司的重要公告、财报，或明显超出平时波动的大跌，才值得说。"),
      mem("dca_no_timing", "instruction", "谈买卖时从长期基本面和我的定投计划出发，不给短线择时的建议。"),
      mem("dca_reading", "preference", "财报先看收入、利润和现金流的长期趋势，还有分红和回购；同比优先于环比。"),
    ],
    briefs: [{ key: "dca_monthly", name: "每月定投复盘", schedule_kind: "every", schedule_time: "10:00", timezone: "Asia/Shanghai", every_value: 30, every_unit: "days", skill_key: "dca_skill_review",
      instruction: "按『定投复盘』的步骤给我一份月度复盘：每只持仓的成本、现价、浮盈亏和占比，和上次比的变化；这段时间持仓公司有没有改变长期判断的事（财报、指引、重要公告）；我记下的看法现在还成立吗。不给择时建议。" }],
    skills: [skill("dca_skill_review", "定投复盘", "定期看一遍持仓：成本、占比、长期基本面的变化和你当初的判断。",
      "1. 用 query_portfolio / query_holdings_overview 读每只持仓的成本、现价、浮盈亏和占比。\n2. 用 query_financials 看最近一期和去年同期的收入、利润、经营现金流；需要的比率用 calculate 算。\n3. 用 query_sec_filings 看这段时间的重要公告和指引。\n4. 对照系统里记下的他的看法，说哪些依据还在、哪些变了；只讲依据，不给择时建议。",
      "**持仓一览**（表格：公司 / 成本 / 现价 / 浮盈亏 / 占比）\n**基本面有没有变**\n**你的看法还成立吗**",
      ["query_portfolio", "query_holdings_overview", "query_financials", "query_sec_filings", "query_stock_prices", "calculate"])],
    usual: ["dca_skill_review", "财报速读"], notes: NOTES,
  },
  {
    id: "fund_manager", label: "基金经理", blurb: "按组合来管：盯集中度和回撤，收盘给一份组合日报，判断都写依据和反方。",
    memory: [
      mem("fm_about", "about_me", "我按组合来管理，关心整体风险、集中度和相对大盘的表现。"),
      mem("fm_limits", "instruction", "单只持仓占总资产超过 25%，或组合一天跌超过 3%，值得告诉我。"),
      mem("fm_position_context", "instruction", "谈个股时顺带说它在组合里的占比和对组合的影响。"),
      mem("fm_both_sides", "instruction", "每个判断写清依据，也写反方的看法。"),
      mem("fm_format", "preference", "数字尽量用表格，金额用美元，比例保留一位小数。"),
    ],
    briefs: [
      { key: "fm_daily", name: "收盘组合日报", schedule_kind: "weekdays", schedule_time: "16:30", timezone: "America/New_York", every_value: null, every_unit: null, skill_key: null,
        instruction: "收盘后给我一份组合日报：总资产和当日涨跌，贡献最大和拖累最大的各三只，占比的变化，今天持仓公司的公告和重要新闻；超过我说过的集中度或回撤线的单独标出来。" },
      { key: "fm_weekly", name: "每周组合体检", schedule_kind: "every", schedule_time: "10:00", timezone: "Asia/Shanghai", every_value: 7, every_unit: "days", skill_key: "fm_skill_check",
        instruction: "按『组合体检』的步骤做一次周度体检，重点写这一周变了什么。" },
    ],
    skills: [skill("fm_skill_check", "组合体检", "看组合整体：集中度、各只的贡献、相对大盘的表现和主要风险。",
      "1. 用 query_portfolio / query_holdings_overview 读持仓、占比和总资产。\n2. 用 query_stock_prices 看各只和大盘（如 SPY）同一段时间的涨跌；贡献和相对表现用 calculate 算。\n3. 标出占比最高的几只和超过他说过的上限的。\n4. 用 query_financials / query_sec_filings 看重仓公司最近有没有基本面变化。\n5. 每条判断写依据和反方看法。",
      "**组合概况**（总资产、期间涨跌、相对大盘）\n**集中度**（表格：公司 / 占比 / 期间贡献）\n**要留意的风险**（每条带依据和反方）",
      ["query_portfolio", "query_holdings_overview", "query_stock_prices", "query_market_quote", "query_financials", "query_sec_filings", "calculate"])],
    usual: ["fm_skill_check", "同行对比", "财报速读"], notes: NOTES,
  },
];

/** The fake backend's template state: nothing applied yet; `full` makes the memory part come back refused (memory_full), `seq` numbers what is written. */
export function buildTemplates() { return { applications: [], full: false, seq: 0, writes: [] }; }

const BOT_NAMES = { [BOT.newsbot]: "NewsBot", [BOT.applebot]: "AppleBot", [BOT.reportbot]: "ReportBot", [BOT.teslabot]: "TeslaBot" };
const find = (id) => TEMPLATES.find((t) => t.id === id);
const sameText = (state, botId, text) => state.assistant.profile.find((p) => p.status === "active" && (p.bot_id ?? null) === (botId ?? null) && p.text === text);

/** GET /role-templates: every template, the applications with what is still there and the things they wrote (current texts), the duty mode. */
export function templatesList(state) {
  const applications = state.templates.applications.map((a) => {
    const items = [
      ...a.profile_item_ids.map((id) => { const p = state.assistant.profile.find((x) => x.id === id); return { id, part: "memory", text: p?.text ?? "", gone: !p }; }),
      ...a.briefs.map((b) => ({ id: b.id, part: "brief", text: b.name, gone: false })),
      ...a.skills.map((s) => ({ id: s.id, part: "skill", text: s.name, gone: false })),
    ];
    const there = (part) => items.filter((i) => i.part === part && !i.gone).length;
    return { id: a.id, template: a.template, label: find(a.template).label, bot_id: a.bot_id, bot_name: a.bot_id ? BOT_NAMES[a.bot_id] ?? null : null, applied_at: a.applied_at, undone_at: a.undone_at,
      still_there: a.undone_at ? { profile_items: 0, tasks: 0, skills: 0, usual: 0 } : { profile_items: there("memory"), tasks: there("brief"), skills: there("skill"), usual: 0 }, items };
  });
  return { templates: TEMPLATES, applications, duty_mode: "shadow" };
}

/** What a preview or an apply finds for a body: the keys already there (the same text in the layer) are reused; with `full` the whole memory part is refused. */
function plan(state, template, body) {
  const out = new Set(body?.leave_out ?? []), botId = body?.bot_id ?? null;
  const reuse = [], skip = [], create = [];
  const memory = template.memory.filter((m) => !out.has(m.key));
  if (state.templates.full && memory.length > 0) skip.push({ key: "memory", reason: `这一层记忆已有 28 条，再加 ${memory.length} 条会超过 30 条；先删几条或少勾几条` });
  else for (const m of memory) { if (sameText(state, botId, m.text)) reuse.push({ key: m.key, reason: "已有，沿用" }); else create.push({ key: m.key }); }
  for (const part of [template.briefs, template.skills]) for (const row of part) if (!out.has(row.key)) create.push({ key: row.key });
  return { reuse, skip, create, memory: state.templates.full ? [] : memory.filter((m) => !sameText(state, botId, m.text)) };
}

export function templatePreview(state, id, body) {
  const template = find(id);
  if (!template) return null;
  const p = plan(state, template, body);
  return { will_create: p.create, reuse: p.reuse, skip: p.skip, notes: NOTES };
}

export function templateApply(state, id, body) {
  const template = find(id);
  if (!template) return null;
  const botId = body?.bot_id ?? null, out = new Set(body?.leave_out ?? []), p = plan(state, template, body), t = state.templates;
  const seq = () => String(100 + ++t.seq).padStart(12, "0");
  const ids = [];
  for (const m of p.memory) {
    const pid = `pf000000-0000-4000-8000-${seq()}`;
    state.assistant.profile.push({ id: pid, handle: `T${t.seq}`, kind: m.kind, topic: null, text: m.text, origin: "manual", quote: m.text, status: "active", scope: botId ? "bot" : "global", bot_id: botId, bot_name: botId ? BOT_NAMES[botId] ?? null : null,
      created_at: "2026-11-26T03:00:00+00:00", updated_at: "2026-11-26T03:00:00+00:00", last_used_at: null, last_seen_at: null, archived_at: null, archived_reason: null, settled_at: null, settled_label: "", template: id, template_label: template.label });
    ids.push(pid);
  }
  const briefs = template.briefs.filter((b) => !out.has(b.key)).map((b) => ({ id: `t5000000-0000-4000-8000-${seq()}`, name: b.name }));
  const skills = template.skills.filter((s) => !out.has(s.key)).map((s) => ({ id: `s5000000-0000-4000-8000-${seq()}`, name: s.name }));
  const record = { id: `a5000000-0000-4000-8000-${seq()}`, template: id, bot_id: botId, applied_at: "2026-11-26T03:00:00+00:00", undone_at: null, profile_item_ids: ids, briefs, skills };
  t.applications.push(record);
  const application = templatesList(state).applications.find((a) => a.id === record.id);
  return { application, created: { profile_item_ids: ids, task_ids: briefs.map((b) => b.id), skill_ids: skills.map((s) => s.id), usual_added: [] }, reused: p.reuse, skipped: p.skip };
}

export function templateUndo(state, applicationId, body) {
  const record = state.templates.applications.find((a) => a.id === applicationId && !a.undone_at);
  if (!record) return null;
  const left = new Set(body?.leave_out ?? []);
  const removed = [], gone = [];
  for (const id of record.profile_item_ids) {
    if (left.has(id)) continue;
    if (state.assistant.profile.some((p) => p.id === id)) { state.assistant.profile = state.assistant.profile.filter((p) => p.id !== id); removed.push(id); } else gone.push(id);
  }
  for (const row of [...record.briefs, ...record.skills]) if (!left.has(row.id)) removed.push(row.id);
  record.undone_at = "2026-11-26T04:00:00+00:00";
  return { removed, gone };
}
