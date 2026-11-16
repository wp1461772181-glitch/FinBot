import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export type TabSpec<T extends string> = { value: T; label: string; testId: string };

/**
 * The company page's tab list (overview | forecasts | materials): a WAI-ARIA tab list with manual activation, so the arrow keys only move the focus
 * (one history entry per tab actually opened, not per arrow) and Enter or Space opens the one in focus.  Written here instead of using the shared Radix
 * Tabs: the chat's side panel uses those, and a second page using them would move them out of the chat's own chunk and into the first screen's.
 */
export function CompanyTabs<T extends string>({ tabs, value, onChange, label, children }: {
  tabs: TabSpec<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
  /** The panel of the selected tab. */
  children: ReactNode;
}) {
  const list = useRef<HTMLDivElement>(null);
  const idOf = (tab: string) => `company-tab-${tab}`;
  const move = (event: KeyboardEvent<HTMLDivElement>) => {
    const keys: Record<string, (index: number, count: number) => number> = {
      ArrowRight: (index, count) => (index + 1) % count, ArrowLeft: (index, count) => (index - 1 + count) % count, Home: () => 0, End: (_, count) => count - 1,
    };
    const next = keys[event.key];
    if (!next) return;
    const buttons = [...(list.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]') ?? [])];
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (index < 0) return;
    event.preventDefault();
    buttons[next(index, buttons.length)]?.focus();
  };
  return <div className="flex flex-col gap-4">
    <div ref={list} role="tablist" aria-label={label} onKeyDown={move} className="flex gap-1 border-b border-line">
      {tabs.map(tab => <button key={tab.value} type="button" role="tab" id={idOf(tab.value)} data-testid={tab.testId} aria-selected={tab.value === value} aria-controls="company-tab-panel"
        tabIndex={tab.value === value ? 0 : -1} onClick={() => onChange(tab.value)}
        className={cn("-mb-px border-b-2 px-4 py-2 text-body outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
          tab.value === value ? "border-brand font-medium text-ink" : "border-transparent text-muted-foreground hover:text-ink")}>{tab.label}</button>)}
    </div>
    <div role="tabpanel" id="company-tab-panel" aria-labelledby={idOf(value)} tabIndex={-1} className="outline-none">{children}</div>
  </div>;
}
