import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export type DetailTabSpec<T extends string> = { id: T; label: ReactNode; testid: string };

/**
 * The material's three tabs (a tab list that follows the ARIA pattern: one tab in the Tab order, the arrows, Home and End move and pick).  It is written here and
 * not taken from the shared Tabs part because that part is a file of the first screen, and a second user in a lazy chunk would make it a file of its own there.
 */
export function DetailTabs<T extends string>({ tabs, value, onChange, label, panelId }: { tabs: DetailTabSpec<T>[]; value: T; onChange: (id: T) => void; label: string; panelId: string }) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const move = (event: KeyboardEvent, index: number) => {
    const last = tabs.length - 1;
    const next = event.key === "ArrowRight" ? (index === last ? 0 : index + 1) : event.key === "ArrowLeft" ? (index === 0 ? last : index - 1) : event.key === "Home" ? 0 : event.key === "End" ? last : null;
    if (next === null) return;
    event.preventDefault();
    onChange(tabs[next].id);
    refs.current[tabs[next].id]?.focus();
  };
  return <div role="tablist" aria-label={label} data-slot="detail-tabs" className="inline-flex h-9 w-full items-center justify-start rounded-lg bg-muted p-[3px] text-muted-foreground">
    {tabs.map((tab, index) => {
      const active = tab.id === value;
      return <button key={tab.id} ref={element => { refs.current[tab.id] = element; }} type="button" role="tab" id={`material-tab-${tab.id}`} data-testid={tab.testid} data-state={active ? "active" : "inactive"} aria-selected={active} aria-controls={panelId}
        tabIndex={active ? 0 : -1} onClick={() => onChange(tab.id)} onKeyDown={event => move(event, index)}
        className={cn("inline-flex h-[calc(100%-1px)] flex-1 items-center justify-center rounded-md border border-transparent px-2 py-1 text-sm font-medium whitespace-nowrap outline-none transition-colors hover:text-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 max-sm:min-h-11",
          active ? "bg-background text-foreground shadow-sm dark:border-input dark:bg-input/30" : "text-foreground/60 dark:text-muted-foreground")}>{tab.label}</button>;
    })}
  </div>;
}
