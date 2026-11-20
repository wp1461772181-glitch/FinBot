import { Suspense, lazy } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { Star } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/state/EmptyState";
import { SkeletonCard } from "@/components/state/Skeleton";
import { confirm } from "@/components/state/confirm";
import { notify } from "@/components/state/notify";
import { Change } from "@/components/StatTile";
import { getV2Prices } from "../../api/prices";
import { companyName } from "../../company-page.mjs";
import { checkWatchAdd } from "../../watchlist-add.mjs";
import { restoreAt } from "../../watchlist-rows.mjs";
import { priceChange } from "../../data-display.mjs";
import { useLocale, colon } from "../../i18n";
import { companyTab, paths, type CompanyTab } from "../../routes.mjs";
import { useWorkspace } from "../workspace";
import { AskBotMenu } from "./AskBotMenu";
import { CompanyOverview } from "./CompanyOverview";
import { CompanyTabs } from "./CompanyTabs";
import { removeTitle } from "./support";
import { useRead } from "./use-read";

// The two pages the tabs embed are chunks of their own, fetched when the tab is opened.
const ForecastsTab = lazy(() => import("./EmbeddedTabs").then(m => ({ default: m.ForecastsTab })));
const MaterialsTab = lazy(() => import("./EmbeddedTabs").then(m => ({ default: m.MaterialsTab })));

/** The page of a code that is not a ticker: nothing to read, the way back to the watchlist. */
export function CompanyUnknown({ raw }: { raw: string }) {
  const { t, locale } = useLocale();
  const quoted = raw ? (locale === "en-US" ? `“${raw.slice(0, 24)}” ` : `「${raw.slice(0, 24)}」`) : "";
  return <main data-testid="company-unknown" className="mx-auto flex w-full max-w-[1120px] flex-1 flex-col p-4 lg:p-6">
    <EmptyState title={t("找不到这个公司代码")} description={`${quoted}${t("不是有效的美股代码。代码是 1 到 5 个字母，例如 AMD 或 BRK.B。")}`} action={{ label: t("返回自选"), to: paths.research() }} />
  </main>;
}

/**
 * 公司页 (#/research/c/:symbol, ?tab=overview|forecasts|materials; design 4.5): the title row (code, name, last close and change, 问 bot, ★), then the tabs.  The
 * company is in the address, so a reload, a link and the back button all land on the same company and tab.  A company that is not in the watchlist can be read; its
 * title row offers 加入自选.
 */
export function CompanyPage({ symbol }: { symbol: string }) {
  const { t, locale } = useLocale();
  const ws = useWorkspace();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const tab = companyTab(params);
  const [prices, reloadPrices] = useRead(`prices:${symbol}`, signal => getV2Prices(symbol, signal));
  const listed = ws.symbols.includes(symbol);
  const change = prices.kind === "ready" ? priceChange(prices.value.price_history.candles) : null;
  const name = companyName(symbol, ws.bots.bots);

  const toggleListed = async () => {
    if (!listed) {
      const added = checkWatchAdd(symbol, ws.symbols);
      if (added.ok) { ws.setSymbols(items => [...items, added.ticker]); notify.success(`${t("已加入自选")}${colon()}${symbol}`, { id: `watch-add:${symbol}` }); }
      else notify.error(t(added.error), { id: `watch-add:${symbol}` });
      return;
    }
    const index = ws.symbols.indexOf(symbol);
    const ok = await confirm({
      title: removeTitle(symbol, locale), description: t("它不再出现在自选和研究队列里；已有的预测和材料不会删除，可以随时再加回来。"),
      confirmLabel: t("移出"), cancelLabel: t("取消"), tone: "danger",
    });
    if (!ok) return;
    ws.removeWatchSymbol(symbol, { stay: true });
    notify.success(`${t("已移出自选")}${colon()}${symbol}`, { id: `watch-remove:${symbol}`, undo: { label: t("撤销"), onClick: () => ws.setSymbols(items => restoreAt(items, symbol, index)) } });
  };

  return <main data-testid="company-page" data-symbol={symbol} aria-labelledby="company-title" className="mx-auto flex w-full max-w-[1280px] flex-1 flex-col gap-4 p-4 lg:p-6">
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 id="company-title" data-testid="company-title" className="font-mono text-title-l text-ink">{symbol}</h1>
        {name && <span data-testid="company-name" className="text-body text-muted-foreground">{name}</span>}
        {change && <>
          <span data-testid="company-price" className="font-mono text-title-l tabular-nums text-ink">{change.close.toFixed(2)}</span>
          {change.text && <Change direction={change.direction} text={change.text} className="text-body" />}
        </>}
      </div>
      <div className="ml-auto flex items-center gap-2">
        {ws.personal && <AskBotMenu symbol={symbol} bots={ws.bots.bots} />}
        <Button type="button" variant={listed ? "secondary" : "outline"} data-testid="watch-toggle" data-listed={listed ? "true" : "false"} onClick={() => void toggleListed()}>
          <Star aria-hidden="true" className={listed ? "fill-current" : undefined} />{listed ? t("已在自选") : t("加入自选")}
        </Button>
      </div>
    </header>
    <CompanyTabs label={t("公司页签")} value={tab as CompanyTab} onChange={value => navigate(paths.company(symbol, value))}
      tabs={[{ value: "overview", label: t("概览"), testId: "tab-overview" }, { value: "forecasts", label: t("预测"), testId: "tab-forecasts" }, { value: "materials", label: t("材料"), testId: "tab-materials" }]}>
      {tab === "overview" && <CompanyOverview symbol={symbol} prices={prices} reloadPrices={reloadPrices} />}
      {tab === "forecasts" && <Suspense fallback={<SkeletonCard />}><ForecastsTab symbol={symbol} /></Suspense>}
      {tab === "materials" && <Suspense fallback={<SkeletonCard />}><MaterialsTab symbol={symbol} /></Suspense>}
    </CompanyTabs>
  </main>;
}

