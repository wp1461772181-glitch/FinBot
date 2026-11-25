import { Checkbox } from "@/components/ui/checkbox";
import type { ApplicationItem } from "../../../api/role-templates";
import { useLocale } from "../../../i18n";

const PARTS: Array<{ part: string; title: string }> = [{ part: "memory", title: "记忆" }, { part: "brief", title: "简报" }, { part: "skill", title: "技能" }, { part: "usual", title: "常用技能" }];

/**
 * What one application wrote, in groups (记忆 / 简报 / 技能 / 常用技能), each with its current text (he may have edited it since).  A thing that is already gone says so.  With `onToggle` every
 * thing still there has a checkbox (the undo dialog); without it the list is only read (the applied list's 看它加了什么).
 */
export function ApplicationRowList({ rows, ticked, onToggle, disabled = false }: { rows: ApplicationItem[]; ticked?: ReadonlySet<string>; onToggle?: (id: string, on: boolean) => void; disabled?: boolean }) {
  const { t } = useLocale();
  const known = new Set(PARTS.map(entry => entry.part));
  const groups = [...PARTS.map(entry => ({ part: entry.part, title: entry.title, rows: rows.filter(row => row.part === entry.part) })), { part: "other", title: "其他", rows: rows.filter(row => !known.has(row.part)) }].filter(group => group.rows.length > 0);
  return <div data-testid="template-application-rows" className="flex min-w-0 flex-col gap-3">
    {groups.map(group => <section key={group.part} data-part={group.part} aria-label={t(group.title)} className="flex min-w-0 flex-col gap-1">
      <h4 className="text-small font-medium text-ink-2">{t(group.title)}<span className="ml-2 font-mono text-caption font-normal text-muted-foreground">{group.rows.length}</span></h4>
      <ul className="m-0 flex list-none flex-col gap-1 p-0">{group.rows.map(row => <li key={row.id} data-testid="template-application-row" data-gone={row.gone ? "true" : undefined} className="min-w-0">
        {onToggle && !row.gone
          ? <label className="flex min-h-11 min-w-0 cursor-pointer items-start gap-2 rounded-sm py-1 text-small text-ink md:min-h-0">
            <Checkbox checked={ticked?.has(row.id) ?? false} disabled={disabled} className="mt-0.5" onCheckedChange={on => onToggle(row.id, on === true)} />
            <span className="min-w-0 [overflow-wrap:anywhere]">{row.text}</span>
          </label>
          : <p className={`m-0 flex min-w-0 items-start gap-2 py-1 text-small ${row.gone ? "text-muted-foreground" : "text-ink"} ${onToggle ? "pl-6" : ""}`}>
            <span className="min-w-0 [overflow-wrap:anywhere]">{row.text}{row.gone && <span data-testid="template-application-gone">{row.text ? " · " : ""}{t("已经不在了")}</span>}</span>
          </p>}
      </li>)}</ul>
    </section>)}
  </div>;
}
