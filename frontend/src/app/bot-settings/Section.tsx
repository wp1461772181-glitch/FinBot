import { useId, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useLocale } from "../../i18n";
import type { SectionId } from "../../bot-settings-form.mjs";

/**
 * One section of the settings page.  Wide: a heading and the body, all sections in one column.  Narrow (a phone): the heading is the button that opens
 * the body; a section with an unsaved change carries a dot.  The body stays mounted when folded (the form's state and the sections that fetch keep what
 * they have), only hidden.
 */
export function SettingsSection({ id, title, hint, narrow, open, onOpenChange, unsaved, children }: {
  id: SectionId; title: string; hint?: string; narrow: boolean; open: boolean; onOpenChange: (open: boolean) => void; unsaved: boolean; children: ReactNode;
}) {
  const { t } = useLocale();
  const heading = useId();
  const dot = unsaved && <span data-testid={`unsaved-${id}`} role="img" aria-label={t("有未保存的修改")} className="size-2 shrink-0 rounded-full bg-brand" />;
  if (!narrow) {
    return <section id={`section-${id}`} data-section={id} aria-labelledby={heading} className="scroll-mt-6 border-b border-line py-6 first:pt-0 last:border-b-0">
      <header className="mb-4 flex items-center gap-2"><h2 id={heading} className="text-title-s text-ink">{title}</h2>{dot}</header>
      {hint && <p className="-mt-2 mb-4 text-small text-muted-foreground">{hint}</p>}
      <div className="grid gap-5">{children}</div>
    </section>;
  }
  const body = `${heading}-body`;
  // Radix's Collapsible does not keep a folded body mounted (forceMount shows it), so the fold is the plain `hidden` attribute on a button-controlled region.
  return <section id={`section-${id}`} data-section={id} data-open={open} aria-labelledby={heading} className="scroll-mt-4 border-b border-line last:border-b-0">
    <h2 id={heading} className="m-0 text-title-s text-ink">
      <button type="button" data-testid={`section-toggle-${id}`} aria-expanded={open} aria-controls={body} onClick={() => onOpenChange(!open)}
        className="flex min-h-12 w-full items-center gap-2 rounded-sm text-left outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <span className="min-w-0 flex-1">{title}</span>{dot}
        <ChevronDown aria-hidden="true" className={cn("size-4 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none", open && "rotate-180")} />
      </button>
    </h2>
    <div id={body} hidden={!open} className="pb-5">
      {hint && <p className="mb-3 text-small text-muted-foreground">{hint}</p>}
      <div className="grid gap-5">{children}</div>
    </div>
  </section>;
}
