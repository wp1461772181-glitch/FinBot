import type { ReactNode } from "react";
import { CircleCheck, CircleX, Hourglass, LoaderCircle, MessageSquareText } from "lucide-react";
import { badgeKind, type BadgeKind } from "../data-display.mjs";
import { cn } from "@/lib/utils";

// Each kind has its own icon and its own colours, nothing else varies: four tones (neutral, in progress, success, failure) and the two
// material colours (the model's opinion, an action that waits for you).  The tones that have no soft token keep the icon coloured and the words in ink.
// The neutral badge's icon is a plain ring drawn in CSS (a lucide Circle would be shared with the chat and pulled into the first screen's chunk).
const KINDS: Record<BadgeKind, { icon: typeof CircleCheck | null; box: string; icon_: string; spin?: boolean }> = {
  neutral: { icon: null, box: "border-line bg-sunken text-ink-2", icon_: "text-muted-foreground" },
  progress: { icon: LoaderCircle, box: "border-transparent bg-brand-soft text-brand", icon_: "text-brand", spin: true },
  success: { icon: CircleCheck, box: "border-line bg-surface text-ink-2", icon_: "text-success" },
  failure: { icon: CircleX, box: "border-line bg-surface text-ink-2", icon_: "text-danger" },
  opinion: { icon: MessageSquareText, box: "border-transparent bg-opinion-soft text-opinion", icon_: "text-opinion" },
  action: { icon: Hourglass, box: "border-transparent bg-action-soft text-action", icon_: "text-action" },
};

/**
 * A status as a small badge (design 5.3, replacing the one-colour pill): a fixed icon and a fixed colour per kind, then the words.  The kind is
 * one of neutral, progress, success, failure, opinion, action; anything else is neutral.  The icon is decoration; the words are the status.
 */
export function StatusBadge({ kind, children, className }: { kind: BadgeKind | string; children: ReactNode; className?: string }) {
  const resolved = badgeKind(kind);
  const spec = KINDS[resolved];
  const Icon = spec.icon;
  return <span data-slot="status-badge" data-kind={resolved} className={cn("inline-flex h-6 items-center gap-1 whitespace-nowrap rounded-full border px-2 text-caption", spec.box, className)}>
    {Icon
      ? <Icon aria-hidden="true" className={cn("size-3.5 shrink-0", spec.icon_, spec.spin && "motion-safe:animate-spin")} />
      : <span aria-hidden="true" className={cn("m-[3px] size-2 shrink-0 rounded-full border-[1.5px] border-current", spec.icon_)} />}
    {children}
  </span>;
}
