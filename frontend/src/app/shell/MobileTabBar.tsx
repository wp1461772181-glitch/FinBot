import { Link } from "react-router";
import { Suspense, lazy, useEffect, useRef, useState, type ComponentType } from "react";
import { CalendarClock, ChartLine, Ellipsis, MessageSquare, Wallet } from "lucide-react";
import { useLocale } from "../../i18n";
import { activeArea, areaPath, type Area } from "../../shell-nav.mjs";
import type { ShellNavProps } from "./AppSidebar";

const MoreDrawer = lazy(() => import("./MoreDrawer"));

type Tab = { area: Exclude<Area, "assistant" | "settings">; label: string; icon: ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" }> };
const TABS: Tab[] = [
  { area: "chat", label: "对话", icon: MessageSquare },
  { area: "research", label: "研究", icon: ChartLine },
  { area: "portfolio", label: "持仓", icon: Wallet },
  { area: "routines", label: "任务", icon: CalendarClock },
];

/**
 * The phone's navigation (design 3.1): 对话 | 研究 | 持仓 | 任务 | 更多.  Every target is at least 44x44 and the bar leaves
 * room for the home indicator (safe-area inset).  任务 carries the same to-do number as the sidebar.  「更多」 opens the
 * drawer with the bots, the assistant and settings pages and the account; it is fetched the first time it is asked for.
 */
export function MobileTabBar({ props }: { props: ShellNavProps }) {
  const { t } = useLocale();
  const area = activeArea(props.path);
  const [moreOpen, setMoreOpen] = useState(false);
  const [moreLoaded, setMoreLoaded] = useState(false);
  const moreButton = useRef<HTMLButtonElement>(null);
  // The drawer closes when the reader goes somewhere (a link inside it was pressed) and hands focus back to its button.
  useEffect(() => { setMoreOpen(false); }, [props.path]);
  const more = area === "assistant" || area === "settings";
  const item = "relative flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 px-1 text-caption text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring aria-[current=page]:text-brand";
  return <>
    <nav aria-label={t("主要导航")} data-slot="mobile-tab-bar" className="fixed inset-x-0 bottom-0 z-sidebar flex border-t border-line bg-background pb-[env(safe-area-inset-bottom)]">
      {TABS.map(tab => {
        const current = area === tab.area;
        const badge = tab.area === "routines" ? props.routinesCount : 0;
        const label = t(tab.label);
        return <Link key={tab.area} to={areaPath(tab.area, props.symbol)} aria-current={current ? "page" : undefined} aria-label={badge > 0 ? `${label}，${badge} ${t("条待确认")}` : label} className={item}>
          <span className="relative"><tab.icon aria-hidden="true" className="size-5" />
            {badge > 0 && <span aria-hidden="true" data-count="" className="absolute -top-1.5 left-3 grid min-w-4 place-items-center rounded-full bg-brand px-1 text-caption leading-4 text-primary-foreground">{badge > 99 ? "99+" : badge}</span>}
          </span>
          <span>{label}</span>
        </Link>;
      })}
      <button ref={moreButton} data-more-trigger="" type="button" aria-haspopup="dialog" aria-expanded={moreOpen} aria-current={more && !moreOpen ? "page" : undefined} className={item} onClick={() => { setMoreLoaded(true); setMoreOpen(true); }}>
        <Ellipsis aria-hidden="true" className="size-5" /><span>{t("更多")}</span>
      </button>
    </nav>
    {moreLoaded && <Suspense fallback={null}><MoreDrawer open={moreOpen} onOpenChange={next => { setMoreOpen(next); if (!next) window.requestAnimationFrame(() => moreButton.current?.focus()); }} props={props} /></Suspense>}
  </>;
}
