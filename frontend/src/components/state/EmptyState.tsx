import type { ReactNode } from "react";
import { Link } from "react-router";

/**
 * An empty place (design 4.0, 空): one sentence on what will appear here and one main action.  No illustration.
 * The action is a button (`onClick`) or a link (`to`); leave both out when there is nothing to do.
 */
export function EmptyState({ title, description, action, className = "", children }: {
  title: string;
  description?: string;
  action?: { label: string; onClick?: () => void; to?: string };
  className?: string;
  children?: ReactNode;
}) {
  const button = "inline-flex h-9 items-center rounded-sm bg-primary px-4 text-small font-medium text-primary-foreground outline-none hover:bg-primary/90 focus-visible:ring-[3px] focus-visible:ring-ring/50";
  return <section data-slot="empty-state" className={`mx-auto flex w-full max-w-md flex-col items-center gap-2 px-4 py-10 text-center text-small ${className}`}>
    <h3 className="text-body font-medium text-ink">{title}</h3>
    {description && <p className="text-small text-muted-foreground">{description}</p>}
    {children}
    {action && (action.to
      ? <Link to={action.to} className={`${button} mt-2`}>{action.label}</Link>
      : <button type="button" onClick={action.onClick} className={`${button} mt-2`}>{action.label}</button>)}
  </section>;
}
