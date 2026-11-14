// Conversations: the default bot's history covers every rendering path the chat page has; the other bots are shorter.
import { BOT, CONVERSATION } from "./ids.mjs";
import { daysAgo, minutesAgo } from "./common.mjs";

const REQUEST_ID = "d0000000-0000-4000-8000-0000000000a1";
const T0 = Date.parse("2026-11-13T00:20:00Z");

const cite = (ordinal, fields) => ({ ordinal, chunk_id: `k0000000-0000-4000-8000-00000000000${ordinal}`, document_id: `a0000000-0000-4000-8000-00000000000${ordinal}`,
  section: "", source_url: null, observed_at: daysAgo(3), published_at: daysAgo(14).slice(0, 10), quote: "", source_type: "saved_filing", truncated: false, ...fields });

const node = (id, kind, fields = {}) => ({ id, kind, name: null, step: null, status: "done", after: [], start_ms: 0, ms: 600, output: null, ...fields });
const TRACE = [
  node("n1", "input", { ms: 20, output: { question: "AAPL 最近一个季度的服务收入怎么样？" } }),
  node("n2", "classify", { after: ["n1"], start_ms: 30, ms: 900, output: { category: "A", company: "Apple", symbol: "AAPL", metrics: ["服务收入"], period: "最近一个季度" } }),
  node("n3", "decide", { after: ["n2"], start_ms: 950, step: 1, ms: 1100, output: { calls: ["get_saved_filings"] } }),
  node("n4", "tool", { name: "get_saved_filings", after: ["n3"], start_ms: 2050, ms: 1400, output: { ok: true, count: 3 } }),
  node("n5", "decide", { after: ["n4"], start_ms: 3500, step: 2, ms: 800, output: { calls: [] } }),
  node("n6", "verify", { after: ["n5"], start_ms: 4300, ms: 700, output: { citations: 2, issues: [] } }),
  node("n7", "output", { after: ["n6"], start_ms: 5000, ms: 10, output: { status: "succeeded", citations: 2 } }),
];

const finbotMessages = [
  // The first question carries its turn id (the server sends it on both lines of a turn): the question rail can bookmark it.
  { role: "user", content: "AAPL 最近一个季度的服务收入怎么样？", turn_id: "t0000000-0000-4000-8000-000000000001" },
  { role: "assistant", status: "complete", turn_id: "t0000000-0000-4000-8000-000000000001", thinking_ms: 5100, trace: TRACE, started_at: T0,
    content: "根据已保存的最新 10-Q，Apple 服务收入本季为 **288 亿美元**，同比增长 14% [1]。服务毛利率约 75%，与上一季度基本持平 [2]。\n\n需要注意：服务收入的增速高于硬件，但管理层在电话会上提示汇率会带来小幅拖累 [2]。",
    citations: [
      cite(1, { title: "AAPL 10-Q（2026 财年第四季度）", section: "Item 2. 管理层讨论", source_url: "https://www.sec.gov/Archives/edgar/data/0000000/000000000026000001/aapl-20260930.htm",
        quote: "Services net sales were $28.8 billion, an increase of 14% compared with the same quarter of the prior year." }),
      cite(2, { title: "AAPL 财报电话会纪要", section: "Q&A", source_type: "saved_ai_analysis", quote: "Services gross margin was 75.0%, and we expect a modest foreign-exchange headwind next quarter." }),
    ] },
  { role: "user", content: "把 AAPL 的两版预测放在一起比较一下，列成表，再给我三条要点。" },
  { role: "assistant", status: "complete", turn_id: "t0000000-0000-4000-8000-000000000002",
    tool_trace: [{ name: "get_forecast", status: "complete", result: { count: 2 } }, { name: "get_market_data", status: "complete", result: { count: 30 } }],
    content: "下面是 AAPL 同一目标日的前两版预测：\n\n| 版本 | 看跌 | 中性 | 看涨 | 触发 |\n|---|---|---|---|---|\n| 第 1 版 | 24% | 38% | 38% | 首次生成 |\n| 第 2 版 | 20% | 41% | 39% | 新增 10-Q |\n\n要点：\n\n1. 第 2 版把看跌概率下调了 4 个百分点，主要依据是服务收入超出预期 [1]。\n2. 中性概率上升，说明模型认为短期方向并不明朗。\n3. 两版的看涨概率几乎没变，可以认为新材料没有改变上行逻辑。\n\n以上是模型意见，买不买由你决定。",
    citations: [cite(1, { title: "AAPL 10-Q（2026 财年第四季度）", section: "Item 2. 管理层讨论", quote: "Services net sales were $28.8 billion, an increase of 14%." })],
    public_marks: [{ id: "pm-1", marker: "neutral", template: "来源 [1] 中同一指标的数值与此句不同",
      hover: { answer_sentence: "第 2 版把看跌概率下调了 4 个百分点，主要依据是服务收入超出预期", name_span: "服务收入", evidence: { ordinal: 1, quote: "Services net sales were $28.8 billion, an increase of 14%.", completeness: "excerpt" } } }] },
  { role: "user", content: "【例行任务结果】「盘前新闻速览」2026-11-13 08:30" },
  { role: "assistant", status: "complete", turn_id: "t0000000-0000-4000-8000-000000000003",
    content: "今天盘前关注列表里有 3 条值得看的新闻：\n\n- **NVDA**：多家云厂商上调下一年度的资本开支指引，数据中心需求仍强。\n- **TSLA**：交付数据发布前，分析师预期略低于上季度。\n- **AAPL**：App Store 政策调整在欧盟生效，影响待观察。\n\n来源均为公开新闻，详见例行任务运行记录。" },
  { role: "user", content: "帮我把 NVDA 最新的 10-Q 加入材料库，并生成一份分析。" },
  { role: "assistant", status: "waiting_for_input", turn_id: "t0000000-0000-4000-8000-000000000004",
    content: "我可以先抓取 NVDA 最新 10-Q 的原文并保存到材料库，再生成分析。这会写入你的材料库，请确认。",
    clarification: { request_id: REQUEST_ID, reason: "write_confirmation", question: "要抓取并分析 NVDA 最新 10-Q 吗？",
      display: { title: "抓取并分析 NVDA 10-Q", agent_suggestion: true, targets: [{ symbol: "NVDA", form: "10-Q" }] },
      choices: [{ label: "确认执行", value: "confirm:fetch_analyze" }, { label: "先不要", value: "cancel" }] } },
];

const short = (userText, assistantText, extra = {}) => [{ role: "user", content: userText }, { role: "assistant", status: "complete", turn_id: `t1000000-0000-4000-8000-${String(Math.abs(userText.length * 977)).padStart(12, "0").slice(0, 12)}`, content: assistantText, ...extra }];

const applebotMessages = short("AAPL 本季服务收入和毛利率怎么样？",
  "AAPL 本季服务收入同比增长 14%，毛利率约 75%，与上季持平 [1]。\n\n如果想看对预测的影响，可以打开 AAPL 的正式预测。",
  { citations: [cite(1, { title: "AAPL 10-Q（2026 财年第四季度）", section: "Item 2. 管理层讨论", quote: "Services net sales were $28.8 billion, an increase of 14%." })] });

const MESSAGES = {
  [CONVERSATION.finbot]: finbotMessages,
  [CONVERSATION.applebot]: applebotMessages,
  [CONVERSATION.newsbot]: short("今天有什么值得关注的新闻？", "【例行任务结果】已发布盘前新闻速览，共 6 条，详见例行任务运行记录。"),
  [CONVERSATION.reportbot]: short("读一下 NVDA 最新 10-Q 的风险因素", "我想把 NVDA 最新 10-Q 加入材料库并分析，请确认。"),
  [CONVERSATION.teslabot]: [],
  [CONVERSATION.older]: short("什么是可信度星级？", "可信度星级是你给一份材料打的 1 到 5 星，用来表达你对来源的信任程度，不是事实核查结论。"),
};

export function buildChat() {
  const conversations = new Map(Object.entries(MESSAGES).map(([id, list]) => [id, list.map((m) => ({ ...m }))]));
  return { conversations, titles: {
    [CONVERSATION.finbot]: "AAPL 服务收入与预测对比", [CONVERSATION.older]: "可信度星级是什么", [CONVERSATION.applebot]: "AAPL 本季服务收入",
    [CONVERSATION.newsbot]: "盘前新闻", [CONVERSATION.reportbot]: "NVDA 10-Q 风险因素", [CONVERSATION.teslabot]: "TeslaBot" } };
}

export function conversationSummaries(state) {
  const stamp = (offset) => minutesAgo(offset);
  return [
    { id: CONVERSATION.finbot, title: state.chat.titles[CONVERSATION.finbot], created_at: daysAgo(1), updated_at: stamp(35) },
    { id: CONVERSATION.older, title: state.chat.titles[CONVERSATION.older], created_at: daysAgo(5), updated_at: daysAgo(5) },
  ];
}

export const CONTEXT_USAGE = {
  parts: [{ key: "system", bytes: 6200, tokens: 1800 }, { key: "tools", bytes: 9100, tokens: 2600 }, { key: "summary", bytes: 0, tokens: 0 },
    { key: "compressed", bytes: 0, tokens: 0 }, { key: "recent", bytes: 21800, tokens: 6200, turns: 4 }, { key: "free", bytes: 92000, tokens: 26000 }],
  capacity_bytes: 129100, budget_kb: 126, used_bytes: 37100, remaining_bytes: 92000, remaining_percent: 71, history_used_percent: 29, compact_at_percent: 80, will_compact: false,
  compressing: false, hidden_turns: 0,
};

/** The fake answer to a message typed in the smoke run: SSE events as agentChatStream consumes them. */
export function streamEvents({ conversationId, message, botId }) {
  const answer = "这是一条用于冒烟测试的假回答：AAPL 最新收盘价已在上方图表里，没有新的未读材料。";
  const half = Math.ceil(answer.length / 2);
  const turnId = "t9000000-0000-4000-8000-000000000001";
  return [
    { event: "conversation", data: { conversation_id: conversationId, turn_id: turnId, bot_id: botId ?? null } },
    { event: "trace", data: { id: "s1", kind: "input", status: "done", after: [], start_ms: 0, ms: 10, output: { question: message } } },
    { event: "trace", data: { id: "s2", kind: "decide", step: 1, status: "done", after: ["s1"], start_ms: 20, ms: 300, output: { calls: [] } } },
    { event: "delta", data: { text: answer.slice(0, half) } },
    { event: "delta", data: { text: answer.slice(half) } },
    { event: "done", data: { status: "complete", turn_id: turnId, thinking_ms: 900, citations: [], citation_protocol: null } },
  ];
}

/** The answer to a message holding ASK_MARKER: a short lead-in and a card the user must answer, the turn ending as waiting_for_input. */
export const CLARIFY_REQUEST_ID = "d0000000-0000-4000-8000-0000000000b2";
export function clarificationEvents({ conversationId, botId }) {
  const turnId = "t9000000-0000-4000-8000-000000000002";
  const lead = "这个问题有两种读法，请选一个。";
  const card = { request_id: CLARIFY_REQUEST_ID, reason: "reference_item_unavailable", question: "你指的是哪一条结果？",
    choices: [{ label: "第一条结果", value: "pick-first-result" }, { label: "第二条结果", value: "pick-second-result" }] };
  return [
    { event: "conversation", data: { conversation_id: conversationId, turn_id: turnId, bot_id: botId ?? null } },
    { event: "delta", data: { text: lead } },
    { event: "clarification", data: card },
    { event: "done", data: { status: "waiting_for_input", turn_id: turnId, thinking_ms: 400, citations: [], citation_protocol: null } },
  ];
}

/** What a manual compression leaves behind: one 「已压缩 N 轮」 notice after the given turn (served with the conversation's messages). */
export function compactionNotice(afterTurnId, focus) {
  return { id: 1, after_turn_id: afterTurnId, turns: 2, summary: "两轮对话的摘要：先问服务收入，再比较两版预测。", focus: focus || null, created_at: minutesAgo(1) };
}

/** Older turns for the load-earlier check: a check puts them in state.chat.older[conversationId] = { messages, cursor }. */
export function olderTurns(count = 6) {
  const out = [];
  for (let i = 1; i <= count; i += 1) {
    const turn = `t8000000-0000-4000-8000-${String(i).padStart(12, "0")}`;
    out.push({ role: "user", content: `更早的问题 ${i}：请说明第 ${i} 项风险因素。`, turn_id: turn });
    out.push({ role: "assistant", status: "complete", turn_id: turn, content: `更早的回答 ${i}：${"这一项风险因素在财报里有详细说明，要点是需求、成本与汇率三方面的变化，需要结合原文判断。".repeat(3)}` });
  }
  return out;
}
