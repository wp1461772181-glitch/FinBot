import type { ReactNode } from "react";
import { MoveRight } from "lucide-react";
import { Change } from "@/components/StatTile";
import { cn } from "@/lib/utils";
import { formatDate, getLocalePreference, useLocale } from "../../../i18n";
import { formatMoney, pnlTone } from "../../../portfolio-items.mjs";
import type { Load } from "./use-load";

/** A date in the reader's language (the card lists show the day only); the value itself when it is not a date, a dash when there is none. */
export const day = (value: string | null | undefined) => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value.slice(0, 10) : formatDate(date, getLocalePreference(), "UTC");
};

/** The three states every card has: still reading, could not read, nothing to show (the card's content in the last case is the caller's). */
export function Body<T>({ state, empty, children }: { state: Load<T>; empty?: (value: T) => boolean; children: (value: T) => ReactNode }) {
  const { t } = useLocale();
  if (state.kind === "loading") return <p className="text-caption text-muted-foreground" role="status">{t("正在读取…")}</p>;
  if (state.kind === "error") return <p className="text-caption text-muted-foreground">{t("暂时读不到，稍后再试。")}</p>;
  if (empty?.(state.value)) return <p className="text-caption text-muted-foreground">{t("暂无")}</p>;
  return <>{children(state.value)}</>;
}

const LINK_FOCUS = "rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";
/** A link inside a list row: the ink colour, underlined on hover. */
export const ROW_LINK = cn("text-ink hover:underline [overflow-wrap:anywhere]", LINK_FOCUS);

/** The card's way on to a page: a plain link with the arrow icon after it (`external`: another tab). */
export function MoreLink({ href, children, external }: { href: string; children: ReactNode; external?: boolean }) {
  return <a href={href} {...(external ? { target: "_blank", rel: "noreferrer" } : {})}
    className={cn("inline-flex w-fit items-center gap-1 text-small text-action underline-offset-4 hover:underline", LINK_FOCUS)}>{children}<MoveRight aria-hidden="true" className="size-3.5 shrink-0" /></a>;
}

/** A signed money figure: a gain or a loss is the up / down colour with an arrow and the sign; zero or unknown is plain. */
export function Signed({ value }: { value: string | number | null | undefined }) {
  const tone = pnlTone(value), text = formatMoney(value, { signed: true });
  if (tone === "gain") return <Change direction="up" text={text} />;
  if (tone === "loss") return <Change direction="down" text={text} />;
  return <span className="font-mono tabular-nums text-ink-2">{text}</span>;
}

/** A list of short rows (materials, filings, routines, briefs, positions). */
export const LIST = "m-0 grid list-none gap-1 p-0 text-small";
export const ROW = "flex min-w-0 flex-wrap items-baseline gap-x-1.5 gap-y-0.5";
