import { useEffect, useState, type KeyboardEvent, type MouseEvent } from "react";
import { Link, useNavigate } from "react-router";
import { ArrowRight, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton, useDelayedFlag } from "@/components/state/Skeleton";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import { Sparkline } from "@/components/Sparkline";
import { Change } from "@/components/StatTile";
import { StatusBadge } from "@/components/StatusBadge";
import { getMaterialLibrary } from "../../api/material-library";
import { getV2Prices } from "../../api/prices";
import type { V2ForecastListRow } from "../../api/forecast-v2";
import type { PriceCandle } from "../../types";
import { useLocale } from "../../i18n";
import { paths } from "../../routes.mjs";
import { watchRow, type createPool } from "../../watchlist-rows.mjs";
import { removeLabel } from "./support";
import type { Read } from "./use-read";

type Pool = ReturnType<typeof createPool>;

/** The reads one row makes of its own company: the candles (close, change, the 3-month line) and the material count.  Each fails and retries alone. */
function useRowReads(symbol: string, pool: Pool) {
  const [prices, setPrices] = useState<Read<PriceCandle[]>>({ kind: "loading" });
  const [materials, setMaterials] = useState<Read<number>>({ kind: "loading" });
  const [priceTick, setPriceTick] = useState(0), [materialTick, setMaterialTick] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setPrices({ kind: "loading" });
    pool.run(() => getV2Prices(symbol, controller.signal), controller.signal)
      .then(result => { if (!controller.signal.aborted) setPrices({ kind: "ready", value: result.price_history.candles }); })
      .catch(error => { if (!controller.signal.aborted) setPrices({ kind: "error", error }); });
    return () => controller.abort();
  }, [symbol, priceTick, pool]);
  useEffect(() => {
    const controller = new AbortController();
    setMaterials({ kind: "loading" });
    pool.run(() => getMaterialLibrary(symbol, { limit: 1, signal: controller.signal }), controller.signal)
      .then(library => { if (!controller.signal.aborted) setMaterials({ kind: "ready", value: library.total }); })
      .catch(error => { if (!controller.signal.aborted) setMaterials({ kind: "error", error }); });
    return () => controller.abort();
  }, [symbol, materialTick, pool]);
  return { prices, materials, retryPrices: () => setPriceTick(n => n + 1), retryMaterials: () => setMaterialTick(n => n + 1) };
}

/** A cell that is still loading: nothing for 400ms (a quick read leaves no flash), then a skeleton bar the cell's size. */
function Pending({ className }: { className: string }) {
  const shown = useDelayedFlag(true);
  return <span role="status" aria-busy="true" className="block">{shown && <Skeleton className={className} />}</span>;
}

/** A failed cell: what failed, and 重试 for this one read. */
function CellError({ what, onRetry }: { what: string; onRetry: () => void }) {
  const { t } = useLocale();
  return <span role="alert" className="flex flex-wrap items-center gap-x-2 text-caption text-muted-foreground">
    {what}
    <button type="button" onClick={onRetry} className="rounded-sm text-brand underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">{t("重试")}</button>
  </span>;
}

/** A label that names a cell on the phone's card (the table's header does it on a desktop). */
const Label = ({ children }: { children: string }) => <span className="text-caption text-muted-foreground lg:hidden">{children}</span>;

/**
 * One company of the watchlist: a row of a table on a desktop, a card on a phone (the same cells, laid out by the grid).  The forecast comes from the
 * one list the page reads for the whole queue; the candles and the material count are this row's own reads (through the page's pool), and each of
 * them loads, fails and retries without touching another row.  The whole row opens the company; 打开 is the way to it from the keyboard.
 */
export function WatchRow({ symbol, name, forecast, list, pool, onRemove }: {
  symbol: string;
  name: string | null;
  forecast: V2ForecastListRow | null;
  list: "loading" | "ready" | "error";
  pool: Pool;
  onRemove: (symbol: string) => void;
}) {
  const { t, locale } = useLocale();
  const navigate = useNavigate();
  const reads = useRowReads(symbol, pool);
  const row = watchRow({
    symbol, forecast,
    candles: reads.prices.kind === "ready" ? reads.prices.value : null,
    materialTotal: reads.materials.kind === "ready" ? reads.materials.value : null,
  });
  const open = () => navigate(paths.company(symbol));
  // A press on the row (not on something inside it that does its own thing) opens the company.
  const press = (event: MouseEvent<HTMLElement>) => { if (!(event.target as HTMLElement).closest("a,button,[role=img]")) open(); };
  const priceReady = reads.prices.kind === "ready";
  return <div role="row" data-testid="watch-row" data-symbol={symbol} onClick={press}
    className="group/row grid cursor-pointer grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 gap-y-2 rounded-md border border-line bg-surface p-3 hover:bg-hover lg:grid-cols-[minmax(7rem,1fr)_minmax(9.5rem,1.1fr)_minmax(6rem,0.9fr)_minmax(11rem,1.5fr)_6.5rem_4rem_auto] lg:items-center lg:gap-x-4 lg:rounded-none lg:border-0 lg:border-b lg:bg-transparent lg:px-3 lg:py-2.5 lg:last:border-b-0">
    {/* The cells are in the order of the columns (the order the keyboard and a screen reader meet them); on a phone the grid puts the code and the actions side by side on the first line. */}
    <div role="cell" className="col-start-1 row-start-1 flex min-w-0 flex-col lg:col-start-auto lg:row-start-auto">
      <span data-testid="watch-symbol" className="font-mono text-body font-semibold text-ink">{symbol}</span>
      {name && <span className="truncate text-caption text-muted-foreground">{name}</span>}
    </div>
    <div role="cell" className="col-span-2 flex flex-col gap-0.5 lg:col-span-1">
      <Label>{t("最新收盘")}</Label>
      {reads.prices.kind === "loading" && <Pending className="h-4 w-24" />}
      {reads.prices.kind === "error" && <CellError what={t("行情读取失败")} onRetry={reads.retryPrices} />}
      {priceReady && (row.price
        ? <span className="flex flex-wrap items-baseline gap-x-2">
          <span data-testid="watch-close" className="font-mono text-body tabular-nums text-ink">{row.price.close.toFixed(2)}</span>
          {row.price.text && <Change direction={row.price.direction} text={row.price.text} className="text-small" />}
        </span>
        : <span className="text-small text-muted-foreground">{t("暂无行情")}</span>)}
    </div>
    <div role="cell" className="col-span-2 lg:col-span-1">
      {reads.prices.kind === "loading" && <Pending className="h-8 w-full" />}
      {priceReady && <Sparkline closes={row.closes} label={`${symbol} ${t("近 3 个月")}`} />}
    </div>
    <div role="cell" className="col-span-2 flex flex-col gap-1 lg:col-span-1">
      <span className="flex items-center gap-1.5 lg:hidden"><StatusBadge kind="opinion">{t("模型意见")}</StatusBadge></span>
      {list === "loading" && <Pending className="h-2.5 w-full" />}
      {list === "error" && <span className="text-small text-muted-foreground">—</span>}
      {list === "ready" && (row.forecast
        ? <ProbabilityBar probabilities={row.forecast.probabilities} status={row.forecast.status} size="mini" focusable={false} />
        : <span className="text-small text-muted-foreground">{t("暂无预测")}</span>)}
    </div>
    <div role="cell" className="col-span-2 flex items-baseline justify-between gap-2 lg:col-span-1 lg:block">
      <Label>{t("目标日")}</Label>
      <span data-testid="watch-target" className="font-mono text-small tabular-nums text-ink-2">{list === "ready" ? row.forecast?.targetDate ?? "—" : "—"}</span>
    </div>
    <div role="cell" className="col-span-2 flex items-baseline justify-between gap-2 lg:col-span-1 lg:block">
      <Label>{t("材料")}</Label>
      {reads.materials.kind === "loading" && <Pending className="h-4 w-8" />}
      {reads.materials.kind === "error" && <CellError what="—" onRetry={reads.retryMaterials} />}
      {reads.materials.kind === "ready" && <span data-testid="watch-materials" className="font-mono text-small tabular-nums text-ink-2">{row.materialTotal ?? "—"}</span>}
    </div>
    <div role="cell" className="col-start-2 row-start-1 flex items-center justify-end gap-1 lg:col-start-auto lg:row-start-auto">
      <Button asChild variant="outline" size="sm" data-row-nav="open">
        <Link to={paths.company(symbol)} aria-label={`${t("打开")} ${symbol}`}>{t("打开")}<ArrowRight aria-hidden="true" /></Link>
      </Button>
      <Button type="button" variant="ghost" size="icon-sm" data-row-nav="remove" aria-label={removeLabel(symbol, locale)} onClick={() => onRemove(symbol)}><X aria-hidden="true" /></Button>
    </div>
  </div>;
}

/** ↑ / ↓ move between the rows' 打开 buttons (and between their 移出 buttons): the table is one stop of the keyboard with a way down it. */
export function rowArrowKeys(event: KeyboardEvent<HTMLElement>) {
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  const here = (event.target as HTMLElement).closest<HTMLElement>("[data-row-nav]");
  if (!here) return;
  const kind = here.dataset.rowNav;
  const all = [...event.currentTarget.querySelectorAll<HTMLElement>(`[data-row-nav="${kind}"]`)];
  const next = all[all.indexOf(here) + (event.key === "ArrowDown" ? 1 : -1)];
  if (next) { event.preventDefault(); next.focus(); }
}
