import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";

/** What stands in for a settings sub page while its chunk arrives (after 400 ms; a quick load shows nothing). */
export function SettingsSkeleton() {
  return <DelayedSkeleton><div data-testid="settings-skeleton" className="flex flex-col gap-3" aria-hidden="true">{[0, 1].map((i) => <Skeleton key={i} className="h-40 w-full" />)}</div></DelayedSkeleton>;
}
