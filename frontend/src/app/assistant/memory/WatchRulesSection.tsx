import { useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { StatusBadge } from "@/components/StatusBadge";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import { confirm } from "@/components/state/confirm";
import { deleteWatchRule, getWatch, patchWatchPreset, putAlertSettings, resetWatchPreset, type AlertSettings } from "../../../api/watch-rules";
import { useLocale } from "../../../i18n";
import { appliesText, checkThresholds, presetRows, ruleRows, settingsView, yieldsLine, type PresetRow, type Sensitivity } from "../../../watch-rules-view.mjs";
import { useLoad } from "../../use-load";

/** One card of the rules block: a title, its rows (or the sentence that says there are none). */
function Block({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  const { t } = useLocale();
  return <div data-testid={`watch-${id}`} className="flex min-w-0 flex-col gap-2 rounded-md border border-line bg-surface p-3">
    <h3 className="text-small font-medium text-ink">{t(title)}</h3>
    {children}
  </div>;
}

/**
 * 系统默认 (one row): the default's title and the sentence the server wrote for it, then what the owner can do: a switch (a hard guarantee shows 「硬保证，不能关」 instead), a threshold edit where the
 * default has a number, 恢复默认 when changed.  A refusal from the server is shown under the row with its reason.
 */
function PresetItem({ preset, busy, error, onRun }: { preset: PresetRow; busy: boolean; error: ReactNode; onRun: (key: string, work: () => Promise<unknown>) => Promise<boolean> }) {
  const { t, locale } = useLocale();
  const [inputs, setInputs] = useState<string[] | null>(null);
  const [problem, setProblem] = useState("");
  const edit = preset.levels ?? [];
  const unit = preset.unit === "%" ? "%" : preset.unit === "x" ? t("倍") : t("天");
  const yields = yieldsLine(preset.yields, locale);
  const applies = appliesText(preset.applies, locale);

  async function save() {
    if (!inputs) return;
    const checked = checkThresholds(preset.key, edit, inputs);
    if ("error" in checked) { setProblem(t(checked.error)); return; }
    setProblem("");
    if (await onRun(preset.key, () => patchWatchPreset(preset.key, { levels: checked.levels }))) setInputs(null);
  }
  const keys = (event: KeyboardEvent) => {
    if (event.nativeEvent.isComposing) return;
    if (event.key === "Enter") { event.preventDefault(); void save(); }
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); setInputs(null); setProblem(""); }
  };

  return <li data-testid="watch-preset" data-key={preset.key} data-enabled={preset.enabled ? "true" : "false"} data-hard={preset.hard ? "true" : undefined} className="flex min-w-0 flex-col gap-1.5 border-t border-line pt-3 first:border-t-0 first:pt-0">
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
      <span className={`min-w-0 text-body font-medium [overflow-wrap:anywhere] ${preset.enabled ? "text-ink" : "text-muted-foreground"}`}>{preset.title}</span>
      <span className="ml-auto flex items-center gap-2">
        {preset.hard
          ? <span data-testid="watch-preset-hard" className="text-small text-muted-foreground">{t("硬保证，不能关")}</span>
          : preset.editable
            ? <label className="flex min-h-11 items-center gap-2 text-small text-ink-2 md:min-h-0">
              <span data-testid="watch-preset-state">{preset.enabled ? t("开") : t("关")}</span>
              <Switch size="default" checked={preset.enabled} disabled={busy} aria-label={preset.title} data-testid="watch-preset-switch" onCheckedChange={enabled => void onRun(preset.key, () => patchWatchPreset(preset.key, { enabled }))} />
            </label>
            : <span data-testid="watch-preset-fixed" className="text-small text-muted-foreground">{t("不在这里调整")}</span>}
      </span>
    </div>
    {preset.text && <p data-testid="watch-preset-text" className={`m-0 text-small [overflow-wrap:anywhere] ${preset.enabled ? "text-ink-2" : "text-muted-foreground"}`}>{preset.text}</p>}
    {applies && <p className="m-0 text-caption text-muted-foreground [overflow-wrap:anywhere]">{t("适用于")} <span className="font-mono">{applies}</span></p>}
    {yields && <p data-testid="watch-preset-yields" className="m-0 text-caption text-muted-foreground [overflow-wrap:anywhere]">{yields}</p>}
    {inputs !== null
      ? <div className="flex min-w-0 flex-col gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
          {edit.map((level, i) => <label key={level.level} className="flex items-center gap-1.5 text-small text-ink-2">
            {level.label}
            <Input inputMode="decimal" value={inputs[i] ?? ""} autoFocus={i === 0} data-testid="watch-preset-input" aria-label={`${preset.title} · ${level.label}`} className="h-8 w-20 font-mono max-md:h-11" onChange={event => setInputs(previous => (previous ?? []).map((value, j) => (j === i ? event.target.value : value)))} onKeyDown={keys} />
            {unit}
          </label>)}
          <Button type="button" size="sm" data-testid="watch-preset-save" disabled={busy} className="max-md:h-11" onClick={() => void save()}>{t("保存")}</Button>
          <Button type="button" size="sm" variant="ghost" data-testid="watch-preset-cancel" className="max-md:h-11" onClick={() => { setInputs(null); setProblem(""); }}>{t("取消")}</Button>
        </div>
        {problem && <p role="alert" data-testid="watch-preset-problem" className="m-0 text-small text-danger">{problem}</p>}
      </div>
      : (preset.canEdit || preset.canReset) && <div className="flex flex-wrap items-center gap-x-1 gap-y-1">
        {preset.canEdit && <Button type="button" size="sm" variant="ghost" data-testid="watch-preset-edit" disabled={busy} aria-label={`${t("改门槛")} · ${preset.title}`} className="-ml-3 max-md:h-11" onClick={() => setInputs(edit.map(level => level.text))}>{t("改门槛")}</Button>}
        {preset.canReset && <Button type="button" size="sm" variant="ghost" data-testid="watch-preset-reset" disabled={busy} aria-label={`${t("恢复默认")} · ${preset.title}`} className={`max-md:h-11 ${preset.canEdit ? "" : "-ml-3"}`} onClick={() => void onRun(preset.key, () => resetWatchPreset(preset.key))}>{t("恢复默认")}</Button>}
      </div>}
    {error}
  </li>;
}

/** 灵敏度 and the 5-minute moves switch: a segmented control (one radio group, arrow keys move) with the sigma numbers of each choice in words below, and the switch with its sentence. */
function SensitivityBlock({ settings, busy, onRun }: { settings: AlertSettings; busy: boolean; onRun: (key: string, work: () => Promise<unknown>) => Promise<boolean> }) {
  const { t, locale } = useLocale();
  const view = settingsView(settings, locale);
  const colon = locale === "en-US" ? ": " : "：";
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const choose = (value: Sensitivity) => { if (value !== view.sensitivity) void onRun("settings", () => putAlertSettings({ sensitivity: value })); };
  const move = (event: KeyboardEvent, index: number) => {
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = (index + step + view.choices.length) % view.choices.length;
    refs.current[next]?.focus();
    choose(view.choices[next].value);
  };
  return <Block id="sensitivity" title="灵敏度">
    <p className="m-0 text-small text-muted-foreground">{t("决定一天的涨跌多大才值得提醒。σ 是这只股票平时一天的波动幅度。")}</p>
    <div role="radiogroup" aria-label={t("灵敏度")} data-testid="watch-sensitivity" className="grid grid-cols-3 gap-1 rounded-md border border-line bg-sunken p-1">
      {view.choices.map((choice, index) => {
        const on = choice.value === view.sensitivity;
        return <button key={choice.value} ref={node => { refs.current[index] = node; }} type="button" role="radio" aria-checked={on} tabIndex={on ? 0 : -1} disabled={busy} data-testid="watch-sensitivity-choice" data-value={choice.value}
          className={`min-h-11 rounded-sm px-2 text-small outline-none focus-visible:ring-2 focus-visible:ring-ring md:min-h-9 ${on ? "bg-surface font-medium text-ink shadow-xs" : "text-ink-2 hover:bg-accent"}`}
          onClick={() => choose(choice.value)} onKeyDown={event => move(event, index)}>{t(choice.label)}</button>;
      })}
    </div>
    <ul className="m-0 flex list-none flex-col gap-1 p-0">{view.choices.filter(choice => choice.words).map(choice => <li key={choice.value} data-testid="watch-sensitivity-words" data-value={choice.value} className={`text-small [overflow-wrap:anywhere] ${choice.value === view.sensitivity ? "text-ink" : "text-muted-foreground"}`}>
      <span className="font-medium">{t(choice.label)}</span>{colon}{choice.words}
    </li>)}</ul>
    <label className="flex min-h-11 items-center gap-3 border-t border-line pt-2 md:min-h-0">
      <span className="min-w-0 flex-1 text-small text-ink-2"><span className="font-medium text-ink">{t("5 分钟急动提醒")}</span><br />{t("持仓在 5 分钟内急涨急跌也提醒。默认关着。")}</span>
      <Switch size="default" checked={view.shortMoves} disabled={busy} aria-label={t("5 分钟急动提醒")} data-testid="watch-short-moves" onCheckedChange={shortMoves => void onRun("settings", () => putAlertSettings({ short_moves: shortMoves }))} />
    </label>
  </Block>;
}

/**
 * 规则 (the rules block of 它在帮你盯的, stage 5b-2): his own rules (delete here), the system defaults next to them (each can be turned off or given a new threshold; the stop price and filings are hard
 * guarantees and cannot), the sensitivity and the 5-minute moves switch, and one line on saying it in chat.  Its own read (`GET /agent-chat/watch`); a write is the owner's own act, so it goes straight to the
 * route, then the page reads again (the old rows stay on screen meanwhile).  A refusal shows the server's reason in the place of the row.  `onChanged` tells the overview (its count of what is watched).
 */
export function WatchRulesSection({ onChanged }: { onChanged: () => Promise<void> }) {
  const { t, locale } = useLocale();
  const colon = locale === "en-US" ? ": " : "：";
  const watch = useLoad(signal => getWatch(signal));
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<{ key: string; error: unknown } | null>(null);
  const data = watch.data;
  const rules = ruleRows(data?.rules);
  const presets = presetRows(data?.presets);

  async function run(key: string, work: () => Promise<unknown>): Promise<boolean> {
    setBusy(key); setFailure(null);
    try { await work(); await watch.reload(); void onChanged(); return true; }
    catch (error) { setFailure({ key, error }); return false; }
    finally { setBusy(null); }
  }
  async function remove(id: string, from: HTMLElement | null) {
    const yes = await confirm({ ...(from ? { returnFocus: from } : {}), title: t("删除这条规则？"), description: t("删除后它不再盯这一条，无法恢复。"), confirmLabel: t("删除"), cancelLabel: t("取消"), tone: "danger" });
    if (yes) await run(id, () => deleteWatchRule(id));
  }
  const shown = (key: string) => failure?.key === key ? <ErrorBar error={failure.error} className="mt-1" /> : null;

  return <div data-testid="watch-rules" className="flex min-w-0 flex-col gap-2">
    {watch.error != null && <ErrorBar error={watch.error} onRetry={() => void watch.reload()} retrying={watch.loading} />}
    {!data && watch.error == null && <DelayedSkeleton><div role="status" aria-busy="true" className="flex flex-col gap-2"><span className="sr-only">{t("正在读取")}</span>{[0, 1].map(i => <Skeleton key={i} className="h-20 w-full" />)}</div></DelayedSkeleton>}
    {data && <>
      <Block id="owner-rules" title="你定的规则">
        {rules.length === 0
          ? <p data-testid="watch-owner-rules-empty" className="m-0 text-small text-muted-foreground">{t("你还没有定过自己的规则。")}</p>
          : <ul className="m-0 flex list-none flex-col gap-3 p-0">{rules.map(rule => <li key={rule.id} data-testid="watch-owner-rule" data-id={rule.id} data-symbol={rule.symbol} className="flex min-w-0 flex-col gap-1.5 border-t border-line pt-3 first:border-t-0 first:pt-0">
            <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              <span className="font-mono text-body font-medium text-ink">{rule.symbol}</span>
              <StatusBadge kind={rule.status.kind} className="h-5">{t(rule.status.label)}</StatusBadge>
              <Button type="button" size="sm" variant="ghost" data-testid="watch-owner-rule-delete" disabled={busy !== null} aria-label={`${t("删除")} · ${rule.symbol} · ${rule.text}`} className="ml-auto text-danger max-md:h-11" onClick={event => void remove(rule.id, event.currentTarget)}>{t("删除")}</Button>
            </div>
            <p data-testid="watch-owner-rule-text" className="m-0 text-small text-ink [overflow-wrap:anywhere]">{rule.text}</p>
            {rule.override && <p data-testid="watch-owner-rule-override" className="m-0 text-caption text-muted-foreground [overflow-wrap:anywhere]">{rule.override === true ? t("它替代了对应的系统默认。") : rule.override}</p>}
            {rule.fired && <p data-testid="watch-owner-rule-fired" className="m-0 text-caption text-muted-foreground [overflow-wrap:anywhere]">{t("上次触发")}{colon}{rule.lastFired || t("还没触发过")}</p>}
            {shown(rule.id)}
          </li>)}</ul>}
      </Block>
      <Block id="presets" title="系统默认">
        {presets.length === 0
          ? <p data-testid="watch-presets-empty" className="m-0 text-small text-muted-foreground">{t("（没有）")}</p>
          : <ul className="m-0 flex list-none flex-col gap-3 p-0">{presets.map(preset => <PresetItem key={preset.key} preset={preset} busy={busy !== null} error={shown(preset.key)} onRun={run} />)}</ul>}
      </Block>
      <SensitivityBlock settings={data.settings} busy={busy !== null} onRun={run} />
      {shown("settings")}
      <p data-testid="watch-chat-hint" className="m-0 text-small text-muted-foreground">{t("在对话里也可以说，比如『英特尔跌 8% 提醒我』。")}</p>
    </>}
  </div>;
}
