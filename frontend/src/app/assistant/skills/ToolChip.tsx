import { PencilLine } from "lucide-react";
import { cn } from "@/lib/utils";
import { toolLabel } from "../../../agent-tool-labels.mjs";
import { useLocale } from "../../../i18n";

/**
 * One tool a skill may use, as a small chip.  A tool that changes something (it can be undone, costs a lot, or writes) carries a pen and the words 写操作 (never colour alone):
 * a skill that uses it still needs the confirmation card.
 */
export function ToolChip({ name, write }: { name: string; write: boolean }) {
  const { t } = useLocale();
  return <li data-testid="skill-tool" data-tool={name} data-write={write ? "true" : "false"}
    className={cn("inline-flex h-6 items-center gap-1 rounded-sm border px-1.5 text-caption", write ? "border-action/40 bg-action-soft text-action" : "border-line bg-sunken text-ink-2")}>
    {write && <PencilLine aria-hidden="true" className="size-3.5 shrink-0" />}
    <span>{t(toolLabel(name))}</span>
    {write && <span className="font-medium">{t("写操作")}</span>}
  </li>;
}

/** The chips of a list of tools; `levels` says which of them write (by name). */
export function ToolChips({ names, writes, label }: { names: string[]; writes: ReadonlySet<string>; label: string }) {
  return <ul aria-label={label} data-testid="skill-tools" className="m-0 flex list-none flex-wrap gap-1.5 p-0">{names.map(name => <ToolChip key={name} name={name} write={writes.has(name)} />)}</ul>;
}
