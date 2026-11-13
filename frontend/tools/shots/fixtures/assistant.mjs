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
