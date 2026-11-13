// Bots, the model catalog and the model roles.  The five bots mirror the public properties of the real box list.
import { BOT, CONVERSATION } from "./ids.mjs";
import { daysAgo, minutesAgo } from "./common.mjs";

const bot = (fields) => ({ description: "", tool_scope: null, reasoning_effort: null, skills: [], group: "", hidden: false, daily_notify_cap: 5, default_company: null,
  conversation_id: null, last_message: null, last_at: null, unread: 0, pending: 0, created_at: daysAgo(40), updated_at: daysAgo(2), ...fields });

export function botList() {
  return [
    bot({ id: BOT.finbot, name: "FinBot", title: "默认助理", template: "blank", is_default: true, pinned: true, focus: { companies: [], theme: null },
      look: { shape: "cercle", color: "encre" }, avatar: "bot:kline-mono", model: "haiku-5.5", conversation_id: CONVERSATION.finbot,
      description: "默认助理：行情、财报、预测与持仓问题都可以问我。", last_message: "已把 AAPL 的两版预测放在一起对比，第三版把概率略调向中性。", last_at: minutesAgo(35) }),
    bot({ id: BOT.newsbot, name: "NewsBot", title: "新闻监控", template: "news_monitor", is_default: false, pinned: false, focus: { companies: [], theme: null },
      look: { shape: "nuage", color: "gris" }, avatar: "bot:square-idle", model: null, conversation_id: CONVERSATION.newsbot, unread: 2,
      description: "盯着关注列表里的公司新闻，有变化时在这里留言。", last_message: "【例行任务结果】「盘前新闻速览」已发布，共 6 条。", last_at: minutesAgo(190) }),
    bot({ id: BOT.applebot, name: "AppleBot", title: "资料助手", template: "blank", is_default: false, pinned: true,
      focus: { companies: [{ symbol: "AAPL", name: null }], theme: "所有相关资讯" }, look: { shape: "hexagone", color: "orange" }, avatar: "bot:bull-bull", model: null,
      conversation_id: CONVERSATION.applebot, default_company: { symbol: "AAPL", company: "Apple Inc." },
      description: "只关注 Apple：财报、新闻、预测与材料。", last_message: "AAPL 本季服务收入同比增长，毛利率持平，详见引用 [1]。", last_at: minutesAgo(900) }),
    bot({ id: BOT.reportbot, name: "ReportBot", title: "财报解读", template: "earnings_reader", is_default: false, pinned: false, focus: { companies: [], theme: null },
      look: { shape: "capsule", color: "violet" }, avatar: "bot:bull-idle", model: null, conversation_id: CONVERSATION.reportbot, pending: 1,
      description: "逐条读财报，给出要点与风险。", last_message: "我想把 NVDA 最新 10-Q 加入材料库并分析，请确认。", last_at: minutesAgo(1500) }),
    bot({ id: BOT.teslabot, name: "TeslaBot", title: "盯一家公司", template: "company_researcher", is_default: false, pinned: false,
      focus: { companies: [], theme: null }, look: null, avatar: "bot:kline-focus", model: "haiku-5.5", conversation_id: CONVERSATION.teslabot,
      default_company: null, description: "围绕一家公司做证据链研究。", last_message: null, last_at: null }),
  ];
}

export const BOT_TEMPLATES = {
  templates: [
    { id: "blank", label: "空白助理", name: "新助理", title: "", description: "", tool_scope: null },
    { id: "news_monitor", label: "新闻监控", name: "NewsBot", title: "新闻监控", description: "盯新闻、整理要点。", tool_scope: ["news", "market"] },
    { id: "earnings_reader", label: "财报解读", name: "ReportBot", title: "财报解读", description: "读财报与申报文件。", tool_scope: ["filings", "market"] },
    { id: "company_researcher", label: "公司研究", name: "TeslaBot", title: "盯一家公司", description: "围绕一家公司做证据链研究。", tool_scope: null },
  ],
  tools: [
    { name: "get_market_data", level: "read", owner_only: false }, { name: "search_news", level: "read", owner_only: false },
    { name: "read_filing", level: "read", owner_only: false }, { name: "create_forecast", level: "write", owner_only: true },
    { name: "query_portfolio", level: "read", owner_only: true }, { name: "save_material", level: "write", owner_only: true },
  ],
  always_on: ["get_market_data"],
};

const model = (name, display_name, provider, id, extra = {}) => ({ name, display_name, provider, model: id, base_url: null, origin: "server", key_source: "vault", key_env: null,
  key_status: "configured", is_default: false, migrated: false, ...extra });
export const MODEL_CATALOG = {
  models: [
    model("haiku-5.5", "Haiku 5.5", "openrouter", "anthropic/claude-haiku-5.5", { is_default: true, supported_efforts: ["low", "medium", "high"], reasoning_supported: true }),
    model("muse-ember", "Muse Ember", "openrouter", "muse/ember", { supported_efforts: null, reasoning_supported: true }),
    model("gpt-6.1-terra", "GPT 6.1 Terra", "openrouter", "openai/gpt-6.1-terra", { supported_efforts: ["low", "medium", "high"], reasoning_supported: true }),
    model("deepseek-flash", "DeepSeek Flash", "siliconflow", "deepseek-ai/DeepSeek-V4-Flash"),
    model("glm5.3-flash", "GLM 5.3 Flash", "zhipu", "glm-5.3-flash"),
  ],
  default: "haiku-5.5",
  config_file: { present: false, problems: [] },
};
export const MODEL_ROLES = { roles: { earnings: "muse-ember", forecast: "gpt-6.1-terra", judge: "glm5.3-flash" } };
