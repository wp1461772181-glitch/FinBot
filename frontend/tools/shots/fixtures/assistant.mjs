// 助手 data: news sources, skills, memory (profile + recall), and the settings-page cards (Telegram, Pushover, knowledge).
import { BOT, CONVERSATION } from "./ids.mjs";
import { daysAgo, dayOnly } from "./common.mjs";

const src = (id, name, kind, health, extra = {}) => ({ id, name, enabled: true, kind, url: `https://example.test/feeds/${id}.xml`, homepage: `https://example.test/${id}`, language: "en", tags: ["markets"], markets: ["US"], health, rea_repair: false,
  alternates: [], consecutive_failures: 0, last_error: null, ...extra });
export const NEWS = {
  push: { summary_max_tokens: 256, presets: [] },
  sources: [
    src("wire-markets", "Markets Wire（示例）", "rss", "ok", { tags: ["markets", "macro"] }),
    src("tech-daily", "Tech Daily（示例）", "rss", "ok", { tags: ["tech"] }),
    src("earnings-feed", "Earnings Feed（示例）", "http_json", "ok", { tags: ["earnings"], language: "en" }),
    src("chip-watch", "Chip Watch（示例）", "http_html", "degraded", { tags: ["semiconductors"], consecutive_failures: 2, last_error: "parse_changed", rea_repair: true }),
    src("ev-weekly", "EV Weekly（示例）", "rss", "failed", { tags: ["auto"], consecutive_failures: 7, last_error: "http_503", enabled: true }),
    src("old-blog", "旧博客（示例）", "rss", "ok", { enabled: false, language: "zh" }),
  ],
};

const skill = (n, fields) => ({ id: `s3000000-0000-4000-8000-${String(n).padStart(12, "0")}`, name: "", description: "", body: "", allowed_tools: ["get_market_data"], output_template: null, version: 1, enabled: true, origin: "mine", status: "active", builtin: false, updated_at: daysAgo(10), ...fields });
export const SKILLS = {
  skills: [
    skill(1, { name: "财报速读", description: "读最新财报并列出收入、利润、指引与风险", origin: "builtin", builtin: true, body: "1. 读取最新 10-Q/10-K。\n2. 列出收入、利润、指引。\n3. 单独列出风险与不确定项。", allowed_tools: ["read_filing", "get_market_data"], output_template: "## 要点\n## 风险" }),
    skill(2, { name: "周日复盘", description: "检查持仓计划与本周财报判断", body: "1. 读取持仓。\n2. 对照价格计划。\n3. 列出下周要关注的事项。", allowed_tools: ["query_portfolio", "get_market_data"], version: 3 }),
    skill(3, { name: "新闻去重", description: "把同一事件的多条新闻合并成一条", body: "按事件聚合新闻，保留最早来源。", allowed_tools: ["search_news"], enabled: false, origin: "imported" }),
    skill(4, { name: "估值草稿", description: "未完成的草稿：用可比公司做粗估", body: "（草稿）", allowed_tools: ["get_market_data"], status: "draft", version: 1 }),
  ],
  tools: [{ name: "get_market_data", level: "read" }, { name: "search_news", level: "read" }, { name: "read_filing", level: "read" }, { name: "query_portfolio", level: "read" }, { name: "save_material", level: "write" }],
};

const item = (n, fields) => ({ id: `pf000000-0000-4000-8000-${String(n).padStart(12, "0")}`, handle: `P${n}`, kind: "preference", topic: null, text: "", origin: "explicit", quote: "", status: "active", scope: "global", bot_id: null, bot_name: null,
  created_at: daysAgo(30), updated_at: daysAgo(20), last_used_at: daysAgo(1), ...fields });
export const PROFILE = {
  items: [
    item(1, { kind: "about_me", text: "长期持有美股科技股，偏好以季度为周期做决策。", quote: "我主要持有美股科技，按季度看。" }),
    item(2, { kind: "preference", topic: "回答风格", text: "回答先给结论，再给依据；数字要带出处。", quote: "先说结论。" }),
    item(3, { kind: "instruction", text: "涉及买卖时只给参考意见，不要替我下决定。", origin: "manual" }),
    item(4, { kind: "preference", topic: "新闻", text: "新闻只保留与持仓和关注列表相关的。", origin: "inferred", quote: "别给我推和持仓无关的新闻。", scope: "bot", bot_id: BOT.newsbot, bot_name: "NewsBot", status: "active" }),
    item(5, { kind: "preference", text: "AAPL 的服务业务比硬件更值得看。", scope: "bot", bot_id: BOT.applebot, bot_name: "AppleBot", origin: "inferred", quote: "我更关心服务业务。" }),
    item(6, { kind: "preference", topic: "语言", text: "用简体中文回答，专有名词保留英文。", status: "archived", updated_at: daysAgo(60) }),
  ],
  bots: [{ id: BOT.finbot, name: "FinBot", is_default: true }, { id: BOT.newsbot, name: "NewsBot", is_default: false }, { id: BOT.applebot, name: "AppleBot", is_default: false }, { id: BOT.reportbot, name: "ReportBot", is_default: false }, { id: BOT.teslabot, name: "TeslaBot", is_default: false }],
};
export const RECALL = [
  { conversation_id: CONVERSATION.finbot, title: "AAPL 服务收入与预测对比", date: dayOnly(0), summary: "对比了 AAPL 前两版预测，第 2 版下调了看跌概率。", kind: "summary", link: `#agent/${CONVERSATION.finbot}`, bot_id: BOT.finbot, bot_name: "FinBot" },
  { conversation_id: CONVERSATION.applebot, title: "AAPL 本季服务收入", date: dayOnly(1), summary: "问了服务收入与毛利率，引用了最新 10-Q。", kind: "summary", link: `#agent/${CONVERSATION.applebot}`, bot_id: BOT.applebot, bot_name: "AppleBot" },
  { conversation_id: CONVERSATION.older, title: "可信度星级是什么", date: dayOnly(5), summary: "解释了材料的可信度星级是用户评分，不是事实核查。", kind: "questions", link: `#agent/${CONVERSATION.older}`, bot_id: null, bot_name: null },
  { conversation_id: CONVERSATION.reportbot, title: "NVDA 10-Q 风险因素", date: dayOnly(11), summary: "读了 NVDA 最新 10-Q 的风险因素。", kind: "summary", link: `#agent/${CONVERSATION.reportbot}`, bot_id: BOT.reportbot, bot_name: "ReportBot" },
];

export const TELEGRAM = { configured: true, has_token: true, bound: true, bot_username: "finbot_fixture_bot", chat_id: 100000001, bound_at: daysAgo(40), bind_code_active: false };
export const BOT_TELEGRAM = { ...TELEGRAM, shared: true, status: "running", token_tail: "••••", last_error: null };
export const PUSHOVER = { configured: false, updated_at: null };
export const KNOWLEDGE_DOCS = [
  { id: "kd000000-0000-4000-8000-000000000001", title: "AAPL 10-Q（2026 财年第四季度）", symbol: "AAPL", source_type: "sec", observed_at: daysAgo(13), available_at: daysAgo(13), status: "indexed", active: true, owner_scope: "owner", chunks: 42 },
  { id: "kd000000-0000-4000-8000-000000000002", title: "产品 FAQ：可信度星级", symbol: null, source_type: "faq", observed_at: daysAgo(40), available_at: daysAgo(40), status: "indexed", active: true, owner_scope: "owner", chunks: 6 },
];

// ---- P8.1: what the write routes of the 助手 pages need (the default data above is unchanged; every page reads it through `state.assistant`, a mutable copy made by buildState) ----

/** A skill file as the import box takes it: three header lines (name, description, tools), then the steps.  `save_material` is a write tool, so the preview marks it. */
export const IMPORT_SAMPLE = "---\nname: 周报整理\ndescription: 把本周的新闻和材料整理成一页周报\ntools: search_news, get_market_data, save_material\n---\n1. 读取本周的新闻线索。\n2. 对照行情，列出值得注意的变化。\n3. 把周报存成材料。";
export const IMPORT_READ_ONLY = "---\nname: 只读周报\ndescription: 只读取，不写入\ntools: search_news\n---\n1. 读取新闻。";

const WRITE_LEVELS = new Set(["reversible", "costly", "write"]);
/** The import preview / import of a skill file: the parts the server reads, or the code it refuses with. */
export function readSkillFile(markdown, tools = SKILLS.tools) {
  const text = String(markdown ?? "");
  const head = /^---\n([\s\S]*?)\n---\n?([\s\S]*)$/.exec(text.trim());
  const field = (key) => new RegExp(`^${key}:\\s*(.*)$`, "m").exec(head?.[1] ?? "")?.[1]?.trim() ?? "";
  const name = field("name"), description = field("description"), names = field("tools").split(/[\s,]+/).filter(Boolean);
  if (!head || !name || !description || !names.length) return { error: "invalid_skill_file" };
  const level = (n) => tools.find((tool) => tool.name === n)?.level;
  if (names.some((n) => !level(n))) return { error: "unknown_tool" };
  return { skill: { name, description, body: head[2].trim(), output_template: null, allowed_tools: names }, tools: names.map((n) => ({ name: n, level: level(n), write: WRITE_LEVELS.has(level(n)) })) };
}

/** What each test fetch of a news source answers (the ones not named: `ok: false` with neither a reason nor a code). */
export const DRY_RUNS = {
  "wire-markets": { ok: true, raw_count: 24, valid_count: 22, sample: [{ title: "美联储官员称降息节奏取决于数据", url: "https://example.test/news/fed-pace", published_at: "2026-11-12T09:30:00Z" }, { title: "芯片股盘前走强", url: "https://example.test/news/chips-pre", published_at: "2026-11-12T08:05:00Z" }, { title: "第三条不应出现", url: "https://example.test/news/third", published_at: "2026-11-12T07:00:00Z" }] },
  "earnings-feed": { ok: true, raw_count: 8, valid_count: 8, sample: [{ title: "AAPL 财报日程更新", url: "https://example.test/news/aapl-date", published_at: "2026-11-11T21:10:00Z" }] },
  "chip-watch": { ok: true, raw_count: 12, valid_count: 3, sample: [] },
  "ev-weekly": { ok: false, error_code: "http_503", reason: "上游返回 503，暂时抓不到内容。" },
  "old-blog": { ok: false, error_code: "empty_feed" },
};
/** What 修复 answers (a source not named: not repaired, with no code). */
export const REPAIRS = {
  "chip-watch": { ok: true, status: "repaired", sample: [{ title: "备用源：芯片周报", url: "https://example.test/alt/chip-1" }, { title: "备用源：设备商财报", url: "https://example.test/alt/chip-2" }] },
  "ai-wire": { ok: false, error_code: "no_candidate_feed" },
};

/** The extra sources the news page's states use (a second repairable source whose repair fails with a code, a third whose fails without one, a source with a health value the page does not know). */
export const EXTRA_SOURCES = [
  src("ai-wire", "AI Wire（示例）", "rss", "degraded", { tags: ["ai"], consecutive_failures: 3, last_error: "feed_moved", rea_repair: true }),
  src("macro-wire", "Macro Wire（示例）", "http_json", "failed", { tags: ["macro"], consecutive_failures: 5, last_error: "timeout", rea_repair: true, alternates: ["https://example.test/alt/macro.xml"] }),
  src("odd-state", "Odd State（示例）", "http_html", "unknown", { tags: ["odd"] }),
];

/** What the knowledge page lists beyond the two default documents, and what its other reads answer. */
export const KNOWLEDGE_EXTRA_DOCS = [
  { id: "kd000000-0000-4000-8000-000000000003", title: "AAPL 服务业务分析（AI）", symbol: "AAPL", source_type: "analysis", observed_at: daysAgo(3), available_at: daysAgo(3), status: "pending", active: true, owner_scope: "owner", chunks: 4 },
  { id: "kd000000-0000-4000-8000-000000000004", title: "旧上传：TSLA 交付报道", symbol: "TSLA", source_type: "upload", observed_at: null, available_at: null, status: "withdrawn", active: false, owner_scope: "owner", chunks: 9 },
];
export const KNOWLEDGE_CANDIDATES = [
  { id: "kc000000-0000-4000-8000-000000000001", question: "可信度星级代表什么？", answer: "星级是用户对来源可信度的评分，不是事实核查。", category: "faq", evidence_quote: "可信度星级由上传者自己评分，用于排序，不代表系统核查过内容。" },
  { id: "kc000000-0000-4000-8000-000000000002", question: "往事页签能当证据用吗？", answer: "不能。往事只是找回对话的线索，数字仍要重新取证。", category: "faq", evidence_quote: "往事只是线索，不是证据：回答里的数字仍要重新取证。" },
];
export const KNOWLEDGE_IMPORTABLE = {
  faq: [{ id: "faq-0001", title: "产品 FAQ：可信度星级", symbol: null, source_type: "faq" }, { id: "faq-0002", title: "产品 FAQ：预测与证据", symbol: null, source_type: "faq" }],
  upload: [{ id: "up-0001", title: "AAPL 供应链报道（上传）", symbol: "AAPL", source_type: "upload" }, { id: "up-0002", title: "AAPL 渠道调研纪要（上传）", symbol: "AAPL", source_type: "upload" }],
  sec: [{ id: "sec-0001", title: "AAPL 10-K 风险因素摘录", symbol: "AAPL", source_type: "sec" }],
  analysis: [{ id: "an-0001", title: "AAPL 服务业务分析（AI）", symbol: "AAPL", source_type: "analysis" }],
};
/** The chunks of a document: the analysis one (…03) keeps the AI-derived marker in front of its text. */
export function knowledgeChunks(id, docs) {
  const doc = docs.find((d) => d.id === id);
  if (!doc) return null;
  const analysis = doc.source_type === "analysis";
  return {
    document: { id, title: doc.title, source_text: analysis ? "派生 AI 分析；以下为模型对已保存材料的归纳，不是原文。\n服务业务收入同比增长，毛利率高于硬件。" : "Services revenue grew year over year.\nGross margin on services stayed above the company average.", source_url: doc.symbol ? `https://example.test/docs/${id.slice(-2)}` : null, status: doc.status },
    chunks: Array.from({ length: Math.min(doc.chunks, 3) }, (_, i) => ({ id: `${id}-c${i}`, ordinal: i, section: i === 1 ? "" : `第 ${i + 1} 节`, answer: `这是第 ${i + 1} 块的内容：${doc.title}。`, status: "indexed", needs_review: false })),
  };
}
