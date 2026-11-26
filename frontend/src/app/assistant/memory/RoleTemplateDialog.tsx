import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorBar } from "@/components/state/ErrorBar";
import { StatefulButton } from "@/components/state/StatefulButton";
import { listBots, type Bot } from "../../../api/bots";
import { applyRoleTemplate, previewRoleTemplate, type ApplyResult, type RoleTemplate, type TemplatePreview } from "../../../api/role-templates";
import { useLocale } from "../../../i18n";
import { allTicked, anyTicked, applyBody, createdLine, leaveOutOf, previewMarks, resultLines, skillWarnings, templateKeys, templateLabel, usualRows, whenText } from "../../../role-templates.mjs";
import { useLoad } from "../../use-load";
import { KIND_LABELS } from "./memory-view.mjs";

const GLOBAL = "__global__"; // Radix Select has no empty item value
type Marks = ReturnType<typeof previewMarks>;

/** What the preview found for one key: nothing (it is written), 「已有，沿用」, or the reason it is not written. */
function Mark({ marks, id }: { marks: Marks; id: string }) {
  const { t } = useLocale();
  const mark = marks.get(id);
  if (!mark) return null;
  const head = mark.kind === "reuse" ? t("已有，沿用") : t("不会写");
  return <span data-testid="template-mark" data-mark={mark.kind} className="text-caption text-muted-foreground [overflow-wrap:anywhere]">{head}{mark.reason && t(mark.reason) !== head && ` · ${t(mark.reason)}`}</span>;
}

function Group({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  return <section aria-label={title} data-testid="template-group" className="flex min-w-0 flex-col gap-1.5">
    <h3 className="text-small font-medium text-ink-2">{title}<span className="ml-2 font-mono text-caption font-normal text-muted-foreground">{count}</span></h3>
    {children}
  </section>;
}

/** One ticked-or-not row: a checkbox, the full text, what the preview says about it. */
function Row({ id, ticked, onToggle, disabled, children, marks, testId }: { id: string; ticked: boolean; onToggle: (key: string, on: boolean) => void; disabled: boolean; children: ReactNode; marks: Marks; testId: string }) {
  return <li data-testid={testId} data-key={id} className="min-w-0 rounded-md border border-line bg-surface p-2.5">
    <label className="flex min-h-11 min-w-0 cursor-pointer items-start gap-2.5 md:min-h-0">
      <Checkbox checked={ticked} disabled={disabled} className="mt-1" onCheckedChange={on => onToggle(id, on === true)} />
      <span className="flex min-w-0 flex-1 flex-col gap-1">{children}<Mark marks={marks} id={id} /></span>
    </label>
  </li>;
}

/**
 * 看看会加什么 (4f): the template's every part with its full text, each ticked (briefs too; untick what he does not want), a target (全局 + 助理, or one of his bots), the server's notes,
 * and what the preview found (已有，沿用 / why a part will not be written).  The preview is read again whenever the target or a tick changes and 应用 waits for it; the preview writes
 * nothing.  After 应用 the dialog tells what was written, reused and left out.  What is written is ordinary memory, tasks and skills on their usual pages.
 */
export function RoleTemplateDialog({ template, onClose, onApplied, returnFocus }: { template: RoleTemplate; onClose: () => void; onApplied: (result: ApplyResult) => void | Promise<void>; returnFocus: () => void }) {
  const { t, locale } = useLocale();
  const bots = useLoad(signal => listBots(signal));
  const [botId, setBotId] = useState<string | null>(null);
  const [ticked, setTicked] = useState<Set<string>>(() => allTicked(template));
  const [preview, setPreview] = useState<{ signature: string; value: TemplatePreview } | null>(null);
  const [previewFailure, setPreviewFailure] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [result, setResult] = useState<ApplyResult | null>(null);
  const label = templateLabel(template.label, locale);
  const keys = useMemo(() => templateKeys(template), [template]);
  const leaveOut = leaveOutOf(template, ticked);
  const signature = JSON.stringify([botId, leaveOut]);
  const latestSignature = useRef(signature);
  latestSignature.current = signature;
  const choices = (bots.data?.bots ?? []).filter((bot: Bot) => !bot.is_default);

  // The preview follows the target and the ticks (a short pause so ticking several rows is one read); it writes nothing.
  useEffect(() => {
    if (result) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      previewRoleTemplate(template.id, applyBody(botId, leaveOut), controller.signal)
        .then(value => { if (!controller.signal.aborted) { setPreview({ signature, value }); setPreviewFailure(null); } })
        .catch(error => { if (!controller.signal.aborted) setPreviewFailure(error); });
    }, 200);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [signature, template.id, result]); // eslint-disable-line react-hooks/exhaustive-deps

  const fresh = preview !== null && preview.signature === signature && previewFailure == null;
  const marks: Marks = useMemo(() => (preview ? previewMarks(preview.value) : new Map()), [preview]);
  const toggle = (key: string, on: boolean) => setTicked(current => { const next = new Set(current); if (on) next.add(key); else next.delete(key); return next; });
  const usual = usualRows(template, ticked) as Array<{ key: string; name: string; builtin: boolean }>;
  const warnings = skillWarnings(template, ticked, locale) as string[];
  const notes = preview && preview.value.notes.length > 0 ? preview.value.notes : template.notes;
  const known = new Set(keys.all);
  // A line that is about a whole part (the memory layer is full, the task limit) has no key of the template: it is told here.
  const wholeLines = preview ? (resultLines(preview.value.skip, template) as Array<{ key: string; reason: string; name: string }>).filter(line => !known.has(line.key) && line.reason) : [];
  const can = fresh && !busy && anyTicked(template, ticked);

  async function apply() {
    if (!can) return;
    setBusy(true); setFailure(null);
    try {
      const done = await applyRoleTemplate(template.id, applyBody(botId, leaveOut));
      setResult(done); setBusy(false);
      void onApplied(done);
    } catch (error) { setFailure(error); setBusy(false); }
  }

  const finished = result !== null;
  const written = result ? createdLine(result.created, locale) as string : "";
  const reused = result ? resultLines(result.reused, template) as Array<{ key: string; reason: string; name: string }> : [];
  const skipped = result ? resultLines(result.skipped, template) as Array<{ key: string; reason: string; name: string }> : [];

  return <Dialog open onOpenChange={next => { if (!next && !busy) onClose(); }}>
    <DialogContent data-testid="template-dialog" closeLabel={t("关闭")} aria-describedby="template-dialog-description" onCloseAutoFocus={event => { event.preventDefault(); returnFocus(); }} onInteractOutside={event => { if (busy) event.preventDefault(); }}
      className="flex max-h-[92dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-2xl">
      <DialogHeader className="gap-1 border-b border-line p-4 pr-12 sm:p-5 sm:pr-12">
        <DialogTitle className="text-title-s">{t("用模板起步")} · {label}</DialogTitle>
        <DialogDescription id="template-dialog-description" className="text-small">{t(template.blurb)}</DialogDescription>
      </DialogHeader>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4 sm:p-5">
        {finished ? <div data-testid="template-result" className="flex min-w-0 flex-col gap-3" role="status">
          <p data-testid="template-result-line" className="m-0 text-body text-ink">{written ? `${t("已写入")}：${written}` : t("这次没有写入新的内容。")}</p>
          <p className="m-0 text-small text-ink-2">{t("写进去的都是普通的记忆、简报和技能，可以在各自的页面里改或删；也可以在这一页撤掉。")}</p>
          {reused.length > 0 && <ul data-testid="template-result-reused" className="m-0 flex list-none flex-col gap-1 p-0 text-small text-ink-2">{reused.map((line, at) => <li key={`${line.key}-${at}`} className="[overflow-wrap:anywhere]">{t("已有，沿用")}{line.name && ` · ${line.name}`}{line.reason && ` · ${t(line.reason)}`}</li>)}</ul>}
          {skipped.length > 0 && <ul data-testid="template-result-skipped" className="m-0 flex list-none flex-col gap-1 p-0 text-small text-ink-2">{skipped.map((line, at) => <li key={`${line.key}-${at}`} className="[overflow-wrap:anywhere]">{t("没有写")}{line.name && ` · ${line.name}`}{line.reason && ` · ${t(line.reason)}`}</li>)}</ul>}
        </div> : <>
          <div className="flex min-w-0 flex-col gap-1.5 md:w-72">
            <label id="template-target-label" className="text-small font-medium text-ink">{t("写到哪里")}</label>
            <Select value={botId ?? GLOBAL} disabled={busy} onValueChange={value => setBotId(value === GLOBAL ? null : value)}>
              <SelectTrigger aria-labelledby="template-target-label" data-testid="template-target" className="w-full max-md:h-11"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value={GLOBAL}>{t("全局 + 助理")}</SelectItem>{choices.map((bot: Bot) => <SelectItem key={bot.id} value={bot.id}>{t("本 bot")} · {bot.name}</SelectItem>)}</SelectContent>
            </Select>
            <p className="m-0 text-caption text-muted-foreground">{botId === null ? t("记忆写在全局层，简报和常用技能放在默认 bot「助理」上。") : t("记忆、简报和常用技能都只放在这个 bot 上。")}</p>
          </div>
          {bots.error != null && <ErrorBar error={bots.error} onRetry={() => void bots.reload()} retrying={bots.loading} />}

          <Group title={t("记忆")} count={template.memory.length}>
            <ul className="m-0 flex list-none flex-col gap-1.5 p-0">{template.memory.map(item => <Row key={item.key} id={item.key} ticked={ticked.has(item.key)} onToggle={toggle} disabled={busy} marks={marks} testId="template-memory">
              <span><StatusBadge kind="neutral" className="h-5">{t(KIND_LABELS[item.kind] ?? item.kind)}</StatusBadge></span>
              <span className="text-small text-ink [overflow-wrap:anywhere]">{item.text}</span>
            </Row>)}</ul>
          </Group>

          {template.briefs.length > 0 && <Group title={t("简报")} count={template.briefs.length}>
            <ul className="m-0 flex list-none flex-col gap-1.5 p-0">{template.briefs.map(brief => <Row key={brief.key} id={brief.key} ticked={ticked.has(brief.key)} onToggle={toggle} disabled={busy} marks={marks} testId="template-brief">
              <span className="text-small font-medium text-ink">{brief.name}</span>
              <span data-testid="template-brief-when" className="font-mono text-caption text-muted-foreground">{whenText(brief, locale) as string}</span>
              <span className="text-small text-ink-2 [overflow-wrap:anywhere]">{brief.instruction}</span>
              {brief.skill_key && <span className="text-caption text-muted-foreground">{t("按技能")}：{(template.skills.find(skill => skill.key === brief.skill_key)?.name) ?? brief.skill_key}</span>}
            </Row>)}</ul>
          </Group>}

          {template.skills.length > 0 && <Group title={t("技能")} count={template.skills.length}>
            <ul className="m-0 flex list-none flex-col gap-1.5 p-0">{template.skills.map(skill => <li key={skill.key} className="flex min-w-0 flex-col gap-1">
              <ul className="m-0 list-none p-0"><Row id={skill.key} ticked={ticked.has(skill.key)} onToggle={toggle} disabled={busy} marks={marks} testId="template-skill">
                <span className="text-small font-medium text-ink">{skill.name}</span>
                <span className="text-small text-ink-2 [overflow-wrap:anywhere]">{skill.description}</span>
              </Row></ul>
              <Collapsible data-testid="template-skill-steps" className="pl-3">
                <CollapsibleTrigger className="group/fold flex min-h-11 items-center gap-1.5 rounded-sm text-small text-ink-2 outline-none focus-visible:ring-2 focus-visible:ring-ring md:min-h-0">
                  <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]/fold:rotate-90 motion-reduce:transition-none" />{t("看步骤")}
                </CollapsibleTrigger>
                <CollapsibleContent>
                  <div className="flex min-w-0 flex-col gap-2 pt-1 text-small text-ink-2">
                    <p className="m-0 whitespace-pre-wrap [overflow-wrap:anywhere]">{skill.body}</p>
                    <p className="m-0 whitespace-pre-wrap text-caption text-muted-foreground [overflow-wrap:anywhere]">{skill.output_template}</p>
                    <p className="m-0 font-mono text-caption text-muted-foreground [overflow-wrap:anywhere]">{t("可用的工具")}：{skill.allowed_tools.join("、")}</p>
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </li>)}</ul>
          </Group>}

          {usual.length > 0 && <p data-testid="template-usual" className="m-0 text-small text-ink-2 [overflow-wrap:anywhere]">{t("会加进常用技能")}：{usual.map(row => row.builtin ? `${row.name}（${t("内置")}）` : row.name).join("、")}</p>}
          {warnings.map(text => <p key={text} data-testid="template-warning" className="m-0 text-small text-ink [overflow-wrap:anywhere]">{text}</p>)}
          {wholeLines.length > 0 && <ul data-testid="template-whole-lines" className="m-0 flex list-none flex-col gap-1 p-0">{wholeLines.map((line, at) => <li key={`${line.key}-${at}`} className="text-small text-ink [overflow-wrap:anywhere]">{t(line.reason)}</li>)}</ul>}
          {notes.length > 0 && <ul data-testid="template-notes" className="m-0 flex list-none flex-col gap-1 rounded-md border border-line bg-sunken p-3">{notes.map(note => <li key={note} className="text-small text-ink-2 [overflow-wrap:anywhere]">{t(note)}</li>)}</ul>}
          {previewFailure != null && <ErrorBar error={previewFailure} />}
          {failure != null && <ErrorBar error={failure} />}
        </>}
      </div>
      <DialogFooter className="border-t border-line p-4 sm:p-5">
        {finished
          ? <Button type="button" data-testid="template-done" className="max-md:h-11" onClick={onClose}>{t("完成")}</Button>
          : <>
            <Button type="button" variant="ghost" data-testid="template-cancel" disabled={busy} className="max-md:h-11" onClick={onClose}>{t("取消")}</Button>
            <StatefulButton type="button" data-testid="template-apply" phase={busy ? "loading" : "idle"} disabled={!can && !busy} className="max-md:h-11" onClick={() => void apply()}>{t("应用")}</StatefulButton>
          </>}
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
