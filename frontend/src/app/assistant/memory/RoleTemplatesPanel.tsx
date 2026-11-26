import { useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import { getRoleTemplates, type ApplyResult, type RoleTemplate, type RoleTemplateApplication, type UndoResult } from "../../../api/role-templates";
import { useLocale } from "../../../i18n";
import { applicationGroups, applicationLine, applicationRows, countsLine, removedLine, stillThereLine, templateLabel } from "../../../role-templates.mjs";
import { useLoad } from "../../use-load";
import { ApplicationRowList } from "./ApplicationRows";
import { RoleTemplateDialog } from "./RoleTemplateDialog";
import { UndoDialog } from "./UndoDialog";

type Open = { kind: "preview"; id: string } | { kind: "undo"; id: string } | null;

/** One applied template: where and when, what of it is still there, 看它加了什么 (read-only, current texts) and, while it is in use, 撤掉. */
function ApplicationCard({ application, onUndo }: { application: RoleTemplateApplication; onUndo?: (from: HTMLElement) => void }) {
  const { t, locale } = useLocale();
  const [open, setOpen] = useState(false);
  const rows = applicationRows(application);
  return <li data-testid="template-application" data-id={application.id} data-undone={application.undone_at ? "true" : undefined} className="flex min-w-0 flex-col gap-1 rounded-md border border-line bg-surface p-3">
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
      <span data-testid="template-application-line" className="min-w-0 text-body text-ink [overflow-wrap:anywhere]">{applicationLine(application, locale) as string}</span>
      <span className="ml-auto" />
      {onUndo && <Button type="button" size="sm" variant="ghost" data-testid="template-undo" aria-label={`${t("撤掉")} · ${templateLabel(application.label, locale) as string}`} className="text-danger max-md:h-11" onClick={event => onUndo(event.currentTarget)}>{t("撤掉")}</Button>}
    </div>
    {!application.undone_at && <p data-testid="template-application-still" className="m-0 text-small text-muted-foreground">{stillThereLine(application, locale) as string}</p>}
    {rows.length > 0 && <Collapsible open={open} onOpenChange={setOpen} data-testid="template-application-fold" className="pt-1">
      <CollapsibleTrigger data-testid="template-application-toggle" className="group/fold flex min-h-11 items-center gap-1.5 rounded-sm text-small text-ink-2 outline-none focus-visible:ring-2 focus-visible:ring-ring md:min-h-0">
        <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]/fold:rotate-90 motion-reduce:transition-none" />{t("看它加了什么")}
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-2"><ApplicationRowList rows={rows} /></CollapsibleContent>
    </Collapsible>}
  </li>;
}

/**
 * 用模板起步 (4f, the 它眼中的你 tab, after the summary head): three starting setups (短线, 定投, 基金经理) as cards, each opening the preview dialog (everything it would write, in full, ticked;
 * nothing is written until he presses 应用).  Below, what he has applied: 「在用：短线 · 11月26日 · 全局」 with what is still there, 看它加了什么 and 撤掉.  A template is only
 * starting memory and settings; what it writes is ordinary memory, tasks and skills.  `onChanged` is told after an apply or an undo so the page re-reads what it shows (the profile, the counts).
 */
export function RoleTemplatesPanel({ onChanged }: { onChanged: () => void }) {
  const { t, locale } = useLocale();
  const data = useLoad(signal => getRoleTemplates(signal));
  const [open, setOpen] = useState<Open>(null);
  const [undone, setUndone] = useState("");
  const trigger = useRef<HTMLElement | null>(null);
  const templates: RoleTemplate[] = data.data?.templates ?? [];
  const applications = data.data?.applications ?? [];
  const groups = applicationGroups(applications) as { live: RoleTemplateApplication[]; undone: RoleTemplateApplication[] };
  const chosen = open?.kind === "preview" ? templates.find(one => one.id === open.id) : undefined;
  const undoing = open?.kind === "undo" ? applications.find(one => one.id === open.id) : undefined;
  const close = () => setOpen(null);
  const restoreFocus = () => trigger.current?.focus();

  const applied = async (_result: ApplyResult) => { setUndone(""); onChanged(); await data.reload(); };
  const undid = async (result: UndoResult) => {
    setUndone(removedLine(result, locale) as string);
    close(); onChanged(); await data.reload();
  };

  return <section data-testid="role-templates" aria-labelledby="role-templates-title" className="flex min-w-0 flex-col gap-2">
    <h2 id="role-templates-title" className="text-title-s text-ink">{t("用模板起步")}</h2>
    <p data-testid="role-templates-note" className="m-0 max-w-3xl text-small text-ink-2">{t("选一套起步设置，先看它会写什么，勾掉不想要的，再应用。写进去的只是普通的记忆、简报和技能，之后都能在原来的地方改或删，也可以整套撤掉。")}</p>
    {data.error != null && <ErrorBar error={data.error} onRetry={() => void data.reload()} retrying={data.loading} />}
    {!data.data && data.error == null && data.loading && <DelayedSkeleton><div role="status" aria-busy="true" className="grid gap-2 md:grid-cols-3"><span className="sr-only">{t("正在读取")}</span>{[0, 1, 2].map(i => <Skeleton key={i} className="h-32 w-full" />)}</div></DelayedSkeleton>}
    {data.data && templates.length === 0 && <div data-testid="role-templates-empty" className="rounded-md border border-line bg-surface"><EmptyState title={t("现在没有可用的模板。")} /></div>}
    {templates.length > 0 && <ul className="m-0 grid list-none gap-2 p-0 md:grid-cols-3">{templates.map(template => <li key={template.id} data-testid="role-template" data-template={template.id} className="flex min-w-0 flex-col gap-2 rounded-md border border-line bg-surface p-3">
      <h3 className="text-body font-medium text-ink">{templateLabel(template.label, locale) as string}</h3>
      <p className="m-0 text-small text-ink-2 [overflow-wrap:anywhere]">{t(template.blurb)}</p>
      <p data-testid="role-template-counts" className="m-0 font-mono text-caption text-muted-foreground">{countsLine(template, locale) as string}</p>
      <span className="flex-1" />
      <Button type="button" size="sm" variant="outline" data-testid="role-template-open" aria-label={`${t("看看会加什么")} · ${templateLabel(template.label, locale) as string}`} className="self-start max-md:h-11"
        onClick={event => { trigger.current = event.currentTarget; setOpen({ kind: "preview", id: template.id }); }}>{t("看看会加什么")}</Button>
    </li>)}</ul>}

    {undone && <p data-testid="template-undone-line" role="status" className="m-0 text-small text-ink-2">{undone}</p>}
    {groups.live.length > 0 && <div data-testid="template-applications" className="mt-2 flex min-w-0 flex-col gap-2">
      <h3 className="text-small font-medium text-ink-2">{t("已用的模板")}<span className="ml-2 font-mono text-caption font-normal text-muted-foreground">{groups.live.length}</span></h3>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">{groups.live.map(application => <ApplicationCard key={application.id} application={application} onUndo={from => { trigger.current = from; setUndone(""); setOpen({ kind: "undo", id: application.id }); }} />)}</ul>
    </div>}
    {groups.undone.length > 0 && <Collapsible data-testid="template-applications-undone" className="border-t border-line pt-1">
      <CollapsibleTrigger data-testid="template-applications-undone-toggle" className="group/fold flex min-h-11 items-center gap-1.5 rounded-sm text-small text-ink-2 outline-none focus-visible:ring-2 focus-visible:ring-ring md:min-h-0">
        <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]/fold:rotate-90 motion-reduce:transition-none" />{t("已撤掉的")}<span className="font-mono text-caption text-muted-foreground">· {groups.undone.length}</span>
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-2"><ul className="m-0 flex list-none flex-col gap-2 p-0">{groups.undone.map(application => <ApplicationCard key={application.id} application={application} />)}</ul></CollapsibleContent>
    </Collapsible>}

    {chosen && <RoleTemplateDialog template={chosen} onClose={close} onApplied={applied} returnFocus={restoreFocus} />}
    {undoing && <UndoDialog application={undoing} onClose={close} onDone={undid} returnFocus={restoreFocus} />}
  </section>;
}
