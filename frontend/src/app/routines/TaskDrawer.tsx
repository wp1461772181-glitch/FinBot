import { useEffect, useMemo, useRef, useState } from "react";
import { BotAvatar } from "@/components/bot/BotAvatar";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer";
import { Field, FieldDescription, FieldError, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Segmented } from "@/components/Segmented";
import { Stepper } from "@/components/Stepper";
import { TagInput } from "@/components/TagInput";
import { ErrorBar } from "@/components/state/ErrorBar";
import { StatefulButton } from "@/components/state/StatefulButton";
import { confirm } from "@/components/state/confirm";
import { notify } from "@/components/state/notify";
import { listSkills, type Skill } from "../../api/skills-core";
import { createAgentTask, updateAgentTask, type AgentTask } from "../../api/tasks";
import type { Bot } from "../../api/bots";
import { useLocale } from "../../i18n";
import { usableSkills } from "../../skill-items.mjs";
import { SECTIONS, SYMBOL, MAX_SYMBOLS, MAX_NAME, blankDraft, draftChanged, draftFromTask, firstProblemSection, inputFromDraft, sectionsWithProblems, timezoneChoices, validateDraft, zoneLabel, type RoutineDraft } from "../../routine-form.mjs";
import { PickCombobox, type PickOption } from "./PickCombobox";
import { PriceLineRows } from "./PriceLineRows";

const NO_SKILL = "__none__"; // Radix Select has no empty item value

/**
 * 新建 / 编辑任务 (design 4.10, 5.4): a side drawer (the whole screen on a phone; one drawer at every width, so the draft survives a resize) in four sections: 基本,
 * 时间, 范围, 内容.  The step row shows where the reader is and is a way to any section (nothing forces the order), with a mark on a section that has a rule broken.
 * The rules are the old form's (routine-form.mjs lists them all at once, the old form stopped at the first); they are told in place after a save was tried, and listed
 * under the sections.  The request is the old form's, key for key (draftToInput).  Closing with changes made asks first.  `lockedBotId` fixes the bot (a bot's own settings page).
 */
export function TaskDrawer({ open, onOpenChange, task, bots, lockedBotId, defaultBotId, onSaved, returnFocus }: {
  open: boolean; onOpenChange: (open: boolean) => void;
  /** The task being edited; null for a new one. */
  task: AgentTask | null;
  bots: Bot[]; lockedBotId?: string; defaultBotId: string;
  /** The task was saved: read the lists again. */
  onSaved: () => void;
  /** Where the focus goes when the drawer closes (the button that opened it). */
  returnFocus?: () => void;
}) {
  const { t } = useLocale();
  const [draft, setDraft] = useState<RoutineDraft>(() => blankDraft());
  const [initial, setInitial] = useState<RoutineDraft>(() => blankDraft());
  const [section, setSection] = useState(0);
  const [tried, setTried] = useState(false);
  const [serverError, setServerError] = useState<unknown>(null);
  const [skills, setSkills] = useState<Skill[]>([]);
  const body = useRef<HTMLDivElement>(null);

  // Opening starts clean: the task's own values (what the old form showed), or the blank form with the bot chosen for it.
  useEffect(() => {
    if (!open) return;
    const next = task ? draftFromTask(task, { fallbackBotId: lockedBotId ?? defaultBotId }) : blankDraft({ botId: lockedBotId ?? defaultBotId });
    setDraft(next); setInitial(next); setSection(0); setTried(false); setServerError(null);
  }, [open, task?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    listSkills(controller.signal).then(data => setSkills(data.skills)).catch(() => { /* the list then offers 无 only */ });
    return () => controller.abort();
  }, [open]);

  const problems = useMemo(() => validateDraft(draft), [draft]);
  const messages = useMemo(() => Object.fromEntries(problems.map(problem => [problem.field, t(problem.message)])), [problems, t]);
  const marked = tried ? sectionsWithProblems(problems) : [];
  const patch = (next: Partial<RoutineDraft>) => setDraft(current => ({ ...current, ...next }));
  const shown = (field: string) => tried ? messages[field] : undefined;

  async function requestClose() {
    if (draftChanged(draft, initial)) {
      const yes = await confirm({ title: t("放弃未保存的修改？"), description: t("关闭后，这次改的内容不会保存。"), confirmLabel: t("放弃修改"), cancelLabel: t("继续编辑"), tone: "danger" });
      if (!yes) return;
    }
    onOpenChange(false);
  }
  const go = (index: number) => { setSection(index); requestAnimationFrame(() => body.current?.scrollTo?.({ top: 0 })); };

  function press() {
    setTried(true);
    if (problems.length > 0) {
      const first = firstProblemSection(problems);
      if (first) go(SECTIONS.indexOf(first));
      return undefined;
    }
    setServerError(null);
    return (async () => {
      const input = inputFromDraft(draft, { lockedBotId });
      try { if (task) await updateAgentTask(task.id, input); else await createAgentTask(input); }
      catch (error) { setServerError(error); throw error; }
      notify.success(t(task ? "任务已保存。" : "任务已创建。"), { id: "routines:saved" });
      onSaved();
      onOpenChange(false);
    })();
  }

  const botOptions: PickOption[] = useMemo(() => {
    const list = bots.map(bot => ({ value: bot.id, search: `${bot.name} ${bot.title}`, text: bot.name, label: <><BotAvatar avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={20} /><span className="truncate">{bot.name}</span></> }));
    return draft.botId && !bots.some(bot => bot.id === draft.botId) ? [...list, { value: draft.botId, search: t("已删除的 bot"), text: t("已删除的 bot"), label: <span>{t("已删除的 bot")}</span> }] : list;
  }, [bots, draft.botId, t]);
  const zones = useMemo(() => {
    const all = typeof Intl !== "undefined" && "supportedValuesOf" in Intl ? (Intl as unknown as { supportedValuesOf: (key: string) => string[] }).supportedValuesOf("timeZone") : [];
    const choices = timezoneChoices(all, draft.timezone);
    const option = (zone: string, group: string): PickOption => ({ value: zone, group, text: zoneLabel(zone), search: `${zone} ${zoneLabel(zone)}`, label: <span className="truncate">{zoneLabel(zone)}</span> });
    return [...choices.pinned.map(zone => option(zone, t("常用时区"))), ...(choices.kept ? [option(choices.kept, t("已保存的值"))] : []), ...choices.rest.map(zone => option(zone, t("全部时区")))];
  }, [draft.timezone, t]);
  const skillList = usableSkills(skills) as Skill[];
  const lockedBot = lockedBotId ? bots.find(bot => bot.id === lockedBotId) : undefined;

  const steps = [{ id: "basics", label: t("基本") }, { id: "time", label: t("时间") }, { id: "scope", label: t("范围") }, { id: "content", label: t("内容") }];
  const last = section === steps.length - 1;
  return <Drawer open={open} onOpenChange={next => { if (!next) void requestClose(); }} direction="right" autoFocus>
    <DrawerContent data-testid="task-drawer" data-section={SECTIONS[section]} aria-describedby="task-drawer-description" onCloseAutoFocus={event => { event.preventDefault(); returnFocus?.(); }}
      className="data-[vaul-drawer-direction=right]:w-full data-[vaul-drawer-direction=right]:sm:max-w-lg">
      <DrawerHeader className="gap-3 border-b border-line">
        <DrawerTitle className="text-title-s">{t(task ? "编辑任务" : "新建任务")}</DrawerTitle>
        <DrawerDescription id="task-drawer-description">{t("任务按时运行；睡眠期间错过的会在醒来后补跑一次。简报类任务需要在设置里配置后台任务模型；提醒类任务不调用模型。")}</DrawerDescription>
        <Stepper steps={steps} current={section} label={t("任务的四节")} onSelect={go} marked={marked} />
      </DrawerHeader>
      <div ref={body} className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4" data-testid="task-drawer-body">
        {SECTIONS[section] === "basics" && <FieldSet data-testid="task-section-basics" className="gap-4">
          <FieldLegend className="sr-only">{t("基本")}</FieldLegend>
          <Field>
            <FieldLabel htmlFor="task-bot">{t("所属 bot")}</FieldLabel>
            {lockedBotId
              ? <p id="task-bot" data-testid="task-bot-locked" className="flex h-9 items-center gap-2 text-body text-ink">{lockedBot && <BotAvatar avatar={lockedBot.avatar} look={lockedBot.look} name={lockedBot.name} seed={lockedBot.id} size={20} />}{lockedBot?.name ?? t("已删除的 bot")}<span className="text-small text-muted-foreground">· {t("这个 bot 自己的任务")}</span></p>
              : <PickCombobox id="task-bot" testId="task-bot" value={draft.botId} options={botOptions} onChange={botId => patch({ botId })} label={t("所属 bot")} searchLabel={t("搜索 bot")} emptyLabel={t("没有这个 bot")} />}
          </Field>
          <Field data-invalid={Boolean(shown("name")) || undefined}>
            <FieldLabel htmlFor="task-name">{t("名称")}</FieldLabel>
            <Input id="task-name" value={draft.name} maxLength={MAX_NAME} aria-invalid={Boolean(shown("name")) || undefined} aria-describedby={shown("name") ? "task-name-error" : undefined} onChange={event => patch({ name: event.target.value })} />
            {shown("name") && <FieldError id="task-name-error">{shown("name")}</FieldError>}
          </Field>
          <Segmented name="task-kind" legend={t("类型")} value={draft.kind} testid="task-kind" onChange={kind => patch({ kind })}
            options={[{ value: "brief", label: t("简报（Agent 回答一段说明）") }, { value: "alerts", label: t("提醒（新申报、新闻、价格线）") }]} />
        </FieldSet>}

        {SECTIONS[section] === "time" && <FieldSet data-testid="task-section-time" className="gap-4">
          <FieldLegend className="sr-only">{t("时间")}</FieldLegend>
          <Segmented name="task-schedule" legend={t("频率")} value={draft.schedule} testid="task-schedule" onChange={schedule => patch({ schedule })}
            options={[{ value: "daily", label: t("每天") }, { value: "weekdays", label: t("工作日") }, { value: "hourly", label: t("每小时") }, { value: "every", label: t("每隔一段时间") }]} />
          {draft.schedule === "every" && <div className="flex flex-wrap items-start gap-3">
            <Field className="w-28" data-invalid={Boolean(shown("everyValue")) || undefined}>
              <FieldLabel htmlFor="task-every">{t("间隔")}</FieldLabel>
              <Input id="task-every" type="number" min={1} value={draft.everyValue} aria-invalid={Boolean(shown("everyValue")) || undefined} aria-describedby={shown("everyValue") ? "task-every-error" : undefined} onChange={event => patch({ everyValue: event.target.value })} />
            </Field>
            <Segmented name="task-unit" legend={t("单位")} value={draft.everyUnit} testid="task-unit" onChange={everyUnit => patch({ everyUnit })} options={[{ value: "hours", label: t("小时") }, { value: "days", label: t("天") }, { value: "weeks", label: t("周") }]} />
            {shown("everyValue") && <FieldError id="task-every-error" className="basis-full">{shown("everyValue")}</FieldError>}
          </div>}
          <Field data-invalid={Boolean(shown("time")) || undefined}>
            <FieldLabel htmlFor="task-time">{t("时间")}</FieldLabel>
            <Input id="task-time" type="time" value={draft.time} className="w-40" aria-invalid={Boolean(shown("time")) || undefined} aria-describedby="task-time-hint" onChange={event => patch({ time: event.target.value })} />
            <FieldDescription id="task-time-hint">{draft.schedule === "hourly" ? t("每小时按这里的分钟运行。") : draft.schedule === "every" ? t("从这个时间开始，之后按间隔重复。") : t("按下面的时区算。")}</FieldDescription>
            {shown("time") && <FieldError>{shown("time")}</FieldError>}
          </Field>
          <Field>
            <FieldLabel htmlFor="task-timezone">{t("时区")}</FieldLabel>
            <PickCombobox id="task-timezone" testId="task-timezone" value={draft.timezone} options={zones} onChange={timezone => patch({ timezone })} label={t("时区")} searchLabel={t("搜索时区，如 Asia/Shanghai")} emptyLabel={t("没有这个时区")} />
          </Field>
          <Segmented name="task-count" legend={t("执行次数")} value={draft.countMode} testid="task-count" onChange={countMode => patch({ countMode })}
            options={[{ value: "unlimited", label: t("不限次数") }, { value: "once", label: t("只执行一次") }, { value: "count", label: t("执行指定次数后停止") }]} />
          {draft.countMode === "count" && <Field className="w-40" data-invalid={Boolean(shown("runs")) || undefined}>
            <FieldLabel htmlFor="task-runs">{t("次数")}</FieldLabel>
            <Input id="task-runs" type="number" min={1} max={1000} value={draft.runs} aria-invalid={Boolean(shown("runs")) || undefined} aria-describedby="task-runs-hint" onChange={event => patch({ runs: event.target.value })} />
            <FieldDescription id="task-runs-hint">{t("已执行的次数会累计计入。")}</FieldDescription>
            {shown("runs") && <FieldError>{shown("runs")}</FieldError>}
          </Field>}
        </FieldSet>}

        {SECTIONS[section] === "scope" && <FieldSet data-testid="task-section-scope" className="gap-4">
          <FieldLegend className="sr-only">{t("范围")}</FieldLegend>
          <Segmented name="task-scope" legend={t("范围")} value={draft.scope} testid="task-scope" onChange={scope => patch({ scope })} options={[{ value: "research_queue", label: t("研究队列") }, { value: "symbols", label: t("指定公司") }]} />
          {draft.scope === "symbols"
            ? <Field data-invalid={Boolean(shown("symbols")) || undefined}>
              <FieldLabel htmlFor="task-symbols">{t("股票代码")}</FieldLabel>
              <TagInput id="task-symbols" testid="task-symbols" value={draft.symbols} onChange={symbols => patch({ symbols })} max={MAX_SYMBOLS} normalize={raw => raw.trim().toUpperCase()} validate={item => SYMBOL.test(item)}
                invalidLabel={t("不是股票代码")} limitLabel={t("最多 30 家。")} placeholder="AAPL, MSFT" label={t("股票代码")} describedBy="task-symbols-hint" />
              <FieldDescription id="task-symbols-hint">{t("回车或逗号加入，退格删除最后一个。")}</FieldDescription>
              {shown("symbols") && <FieldError>{shown("symbols")}</FieldError>}
            </Field>
            : <p className="text-small text-muted-foreground">{t("按你的研究队列里的公司运行。")}</p>}
        </FieldSet>}

        {SECTIONS[section] === "content" && <FieldSet data-testid="task-section-content" className="gap-4">
          <FieldLegend className="sr-only">{t("内容")}</FieldLegend>
          {draft.kind === "brief" ? <>
            <Field>
              <FieldLabel htmlFor="task-instruction">{t("任务说明")}</FieldLabel>
              <Textarea id="task-instruction" rows={6} value={draft.instruction} maxLength={2000} placeholder={t("例如：总结研究队列公司过去一天的新申报和新闻，列出值得注意的变化。")} onChange={event => patch({ instruction: event.target.value })} />
            </Field>
            <Field>
              <FieldLabel htmlFor="task-skill">{t("技能")}</FieldLabel>
              <Select value={draft.skill || NO_SKILL} onValueChange={value => patch({ skill: value === NO_SKILL ? "" : value })}>
                <SelectTrigger id="task-skill" data-testid="task-skill" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_SKILL}>{t("无")}</SelectItem>
                  {skillList.map(skill => <SelectItem key={skill.id} value={skill.id}>{skill.name}</SelectItem>)}
                  {draft.skill && !skillList.some(skill => skill.id === draft.skill) && <SelectItem value={draft.skill}>{skills.find(skill => skill.id === draft.skill)?.name ?? t("（已不可用的技能）")}</SelectItem>}
                </SelectContent>
              </Select>
            </Field>
          </> : <>
            <Field orientation="horizontal"><Checkbox id="task-filings" checked={draft.filings} onCheckedChange={on => patch({ filings: on === true })} /><FieldLabel htmlFor="task-filings">{t("新申报")}</FieldLabel></Field>
            <Field orientation="horizontal"><Checkbox id="task-news" checked={draft.news} onCheckedChange={on => patch({ news: on === true })} /><FieldLabel htmlFor="task-news">{t("新闻线索")}</FieldLabel></Field>
            <Field>
              <FieldLabel id="task-price-label">{t("价格线")}</FieldLabel>
              <FieldDescription>{t("一行一条：代码、高于或低于、价格。")}</FieldDescription>
              <PriceLineRows rows={draft.priceRows} onChange={priceRows => patch({ priceRows })} shown={tried} messages={messages} />
            </Field>
            <Field orientation="horizontal"><Checkbox id="task-telegram" checked={draft.telegram} onCheckedChange={on => patch({ telegram: on === true })} /><FieldLabel htmlFor="task-telegram">{t("也发 Telegram")}</FieldLabel></Field>
          </>}
          <p className="text-small text-muted-foreground">{t("要不要通知你，写在 bot 的说明或任务说明里，比如「只有重要程度为高才发 Telegram」。没新东西时不会往对话里发消息。")}</p>
        </FieldSet>}
      </div>
      <div className="flex flex-col gap-2 border-t border-line p-4">
        {tried && problems.length > 0 && <ul role="alert" data-testid="task-problems" className="m-0 flex list-none flex-col gap-1 p-0 text-small text-danger">
          {problems.map(problem => <li key={problem.field}><button type="button" className="rounded-sm text-left underline underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => go(SECTIONS.indexOf(problem.section))}>{t(problem.message)}</button></li>)}
        </ul>}
        {serverError != null && <ErrorBar error={serverError} />}
        <div className="flex items-center gap-2">
          {section > 0 && <Button type="button" variant="outline" data-testid="task-prev" className="max-sm:h-11" onClick={() => go(section - 1)}>{t("上一节")}</Button>}
          {!last && <Button type="button" variant="outline" data-testid="task-next" className="max-sm:h-11" onClick={() => go(section + 1)}>{t("下一节")}</Button>}
          <span className="ml-auto" />
          <Button type="button" variant="ghost" data-testid="task-cancel" className="max-sm:h-11" onClick={() => void requestClose()}>{t("取消")}</Button>
          <StatefulButton type="button" data-testid="task-submit" className="max-sm:h-11" onClick={press}>{t("保存任务")}</StatefulButton>
        </div>
      </div>
    </DrawerContent>
  </Drawer>;
}

