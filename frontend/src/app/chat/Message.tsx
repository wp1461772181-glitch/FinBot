import { useState, type RefObject } from "react";
import { Check, Copy, ThumbsDown, ThumbsUp } from "lucide-react";
import { LegacyFrame } from "../../LegacyFrame";
import { BotOrb } from "../../BotOrb";
import { ThinkingPanel } from "../../ThinkingPanel";
import { isActiveClarification } from "../../chat-clarification.mjs";
import { toolLabel } from "../../agent-tool-labels.mjs";
import { isTaskPostHead } from "../../task-posts.mjs";
import type { AgentChatMessage, Bot } from "../../api";
import { useLocale } from "../../i18n";
import { AnswerBody, CitationDrawer, type CitationItem } from "./Citations";
import { ClarificationCard } from "./ClarificationCard";
import { TaskPostHead } from "./TaskPostHead";
import { useChat } from "./ChatSessionProvider";
import type { useCitations } from "./Citations";
import type { CopyState } from "./use-copy";

function toolResultSummary(value: unknown): string {
  if (!value || typeof value !== "object") return "";
  const result = value as { data?: unknown; job_status?: unknown; status?: unknown; error_code?: unknown };
  if (typeof result.job_status === "string") return `任务 ${result.job_status.slice(0, 32)}`;
  if (Array.isArray(result.data)) return `${result.data.length} 条结果`;
  if (typeof result.error_code === "string") return result.error_code.slice(0, 48);
  return "";
}

const TOOL_STATUS_TEXT: Record<string, string> = { not_found: "没有匹配记录", failed: "查询失败", cancelled: "已取消", submitted: "已提交" };

// Message footer buttons: hidden until the message is hovered, tapped, or something in it has keyboard focus (they stay in the tab order).
const footButton = "inline-flex size-8 items-center justify-center rounded-sm text-muted-foreground outline-none hover:bg-accent hover:text-ink focus-visible:ring-2 focus-visible:ring-ring aria-pressed:text-brand [&_svg]:size-4";

function feedbackOf(turnId: string): string { try { return localStorage.getItem(`market-evidence-agent:feedback:${turnId}`) ?? ""; } catch { return ""; } }

type Props = {
  m: AgentChatMessage; i: number; last: boolean; bot?: Bot | null; botColor?: string;
  streaming: boolean; copy: CopyState; draftBox: RefObject<HTMLTextAreaElement | null>;
  citations: ReturnType<typeof useCitations>; turnIndex?: number; onFeedback: () => void;
};

/** One message of the thread: the owner's bubble, a routine task's head, or the bot's answer (head, process, text, card, foot). */
export function Message({ m, i, last, bot, streaming, copy, draftBox, citations, turnIndex, onFeedback }: Props) {
  const { t } = useLocale(), c = useChat();
  const [tapped, setTapped] = useState(false);
  const { citationDetails, openCitationTurn, setOpenCitationTurn, openCitationAt, showCitation } = citations;
  const common = { id: `chat-message-${i}`, "data-testid": "message", "data-role": m.role, "data-turn-index": turnIndex, "data-last": last || undefined } as const;

  if (m.role === "user" && isTaskPostHead(m.content)) {
    return <article {...common} data-kind="task-post" className="min-w-0 rounded-md"><TaskPostHead content={m.content} /></article>;
  }
  if (m.role === "user") {
    const copiedHere = copy.copied === i;
    return <article {...common} onClick={() => setTapped(x => !x)} className="group/msg flex min-w-0 flex-col items-end gap-1 rounded-md" data-tapped={tapped || undefined}>
      <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-lg bg-brand-soft px-4 py-2.5 text-chat text-ink max-md:max-w-[92%]" data-testid="user-bubble">{m.content}</div>
      <button type="button" data-testid="copy-question" className={`${footButton} opacity-0 transition-opacity duration-1 group-hover/msg:opacity-100 group-focus-within/msg:opacity-100 group-data-[tapped]/msg:opacity-100 focus-visible:opacity-100`}
        aria-label={copiedHere ? t("已复制") : copy.failed === i ? t("复制失败") : t("复制问题")} title={t("复制问题")} onClick={(event) => { event.stopPropagation(); void copy.copyText(m.content, i); }}>
        {copiedHere ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
      </button>
    </article>;
  }

  const name = bot?.name ?? t("模型");
  const time = m.started_at ? new Date(m.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
  const waiting = m.status && m.status !== "complete" && m.status !== "succeeded";
  const copiedHere = copy.copied === i;
  return <article {...common} data-tapped={tapped || undefined} onClick={() => setTapped(x => !x)} className="group/msg flex min-w-0 flex-col gap-2 rounded-md">
    {/* 1. head: small avatar, bot name, time */}
    <header className="flex items-center gap-2 text-caption text-muted-foreground">
      {bot ? <BotOrb avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={24} /> : null}
      <span className="font-medium text-ink-2">{name}</span>
      {time && <time className="tabular-nums">{time}</time>}
    </header>
    {/* 2. process: the old thinking panel and tool badges, untouched until P3.3 */}
    <LegacyFrame><div className="agent-legacy" onClick={(event) => event.stopPropagation()}>
      <ThinkingPanel trace={m.trace} thinkingMs={m.thinking_ms} startedAt={m.started_at} running={last && c.state === "sending"} />
      <div className="agent-tool-badges">{m.reused_sources && <span className="tool-badge status-complete">{t("复用已核实来源")}</span>}{!m.trace?.length && m.tool_trace?.map((tool, j) => <span key={`${tool.name}-${j}`} className={`tool-badge status-${tool.status}`}>{t(toolLabel(tool.name))} · {t(tool.status === "complete" ? (tool.card ? "执行完成" : "已完成") : TOOL_STATUS_TEXT[tool.status] ?? "执行中")}{toolResultSummary(tool.result) && ` · ${toolResultSummary(tool.result)}`}</span>)}</div>
    </div></LegacyFrame>
    {/* 3. text (4. public marks ride inside it as links) */}
    {m.content && <AnswerBody m={m} i={i} streaming={streaming} draftBox={draftBox} openCitationAt={(turn: number, citation: CitationItem) => openCitationAt(turn, citation)} setOpenCitationTurn={setOpenCitationTurn} showCitation={showCitation} />}
    {/* 5. confirmation card */}
    {m.clarification && <LegacyFrame><div className="agent-legacy" onClick={(event) => event.stopPropagation()}>
      <ClarificationCard clarification={m.clarification} active={isActiveClarification(c.messages, i, Boolean(c.archiveView)) && !c.restoring && c.verified && c.state !== "sending" && c.state !== "testing"} onChoose={value => c.choose(value, m.clarification!.request_id)} onChooseMany={values => c.chooseOptions(values, m.clarification!.request_id)} onReply={value => c.replyToCard(value, m.clarification!.request_id)} />
    </div></LegacyFrame>}
    {waiting && <p className="text-caption text-muted-foreground">{t(m.status === "cancelled" ? "本轮已取消，未生成完整回答。" : m.status === "waiting_for_input" ? "等待选择后继续" : m.status === "running" ? "任务运行中，可稍后查询状态" : m.status === "partially_succeeded" ? "部分来源可用；缺项已标出" : "本轮失败；已保留已生成内容。")}</p>}
    {/* 6. foot: copy, helpful, not helpful */}
    {m.content && <div data-testid="message-foot" className="-ml-2 flex items-center gap-0.5 opacity-0 transition-opacity duration-1 group-hover/msg:opacity-100 group-focus-within/msg:opacity-100 group-data-[tapped]/msg:opacity-100">
      <button type="button" className={footButton} aria-label={copiedHere ? t("已复制") : copy.failed === i ? t("复制失败") : t("复制回答")} title={t("复制回答")} onClick={(event) => { event.stopPropagation(); void copy.copyText(m.content, i); }}>{copiedHere ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}</button>
      {m.turn_id && (["up", "down"] as const).map(value => {
        const saved = feedbackOf(m.turn_id!);
        return <button type="button" key={value} className={footButton} aria-pressed={saved === value} aria-label={value === "up" ? t("有帮助") : t("没有帮助")} title={value === "up" ? t("有帮助") : t("没有帮助")}
          onClick={(event) => { event.stopPropagation(); giveFeedback(m.turn_id!, value, onFeedback); }}>{value === "up" ? <ThumbsUp aria-hidden="true" /> : <ThumbsDown aria-hidden="true" />}</button>;
      })}
    </div>}
    {m.content && <LegacyFrame><div className="agent-legacy" onClick={(event) => event.stopPropagation()}><CitationDrawer m={m} i={i} openCitationTurn={openCitationTurn} citationDetails={citationDetails} showCitation={showCitation} /></div></LegacyFrame>}
  </article>;
}

function giveFeedback(turnId: string, value: "up" | "down", done: () => void) {
  const key = `market-evidence-agent:feedback:${turnId}`;
  try { if (localStorage.getItem(key) === value) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch { /* the thumbs are a local note, not required */ }
  done();
}
