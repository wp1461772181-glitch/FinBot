import { ExternalLink } from "lucide-react";
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, SkeletonRows } from "@/components/state/Skeleton";
import { cn } from "@/lib/utils";
import { readAnswer, type AnswerDetail } from "../../api/backstage";
import { answerNotes, detailTimeline, helperLines, formatMs, formatTime, answerStatus, reconcileBlock, answerFeedbackBlock, type TimelineStep } from "../../backstage-view.mjs";
import { colon, useLocale } from "../../i18n";
import { useLoad } from "../use-load";
import { CostText, Status } from "./BackstageTable";
import { useWords } from "./words";

const safeUrl = (value: unknown) => (typeof value === "string" && /^https?:\/\//i.test(value) ? value : null);

function Meta({ children }: { children: React.ReactNode }) {
  return <p className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-caption text-muted-foreground">{children}</p>;
}

/** One step of the timeline.  The marker on the line is decoration; the step's own words say what it is. */
function Step({ step }: { step: TimelineStep }) {
  const { t } = useLocale();
  const wrap = "relative flex min-w-0 flex-col gap-1 pb-4 pl-5 before:absolute before:left-0 before:top-1.5 before:size-2 before:rounded-full before:bg-line-strong after:absolute after:bottom-0 after:left-[3px] after:top-4 after:w-px after:bg-line last:after:hidden";
  switch (step.kind) {
    case "question":
      return <li data-step="question" className={wrap}><p className="text-caption font-medium text-muted-foreground">{step.title}</p><p dir="auto" className="whitespace-pre-wrap [overflow-wrap:anywhere] text-body text-ink">{step.text}</p></li>;
    case "narration":
      return <li data-step="narration" className={wrap}>{step.offset && <Meta><span className="font-mono tabular-nums">{step.offset}</span></Meta>}<p dir="auto" className="whitespace-pre-wrap [overflow-wrap:anywhere] text-small text-ink-2">{step.text}</p></li>;
    case "model":
      return <li data-step="model" data-ok={step.ok ? "true" : "false"} className={cn(wrap, !step.ok && "before:bg-danger")}>
        <p className="flex flex-wrap items-center gap-x-2 text-small text-ink"><span className="font-medium">{step.title}</span>
          {step.tier !== "—" && <span className="rounded-full border border-line px-1.5 text-caption text-muted-foreground">{step.tier}</span>}
          {step.purpose && <span className="text-caption text-muted-foreground">{step.purpose}</span>}
          {(step.attempt ?? 1) > 1 && <span className="text-caption text-muted-foreground">{`${t("尝试次数")}${colon()}${step.attempt}`}</span>}
          {!step.ok && <span className="text-caption text-danger">{`${t("失败")}${colon()}${step.error || t("未知原因")}`}</span>}</p>
        <Meta>{step.offset && <span className="font-mono tabular-nums">{step.offset}</span>}<span>{step.time}</span><span className="font-mono tabular-nums">{step.ms}</span>{step.tokens !== "—" && <span className="font-mono tabular-nums">{`${step.tokens} token`}</span>}{step.cost && step.cost.kind !== "none" && <CostText cost={step.cost} unrecordedLabel />}</Meta>
      </li>;
    case "tool":
      return <li data-step="tool" data-state={step.state} className={wrap}>
        <p className="flex flex-wrap items-center gap-x-2 text-small text-ink"><span className="font-medium">{step.title}</span><span className="font-mono text-caption text-muted-foreground">{step.name}</span>
          {step.state === "unfinished" && <span className="text-caption text-muted-foreground">{t("没有做完")}</span>}
          {step.offset && <span className="font-mono text-caption tabular-nums text-muted-foreground">{step.done_offset ? `${step.offset} → ${step.done_offset}` : step.offset}</span>}</p>
        {step.arguments && <code className="block max-w-full overflow-x-auto whitespace-pre-wrap break-all rounded-sm bg-sunken px-2 py-1 font-mono text-caption text-ink-2">{step.arguments}</code>}
        <p className="[overflow-wrap:anywhere] text-small text-ink-2">{step.result}</p>
      </li>;
    case "card":
      return <li data-step="card" className={wrap}>
        <p className="flex flex-wrap items-center gap-x-2 text-small text-ink"><span className="font-medium">{t("提出确认卡片")}</span><span dir="auto">{step.title}</span>{step.state && typeof step.state === "object" && <Status status={step.state} />}</p>
        {step.text && <p dir="auto" className="text-small text-ink-2">{step.text}</p>}
        {step.targets && step.targets.length > 0 && <ul className="list-disc pl-4 text-small text-ink-2">{step.targets.map(target => <li key={target} dir="auto">{target}</li>)}</ul>}
        {step.choices && step.choices.length > 0 && <p className="flex flex-wrap gap-1.5" aria-label={t("卡片上的选项")}>{step.choices.map(choice => <span key={choice} className="rounded-sm border border-line px-2 text-caption text-muted-foreground">{choice}</span>)}</p>}
      </li>;
    case "card_result":
      return <li data-step="card_result" className={wrap}>
        <p className="text-small text-ink"><span className="font-medium">{t("卡片的结果")}</span>{` · ${step.title}`}</p>
        <Meta><span>{step.time}</span><span>{step.result}</span></Meta>
      </li>;
    default:
      return <li data-step="answer" className={wrap}><p className="text-caption font-medium text-muted-foreground">{step.title}</p><p dir="auto" className="whitespace-pre-wrap [overflow-wrap:anywhere] text-body text-ink">{step.text}</p></li>;
  }
}

/** The course of one turn in a side drawer: notes, the timeline in order, the figure check, the sources, and the Langfuse link when the server has one. */
export function AnswerDrawer({ id, onClose, returnFocus }: { id: string | null; onClose: () => void; returnFocus: () => void }) {
  const { t } = useLocale();
  const w = useWords();
  // The answer is kept with the id it was asked for: a detail is shown only under its own id, never one left over from the previous row.
  const load = useLoad<{ id: string; detail: AnswerDetail } | null>(signal => (id ? readAnswer(id, signal).then(found => ({ id, detail: found })) : Promise.resolve(null)), id ?? "");
  const detail = id && load.data?.id === id ? load.data.detail : null;
  const steps = detail ? detailTimeline(detail, undefined, w) : [];
  const notes = detail ? answerNotes(detail, w) : [];
  const helpers = detail ? helperLines(detail, w) : [];
  const reconcile = detail ? reconcileBlock(detail, w) : null;
  const verdict = detail ? answerFeedbackBlock(detail, w) : null;
  const langfuse = safeUrl(detail?.langfuse_url);
  const citations = detail?.citations ?? [];
  return <Drawer open={id !== null} onOpenChange={open => { if (!open) onClose(); }} direction="right" autoFocus>
    <DrawerContent data-testid="answer-drawer" aria-describedby="answer-drawer-description" onCloseAutoFocus={event => { event.preventDefault(); returnFocus(); }}
      className="data-[vaul-drawer-direction=right]:w-full data-[vaul-drawer-direction=right]:sm:max-w-lg">
      <DrawerHeader className="gap-1 border-b border-line">
        <DrawerTitle className="text-title-s">{t("这一轮的经过")}</DrawerTitle>
        <DrawerDescription id="answer-drawer-description">{detail ? `${detail.bot_name ?? "—"} · ${formatTime(detail.created_at)} · ${formatMs(detail.total_ms)}` : t("正在读取")}</DrawerDescription>
        {detail && <div className="flex flex-wrap items-center gap-2 pt-1"><Status status={answerStatus(detail.status)} />
          {langfuse && <a data-testid="langfuse-link" href={langfuse} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-small text-action underline-offset-2 hover:underline">Langfuse<ExternalLink aria-hidden="true" className="size-3.5" /></a>}</div>}
      </DrawerHeader>
      <div data-testid="answer-drawer-body" className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-4 [overflow-wrap:anywhere]">
        {load.error && !load.loading && !detail ? <ErrorBar error={load.error} onRetry={() => void load.reload()} retrying={load.loading} /> : null}
        {load.loading && !detail ? <DelayedSkeleton delay={150}><SkeletonRows rows={5} /></DelayedSkeleton> : null}
        {verdict && <section data-testid="answer-verdict" data-verdict={verdict.verdict} aria-labelledby="answer-verdict-title" className="flex flex-col gap-1 rounded-md border border-line px-3 py-2">
          <h3 id="answer-verdict-title" className="text-small font-medium text-ink">{verdict.text}</h3>
          {verdict.reason && <p dir="auto" className="whitespace-pre-wrap [overflow-wrap:anywhere] text-small text-ink-2">{verdict.reason}</p>}
        </section>}
        {notes.map(note => <p key={note.kind} data-testid={`note-${note.kind}`} role="note" className="rounded-md border border-line bg-sunken px-3 py-2 text-small text-ink-2">{note.text}</p>)}
        {helpers.length > 0 && <ul data-testid="helpers" aria-label={t("小助手")} className="m-0 flex list-none flex-col gap-1 p-0">{helpers.map(helper => <li key={helper.id} data-testid="helper-line" data-complete={helper.complete ? "true" : "false"} className="rounded-md border border-line bg-sunken px-3 py-2 text-small text-ink-2">{helper.text}</li>)}</ul>}
        {steps.length > 0 && <ol data-testid="timeline" aria-label={t("时间线")} className="m-0 flex list-none flex-col p-0">{steps.map((step, index) => <Step key={`${step.kind}-${index}`} step={step} />)}</ol>}
        {detail && steps.length === 0 && <p className="text-small text-muted-foreground">{t("这一轮没有留下可以显示的内容。")}</p>}
        {reconcile && <section data-testid="reconcile" data-kind={reconcile.kind} aria-labelledby="answer-reconcile" className="flex flex-col gap-1.5">
          <h3 id="answer-reconcile" className="text-small font-medium text-ink">{reconcile.title}</h3>
          {reconcile.checked && <p className="font-mono text-caption tabular-nums text-muted-foreground">{reconcile.checked}</p>}
          {reconcile.text && <p className="text-small text-ink-2">{reconcile.text}</p>}
          {reconcile.lines.length > 0 && <ul className="m-0 flex list-none flex-col gap-1 p-0">{reconcile.lines.map((item, index) => <li key={`${index}-${item.line}`} data-testid="reconcile-line" className="flex flex-col gap-0.5 rounded-md border border-line px-3 py-2">
            <p dir="auto" className="whitespace-pre-wrap [overflow-wrap:anywhere] text-small text-ink">{item.line}</p>
            {item.values && <p className="font-mono text-caption tabular-nums text-muted-foreground">{item.values}</p>}
          </li>)}</ul>}
          {reconcile.note && <p data-testid="reconcile-note" role="note" className="rounded-md border border-line bg-sunken px-3 py-2 text-small text-ink-2">{reconcile.note}</p>}
        </section>}
        {citations.length > 0 && <section aria-labelledby="answer-citations" className="flex flex-col gap-1.5">
          <h3 id="answer-citations" className="text-small font-medium text-ink">{t("引用的来源")}</h3>
          <ol className="m-0 flex list-none flex-col gap-1 p-0 text-small text-ink-2">{citations.map(citation => {
            const href = safeUrl(citation.url);
            return <li key={citation.ordinal} className="flex gap-2"><span className="font-mono text-muted-foreground">{citation.ordinal}</span>
              {href ? <a href={href} target="_blank" rel="noreferrer noopener" dir="auto" className="min-w-0 [overflow-wrap:anywhere] text-action underline-offset-2 hover:underline">{citation.title || href}</a> : <span dir="auto" className="min-w-0 [overflow-wrap:anywhere]">{citation.title}</span>}</li>;
          })}</ol>
        </section>}
      </div>
    </DrawerContent>
  </Drawer>;
}
