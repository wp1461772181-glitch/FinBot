import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { Bot } from "../../../api/bots";
import { useLocale } from "../../../i18n";
import { CARDS, type LayoutItem } from "../../../workspace-cards.mjs";
import { FilingsCard, ForecastCard, MaterialsCard, PriceCard } from "./market-cards";
import { BriefCard, PortfolioCard, RoutinesCard, WatchlistCard } from "./personal-cards";

/** The cards that follow a stock (the pane's current one, or the one the card is pinned to): only these can be pinned. */
export const PER_STOCK = ["price", "forecast", "materials", "filings"];

/**
 * One card: a titled box with its own read.  The stock it is about is in its title when it follows one.  While the layout is being edited the card shows its title and
 * `controls` instead of its content (so nothing is read for a card that is about to move or go).
 */
export function WorkspaceCard({ item, bot, symbol, wide, editing, controls, onPickSymbol }: {
  item: LayoutItem; bot: Bot; symbol: string; wide: boolean; editing: boolean; controls?: ReactNode; onPickSymbol: (symbol: string) => void;
}) {
  const { t } = useLocale();
  const card = CARDS.find(c => c.id === item.card)!;
  const sym = item.symbol || symbol;
  const size = item.size ?? card.size;
  const body = item.card === "price" ? <PriceCard symbol={sym} wide={wide || item.size === "l"} />
    : item.card === "forecast" ? <ForecastCard symbol={sym} />
    : item.card === "materials" ? <MaterialsCard symbol={sym} />
    : item.card === "filings" ? <FilingsCard symbol={sym} />
    : item.card === "routines" ? <RoutinesCard bot={bot} />
    : item.card === "brief" ? <BriefCard bot={bot} />
    : item.card === "portfolio" ? <PortfolioCard />
    : <WatchlistCard onPick={onPickSymbol} />;
  return <section aria-label={t(card.title)} data-testid="workspace-card" data-card={item.card} data-size={size}
    className={cn("grid min-w-0 content-start gap-2 rounded-md border border-line bg-surface p-3", wide && size === "l" && "col-span-full")}>
    <header className="flex min-w-0 flex-wrap items-center justify-between gap-1.5">
      <h3 className="m-0 text-small font-semibold text-ink">{t(card.title)}{PER_STOCK.includes(item.card) ? <span className="font-normal text-muted-foreground"> · {sym}</span> : null}</h3>
      {controls}
    </header>
    {editing ? null : body}
  </section>;
}
