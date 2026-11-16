import { cn } from "@/lib/utils";

/** A down chevron, drawn here (the same stroke as lucide's ChevronDown): the chat's chunk on the first screen holds lucide's own, and sharing it would pull a new file into the first screen. */
export function Chevron({ className }: { className?: string }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={cn("size-4 shrink-0", className)}><path d="m6 9 6 6 6-6" /></svg>;
}
