import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { confirm } from "@/components/state/confirm";
import { notify } from "@/components/state/notify";
import { StatusBadge } from "@/components/StatusBadge";
import { getV2Forecasts, type V2ForecastList } from "../../api/forecast-v2";
import { companyName } from "../../company-page.mjs";
import { OPINION_DISCLAIMER } from "../../data-display.mjs";
import { hasProbabilities } from "../../probability-bar.mjs";
import { useLocale, colon } from "../../i18n";
import { paths } from "../../routes.mjs";
import { MAX_WATCHLIST } from "../../watchlist.mjs";
import { checkWatchAdd } from "../../watchlist-add.mjs";
import { createPool, latestForecast, restoreAt } from "../../watchlist-rows.mjs";
import { DEFAULT_SYMBOL, DEFAULT_SYMBOLS } from "../WorkspaceLayout";
import { useWorkspace } from "../workspace";
import { MonitorChip } from "./MonitorChip";
import { WatchRow, rowArrowKeys } from "./WatchRow";
import { removeTitle } from "./support";
import { useRead } from "./use-read";

/**
 * 自选 (#/research, design 4.5): the research queue as a table (a card list on a phone), one row per company.  The queue itself is the workspace's
 * (kept on the server for the owner, in the browser for a guest); adding, removing and the order are the same as ever.  The forecasts of every row
 * come from one list read; the candles and material counts are per row, through a pool of six at a time.  The one disclaimer of the page is the
 * footnote under the table, where the probability bars are.
 */
export function WatchlistPage() {
  const { t, locale } = useLocale();
  const ws = useWorkspace();
  const wsRef = useRef(ws); wsRef.current = ws;
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const pool = useMemo(() => createPool(6), []);

  // One forecast list for the whole queue.  A new queue reads again but keeps the old answer on screen meanwhile (a row added does not blank the others).
  const queue = ws.symbols.slice(0, MAX_WATCHLIST);
  const key = queue.join(",");
  const [list, setList] = useState<{ kind: "loading" } | { kind: "ready"; data: V2ForecastList } | { kind: "error" }>({ kind: "loading" });
  const [listTick, setListTick] = useState(0);
  useEffect(() => {
    if (!queue.length) { setList({ kind: "ready", data: { forecasts: [], limit: 200, pending_job_count: 0, job_alerts: [] } }); return; }
    const controller = new AbortController();
    getV2Forecasts({ symbols: queue, limit: 200 }, controller.signal)
      .then(data => { if (!controller.signal.aborted) setList({ kind: "ready", data }); })
      .catch(() => { if (!controller.signal.aborted) setList(previous => previous.kind === "ready" ? previous : { kind: "error" }); });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, listTick]);
  const retryList = () => { setList({ kind: "loading" }); setListTick(n => n + 1); };

  const add = (event: FormEvent) => {
    event.preventDefault();
    const added = checkWatchAdd(code, ws.symbols);
    if (!added.ok) { setError(added.error); return; }
    ws.setSymbols(items => [...items, added.ticker]);
    setCode(""); setError("");
    notify.success(`${t("已加入自选")}${colon()}${added.ticker}`, { id: `watch-add:${added.ticker}` });
  };
  const remove = async (symbol: string) => {
    const index = wsRef.current.symbols.indexOf(symbol);
    const ok = await confirm({
      title: removeTitle(symbol, locale), description: t("它不再出现在自选和研究队列里；已有的预测和材料不会删除，可以随时再加回来。"),
      confirmLabel: t("移出"), cancelLabel: t("取消"), tone: "danger",
    });
    if (!ok) return;
    wsRef.current.removeWatchSymbol(symbol);
    notify.success(`${t("已移出自选")}${colon()}${symbol}`, { id: `watch-remove:${symbol}`, undo: { label: t("撤销"), onClick: () => wsRef.current.setSymbols(items => restoreAt(items, symbol, index)) } });
  };
  const restoreDefaults = () => { ws.setSymbols(DEFAULT_SYMBOLS); ws.setPreferredSymbol(DEFAULT_SYMBOL); };

  const rows = list.kind === "ready" ? list.data.forecasts : [];
  const count = ws.symbols.length;
  return <main data-testid="watchlist-page" aria-labelledby="watchlist-title" className="mx-auto flex w-full max-w-[1120px] flex-1 flex-col gap-4 p-4 lg:p-6">
    <header className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <h1 id="watchlist-title" className="text-title-m text-ink">{t("自选")}</h1>
      <span data-testid="watchlist-count" className="rounded-full bg-sunken px-2 py-0.5 font-mono text-caption text-muted-foreground" aria-label={`${count} / ${MAX_WATCHLIST}`}>{count}</span>
      <div className="ml-auto flex flex-wrap items-center gap-x-3 gap-y-2">
        <form className="flex items-center gap-2" onSubmit={add}>
          <label className="sr-only" htmlFor="watchlist-add">{t("添加股票")}</label>
          <Input ref={input} id="watchlist-add" value={code} onChange={event => { setCode(event.target.value); setError(""); }} placeholder={t("添加代码，如 AMD")} maxLength={10} autoComplete="off" className="h-9 w-44" aria-invalid={error ? true : undefined} aria-describedby={error ? "watchlist-add-error" : undefined} />
          <Button type="submit" variant="outline"><Plus aria-hidden="true" />{t("添加")}</Button>
        </form>
        <MonitorChip />
      </div>
      {error && <p id="watchlist-add-error" role="alert" className="basis-full text-small text-danger">{t(error)}</p>}
    </header>
    {list.kind === "error" && count > 0 && <ErrorBar message={t("预测暂时读不到，其余数据照常显示。")} onRetry={retryList} />}
    {count === 0
      ? <EmptyState title={t("自选里还没有股票")} description={t("自选是你的研究队列：加进来的公司会在这里列出行情、最新预测和材料数。")}>
        <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
          <button type="button" onClick={() => input.current?.focus()} className="inline-flex h-9 items-center rounded-sm bg-primary px-4 text-small font-medium text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-[3px] focus-visible:ring-ring/50">{t("添加第一只股票")}</button>
          <button type="button" onClick={restoreDefaults} className="inline-flex h-9 items-center rounded-sm border border-line-strong px-4 text-small font-medium text-ink outline-none hover:bg-hover focus-visible:ring-[3px] focus-visible:ring-ring/50">{t("恢复默认七只")}</button>
        </div>
      </EmptyState>
      : <>
        <div role="table" aria-label={t("自选")} data-testid="watchlist-table" onKeyDown={rowArrowKeys} className="flex flex-col gap-2 lg:gap-0 lg:rounded-md lg:border lg:border-line lg:bg-surface">
          <div role="rowgroup" className="hidden lg:block">
            <div role="row" className="grid grid-cols-[minmax(7rem,1fr)_minmax(9.5rem,1.1fr)_minmax(6rem,0.9fr)_minmax(11rem,1.5fr)_6.5rem_4rem_auto] items-center gap-x-4 border-b border-line px-3 py-2 text-caption text-muted-foreground">
              <span role="columnheader">{t("代码")}</span>
              <span role="columnheader">{t("最新收盘")}</span>
              <span role="columnheader">{t("近 3 个月")}</span>
              <span role="columnheader" className="flex items-center gap-1.5">{t("最新预测")}<StatusBadge kind="opinion" className="h-5">{t("模型意见")}</StatusBadge></span>
              <span role="columnheader">{t("目标日")}</span>
              <span role="columnheader">{t("材料")}</span>
              <span role="columnheader" className="w-[7.25rem]"><span className="sr-only">{t("操作")}</span></span>
            </div>
          </div>
          <div role="rowgroup" className="flex flex-col gap-2 lg:gap-0">
            {ws.symbols.map(symbol => <WatchRow key={symbol} symbol={symbol} name={companyName(symbol, ws.bots.bots)} pool={pool} onRemove={remove}
              list={list.kind} forecast={latestForecast(rows, symbol)} />)}
          </div>
        </div>
        {rows.some(row => queue.includes(row.symbol) && hasProbabilities(row.probabilities)) && <p data-testid="watchlist-disclaimer" className="material-opinion-footnote">{t(OPINION_DISCLAIMER)}</p>}
      </>}
  </main>;
}
