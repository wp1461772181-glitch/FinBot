import { useEffect, useMemo, useRef, useState } from "react";
import { Input } from "@/components/ui/input";
import { listAnswers, type AnswerItem } from "../../api/backstage";
import { ANSWER_ENGINES, ANSWER_FILTER_DEFAULTS, ANSWER_STATUSES, answerRow, answerStatus, slowRuleText, type AnswerFilters, type AnswerRow } from "../../backstage-view.mjs";
import { colon, useLocale } from "../../i18n";
import { BotFilter } from "../routines/BotFilter";
import { useWorkspace } from "../workspace";
import { AnswerDrawer } from "./AnswerDrawer";
import { useWords } from "./words";
import { BackstageTable, CostText, PagedFooter, Status, TabState, type Column } from "./BackstageTable";
import { usePaged } from "./use-paged";

const field = "h-9 rounded-sm border border-input bg-background px-2 text-small text-ink outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 max-sm:h-11";

function useDebounced<T>(value: T, delay: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => { const timer = window.setTimeout(() => setSettled(value), delay); return () => window.clearTimeout(timer); }, [value, delay]);
  return settled;
}

/**
 * 回答: every answer the assistant gave, newest first, one line per turn.  Filters on top (bot, engine, status, only the high tier, only the slow ones, a search over the
 * question and the answer), the list pages itself as it scrolls, and a line opens the turn's course in a side drawer.  Nothing here writes.
 */
export function AnswersTab() {
  const { t } = useLocale();
  const w = useWords();
  const ws = useWorkspace();
  const [filters, setFilters] = useState<AnswerFilters>({ ...ANSWER_FILTER_DEFAULTS });
  const searched = useDebounced(filters.q, 350);
  const applied = useMemo(() => ({ ...filters, q: searched }), [filters, searched]);
  const key = JSON.stringify(applied);
  const list = usePaged<AnswerItem, Awaited<ReturnType<typeof listAnswers>>>((before, signal) => listAnswers({ ...applied, before: before ?? "" }, signal), key);
  const [openId, setOpenId] = useState<string | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const open = (id: string) => { opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; setOpenId(id); };
  const set = (patch: Partial<AnswerFilters>) => setFilters(current => ({ ...current, ...patch }));

  const rows = list.items.map(item => answerRow(item, undefined, w));
  const columns: Column<AnswerRow>[] = [
    { key: "time", header: t("时间（本地时间）"), cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.time}</span> },
    { key: "bot", header: "bot", cell: row => row.bot },
    { key: "question", header: t("问题"), className: "sm:w-[34%]", wide: true, cell: row => <span className="flex min-w-0 flex-col gap-1">
      <button type="button" data-testid="answer-open" onClick={event => { event.stopPropagation(); open(row.id); }} className="line-clamp-2 text-left text-ink underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">{row.question}</button>
      {row.old_engine && <span className="text-caption text-muted-foreground">{t("旧流程的记录，只有部分经过")}</span>}
    </span> },
    { key: "status", header: t("状态"), className: "whitespace-nowrap", cell: row => <Status status={row.status} /> },
    { key: "tier", header: t("档位"), cell: row => <span className="whitespace-nowrap">{row.tier}</span> },
    { key: "time_taken", header: t("耗时"), cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.time_taken}</span> },
    { key: "calls", header: t("调用"), cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.calls}</span> },
    { key: "tokens", header: "token", cell: row => <span className="whitespace-nowrap font-mono tabular-nums">{row.tokens}</span> },
    { key: "cost", header: t("费用"), cell: row => <CostText cost={row.cost} /> },
  ];
  const slow = filters.slow ? slowRuleText(list.extra?.slow_threshold_ms, w) : "";
  const label = t("回答记录");

  return <div data-testid="answers-tab" className="flex min-w-0 flex-col gap-3">
    <div role="search" aria-label={t("筛选回答")} className="flex flex-wrap items-end gap-x-3 gap-y-2">
      <BotFilter bots={ws.bots.bots} value={filters.botId} onChange={botId => set({ botId })} />
      <label className="flex flex-col gap-1 text-caption text-muted-foreground">{t("流程")}
        <select data-testid="filter-engine" value={filters.engine} onChange={event => set({ engine: event.target.value })} className={field}>
          <option value="">{t("全部")}</option>
          {ANSWER_ENGINES.map(engine => <option key={engine.value} value={engine.value}>{t(engine.label)}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-caption text-muted-foreground">{t("状态")}
        <select data-testid="filter-status" value={filters.status} onChange={event => set({ status: event.target.value })} className={field}>
          <option value="">{t("全部")}</option>
          {ANSWER_STATUSES.map(status => <option key={status} value={status}>{t(answerStatus(status).label)}</option>)}
        </select>
      </label>
      <label className="flex min-h-9 items-center gap-2 text-small text-ink max-sm:min-h-11"><input type="checkbox" data-testid="filter-high" checked={filters.highTier} onChange={event => set({ highTier: event.target.checked })} className="size-4" />{t("只看用了高档的")}</label>
      <label className="flex min-h-9 items-center gap-2 text-small text-ink max-sm:min-h-11"><input type="checkbox" data-testid="filter-slow" checked={filters.slow} onChange={event => set({ slow: event.target.checked })} className="size-4" />{t("只看慢的")}</label>
      <label className="flex min-w-0 flex-1 basis-56 flex-col gap-1 text-caption text-muted-foreground">{t("搜索问题和回答")}
        <Input type="search" data-testid="filter-q" value={filters.q} maxLength={100} onChange={event => set({ q: event.target.value })} placeholder={t("搜索问题和回答")} className="max-sm:h-11" />
      </label>
    </div>
    {slow && <p data-testid="slow-rule" className="text-caption text-muted-foreground">{slow}</p>}
    {filters.slow && !slow && !list.loading && <p className="text-caption text-muted-foreground">{t("这一页的回答都没有记下耗时，没法判断哪些慢。")}</p>}
    <TabState loading={list.loading && rows.length === 0} error={list.error} empty={!list.loading && rows.length === 0} onRetry={() => void list.reload()}
      emptyTitle={filters.botId || filters.engine || filters.status || filters.highTier || filters.slow || searched ? t("没有符合筛选的回答。") : t("还没有回答的记录。")}
      emptyDescription={t("助手每回答一次，这里就多一行。")} />
    {rows.length > 0 && <>
      <BackstageTable testId="answers-table" label={label} columns={columns} rows={rows} rowKey={row => row.id} onOpen={row => open(row.id)} />
      <PagedFooter hasMore={Boolean(list.next)} loading={list.more} error={list.moreError} onMore={() => void list.loadMore()} />
      <p className="sr-only" aria-live="polite">{`${t("已显示")}${colon()}${rows.length}`}</p>
    </>}
    <AnswerDrawer id={openId} onClose={() => setOpenId(null)} returnFocus={() => { if (opener.current?.isConnected) opener.current.focus(); }} />
  </div>;
}
