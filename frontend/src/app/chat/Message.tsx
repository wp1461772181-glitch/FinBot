import { Suspense, lazy, useMemo, useRef, useState, type RefObject } from "react";
import { Check, Copy, ThumbsDown, ThumbsUp } from "lucide-react";
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
import { useLocale } from "../../i18n";
import { AnswerBody } from "./AnswerBody";
import { DoneLine } from "./DoneLine";
import { TaskPostHead } from "./TaskPostHead";
import { TurnSteps } from "./TurnSteps";
import { useChat } from "./ChatSessionProvider";
import { usePanel } from "./panel-context";
import type { CopyState } from "./use-copy";
import type { LiveMessage } from "./live-message";

// The confirmation card is only needed once a message carries one: a chunk of its own.
const ApprovalCard = lazy(() => import("@/components/ApprovalCard"));

// Message footer buttons: hidden until the message is hovered, tapped, or something in it has keyboard focus (they stay in the tab order).
const footButton = "inline-flex size-8 items-center max-lg:size-11 justify-center rounded-sm text-muted-foreground outline-none hover:bg-accent hover:text-ink focus-visible:ring-2 focus-visible:ring-ring aria-pressed:text-brand [&_svg]:size-4";

function feedbackOf(turnId: string): string { try { return localStorage.getItem(`market-evidence-agent:feedback:${turnId}`) ?? ""; } catch { return ""; } }

type Props = {
  m: AgentChatMessage; i: number; last: boolean; bot?: Bot | null; botColor?: string;
  streaming: boolean; copy: CopyState; draftBox: RefObject<HTMLTextAreaElement | null>;
  turnIndex?: number; onFeedback: () => void;
  /** How the turn that ended on this message ended, when this tab watched it end (the closing line sweeps then); absent for everything else. */
  ended?: TurnEnd | null;
};

/** One message of the thread: the owner's bubble, a routine task's head, or the bot's answer (head, process, text, card, foot). */
export function Message({ m, i, last, bot, streaming, copy, draftBox, turnIndex, onFeedback, ended = null }: Props) {
  const { t } = useLocale(), c = useChat(), panel = usePanel();
  const [tapped, setTapped] = useState(false);
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
  const copiedHere = copy.copied === i;
  const sourceCount = roundSources(m).length;
  const lineState = doneLineState(m, { streaming, ended });
  return <article {...common} data-tapped={tapped || undefined} onClick={() => setTapped(x => !x)} className="group/msg flex min-w-0 flex-col gap-2 rounded-md">
    {/* 1. head: small avatar, bot name, time */}
    <header className="flex items-center gap-2 text-caption text-muted-foreground">
      {bot ? <BotAvatar avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={BOT_AVATAR_SIZE.message} /> : null}
      <span className="font-medium text-ink-2">{name}</span>
      {time && <time className="tabular-nums">{time}</time>}
    </header>
    {/* 2. process: the bar of steps, one line */}
    <div onClick={(event) => event.stopPropagation()}><TurnSteps m={m} i={i} running={last && c.state === "sending"} status={c.state === "sending" ? c.status : ""} /></div>
    {/* 3. text (4. public marks ride inside it as links) */}
    {m.content && <AnswerBody m={m} i={i} streaming={streaming} draftBox={draftBox} />}
    {/* 5. confirmation card: folds to a line once answered or past its time */}
    {m.clarification && <div onClick={(event) => event.stopPropagation()}><OptionalChunk><Suspense fallback={<Skeleton className="h-24 w-full" />}>
      <ApprovalCard card={m.clarification} botName={name} freshAt={(m as LiveMessage).card_at}
        active={isActiveClarification(c.messages, i, Boolean(c.archiveView)) && !c.restoring && c.verified && c.state !== "sending" && c.state !== "testing"}
        answered={i < c.messages.length - 1} reply={c.messages[i + 1]?.role === "user" ? c.messages[i + 1].content : ""}
        onChoose={value => c.choose(value, m.clarification!.request_id)} onChooseMany={values => c.chooseOptions(values, m.clarification!.request_id)} onReply={value => c.replyToCard(value, m.clarification!.request_id)} />
    </Suspense></OptionalChunk></div>}
    {/* the turn's own end: stopped, failed (the error bar says why, and offers 重试 on the newest one), or running without a card */}
    {m.status === "cancelled" && <p data-testid="stopped-note" className="text-small text-muted-foreground">{t("已停止")}{c.state !== "sending" && last ? <span className="text-caption"> · {t("供应商可能仍会计费")}</span> : null}</p>}
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
export function PendingAnswer({ bot, status }: { bot?: Bot | null; status: string }) {
  const { t } = useLocale();
  const sentAt = useRef(Date.now());
  const m = useMemo<AgentChatMessage>(() => ({ role: "assistant", content: "", started_at: sentAt.current }), []);
  return <div data-testid="pending-answer" className="flex min-w-0 flex-col gap-2">
    <header className="flex items-center gap-2 text-caption text-muted-foreground">
      {bot ? <BotAvatar avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={BOT_AVATAR_SIZE.message} /> : null}
      <span className="font-medium text-ink-2">{bot?.name ?? t("模型")}</span>
    </header>
    <TurnSteps m={m} i={-1} running status={status} />
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
