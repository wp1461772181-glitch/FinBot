import { useRef, useState } from "react";
import { ChevronRight, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatusBadge } from "@/components/StatusBadge";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import { confirm } from "@/components/state/confirm";
import { confirmProfileItem, createProfileItem, deleteProfileItem, listProfileItems, restoreProfileItem, updateProfileItem, type ProfileItem } from "../../../api/memory";
import { useLocale } from "../../../i18n";
import { archiveNote, exampleLines, isSettled, layerLabel, manualItemDraft, originLabel, profileGroups, profileLayers, proposedItems, seenLine, templateNote } from "../../../memory-items.mjs";
import { useLoad } from "../../use-load";
import { KINDS, KIND_LABELS, MAX_TEXT, canSaveEdit, isInferred, scopeChoices } from "./memory-view.mjs";

const GLOBAL = "__global__"; // Radix Select has no empty item value
type Layer = { key: string; label: string; items: ProfileItem[] };

/**
 * 画像 (design 4.11): what the agent should remember about the owner, in layers (全局 first, then each bot, then the bots that are gone).  Each item says its kind and where it came from: what the owner said or
 * typed is plain, what the model inferred is marked 推断 in the opinion colour and carries 确认.  The owner's own words are quoted in the fact material.  The add row is on top; 已归档 is a fold.
 * Every request is the old page's (src/api/memory.ts): the same bodies, which memory-items.mjs makes.  `onChanged` (4e): called after a write succeeded, so the overview above and below re-reads its counts and the block the model sees.
 */
export function ProfilePanel({ onChanged }: { onChanged?: () => void } = {}) {
  const { t, locale } = useLocale();
  const data = useLoad(signal => listProfileItems(signal));
  const items = data.data?.items ?? null, bots = data.data?.bots ?? [];
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const [draft, setDraft] = useState<{ kind: ProfileItem["kind"]; text: string; layer: string }>({ kind: "preference", text: "", layer: "" });
  const addInput = useRef<HTMLInputElement>(null);

  async function run(id: string, work: () => Promise<unknown>): Promise<boolean> {
    setBusy(id); setError(null);
    try { await work(); await data.reload(); onChanged?.(); return true; }
    catch (failure) { setError(failure); return false; }
    finally { setBusy(null); }
  }
  async function remove(item: ProfileItem, from: HTMLElement | null) {
    const yes = await confirm({ ...(from ? { returnFocus: from } : {}), title: t("删除这条记忆？"), description: t("之后的对话不再按它回答。"), confirmLabel: t("删除"), cancelLabel: t("取消"), tone: "danger", hold: true });
    if (yes) await run(item.id, () => deleteProfileItem(item.id));
  }
  async function saveEdit() {
    if (!editing || !canSaveEdit(editing.text)) return;
    const { id, text } = editing;
    if (await run(id, () => updateProfileItem(id, { text: text.trim() }))) setEditing(null);
  }
  async function add() {
    const checked = manualItemDraft(draft) as { fields?: { kind: ProfileItem["kind"]; text: string; bot_id: string | null }; error?: string };
    if (!checked.fields) { setError(checked.error); return; }
    const fields = checked.fields;
    if (await run("new", () => createProfileItem(fields))) { setDraft(current => ({ ...current, text: "" })); addInput.current?.focus(); }
  }

  const layers = (profileLayers(items ?? [], bots) as Layer[]).filter(layer => layer.items.length > 0);
  const archived = (profileGroups(items ?? []) as { archived: ProfileItem[] }).archived;
  const proposed = proposedItems(items ?? []) as ProfileItem[];
  const empty = (items ?? []).every(item => item.status !== "active" && item.status !== "proposed");
  const layerTitle = (layer: Layer) => layer.key === "global" ? t("全局") : layer.key === "gone" ? t("已删除的 bot") : layer.label;
  const kindText = (kind: ProfileItem["kind"]) => t(KIND_LABELS[kind] ?? kind);

  return <div data-testid="memory-profile" className="flex min-w-0 flex-col gap-4">
    <div className="flex flex-col gap-1.5">
      <p data-testid="memory-note-profile" className="max-w-3xl text-small text-ink-2">{t("在这里直接写下要 Agent 记住的事，或对 Agent 说「记住……」「以后都……」并在确认卡上点同意；说「忘掉……」即可撤回。Agent 也会从你自己说的话里推断偏好，标为“推断”，你可以在这里确认或删除。画像只是偏好，不是证据，也不授权任何操作。")}</p>
      <p data-testid="memory-note-scope" className="max-w-3xl text-small text-muted-foreground">{t("全局：每个 bot 都用。本 bot：只有这个 bot 和默认 bot「助理」能读。可以在每条的“范围”里改。")}</p>
    </div>
    <div role="group" aria-label={t("添加")} data-testid="memory-add" className="flex flex-col gap-2 rounded-md border border-line bg-surface p-3 md:flex-row md:items-end">
      <div className="flex flex-col gap-1.5 md:w-52">
        <label id="memory-add-scope-label" className="text-small font-medium text-ink">{t("范围")}</label>
        <Select value={draft.layer || GLOBAL} onValueChange={value => setDraft(current => ({ ...current, layer: value === GLOBAL ? "" : value }))}>
          <SelectTrigger aria-labelledby="memory-add-scope-label" data-testid="memory-add-scope" className="w-full max-md:h-11"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value={GLOBAL}>{t("全局（所有 bot）")}</SelectItem>{bots.map(bot => <SelectItem key={bot.id} value={bot.id}>{t("本 bot")} · {bot.name}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      <div className="flex flex-col gap-1.5 md:w-40">
        <label id="memory-add-kind-label" className="text-small font-medium text-ink">{t("类型")}</label>
        <Select value={draft.kind} onValueChange={value => setDraft(current => ({ ...current, kind: value as ProfileItem["kind"] }))}>
          <SelectTrigger aria-labelledby="memory-add-kind-label" data-testid="memory-add-kind" className="w-full max-md:h-11"><SelectValue /></SelectTrigger>
          <SelectContent>{KINDS.map(kind => <SelectItem key={kind} value={kind}>{kindText(kind)}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <label htmlFor="memory-add-text" className="text-small font-medium text-ink">{t("要记住的内容")}</label>
        <Input ref={addInput} id="memory-add-text" data-testid="memory-add-text" value={draft.text} maxLength={MAX_TEXT} placeholder={t("例如：金额都用亿美元；我主要看半导体")} className="max-md:h-11" onChange={event => setDraft(current => ({ ...current, text: event.target.value }))} onKeyDown={event => { if (event.key === "Enter" && !event.nativeEvent.isComposing) { event.preventDefault(); if (draft.text.trim() && busy !== "new") void add(); } }} />
      </div>
      <Button type="button" data-testid="memory-add-submit" disabled={busy === "new" || !draft.text.trim()} className="max-md:h-11" onClick={() => void add()}><Plus aria-hidden="true" />{t("添加")}</Button>
    </div>
    {error != null && <ErrorBar {...(typeof error === "string" ? { message: t(error) } : { error })} />}
    {data.error != null && <ErrorBar error={data.error} onRetry={() => void data.reload()} retrying={data.loading} />}
    {!items && data.loading && <DelayedSkeleton><div role="status" aria-busy="true" className="flex flex-col gap-3"><span className="sr-only">{t("正在读取")}</span>{[0, 1, 2].map(i => <Skeleton key={i} className="h-20 w-full" />)}</div></DelayedSkeleton>}
    {items && empty && <div data-testid="memory-empty" className="rounded-md border border-line bg-surface"><EmptyState title={t("还没有画像条目。")} /></div>}
    {layers.map(layer => <section key={layer.key} data-testid="memory-layer" data-layer={layer.key} aria-label={layerTitle(layer)} className="flex min-w-0 flex-col gap-2">
      <h2 className="text-title-s text-ink">{layerTitle(layer)}<span className="ml-2 font-mono text-caption font-normal text-muted-foreground">{layer.items.length}</span></h2>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">{layer.items.map(item => {
        const mine = editing?.id === item.id, choices = scopeChoices(item, bots);
        return <li key={item.id} data-testid="memory-item" data-item={item.id} data-origin={item.origin} className="flex min-w-0 flex-col gap-2 rounded-md border border-line bg-surface p-3">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span data-testid="memory-kind"><StatusBadge kind="neutral" className="h-5">{kindText(item.kind)}</StatusBadge></span>
            <span data-testid="memory-origin" data-inferred={isInferred(item) ? "true" : "false"}><StatusBadge kind={isInferred(item) ? "opinion" : "neutral"} className="h-5">{t(originLabel(item.origin))}</StatusBadge></span>
            {isSettled(item) && <span data-testid="memory-settled"><StatusBadge kind="neutral" className="h-5">{t("长期")}</StatusBadge></span>}
            {templateNote(item, locale) && <span data-testid="memory-template"><StatusBadge kind="neutral" className="h-5">{templateNote(item, locale)?.badge}</StatusBadge></span>}
            {!mine && <p className="min-w-0 flex-1 basis-60 text-body font-medium text-ink [overflow-wrap:anywhere]">{item.text}</p>}
          </div>
          {mine && <Input value={editing.text} maxLength={MAX_TEXT} aria-label={t("编辑")} data-testid="memory-edit-input" autoFocus className="max-md:h-11" onChange={event => setEditing({ id: item.id, text: event.target.value })}
            onKeyDown={event => { if (event.nativeEvent.isComposing) return; if (event.key === "Enter") { event.preventDefault(); void saveEdit(); } if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); setEditing(null); } }} />}
          {templateNote(item, locale)
            ? <p data-testid="memory-template-note" className="m-0 text-small text-muted-foreground">{templateNote(item, locale)?.line}</p>
            : item.quote?.trim() && <blockquote data-testid="memory-quote" className="material-fact m-0 px-3 py-2 font-quote text-small text-ink">“{item.quote}”</blockquote>}
          {seenLine(item, locale) && <p data-testid="memory-seen" className="m-0 font-mono text-caption text-muted-foreground">{t(seenLine(item, locale))}</p>}
          <div className="flex flex-wrap items-center gap-2">
            <Select value={item.bot_id ?? GLOBAL} disabled={busy === item.id} onValueChange={value => { const target = value === GLOBAL ? null : value; void run(item.id, () => updateProfileItem(item.id, { bot_id: target })); }}>
              <SelectTrigger size="sm" aria-label={`${t("范围")} · ${item.text}`} data-testid="memory-scope" className="w-44 max-md:h-11"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value={GLOBAL}>{t("全局")}</SelectItem>
                {choices.bots.map(bot => <SelectItem key={bot.id} value={bot.id}>{bot.name}</SelectItem>)}
                {choices.gone && item.bot_id && <SelectItem value={item.bot_id}>{t("已删除的 bot")}</SelectItem>}
              </SelectContent>
            </Select>
            <span className="ml-auto" />
            {mine
              ? <><Button type="button" size="sm" data-testid="memory-save" disabled={busy === item.id || !canSaveEdit(editing.text)} className="max-md:h-11" onClick={() => void saveEdit()}>{t("保存")}</Button>
                  <Button type="button" size="sm" variant="ghost" data-testid="memory-cancel" className="max-md:h-11" onClick={() => setEditing(null)}>{t("取消")}</Button></>
              : <Button type="button" size="sm" variant="ghost" data-testid="memory-edit" disabled={busy === item.id} aria-label={`${t("编辑")} · ${item.text}`} className="max-md:h-11" onClick={() => setEditing({ id: item.id, text: item.text })}>{t("编辑")}</Button>}
            {isInferred(item) && <Button type="button" size="sm" variant="outline" data-testid="memory-confirm" disabled={busy === item.id} aria-label={`${t("确认")} · ${item.text}`} className="max-md:h-11" onClick={() => void run(item.id, () => confirmProfileItem(item.id))}>{t("确认")}</Button>}
            <Button type="button" size="sm" variant="ghost" data-testid="memory-delete" disabled={busy === item.id} aria-label={`${t("删除")} · ${item.text}`} className="text-danger max-md:h-11" onClick={event => void remove(item, event.currentTarget)}>{t("删除")}</Button>
          </div>
        </li>;
      })}</ul>
    </section>)}
    {proposed.length > 0 && <section data-testid="memory-proposed" aria-labelledby="memory-proposed-title" className="flex min-w-0 flex-col gap-2">
      <h2 id="memory-proposed-title" className="text-title-s text-ink">{t("我的推测（未经你确认）")}<span className="ml-2 font-mono text-caption font-normal text-muted-foreground">{proposed.length}</span></h2>
      <p data-testid="memory-proposed-note" className="max-w-3xl text-small text-ink-2">{t("这些是我从你最近的对话里归纳的，只影响回答的详略和先后，不影响结论。对的点「对」，不对的点「不对」。")}</p>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">{proposed.map(item => <li key={item.id} data-testid="memory-proposed-item" data-item={item.id} className="flex min-w-0 flex-col gap-2 rounded-md border border-line bg-surface p-3">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span data-testid="memory-kind"><StatusBadge kind="neutral" className="h-5">{kindText(item.kind)}</StatusBadge></span>
          <p className="min-w-0 flex-1 basis-60 text-body font-medium text-ink [overflow-wrap:anywhere]">{item.text}</p>
        </div>
        <ul data-testid="memory-examples" className="m-0 flex list-none flex-col gap-1 p-0">{exampleLines(item).map(example => <li key={example.key} data-testid="memory-example" className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-small text-muted-foreground">
          <q className="min-w-0 font-quote [overflow-wrap:anywhere]">{example.quote}</q>{example.date && <span className="font-mono text-caption">{example.date}</span>}
        </li>)}</ul>
        <div className="flex flex-wrap items-center gap-2">
          <span className="ml-auto" />
          <Button type="button" size="sm" variant="outline" data-testid="memory-proposed-yes" disabled={busy === item.id} aria-label={`${t("对")} · ${item.text}`} className="max-md:h-11" onClick={() => void run(item.id, () => confirmProfileItem(item.id))}>{t("对")}</Button>
          <Button type="button" size="sm" variant="ghost" data-testid="memory-proposed-no" disabled={busy === item.id} aria-label={`${t("不对")} · ${item.text}`} className="max-md:h-11" onClick={() => void run(item.id, () => deleteProfileItem(item.id))}>{t("不对")}</Button>
        </div>
      </li>)}</ul>
    </section>}
    {archived.length > 0 && <Collapsible data-testid="memory-archived" className="rounded-md border border-line bg-surface">
      <CollapsibleTrigger className="group/fold flex min-h-11 w-full items-center gap-2 rounded-md px-3 text-left text-body text-ink outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground transition-transform group-data-[state=open]/fold:rotate-90 motion-reduce:transition-none" />{t("已归档")}<span className="font-mono text-caption text-muted-foreground">· {archived.length}</span>
      </CollapsibleTrigger>
      <CollapsibleContent><ul className="m-0 flex list-none flex-col gap-2 border-t border-line p-3">{archived.map(item => { const note = archiveNote(item, locale); return <li key={item.id} data-testid="memory-archived-item" data-item={item.id} className="flex min-w-0 flex-wrap items-center gap-2">
        <StatusBadge kind="neutral" className="h-5">{kindText(item.kind)}</StatusBadge>
        <StatusBadge kind="neutral" className="h-5">{item.bot_id ? (item.bot_name ?? t("已删除的 bot")) : t(layerLabel(item))}</StatusBadge>
        <span className="min-w-0 flex-1 basis-48 text-small text-ink-2 [overflow-wrap:anywhere]">{item.text}</span>
        {(note.reason || note.date) && <p data-testid="memory-archived-note" className="m-0 w-full basis-full text-caption text-muted-foreground">{note.reason && <span data-testid="memory-archived-reason">{t(note.reason)}</span>}{note.reason && note.date && " · "}{note.date && <span className="font-mono">{t(note.date)}</span>}</p>}
        <Button type="button" size="sm" variant="outline" data-testid="memory-restore" disabled={busy === item.id} aria-label={`${t("恢复")} · ${item.text}`} className="max-md:h-11" onClick={() => void run(item.id, () => restoreProfileItem(item.id))}>{t("恢复")}</Button>
        <Button type="button" size="sm" variant="ghost" disabled={busy === item.id} aria-label={`${t("删除")} · ${item.text}`} className="text-danger max-md:h-11" onClick={event => void remove(item, event.currentTarget)}>{t("删除")}</Button>
      </li>; })}</ul></CollapsibleContent>
    </Collapsible>}
  </div>;
}
