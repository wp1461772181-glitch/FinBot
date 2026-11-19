import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** One block of a settings page: a surface with a heading, an optional line of explanation, then the content. */
export function SettingsCard({ id, title, description, actions, testid, className, children }: { id: string; title: ReactNode; description?: ReactNode; actions?: ReactNode; testid?: string; className?: string; children: ReactNode }) {
  return <section aria-labelledby={`${id}-title`} data-testid={testid} className={cn("flex min-w-0 flex-col gap-4 rounded-md border border-line bg-surface p-4 lg:p-5", className)}>
    <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <h2 id={`${id}-title`} className="text-title-s text-ink">{title}</h2>
        {description && <p className="max-w-2xl text-small text-muted-foreground">{description}</p>}
      </div>
      {actions}
    </header>
    {children}
  </section>;
}
