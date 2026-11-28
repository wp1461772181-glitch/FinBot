import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Field, FieldContent, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { TagInput } from "@/components/TagInput";
import { Skeleton } from "@/components/state/Skeleton";
import type { Bot, BotTool, ModelCatalog } from "../../api/bots";
import { useLocale } from "../../i18n";
import { botModelLabel, keyStatusLabel, MAX_FOCUS_COMPANIES, parseFocusSymbols, toggleTool, toolEnabled } from "../../bot-form-items.mjs";

import { groupTools, focusSymbols, scopeSummary, withFocusSymbols, withFocusTheme, type BotDraft } from "../../bot-settings-form.mjs";
import { toolLabel } from "../../agent-tool-labels.mjs";
import { paths } from "../../routes.mjs";

/** What every form section is given: the draft, a way to change it, whether a save is running, and what the fields are told about themselves. */
export type FormProps = { draft: BotDraft; update: (next: BotDraft) => void; disabled: boolean };

const DEFAULT_ITEM = "__default__"; // Radix Select has no empty item value: 默认 is this one, and means null

/** 档案: name, title, description (with its count), group, pinned, hidden. */
export function ProfileFields({ draft, update, disabled, nameError, isDefault }: FormProps & { nameError?: string; isDefault: boolean }) {
  const { t } = useLocale();
  const patch = (next: Partial<BotDraft>) => update({ ...draft, ...next });
  return <>
    <Field data-invalid={Boolean(nameError) || undefined}>
      <FieldLabel htmlFor="bot-name">{t("名字")}</FieldLabel>
      <Input id="bot-name" value={draft.name} maxLength={40} disabled={disabled} aria-invalid={Boolean(nameError) || undefined} aria-describedby={nameError ? "bot-name-error" : undefined}
        placeholder={t("例如：读财报")} onChange={(e) => patch({ name: e.target.value })} />
      {nameError && <FieldError id="bot-name-error">{t(nameError)}</FieldError>}
    </Field>
    <Field>
      <FieldLabel htmlFor="bot-title">{t("头衔")}</FieldLabel>
      <Input id="bot-title" value={draft.title} maxLength={60} disabled={disabled} placeholder={t("例如：财报解读")} onChange={(e) => patch({ title: e.target.value })} />
    </Field>
    <Field>
      <div className="flex items-baseline justify-between gap-3">
        <FieldLabel htmlFor="bot-description">{t("说明")}</FieldLabel>
        <span data-testid="description-count" aria-live="off" className="font-mono text-caption text-muted-foreground">{draft.description.length} / 4000</span>
      </div>
      <Textarea id="bot-description" rows={5} value={draft.description} maxLength={4000} disabled={disabled} placeholder={t("它的工作是什么、怎么做、什么时候该通知你。")} onChange={(e) => patch({ description: e.target.value })} />
    </Field>
    <Field>
      <FieldLabel htmlFor="bot-group">{t("分组")}</FieldLabel>
      <Input id="bot-group" value={draft.group ?? ""} maxLength={40} disabled={disabled} placeholder={t("例如：公司")} onChange={(e) => patch({ group: e.target.value })} />
    </Field>
    <Field orientation="horizontal">
      <Switch id="bot-pinned" checked={Boolean(draft.pinned)} disabled={disabled} onCheckedChange={(on) => patch({ pinned: on })} />
      <FieldContent><FieldLabel htmlFor="bot-pinned">{t("置顶")}</FieldLabel></FieldContent>
    </Field>
    {!isDefault && <Field orientation="horizontal">
      <Switch id="bot-hidden" checked={Boolean(draft.hidden)} disabled={disabled} onCheckedChange={(on) => patch({ hidden: on })} />
      <FieldContent><FieldLabel htmlFor="bot-hidden">{t("在侧栏隐藏")}</FieldLabel></FieldContent>
    </Field>}
  </>;
}

/** 关注: the companies as tags (the existing ticker check decides what a tag may be), and the theme. */
export function FocusFields({ draft, update, disabled, bot }: FormProps & { bot: Bot }) {
  const { t } = useLocale();
  const symbols = focusSymbols(draft);
  const hint = symbols.length === 1 ? `${t("没点名公司的问题默认问")} ${symbols[0]}` : symbols.length > 1 ? t("关注多家公司时，没有默认公司。") : t("不填就没有默认公司。");
  return <>
    <Field>
      <FieldLabel htmlFor="bot-companies">{t("关注公司（可空）")}</FieldLabel>
      <TagInput id="bot-companies" testid="focus-tags" value={symbols} onChange={(next) => update(withFocusSymbols(draft, next))} disabled={disabled} max={MAX_FOCUS_COMPANIES}
        normalize={(raw) => raw.trim().toUpperCase()} validate={(item) => parseFocusSymbols(item).companies.length === 1} invalidLabel={t("不是股票代码")} limitLabel={t("最多 20 家。")}
        placeholder="AAPL, MSFT" label={t("关注公司（可空）")} describedBy="bot-companies-hint" />
      <FieldDescription id="bot-companies-hint">{hint}{bot.default_company && symbols.length === 1 && bot.default_company.symbol === symbols[0] && bot.default_company.company ? ` · ${bot.default_company.company}` : ""} · {t("回车或逗号加入，退格删除最后一个。")}</FieldDescription>
    </Field>
    <Field>
      <FieldLabel htmlFor="bot-theme">{t("关注主题（可空）")}</FieldLabel>
      <Input id="bot-theme" value={draft.focus.theme ?? ""} maxLength={200} disabled={disabled} placeholder={t("例如：AI 资本开支")} onChange={(e) => update(withFocusTheme(draft, e.target.value))} />
    </Field>
  </>;
}

/** 模型: the model (the chat's model badge changes the same field: a save here shows there, and the other way round).  No effort choice: how
 * hard to think is the model's call, question by question (owner 11-22; the picker was left in until 11-28). */
export function ModelFields({ draft, update, disabled, bot, catalog }: FormProps & { bot: Bot; catalog: ModelCatalog | null }) {
  const { t } = useLocale();
  const picked = botModelLabel({ ...bot, model: draft.model }, catalog);
  return <>
    <Field>
      <FieldLabel htmlFor="bot-model">{t("模型")}</FieldLabel>
      <Select value={draft.model ?? DEFAULT_ITEM} disabled={disabled || !catalog} onValueChange={(value) => update({ ...draft, model: value === DEFAULT_ITEM ? null : value })}>
        <SelectTrigger id="bot-model" data-testid="model-select" className="w-full"><SelectValue /></SelectTrigger>
        <SelectContent>
          <SelectItem value={DEFAULT_ITEM}>{t("服务器默认模型")}{catalog?.default ? ` (${catalog.default})` : ""}</SelectItem>
          {catalog?.models.map((m) => <SelectItem key={m.name} value={m.name}>{m.display_name || m.name} · {t(keyStatusLabel(m))}</SelectItem>)}
        </SelectContent>
      </Select>
      <FieldDescription>{t("换模型后下一轮生效。key 只在服务器上。")}</FieldDescription>
      {picked.name && !picked.usable && catalog && <p data-testid="model-missing-key" className="flex flex-wrap items-center gap-x-2 text-small text-ink">
        <span>{t("缺 key，去设置里补上")}</span><Link to={paths.settings("models")} className="font-medium text-brand underline underline-offset-4">{t("去设置补 key")}</Link></p>}
    </Field>
    <p data-testid="effort-note" className="text-small text-muted-foreground">{t("思考深度不用设置：它按每个问题自己决定，从浅到深。")}</p>
  </>;
}

/** 工具: the scope as switches by group.  null is every tool (the server's meaning); 全部打开 goes back to null and never sends a full list. */
export function ToolFields({ draft, update, disabled, tools, loaded }: FormProps & { tools: BotTool[]; loaded: boolean }) {
  const { t } = useLocale();
  const names = tools.map((tool) => tool.name);
  const summary = scopeSummary(draft.tool_scope, names.length);
  if (!loaded) return <div className="grid gap-2" aria-busy="true"><Skeleton className="h-8" /><Skeleton className="h-8" /><Skeleton className="h-8" /></div>;
  return <>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p data-testid="tool-summary" className="text-small text-ink">{t("工具范围")} · {summary.all ? t("全部工具") : `${summary.count} / ${summary.total}`}</p>
      <Button type="button" variant="outline" size="sm" disabled={disabled || summary.all} onClick={() => update({ ...draft, tool_scope: null })}>{t("全部打开")}</Button>
    </div>
    {groupTools(tools).map((group) => <fieldset key={group.id} data-tool-group={group.id} className="m-0 grid min-w-0 gap-1 border-0 p-0" disabled={disabled}>
      <legend className="mb-1 p-0 text-small font-medium text-ink">{t(group.label)}</legend>
      <ul className="m-0 grid list-none gap-0.5 p-0">
        {group.tools.map((tool) => {
          const id = `tool-${tool.name}`;
          return <li key={tool.name} className="flex min-h-9 items-center gap-3 rounded-sm px-1 max-md:min-h-11">
            <Switch id={id} data-tool={tool.name} size="sm" checked={toolEnabled(draft.tool_scope, tool.name)} onCheckedChange={() => update({ ...draft, tool_scope: toggleTool(draft.tool_scope, tool.name, names) })} />
            <label htmlFor={id} className="min-w-0 flex-1 cursor-pointer text-small text-ink">{t(toolLabel(tool.name))}</label>
            {group.id === "write" && <span className="shrink-0 text-caption text-muted-foreground">{t("需确认")}</span>}
          </li>;
        })}
      </ul>
    </fieldset>)}
    <p className="text-small text-muted-foreground">{t("提问、引用、计算等基础工具总是开着。范围外的工具这个 bot 调不到。")}</p>
    <p className="text-small text-muted-foreground">{t("写入类工具只是提醒：它们要不要你确认，由系统的确认流程决定，这里的开关不改变它。")}</p>
  </>;
}

/** 通知: the daily cap (the old form's field, kept for every bot). */
export function NotifyCapField({ draft, update, disabled }: FormProps) {
  const { t } = useLocale();
  return <Field>
    <FieldLabel htmlFor="bot-cap">{t("每日通知上限")}</FieldLabel>
    <Input id="bot-cap" type="number" inputMode="numeric" min={0} max={50} className="max-w-32" value={draft.daily_notify_cap ?? 5} disabled={disabled}
      onChange={(e) => update({ ...draft, daily_notify_cap: Math.max(0, Math.min(50, Number(e.target.value) || 0)) })} />
    <FieldDescription>{t("这个 bot 一天最多主动通知你几次（0 到 50）。")}</FieldDescription>
  </Field>;
}

