import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { ArrowDown, ArrowUpRight, ChevronRight, LoaderCircle } from "lucide-react";
import { SkeletonMessages, DelayedSkeleton } from "@/components/state/Skeleton";
import { chatTurnPreviews } from "../../chat-thread.mjs";
import { bottomScrollTop, isFollowing, keepPositionAfterPrepend, showJumpToBottom } from "../../chat-scroll.mjs";
import { noticesAfter } from "../../context-usage.mjs";
import type { Bot } from "../../api";
import { useLocale } from "../../i18n";
import { useCitations } from "./Citations";
import { useChat } from "./ChatSessionProvider";
import { useMarkdown } from "./markdown-loader";
import { Message } from "./Message";
import { QuestionRail } from "./QuestionRail";
import { useCopy } from "./use-copy";

const STARTERS = ["查看 AAPL 最近行情", "AAPL 已保存的最新财报有哪些", "可信度星级是什么"];

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
  const citations = useCitations();
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
  return <div className="relative flex min-h-0 flex-1 flex-col">
    <section ref={transcriptRef} data-testid="transcript" aria-live="polite" aria-label={t("对话")} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 lg:px-6"
      onScroll={e => { if (e.currentTarget.scrollTop < 32) void loadEarlierAtTop(); }}>
      {!c.archiveView && c.historyHasMore && <div className="flex justify-center pt-4">
        <button type="button" data-testid="load-earlier" disabled={c.loadingEarlier} onClick={() => void loadEarlierAtTop()} className="inline-flex h-8 items-center gap-1.5 rounded-sm px-3 text-caption text-muted-foreground outline-none hover:bg-accent hover:text-ink focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-70">
          {c.loadingEarlier && <LoaderCircle className="size-3.5 animate-spin" aria-hidden="true" />}{c.loadingEarlier ? t("正在加载更早消息…") : t("加载更早消息")}
        </button>
      </div>}
      {c.restoring && c.messages.length === 0 && <DelayedSkeleton active><div className="mx-auto w-full max-w-[760px] py-6"><SkeletonMessages /></div></DelayedSkeleton>}
      {c.messages.length === 0 ? (c.restoring ? null : <div data-testid="welcome" className="mx-auto flex w-full max-w-[760px] flex-col gap-3 py-10">
        <h2 className="text-title-m text-ink">{t("从一个问题开始")}</h2>
        <p className="text-body text-muted-foreground">{t(c.verified ? "连接已就绪，可以输入问题或选择下方建议。" : "登录个人聊天后才能对话：模型由服务器模型目录提供。")}</p>
        <div className="flex flex-wrap gap-2">{STARTERS.map(x => <button type="button" key={x} onClick={() => c.setDraft(t(x))} className="inline-flex h-9 items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3 text-small text-ink-2 outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring">{t(x)}<ArrowUpRight className="size-3.5" aria-hidden="true" /></button>)}</div>
      </div>) : c.messages.length > 0 &&
        <div className="mx-auto grid w-full grid-cols-1 pb-20 pt-6 lg:max-w-[880px] lg:grid-cols-[minmax(0,1fr)_minmax(0,760px)_minmax(0,1fr)]">
          <QuestionRail turns={railTurns} activeTurn={activeTurn} transcriptRef={transcriptRef} conversationId={c.conversationId} />
          <div data-testid="thread" className="flex min-w-0 flex-col gap-7 lg:col-start-2 lg:row-start-1">{c.messages.map((m, i) => <Fragment key={i}>
            <Message m={m} i={i} last={i === lastIndex} bot={bot} streaming={i === lastIndex && c.state === "sending"} copy={copy} draftBox={draftBox} citations={citations}
              turnIndex={m.role === "user" ? turnPreviews.findIndex(turn => turn.userIndex === i) : undefined} onFeedback={() => setFeedbackTick(x => x + 1)} />
            {m.role === "assistant" && noticesAfter(c.notices, m.turn_id).map(notice => <CompactionDivider key={`compaction-${notice.id}`} turns={notice.turns} focus={notice.focus} summary={notice.summary} />)}
          </Fragment>)}</div>
        </div>}
    </section>
    {away && <button type="button" data-testid="jump-bottom" onClick={jumpToBottom} className="absolute bottom-3 left-1/2 z-sticky inline-flex h-9 -translate-x-1/2 items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3.5 text-small text-ink shadow-pop outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring">
      <ArrowDown className="size-4" aria-hidden="true" />{t("回到底部")}
    </button>}
  </div>;
}
