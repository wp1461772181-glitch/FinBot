import type { ReactNode } from "react";
import { Link } from "react-router";
import { useLocale } from "../../i18n";
import { paths } from "../../routes.mjs";
import { SETTINGS_ITEMS } from "../../shell-nav.mjs";
import { cn } from "@/lib/utils";

export type SettingsSection = "models" | "notifications" | "appearance" | "data" | "account";

/**
 * The settings area (design 4.12): a list of the five sub pages on the left, the page on the right.  Below 1024 the same list is a row of links above the page that scrolls sideways
 * (one node in both shapes, so nothing is mounted twice).  The sidebar's own 设置 group highlights the same page; this list is the page's way between them.
 */
export function SettingsLayout({ section, children }: { section: SettingsSection; children: ReactNode }) {
  const { t } = useLocale();
  const items = SETTINGS_ITEMS as ReadonlyArray<{ id: SettingsSection; label: string }>;
  const title = items.find((item) => item.id === section)?.label ?? "模型";
  return <main data-testid="settings-page" data-section={section} aria-labelledby="settings-title" className="mx-auto flex w-full min-w-0 max-w-[1100px] flex-1 flex-col gap-4 p-4 lg:flex-row lg:gap-8 lg:p-6">
    <nav data-testid="settings-subnav" aria-label={t("设置")} className="-mx-4 shrink-0 overflow-x-auto px-4 lg:mx-0 lg:w-44 lg:overflow-visible lg:px-0">
      <ul className="m-0 flex list-none gap-1 p-0 lg:sticky lg:top-6 lg:flex-col">
        {items.map((item) => {
          const current = item.id === section;
          return <li key={item.id} className="shrink-0">
            <Link to={paths.settings(item.id)} data-testid={`settings-nav-${item.id}`} aria-current={current ? "page" : undefined}
              className={cn("flex min-h-9 items-center rounded-sm px-3 py-1.5 text-small whitespace-nowrap outline-none focus-visible:ring-2 focus-visible:ring-ring max-lg:min-h-11",
                current ? "bg-brand-soft font-medium text-ink" : "text-ink-2 hover:bg-sunken")}>{t(item.label)}</Link>
          </li>;
        })}
      </ul>
    </nav>
    <div data-testid={`settings-${section}`} className="flex min-w-0 flex-1 flex-col gap-5">
      <h1 id="settings-title" className="text-title-m text-ink">{t(title)}</h1>
      {children}
    </div>
  </main>;
}
