// 你的看法 (the owner's views of companies): NVDA has three versions (the first withdrawn, the second replaced, the third active), TSLA and AMD one active view each.  Every other
// company has none, so its page shows no card.  Said in a conversation (a view typed on the memory page has `conversation_id` null: see stateMemoryOverview).  Invented sentences; the ids are fixed fake UUIDs.
import { CONVERSATION } from "./ids.mjs";
const id = (n) => `d0000000-0000-4000-8000-0000000000${String(n).padStart(2, "0")}`;
const version = (n, symbol, status, text, quote, created_at, ended_at = null) => ({ id: id(n), symbol, text, quote, status, status_label: status === "superseded" ? "已更新" : status === "dropped" ? "已撤回" : status === "archived" ? "已归档" : "", archived_reason: null, source_message_id: null, conversation_id: CONVERSATION.finbot, turn_id: null, created_at, ended_at });

export const OWNER_VIEWS = [
  version(1, "NVDA", "dropped", "数据中心收入今年还会翻倍", "我觉得英伟达今年数据中心还会翻倍", "2026-10-03T03:10:00+00:00", "2026-10-20T01:00:00+00:00"),
  version(2, "NVDA", "superseded", "增长还在，但看客户资本开支是否放缓", "增长还在，但我得盯着几家大客户的资本开支，一放缓就要重新想", "2026-10-28T09:30:00+00:00", "2026-11-08T02:20:00+00:00"),
  version(3, "NVDA", "active", "估值太高，现在不想追", "我改主意了，英伟达估值太高，现在不想追", "2026-11-08T02:20:00+00:00"),
  version(4, "TSLA", "active", "交付量比利润率更值得看", "特斯拉我更看交付量，利润率短期是噪音", "2026-11-11T08:00:00+00:00"),
  version(5, "AMD", "active", "数据中心 GPU 份额会慢慢涨，不会很快", "AMD 的数据中心 GPU 份额会慢慢涨，但不会很快", "2026-11-02T06:45:00+00:00"),
];
const newest = (a, b) => b.created_at.localeCompare(a.created_at);
export const activeViews = (views) => views.filter((v) => v.status === "active").sort(newest);
export const viewHistory = (views, symbol) => views.filter((v) => v.symbol === symbol).sort(newest);
