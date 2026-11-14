import { useEffect, useState, type ReactNode } from "react";
import { useLocale } from "../../i18n";

/** How long a load must take before a skeleton shows (design 4.0): a fast answer never flashes one. */
export const SKELETON_DELAY_MS = 400;

/** True once `active` has stayed true for `delay` ms; false again the moment it goes false. */
export function useDelayedFlag(active: boolean, delay = SKELETON_DELAY_MS): boolean {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (!active) { setShown(false); return; }
    const timer = window.setTimeout(() => setShown(true), delay);
    return () => window.clearTimeout(timer);
  }, [active, delay]);
  return active && shown;
}

/**
 * One block of a skeleton.  The pulse is only for readers who have not asked for less motion; with reduced motion the block is
 * simply there (no flicker).  Plain markup: skeletons are used inside old pages and in the first load.
 */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div data-slot="skeleton" aria-hidden="true" className={`rounded-sm bg-sunken motion-safe:animate-pulse ${className}`} />;
}

/** Wraps a skeleton: the reader's screen reader hears one "正在读取", not a hundred empty blocks. */
function Frame({ variant, className = "", children }: { variant: string; className?: string; children: ReactNode }) {
  const { t } = useLocale();
  return <div data-slot="skeleton-frame" data-variant={variant} role="status" aria-busy="true" className={className}>
    <span className="sr-only">{t("正在读取")}</span>{children}
  </div>;
}

/** A list of lines: the shape of rows that are about to appear. */
export function SkeletonRows({ rows = 5, className = "" }: { rows?: number; className?: string }) {
  return <Frame variant="rows" className={`flex flex-col gap-3 ${className}`}>
    {Array.from({ length: rows }, (_, i) => <div key={i} className="flex items-center gap-3"><Skeleton className="size-8 shrink-0 rounded-full" /><div className="flex flex-1 flex-col gap-1.5"><Skeleton className="h-3.5 w-2/5" /><Skeleton className="h-3 w-4/5" /></div></div>)}
  </Frame>;
}

/** A card: a title line, a few text lines and a footer line. */
export function SkeletonCard({ className = "" }: { className?: string }) {
  return <Frame variant="card" className={`flex flex-col gap-3 rounded-lg border border-line bg-surface p-4 ${className}`}>
    <Skeleton className="h-4 w-1/3" /><Skeleton className="h-3 w-full" /><Skeleton className="h-3 w-11/12" /><Skeleton className="h-3 w-3/5" />
  </Frame>;
}

/** A table: a header line and rows of cells. */
export function SkeletonTable({ rows = 6, cols = 4, className = "" }: { rows?: number; cols?: number; className?: string }) {
  return <Frame variant="table" className={`flex flex-col gap-2 ${className}`}>
    <div className="grid gap-3 border-b border-line pb-2" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>{Array.from({ length: cols }, (_, i) => <Skeleton key={i} className="h-3 w-3/5" />)}</div>
    {Array.from({ length: rows }, (_, r) => <div key={r} className="grid gap-3 py-1" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>{Array.from({ length: cols }, (_, c) => <Skeleton key={c} className={`h-3.5 ${c === 0 ? "w-4/5" : "w-3/5"}`} />)}</div>)}
  </Frame>;
}

/** Three messages of a conversation: the reader's line, then two answers of different length. */
export function SkeletonMessages({ className = "" }: { className?: string }) {
  return <Frame variant="messages" className={`flex flex-col gap-6 ${className}`}>
    <div className="flex justify-end"><Skeleton className="h-9 w-2/5 rounded-lg" /></div>
    <div className="flex flex-col gap-2"><Skeleton className="h-3.5 w-full" /><Skeleton className="h-3.5 w-11/12" /><Skeleton className="h-3.5 w-3/5" /></div>
    <div className="flex justify-end"><Skeleton className="h-9 w-1/3 rounded-lg" /></div>
    <div className="flex flex-col gap-2"><Skeleton className="h-3.5 w-10/12" /><Skeleton className="h-3.5 w-4/5" /></div>
  </Frame>;
}

/**
 * Show `children` (a skeleton) only when `active` has lasted past the delay.  While it has not, nothing shows, so a quick
 * load leaves no flash.  `delay={0}` shows it at once (the sample page's "立即显示").
 */
export function DelayedSkeleton({ active = true, delay = SKELETON_DELAY_MS, children }: { active?: boolean; delay?: number; children: ReactNode }) {
  const shown = useDelayedFlag(active, delay);
  // With no delay the first paint already has it.
  return active && (delay === 0 || shown) ? <>{children}</> : null;
}

/** The skeleton a page of this address gets while its code loads (see skeleton-kind.mjs). */
export function PageSkeleton({ kind }: { kind: "messages" | "table" | "cards" | "rows" }) {
  const pad = "mx-auto w-full max-w-[1280px] p-4 lg:p-6";
  if (kind === "messages") return <div className={`${pad} max-w-3xl`}><SkeletonMessages /></div>;
  if (kind === "table") return <div className={pad}><SkeletonTable rows={8} cols={5} /></div>;
  if (kind === "cards") return <div className={`${pad} grid gap-4 md:grid-cols-2`}><SkeletonCard /><SkeletonCard /><SkeletonCard /><SkeletonCard /></div>;
  return <div className={`${pad} max-w-3xl`}><SkeletonRows rows={6} /></div>;
}
