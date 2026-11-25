import { Suspense, lazy, useMemo, useRef, useState, type CSSProperties, type RefObject } from "react";
import { Check, Copy, LoaderCircle, ThumbsDown, ThumbsUp } from "lucide-react";
import { Skeleton } from "@/components/state/Skeleton";
import { ErrorBar } from "@/components/state/ErrorBar";
import { OptionalChunk } from "../../OptionalChunk";
import { failureNeedsSettings } from "../../chat-states.mjs";
import { BotAvatar } from "@/components/bot/BotAvatar";
import { BOT_AVATAR_SIZE } from "../../bot-sizes.mjs";
import { isActiveClarification } from "../../chat-clarification.mjs";
import { isTaskPostHead } from "../../task-posts.mjs";
import { doneLineState, type TurnEnd } from "../../signature.mjs";
import { roundSources, turnKey } from "../../panel-model.mjs";
import type { AgentChatMessage } from "../../api/conversations";
import type { Bot } from "../../api/bots";
import { useLocale, colon } from "../../i18n";
import { queuedText, type Delivery } from "../../chat-interject.mjs";
import { AnswerBody } from "./AnswerBody";
import { DoneLine } from "./DoneLine";
import { TaskPostHead } from "./TaskPostHead";
import { TurnSteps } from "./TurnSteps";
import { TurnProgress } from "./TurnProgress";
import { progressModel } from "../../turn-progress.mjs";
import { useChat } from "./ChatSessionProvider";
import { usePanel } from "./panel-context";
import type { CopyState } from "./use-copy";
import type { LiveMessage } from "./live-message";

// The confirmation card is only needed once a message carries one: a chunk of its own.
const ApprovalCard = lazy(() => import("@/components/ApprovalCard"));

/** The words under a message that was sent while a turn was answering (the queue's sentence has a number in it: queuedText). */
const DELIVERY_TEXT = { sending: "发送中", received: "已收到", merged: "已并入上一个回答", separate: "单独回答中", stopped: "已停下上一个回答" } as const;

// Message footer buttons: hidden until the message is hovered, tapped, or something in it has keyboard focus (they stay in the tab order).
const footButton = "inline-flex size-8 items-center max-lg:size-11 justify-center rounded-sm text-muted-foreground outline-none hover:bg-accent hover:text-ink focus-visible:ring-2 focus-visible:ring-ring aria-pressed:text-brand [&_svg]:size-4";

function feedbackOf(turnId: string): string { try { return localStorage.getItem(`market-evidence-agent:feedback:${turnId}`) ?? ""; } catch { return ""; } }

type Props = {
  m: AgentChatMessage; i: number; last: boolean; bot?: Bot | null; botColor?: string;
  streaming: boolean; copy: CopyState; draftBox: RefObject<HTMLTextAreaElement | null>;
  turnIndex?: number; onFeedback: () => void;
  /** 3c: what became of this message when it was sent while a turn was answering (a user message), and what an answer answers when it is not directly below it. */
  mark?: Delivery; quote?: string | null;
  /** How the turn that ended on this message ended, when this tab watched it end (the closing line sweeps then); absent for everything else. */
  ended?: TurnEnd | null;
  /** The handoff (design 6.7): this message fades in this many seconds after the line was mounted (one of the last three of the line that has just been switched to). */
  entry?: number;
};

/** One message of the thread: the owner's bubble, a routine task's head, or the bot's answer (head, process, text, card, foot). */
export function Message({ m, i, last, bot, streaming, copy, draftBox, turnIndex, onFeedback, ended = null, entry, mark = null, quote = null }: Props) {
  const { t, locale } = useLocale(), c = useChat(), panel = usePanel();
  const [tapped, setTapped] = useState(false);
  const common = { id: `chat-message-${i}`, "data-testid": "message", "data-role": m.role, "data-turn-index": turnIndex, "data-last": last || undefined, ...(entry === undefined ? {} : { "data-entry": "", style: { "--entry-delay": `${entry}s` } as CSSProperties }) } as const;

  if (m.role === "user" && isTaskPostHead(m.content)) {
    return <article {...common} data-kind="task-post" className="min-w-0 rounded-md"><TaskPostHead content={m.content} /></article>;
  }
  if (m.role === "user") {
    const copiedHere = copy.copied === i;
    return <article {...common} onClick={() => setTapped(x => !x)} className="group/msg flex min-w-0 flex-col items-end gap-1 rounded-md" data-tapped={tapped || undefined}>
      <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-lg bg-brand-soft px-4 py-2.5 text-chat text-ink max-md:max-w-[92%]" data-testid="user-bubble">{m.content}</div>
      {mark && <p data-testid="delivery-note" data-kind={mark.kind} role="status" className="text-caption text-muted-foreground">{mark.kind === "queued" ? queuedText(mark.ahead ?? 0, locale) : t(DELIVERY_TEXT[mark.kind])}</p>}
      <button type="button" data-testid="copy-question" className={`${footButton} opacity-0 transition-opacity duration-1 group-hover/msg:opacity-100 group-focus-within/msg:opacity-100 group-data-[tapped]/msg:opacity-100 focus-visible:opacity-100`}
        aria-label={copiedHere ? t("已复制") : copy.failed === i ? t("复制失败") : t("复制问题")} title={t("复制问题")} onClick={(event) => { event.stopPropagation(); void copy.copyText(m.content, i); }}>
        {copiedHere ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
      </button>
    </article>;
  }

  const name = bot?.name ?? t("模型");
  const time = m.started_at ? new Date(m.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
  const copiedHere = copy.copied === i;
  const sourceCount = roundSources(m).length;
  // Two answers can be running at once (a message sent meanwhile that gets its own): each knows it is running, the line's state does not say which.
  const running = Boolean(m.live);
  const lineState = doneLineState(m, { streaming: streaming || running, ended });
  const stoppedByMessage = m.status === "cancelled" && (Boolean(m.stopped_by_message) || (m.reply_to?.length ?? 0) > 1);
  const kernelProgress = progressModel({ narration: m.narration, checklist: m.checklist, tier: m.tier, toolTrace: m.tool_trace, running });
  return <article {...common} data-tapped={tapped || undefined} onClick={() => setTapped(x => !x)} className="group/msg flex min-w-0 flex-col gap-2 rounded-md">
    {/* 1. head: small avatar, bot name, time */}
    <header className="flex items-center gap-2 text-caption text-muted-foreground">
      {bot ? <BotAvatar avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={BOT_AVATAR_SIZE.message} /> : null}
      <span className="font-medium text-ink-2">{name}</span>
      {time && <time className="tabular-nums">{time}</time>}
    </header>
    {quote && <p data-testid="reply-quote" className="min-w-0 truncate text-caption text-muted-foreground" title={quote}>{t("回复")}{colon(locale)}{quote}</p>}
    {m.queued_ahead ? <p data-testid="queued-note" role="status" className="text-small text-muted-foreground">{queuedText(m.queued_ahead, locale)}</p> : null}
    {/* 2. process: the bar of steps, one line */}
    {!m.queued_ahead && <div onClick={(event) => event.stopPropagation()}>{kernelProgress
      ? <TurnProgress m={m} model={kernelProgress} running={running} status={running ? c.status : ""} />
      : <TurnSteps m={m} i={i} running={running} status={running ? c.status : ""} />}</div>}
    {/* 3. text (4. public marks ride inside it as links) */}
    {m.content && <div data-paused={m.paused || undefined} className={m.paused ? "opacity-60" : undefined}><AnswerBody m={m} i={i} streaming={streaming} draftBox={draftBox} /></div>}
    {m.paused && <p data-testid="paused-note" role="status" className="text-small text-muted-foreground">{t("写到这里先停下了：你刚发的消息在处理，处理完会接着答。")}</p>}
    {/* 5. confirmation card: folds to a line once answered or past its time */}
    {m.clarification && <div onClick={(event) => event.stopPropagation()}><OptionalChunk><Suspense fallback={<Skeleton className="h-24 w-full" />}>
      <ApprovalCard card={m.clarification} botName={name} freshAt={(m as LiveMessage).card_at}
        active={isActiveClarification(c.messages, i, Boolean(c.archiveView)) && !c.restoring && c.verified && c.state !== "sending" && c.state !== "testing"}
        answered={i < c.messages.length - 1} reply={c.messages[i + 1]?.role === "user" ? c.messages[i + 1].content : ""}
        onChoose={value => c.choose(value, m.clarification!.request_id)} onChooseMany={values => c.chooseOptions(values, m.clarification!.request_id)} onReply={value => c.replyToCard(value, m.clarification!.request_id)} />
    </Suspense></OptionalChunk></div>}
    {/* the turn's own end: stopped, failed (the error bar says why, and offers 重试 on the newest one), or running without a card */}
    {stoppedByMessage && <p data-testid="stopped-note" data-by="message" className="text-small text-muted-foreground">{t("已停下")}</p>}
    {m.status === "cancelled" && !stoppedByMessage && <p data-testid="stopped-note" className="text-small text-muted-foreground">{t("已停止")}{c.state !== "sending" && last ? <span className="text-caption"> · {t("供应商可能仍会计费")}</span> : null}</p>}
    {m.status === "failed" && <FailedNote m={m as LiveMessage} last={last} />}
    {m.status === "running" && <p className="text-caption text-muted-foreground">{t("任务运行中，可稍后查询状态")}</p>}
    {m.status === "partially_succeeded" && <p className="text-caption text-muted-foreground">{t("部分来源可用；缺项已标出")}</p>}
    {/* the finish line: a hairline under a finished answer; the turn this tab just saw end draws the bot's stroke over it once (red and still when it failed) */}
    {lineState && <DoneLine state={lineState} />}
    {/* 6. foot: the sources chip (always there), copy, helpful, not helpful (these three show on hover, tap or focus) */}
    {m.content && <div className="flex flex-wrap items-center gap-x-1 gap-y-0.5">
      {sourceCount > 0 && <button type="button" data-testid="sources-chip" data-count={sourceCount} className="inline-flex h-7 items-center gap-1 rounded-full border border-line bg-surface px-2.5 text-caption max-lg:h-11 max-lg:px-3.5 text-ink-2 outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
        onClick={(event) => { event.stopPropagation(); panel.showSource(turnKey(m, i), null, event.currentTarget, event.detail === 0); }}>{t("来源")} {sourceCount}</button>}
      <div data-testid="message-foot" className={`${sourceCount > 0 ? "" : "-ml-2 "}flex items-center gap-0.5 opacity-0 transition-opacity duration-1 group-hover/msg:opacity-100 group-focus-within/msg:opacity-100 group-data-[tapped]/msg:opacity-100`}>
        <button type="button" className={footButton} aria-label={copiedHere ? t("已复制") : copy.failed === i ? t("复制失败") : t("复制回答")} title={t("复制回答")} onClick={(event) => { event.stopPropagation(); void copy.copyText(m.content, i); }}>{copiedHere ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}</button>
        {m.turn_id && (["up", "down"] as const).map(value => {
          const saved = feedbackOf(m.turn_id!);
          return <button type="button" key={value} className={footButton} aria-pressed={saved === value} aria-label={value === "up" ? t("有帮助") : t("没有帮助")} title={value === "up" ? t("有帮助") : t("没有帮助")}
            onClick={(event) => { event.stopPropagation(); giveFeedback(m.turn_id!, value, onFeedback); }}>{value === "up" ? <ThumbsUp aria-hidden="true" /> : <ThumbsDown aria-hidden="true" />}</button>;
        })}
      </div>
    </div>}
  </article>;
}

function giveFeedback(turnId: string, value: "up" | "down", done: () => void) {
  const key = `market-evidence-agent:feedback:${turnId}`;
  try { if (localStorage.getItem(key) === value) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch { /* the thumbs are a local note, not required */ }
  done();
}

/**
 * The bot's turn between 「sent」 and the first event: no message exists yet, but the reader should see the line has been taken.  The head and the process
 * bar's first cell (dots, 思考中, the seconds); the first event replaces it with the real message.
 */
export function PendingAnswer({ bot, status, queuedAhead = 0 }: { bot?: Bot | null; status: string; queuedAhead?: number }) {
  const { t, locale } = useLocale();
  const sentAt = useRef(Date.now());
  const m = useMemo<AgentChatMessage>(() => ({ role: "assistant", content: "", started_at: sentAt.current }), []);
  return <div data-testid="pending-answer" className="flex min-w-0 flex-col gap-2">
    <header className="flex items-center gap-2 text-caption text-muted-foreground">
      {bot ? <BotAvatar avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={BOT_AVATAR_SIZE.message} /> : null}
      <span className="font-medium text-ink-2">{bot?.name ?? t("模型")}</span>
    </header>
    {queuedAhead > 0 ? <p data-testid="queued-note" role="status" className="text-small text-muted-foreground">{queuedText(queuedAhead, locale)}</p> : <TurnSteps m={m} i={-1} running status={status} />}
  </div>;
}

/** 「后台运行中」: a turn the server is still running while this page is not watching it.  Not an error (no alert, no retry): it sits where the answer will appear, with a stop button. */
export function BackgroundTurn({ bot }: { bot?: Bot | null }) {
  const { t } = useLocale(), c = useChat();
  const [stopping, setStopping] = useState(false);
  const bg = c.background;
  if (!bg) return null;
  const text = bg.reason === "dropped" ? t("连接断开了：这一轮仍在服务器上继续，完成后会自动出现在这里。")
    : bg.reason === "stop_unreachable" ? t("没能通知服务器停止：这一轮可能仍在后台继续，完成后会出现在对话里。")
    : bg.reason === "busy" ? t("上一条消息还在回答中（可能在别的页面、Telegram 或后台），等它答完再发。")
    : t("上次离开时这一轮还没答完，它应该仍在服务器上继续，完成后会自动出现在这里。");
  return <div className="flex min-w-0 flex-col gap-2">
    <header className="flex items-center gap-2 text-caption text-muted-foreground">
      {bot ? <BotAvatar avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={BOT_AVATAR_SIZE.message} /> : null}
      <span className="font-medium text-ink-2">{bot?.name ?? t("模型")}</span>
    </header>
    <p role="status" data-testid="background-turn" data-reason={bg.reason} className="text-small text-muted-foreground">{text}</p>
    {bg.conversationId && <button type="button" data-testid="stop-background" disabled={stopping} aria-busy={stopping}
      onClick={() => { setStopping(true); void c.cancelBackground().finally(() => setStopping(false)); }}
      className="inline-flex h-8 w-fit items-center gap-1.5 rounded-sm border border-line px-3 text-small text-ink outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-70">
      {stopping && <LoaderCircle aria-hidden="true" className="size-3.5 motion-safe:animate-spin" />}{t("停止后台回答")}
    </button>}
  </div>;
}

/** The error bar under a failed turn: why (the server's code through friendlyError, or the plain sentence for a request that got no answer), 重试, and 去设置 when a setting is the way out. */
function FailedNote({ m, last }: { m: LiveMessage; last: boolean }) {
  const { t } = useLocale(), c = useChat();
  const [retrying, setRetrying] = useState(false);
  const canRetry = last && !c.archiveView && c.state !== "sending" && c.verified;
  return <div data-testid="turn-error" data-code={m.failure?.code || undefined} onClick={(event) => event.stopPropagation()}>
    <ErrorBar message={m.failure?.message ?? t("本轮失败；已保留已生成内容。")} settings={failureNeedsSettings(m.failure?.code)}
      retrying={retrying} onRetry={canRetry ? () => { setRetrying(true); void c.retry().finally(() => setRetrying(false)); } : undefined} />
  </div>;
}
