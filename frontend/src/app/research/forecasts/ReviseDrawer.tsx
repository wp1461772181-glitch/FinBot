import { useEffect, useMemo, useRef, useState } from "react";
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ErrorBar } from "@/components/state/ErrorBar";
import { SkeletonRows } from "@/components/state/Skeleton";
import { StatefulButton } from "@/components/state/StatefulButton";
import { StatusBadge } from "@/components/StatusBadge";
import { Stepper } from "@/components/Stepper";
import { cn } from "@/lib/utils";
import { createV2ManualRevisionJob, getV2RevisionCandidates } from "../../../api/forecast-v2";
import type { V2RevisionCandidates } from "../../../api/forecast-v2";
import type { V2ForecastJob, V2SourceRef, V2TimelineEntry } from "../../../types";
import { MAX_REVISION_SOURCES, REVISE_STEPS, candidateGroups, canContinue, pickedSources, revisionRefs, reviseTarget, sourceDisabled, toggleSource, versionMethod } from "../../../forecast-detail.mjs";
import { useLocale, colon } from "../../../i18n";
import { actionMessage } from "../support";
import { day } from "./format";

type Option = { key: string; source_type: V2SourceRef["source_type"]; source_id: string; label: string; publishedAt: string | null; observedAt: string | null; revisionType: string };
type Candidates = { kind: "loading" } | { kind: "error"; message: string } | { kind: "ready"; data: V2RevisionCandidates };

/** What each category of a candidate is called; a category the groups do not name is a source status update. */
const TYPE_LABEL: Record<string, string> = { new: "新发布材料", backfilled: "过往补充材料", preexisting: "预测前已入库、本版未采用", reanalyzed: "新完成分析" };

/**
 * 发起修订 (design 4.6, 5.4): a side drawer of three steps.  1 选父版本 (the newest by default), 2 勾选材料 (the candidates the server offers for that
 * version, in its four groups; at most 10; NOTHING is ticked for the reader and nothing ticks them: no 全选, no recommendation), 3 确认.  The candidates are
 * read again every 10 s while the drawer is open.  `locate` is a filing an address named (?revise=): the list scrolls to it and marks it, it is not ticked.
 * The request is the old one (createV2ManualRevisionJob), its sources in the server's order whatever the order of the ticks.
 */
export function ReviseDrawer({ open, onOpenChange, versions, locate, onSubmitted, jobActive, returnFocus }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  versions: V2TimelineEntry[];
  locate?: string;
  onSubmitted: (job: V2ForecastJob) => void;
  jobActive: boolean;
  /** Where the focus goes when the drawer closes (the button that opened it). */
  returnFocus?: () => void;
}) {
  const { t } = useLocale();
  const latest = versions.at(-1)?.id ?? "";
  const [step, setStep] = useState<number>(locate ? 1 : 0);
  const [parentId, setParentId] = useState("");
  const [keys, setKeys] = useState<string[]>([]);
  const [candidates, setCandidates] = useState<Candidates>({ kind: "loading" });
  const [error, setError] = useState<string | null>(null);
  const parent = versions.find(version => version.id === parentId)?.id ?? latest;
  const located = useRef<HTMLElement | null>(null);

  // Opening starts clean: the newest version, nothing ticked (a drawer opened by ?revise= starts on the materials step).
  useEffect(() => {
    if (!open) return;
    setStep(locate ? 1 : 0); setParentId(""); setKeys([]); setError(null);
  }, [open, locate]);

  useEffect(() => {
    if (!open || !parent) { setCandidates({ kind: "loading" }); return; }
    let cancelled = false;
    let timer: number | undefined;
    const controller = new AbortController();
    setCandidates({ kind: "loading" });
    async function refresh() {
      try {
        const next = await getV2RevisionCandidates(parent, controller.signal);
        if (!cancelled) setCandidates({ kind: "ready", data: next });
      } catch (failure) {
        if (!cancelled && !controller.signal.aborted) setCandidates({ kind: "error", message: actionMessage(failure, "暂时无法读取可选修订材料。") });
      } finally {
        if (!cancelled) timer = window.setTimeout(() => { void refresh(); }, 10_000);
      }
    }
    void refresh();
    return () => { cancelled = true; if (timer !== undefined) window.clearTimeout(timer); controller.abort(); };
  }, [open, parent]);

  const data = candidates.kind === "ready" && candidates.data.version_id === parent ? candidates.data : null;
  const options: Option[] = useMemo(() => (data?.candidates ?? []).map(candidate => ({
    key: `${candidate.source_type}:${candidate.source_id}`, source_type: candidate.source_type, source_id: candidate.source_id, label: candidate.title,
    publishedAt: candidate.published_at, observedAt: candidate.observed_at, revisionType: candidate.category,
  })), [data]);
  const picked = pickedSources(options, keys);
  const groups = candidateGroups(options);
  const target = reviseTarget(options, locate);

  // The filing an address named is brought into view once the list is there.
  useEffect(() => { if (step === 1 && target) located.current?.scrollIntoView?.({ block: "center" }); }, [step, target?.key, options.length]);

  async function submit() {
    if (!data || picked.length === 0) return;
    setError(null);
    try {
      const job = await createV2ManualRevisionJob(parent, revisionRefs(options, keys));
      onSubmitted(job);
      onOpenChange(false);
    } catch (failure) {
      setError(actionMessage(failure, "无法创建手动修订任务。"));
      throw failure;
    }
  }

  const steps = [{ id: "parent", label: t("选父版本") }, { id: "materials", label: t("勾选材料") }, { id: "confirm", label: t("确认") }];
  const typeLabel = (category: string) => t(TYPE_LABEL[category] ?? "来源状态更新");
  const move = (to: number) => { setError(null); setStep(to); };
  return <Drawer open={open} onOpenChange={onOpenChange} direction="right">
    <DrawerContent data-testid="revise-drawer" aria-describedby="revise-drawer-description" onCloseAutoFocus={event => { event.preventDefault(); returnFocus?.(); }} className="data-[vaul-drawer-direction=right]:w-full data-[vaul-drawer-direction=right]:sm:max-w-lg">
      <DrawerHeader className="gap-3 border-b border-line">
        <DrawerTitle className="text-title-s">{t("发起修订")}</DrawerTitle>
        <DrawerDescription id="revise-drawer-description">{t("系统会在服务端检查材料的发布时点、观察时点、来源状态变化和固定目标合同；未来材料仍会被拒绝。提交成功只代表已入队，原版本保持不变。")}</DrawerDescription>
        <Stepper steps={steps} current={step} label={t("修订步骤")} />
      </DrawerHeader>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4" data-step={REVISE_STEPS[step]}>
        {step === 0 && <fieldset data-testid="revise-step-parent" className="m-0 flex min-w-0 flex-col gap-2 border-0 p-0">
          <legend className="mb-2 p-0 text-small font-medium text-ink">{t("修订哪一个预测版本")}</legend>
          {[...versions].reverse().map(version => <label key={version.id} className={cn("flex min-h-11 cursor-pointer items-center gap-3 rounded-md border px-3 py-2 text-small has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring", version.id === parent ? "border-brand bg-brand-soft" : "border-line bg-surface hover:bg-sunken")}>
            <input type="radio" name="revise-parent" value={version.id} checked={version.id === parent} onChange={() => { setParentId(version.id); setKeys([]); }} className="size-4 accent-[var(--brand)]" />
            <span className="min-w-0 flex-1"><span className="font-mono">{t("第")} {version.version_no} {t("版")}</span> · {day(version.decision_at)} · {t(versionMethod(version).phrase)}{version.id === latest && <span className="ml-2 text-caption text-muted-foreground">{t("最新")}</span>}</span>
          </label>)}
        </fieldset>}

        {step === 1 && <div data-testid="revise-step-materials" className="flex min-w-0 flex-col gap-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <p className="text-small font-medium text-ink">{t("用于本次修订的材料")}<span data-testid="revise-count" className="ml-2 font-mono text-caption font-normal text-muted-foreground">{t("已选")} {keys.length} / {t("最多 10 份")}</span></p>
            {keys.length > 0 && <button type="button" onClick={() => setKeys([])} className="ml-auto inline-flex h-8 items-center rounded-sm px-2 text-small text-brand outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring">{t("清空已选")}</button>}
          </div>
          {candidates.kind === "error" && <ErrorBar message={`${t("无法读取可选修订材料，系统会继续重试：")}${candidates.message}`} />}
          {candidates.kind !== "error" && !data && <SkeletonRows rows={3} />}
          {data?.expired && <p data-testid="revise-expired" className="text-small text-ink-2">{t(data.target_end_date === null ? "该预测的目标合同无效，只能查看历史版本。" : "该预测的目标已到期，只能查看历史版本。")}</p>}
          {data && !data.expired && options.length === 0 && <div data-testid="revise-empty" className="flex flex-col gap-2">
            <p className="text-small font-medium text-ink">{t("没有可用于修订的新材料。")}</p>
            <p className="text-small text-muted-foreground">{t("当前没有可用于修订的材料。可选的是：预测后 7 天内发布的新材料，预测前 30 天内发布、预测之后才收录的材料，或预测前已入库但本版未采用的材料。")}</p>
            {data.excluded.length > 0 && <ul className="m-0 flex list-none flex-col gap-1.5 p-0">{data.excluded.map(item => <li key={`${item.source_type}:${item.source_id}`} className="material-fact flex flex-col gap-0.5 px-3 py-2 text-small"><span className="text-ink [overflow-wrap:anywhere]">{item.title}</span><span className="text-caption text-muted-foreground">{item.reason_text ?? item.reason}</span></li>)}</ul>}
          </div>}
          {data && !data.expired && groups.map(group => <section key={group.id} data-group={group.id} className="flex min-w-0 flex-col gap-1.5">
            <h3 className="text-caption font-medium text-muted-foreground">{t(group.phrase)}</h3>
            <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
              {group.items.map(option => {
                const checked = keys.includes(option.key);
                const disabled = sourceDisabled(keys, option.key);
                const here = target?.key === option.key;
                return <li key={option.key}>
                  <label ref={here ? (node => { located.current = node; }) : undefined} data-located={here ? "" : undefined} data-source={option.key} className={cn("flex min-h-11 cursor-pointer items-start gap-3 rounded-md border px-3 py-2 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring", checked ? "border-brand bg-brand-soft" : "border-line bg-surface hover:bg-sunken", disabled && "cursor-not-allowed opacity-55 hover:bg-surface", here && "ring-2 ring-accent")}>
                    <Checkbox checked={checked} disabled={disabled} onCheckedChange={() => setKeys(current => toggleSource(current, option.key))} aria-label={option.label} className="mt-0.5" />
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-1"><StatusBadge kind="neutral" className="h-5">{typeLabel(option.revisionType)}</StatusBadge>{here && <StatusBadge kind="progress" className="h-5">{t("地址指向这份")}</StatusBadge>}</span>
                      <span className="text-small text-ink [overflow-wrap:anywhere]">{option.label}</span>
                      <span className="text-caption text-muted-foreground">{t("发布时间")}{colon()}{day(option.publishedAt)}{option.observedAt && <> · {t("入库时间")}{colon()}{day(option.observedAt)}</>}</span>
                    </span>
                  </label>
                </li>;
              })}
            </ul>
          </section>)}
          {keys.length >= MAX_REVISION_SOURCES && <p data-testid="revise-cap" className="text-caption text-muted-foreground">{t("已选满 10 份，取消一份才能再选别的。")}</p>}
        </div>}

        {step === 2 && <div data-testid="revise-step-confirm" className="flex min-w-0 flex-col gap-3">
          <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-small">
            <dt className="text-muted-foreground">{t("修订哪一个预测版本")}</dt>
            <dd className="m-0 text-ink"><span className="font-mono">{t("第")} {versions.find(version => version.id === parent)?.version_no} {t("版")}</span></dd>
            <dt className="text-muted-foreground">{t("用于本次修订的材料")}</dt><dd className="m-0 font-mono text-ink">{picked.length} / {MAX_REVISION_SOURCES}</dd>
          </dl>
          <ul className="m-0 flex list-none flex-col gap-1.5 p-0">{picked.map(option => <li key={option.key} className="material-fact flex flex-col gap-0.5 px-3 py-2 text-small"><span className="text-ink [overflow-wrap:anywhere]">{option.label}</span><span className="text-caption text-muted-foreground">{typeLabel(option.revisionType)} · {day(option.publishedAt)}</span></li>)}</ul>
          {error && <ErrorBar message={error} />}
        </div>}
      </div>
      <div className="flex items-center gap-2 border-t border-line p-4">
        {step > 0 && <Button type="button" variant="outline" onClick={() => move(step - 1)}>{t("上一步")}</Button>}
        <span className="ml-auto" />
        {step < 2 && <Button type="button" data-testid="revise-next" disabled={!canContinue(REVISE_STEPS[step], { picked: keys.length })} onClick={() => move(step + 1)}>{t("下一步")}</Button>}
        {step === 2 && <StatefulButton type="button" data-testid="revise-submit" disabled={!data || data.expired || picked.length === 0 || jobActive} onClick={submit}>{t("创建人工修订任务")} ({picked.length})</StatefulButton>}
      </div>
    </DrawerContent>
  </Drawer>;
}
