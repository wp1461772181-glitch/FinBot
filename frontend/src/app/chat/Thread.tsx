import { Fragment, Suspense, lazy, useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { ArrowDown, ChevronRight, LoaderCircle } from "lucide-react";
import { SkeletonMessages, DelayedSkeleton } from "@/components/state/Skeleton";
import { chatTurnPreviews } from "../../chat-thread.mjs";
import { bottomScrollTop, isFollowing, keepPositionAfterPrepend, showJumpToBottom } from "../../chat-scroll.mjs";
import { noticesAfter } from "../../context-usage.mjs";
import { externalSource, firstOfTurns } from "../../chat-states.mjs";
import { OptionalChunk } from "../../OptionalChunk";
import type { Bot } from "../../api";
import { useLocale } from "../../i18n";
import { useChat } from "./ChatSessionProvider";
import { useMarkdown } from "./markdown-loader";
import { Message, PendingAnswer } from "./Message";
import { QuestionRail } from "./QuestionRail";
import { useCopy } from "./use-copy";

// The empty line (the bot, its companies, three starter questions) is only needed on a line that has not spoken yet: a chunk of its own.
const EmptyChat = lazy(() => import("./EmptyChat"));

/** 「来自 …」: a divider above a turn that was written from outside this tab.  The server marks a routine's result and nothing else, so anything unmarked is just an outside message. */
function ExternalDivider({ content }: { content: string }) {
  const { t } = useLocale();
  const source = externalSource(content);
  const text = source.kind === "routine" ? `${t("例行任务")}「${source.name}」${source.time ? ` · ${source.time}` : ""}` : t("外部消息");
  return <div data-testid="external-divider" data-source={source.kind} role="separator" aria-label={text} className="flex items-center gap-3 text-caption text-muted-foreground">
    <span className="h-px flex-1 bg-line" aria-hidden="true" /><span>{text}</span><span className="h-px flex-1 bg-line" aria-hidden="true" />
  </div>;
}

/** 「已压缩 N 轮」: a divider in the thread; it opens to the summary. */
function CompactionDivider({ turns, focus, summary }: { turns: number; focus?: string; summary?: string }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  return <div data-testid="compaction" className="flex flex-col gap-2">
    <button type="button" aria-expanded={open} onClick={() => setOpen(x => !x)} className="group/divider flex w-full items-center gap-3 rounded-sm text-caption text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <span className="h-px flex-1 bg-line" aria-hidden="true" />
      <span className="inline-flex items-center gap-1 hover:text-ink"><ChevronRight className={`size-3.5 transition-transform duration-1 ${open ? "rotate-90" : ""}`} aria-hidden="true" />{t("已压缩")} {turns} {t("轮")}{focus ? ` · ${focus}` : ""}</span>
      <span className="h-px flex-1 bg-line" aria-hidden="true" />
    </button>
    {open && <pre className="whitespace-pre-wrap break-words rounded-md bg-sunken p-3 font-sans text-small text-ink-2">{summary || t("（摘要为空）")}</pre>}
  </div>;
}

export function Thread({ bot, draftBox }: { bot?: Bot | null; draftBox: RefObject<HTMLTextAreaElement | null> }) {
  const { t } = useLocale(), c = useChat(), copy = useCopy();
  const transcriptRef = useRef<HTMLElement>(null);
  const turnPreviews = chatTurnPreviews(c.messages);
  const railTurns = turnPreviews.map(turn => ({ ...turn, turnId: c.messages[turn.userIndex]?.turn_id }));
  const [, setFeedbackTick] = useState(0);
  const { phase: markdownPhase } = useMarkdown();

  // Following: the newest line stays in view while the reader is at the bottom; one scroll up lets go and offers 回到底部.
  const following = useRef(true);
  const [away, setAway] = useState(false);
  const [activeTurn, setActiveTurn] = useState(0);
  const pinToBottom = useCallback(() => {
    const el = transcriptRef.current; if (!el) return;
    el.scrollTop = bottomScrollTop(el);
  }, []);
  useEffect(() => {
    const el = transcriptRef.current; if (!el) return;
    const update = () => { following.current = isFollowing(el); setAway(showJumpToBottom(el)); };
    el.addEventListener("scroll", update, { passive: true });
    return () => el.removeEventListener("scroll", update);
  }, []);
  // Which question the reader is on (the rail's focus).
  useEffect(() => {
    const el = transcriptRef.current; if (!el) return;
    const update = () => {
      const top = el.getBoundingClientRect().top;
      let active = 0;
      el.querySelectorAll<HTMLElement>("[data-testid=message][data-role=user]").forEach((item, i) => { if (item.getBoundingClientRect().top <= top + 100) active = i; });
      setActiveTurn(active);
    };
    el.addEventListener("scroll", update, { passive: true }); update();
    return () => el.removeEventListener("scroll", update);
  }, [c.messages]);
  // New text, a state change, or the renderer arriving (the skeleton becomes the typeset text, a different height): keep the bottom in view.
  useLayoutEffect(() => { if (following.current) pinToBottom(); }, [c.messages, c.state, c.restoring, markdownPhase, pinToBottom]);
  const jumpToBottom = () => { following.current = true; setAway(false); pinToBottom(); };

  async function loadEarlierAtTop() {
    const el = transcriptRef.current; if (!el || !c.historyHasMore || c.loadingEarlier || c.archiveView) return;
    const before = { scrollHeight: el.scrollHeight, scrollTop: el.scrollTop };
    await c.loadEarlier();
    requestAnimationFrame(() => { if (el) el.scrollTop = keepPositionAfterPrepend(before, el.scrollHeight); });
  }

  const lastIndex = c.messages.length - 1;
  const externalStarts = firstOfTurns(c.messages, c.externalTurns);
  return <div className="relative flex min-h-0 flex-1 flex-col">
    <section ref={transcriptRef} data-testid="transcript" aria-live="polite" aria-label={t("对话")} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 lg:px-6"
      onScroll={e => { if (e.currentTarget.scrollTop < 32) void loadEarlierAtTop(); }}>
      {!c.archiveView && c.historyHasMore && <div className="flex justify-center pt-4">
        <button type="button" data-testid="load-earlier" disabled={c.loadingEarlier} onClick={() => void loadEarlierAtTop()} className="inline-flex h-8 items-center gap-1.5 rounded-sm px-3 text-caption text-muted-foreground outline-none hover:bg-accent hover:text-ink focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-70">
          {c.loadingEarlier && <LoaderCircle className="size-3.5 animate-spin" aria-hidden="true" />}{c.loadingEarlier ? t("正在加载更早消息…") : t("加载更早消息")}
        </button>
      </div>}
      {c.restoring && c.messages.length === 0 && <DelayedSkeleton active><div className="mx-auto w-full max-w-[760px] py-6"><SkeletonMessages /></div></DelayedSkeleton>}
      {c.messages.length === 0 ? (c.restoring ? null : <OptionalChunk><Suspense fallback={null}><EmptyChat bot={bot} verified={c.verified} onPick={(text) => { c.setDraft(text); draftBox.current?.focus(); }} /></Suspense></OptionalChunk>) : c.messages.length > 0 &&
        <div className="mx-auto grid w-full grid-cols-1 pb-20 pt-6 lg:max-w-[880px] lg:grid-cols-[minmax(3rem,1fr)_minmax(0,760px)_minmax(0,1fr)]">
          <QuestionRail turns={railTurns} activeTurn={activeTurn} transcriptRef={transcriptRef} conversationId={c.conversationId} />
          <div data-testid="thread" className="flex min-w-0 flex-col gap-7 lg:col-start-2 lg:row-start-1">{c.messages.map((m, i) => <Fragment key={i}>
            {externalStarts.has(i) && <ExternalDivider content={m.role === "user" ? m.content : ""} />}
            <Message m={m} i={i} last={i === lastIndex} bot={bot} streaming={i === lastIndex && c.state === "sending"} copy={copy} draftBox={draftBox}
              turnIndex={m.role === "user" ? turnPreviews.findIndex(turn => turn.userIndex === i) : undefined} onFeedback={() => setFeedbackTick(x => x + 1)} />
            {m.role === "assistant" && noticesAfter(c.notices, m.turn_id).map(notice => <CompactionDivider key={`compaction-${notice.id}`} turns={notice.turns} focus={notice.focus} summary={notice.summary} />)}
          </Fragment>)}
            {c.state === "sending" && c.messages.at(-1)?.role === "user" && <PendingAnswer bot={bot} status={c.status} />}
          </div>
        </div>}
    </section>
    {away && <button type="button" data-testid="jump-bottom" onClick={jumpToBottom} className="absolute bottom-3 left-1/2 z-sticky inline-flex h-9 -translate-x-1/2 items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3.5 text-small text-ink shadow-pop outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring">
      <ArrowDown className="size-4" aria-hidden="true" />{t("回到底部")}
    </button>}
  </div>;
}
