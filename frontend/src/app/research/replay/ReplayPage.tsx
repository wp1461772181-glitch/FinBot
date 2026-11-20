import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";
import { getV2Evaluations, getV2ForecastVersion } from "../../../api/forecast-v2";
import type { V2ForecastJob } from "../../../types";
import { useLocale } from "../../../i18n";
import "../../../styles/forecast.css";
import { actionMessage } from "../support";
import { useRead } from "../use-read";
import { day } from "../forecasts/format";
import { ReplayDetail } from "./ReplayDetail";
import { ReplayForm } from "./ReplayForm";
import { ReplayList, type ListState } from "./ReplayList";
import { dismissReplayFailure, followReplayJob, onReplaySettled, useReplayFailure, useReplayRunning } from "./replay-jobs";
import { defaultReplayDate, replayFailure, replayRows } from "./replay-model.mjs";
import { useDetailLayer } from "../use-detail-layer";
import { usePhone } from "../materials/use-phone";

// The bar is a chunk of its own, fetched when a task runs (the shell's dock does the same).
const TaskBar = lazy(() => import("@/components/state/TaskBar").then(m => ({ default: m.TaskBar })));

/**
 * 历史回放 (#/research/replay, design 4.8): the form on top, the replays of the chosen company on the left, the chosen replay on the right (a full-screen layer on a
 * phone).  The detail is one element in both layouts, so a window moved across the breakpoint never drops what the reader has open.  The jobs, the polling and the
 * request are the old page's; a replay still under way is on the task bar, one that ended without a replay is told here with its reason.
 */
export function ReplayPage({ initialSymbol, symbols }: { initialSymbol: string; symbols: string[] }) {
  const { t, locale } = useLocale();
  const phone = usePhone();
  const [symbol, setSymbol] = useState(initialSymbol);
  const [date, setDate] = useState(() => defaultReplayDate());
  const [refresh, setRefresh] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const [detailOpen, setDetailOpen] = useState(false);
  const wanted = useRef<string | null>(null);
  const running = useReplayRunning();
  const failure = useReplayFailure();
  const choices = useMemo(() => (symbols.includes(symbol) ? symbols : [symbol, ...symbols]), [symbols, symbol]);

  const [evaluation, retryList] = useRead(`replay-list:${symbol}:${refresh}`, signal => getV2Evaluations(symbol, signal));
  const list: ListState = evaluation.kind === "loading" ? { kind: "loading" }
    : evaluation.kind === "error" ? { kind: "error", message: actionMessage(evaluation.error, "暂时无法读取历史回放记录。") }
    : { kind: "ready", rows: replayRows(evaluation.value) };
  const rows = list.kind === "ready" ? list.rows : null;

  // The list says which replay is chosen: the one a finished job made (when it is in the list), else the one that was chosen, else the newest.
  useEffect(() => {
    if (!rows?.length) { if (rows && selectedId) setSelectedId(""); return; }
    const preferred = wanted.current && rows.some(row => row.id === wanted.current) ? wanted.current : null;
    if (preferred) wanted.current = null;
    if (preferred) setSelectedId(preferred);
    else if (!rows.some(row => row.id === selectedId)) setSelectedId(rows[0].id);
  }, [rows, selectedId]);

  const selectedRow = rows?.find(row => row.id === selectedId) ?? null;
  const [version, retryVersion] = useRead(`replay-version:${selectedId}`, signal => getV2ForecastVersion(selectedId, signal), selectedId !== "");

  // A replay that ends while the page is open: the list is read again, and a replay that was made is the one shown.
  useEffect(() => onReplaySettled((job: V2ForecastJob) => {
    if (job.symbol !== symbol) return;
    if ((job.status === "succeeded" || job.status === "succeeded_no_change") && job.result_version_id) wanted.current = job.result_version_id;
    setRefresh(value => value + 1);
  }), [symbol]);

  const started = useCallback((job: V2ForecastJob) => followReplayJob(job, `${t("历史回放")} · ${job.symbol} · ${(job.requested_decision_at ?? date).slice(0, 10)}`), [t, date]);
  const changeSymbol = (next: string) => { setSymbol(next); setSelectedId(""); setDetailOpen(false); };
  // Only a press on a phone opens the layer: a choice made on a wide screen must not turn into a layer when the window is later narrowed.
  const choose = (id: string) => { setSelectedId(id); setDetailOpen(phone); };
  const fillForm = () => document.getElementById("replay-date")?.focus();

  const overlay = phone && detailOpen && selectedRow !== null;
  const layer = useRef<HTMLDivElement | null>(null);
  const back = useRef<HTMLButtonElement | null>(null);
  useDetailLayer({ open: overlay, layer, back, onClose: () => setDetailOpen(false), returnTo: "[data-testid=replay-row][data-selected]" });

  const failed = failure ? replayFailure(failure) : null;
  const detail = selectedRow
    ? <ReplayDetail key={selectedRow.id} symbol={symbol} evaluation={selectedRow} read={version} onRetry={retryVersion} />
    : <div data-testid="replay-detail-empty" className="flex min-h-48 items-center justify-center rounded-md border border-dashed border-line px-4 text-center text-small text-muted-foreground">{t("选择一条回放查看详情。")}</div>;
  return <main data-testid="replay-page" aria-labelledby="replay-title" className="mx-auto flex w-full min-w-0 max-w-[1280px] flex-1 flex-col gap-4 p-4 lg:p-6">
    <header className="flex min-w-0 flex-col gap-1">
      <p className="text-caption text-muted-foreground">{t("历史研究 · 单独分组")}</p>
      <h1 id="replay-title" className="text-title-m text-ink">{t("历史回放")}</h1>
      <p className="m-0 max-w-3xl text-small text-ink-2">{t("选择股票和历史决策日，系统会按当时可用行情建立 20 个交易日目标，再读取目标期的真实结果。历史回放单独归档，不会进入当前预测或真实前向表现。")}</p>
    </header>
    <ReplayForm symbol={symbol} choices={choices} onSymbol={changeSymbol} date={date} onDate={setDate} running={running} onStarted={started} />
    <div data-task-strip="" data-testid="replay-jobs" className="empty:hidden"><Suspense fallback={null}><TaskBar /></Suspense></div>
    {failed && failure && <section data-testid="replay-failure" role="status" aria-label={t(failed.title)} className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-line bg-sunken px-3 py-2.5 text-small max-sm:flex-col max-sm:items-start">
      <StatusBadge kind="failure" className="h-5">{t(failed.title)}</StatusBadge>
      <span className="min-w-0 flex-1 text-ink-2 [overflow-wrap:anywhere]"><span className="font-mono">{failure.symbol}</span> · {failure.requested_decision_at ? day(failure.requested_decision_at) : date}{locale === "en-US" ? ". " : "。"}{t("未生成回放：")} {failed.reason ? t(failed.reason) : null}{failed.code && <> <code data-testid="replay-failure-code" className="font-mono text-caption text-muted-foreground">{failed.code}</code></>}</span>
      <button type="button" onClick={dismissReplayFailure} className="inline-flex h-8 items-center rounded-sm border border-line-strong bg-background px-3 text-small font-medium text-ink outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring max-sm:min-h-11">{t("忽略")}</button>
    </section>}
    <div className="grid min-w-0 items-start gap-6 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
      <ReplayList symbol={symbol} state={list} selectedId={selectedId} onSelect={choose} onRetry={retryList} onFillForm={fillForm} />
      <div ref={layer} data-testid={overlay ? "replay-drawer" : "replay-detail-pane"} {...(overlay ? { role: "dialog", "aria-modal": true, "aria-label": `${symbol} · ${t("决策日")} ${day(selectedRow?.decision_at)}` } : {})}
        className={overlay ? "fixed inset-0 z-50 flex flex-col bg-background outline-none" : phone ? "hidden" : "min-w-0"}>
        {overlay && <div className="flex shrink-0 items-center gap-2 border-b border-line p-2">
          <Button ref={back} type="button" variant="ghost" size="sm" onClick={() => setDetailOpen(false)} className="min-h-11" data-testid="replay-drawer-back"><ArrowLeft aria-hidden="true" />{t("返回列表")}</Button>
        </div>}
        <div className={overlay ? "min-h-0 flex-1 overflow-y-auto p-4" : undefined}>{detail}</div>
      </div>
    </div>
  </main>;
}
