import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { TagInput } from "@/components/TagInput";
import { ErrorBar } from "@/components/state/ErrorBar";
import { StatefulButton } from "@/components/state/StatefulButton";
import type { NewsSource, NewsSourceInput } from "../../../api/news-sources";
import { useLocale } from "../../../i18n";
import { KINDS, KIND_LABELS, MAX_ID, MAX_NAME, blankDraft, draftFromSource, inputFromDraft, normalizeMarket, normalizeTag, validateDraft, withName, type NewsDraft } from "./news-form.mjs";

/**
 * 新建 / 编辑新闻源 (design 4.11): a side drawer (the whole screen on a phone; one drawer at every width).  The ID of a new source is made from its name (and follows it until the reader types in the ID box); one that is empty, wrong
 * or already taken is said at once and nothing is sent; the ID of an existing source cannot be changed.  Markets, tags and spare addresses are tag boxes that only tidy what is typed (markets in capitals).  The request is the old form's, key for key.
 */
export function NewsDrawer({ open, onOpenChange, source, existing, save, returnFocus }: {
  open: boolean; onOpenChange: (open: boolean) => void;
  /** The source being edited; null for a new one. */
  source: NewsSource | null;
  /** The IDs of the sources there are. */
  existing: readonly string[];
  save: (input: NewsSourceInput) => Promise<void>;
  returnFocus?: () => void;
}) {
  const { t } = useLocale();
  const [draft, setDraft] = useState<NewsDraft>(blankDraft);
  const [tried, setTried] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  useEffect(() => { if (open) { setDraft(source ? draftFromSource(source) : blankDraft()); setTried(false); setFailure(null); } }, [open, source?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const editing = Boolean(source);
  const problems = useMemo(() => validateDraft(draft, { editing, existing }), [draft, editing, existing]);
  const said = (field: "id" | "url") => {
    const problem = problems.find(p => p.field === field);
    if (!problem) return undefined;
    const live = tried || (field === "url" ? draft.url.trim() !== "" : draft.id.trim() !== "" || (!draft.idTouched && draft.name.trim() !== ""));
    return live ? t(problem.message) : undefined;
  };
  const patch = (next: Partial<NewsDraft>) => setDraft(current => ({ ...current, ...next }));
  const press = () => {
    setTried(true);
    if (problems.length) return undefined;
    setFailure(null);
    return (async () => { try { await save(inputFromDraft(draft)); } catch (error) { setFailure(error); throw error; } })();
  };
  const idError = said("id"), urlError = said("url");
  return <Drawer open={open} onOpenChange={onOpenChange} direction="right" autoFocus>
    <DrawerContent data-testid="news-drawer" data-mode={editing ? "edit" : "new"} aria-describedby="news-drawer-description" onCloseAutoFocus={event => { event.preventDefault(); returnFocus?.(); }}
      className="data-[vaul-drawer-direction=right]:w-full data-[vaul-drawer-direction=right]:sm:max-w-lg">
      <DrawerHeader className="gap-2 border-b border-line">
        <DrawerTitle className="text-title-s">{t(editing ? "编辑新闻源" : "新建新闻源")}</DrawerTitle>
        <DrawerDescription id="news-drawer-description">{t("Agent 查询最新动态或运行例行简报时，会优先检索已启用的配置源。")}</DrawerDescription>
      </DrawerHeader>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4" data-testid="news-drawer-body">
        <Field>
          <FieldLabel htmlFor="news-name">{t("名称")}</FieldLabel>
          <Input id="news-name" data-testid="news-field-name" value={draft.name} maxLength={MAX_NAME} placeholder={t("例如：财联社电报 / Yahoo Finance")} onChange={event => setDraft(current => editing ? { ...current, name: event.target.value } : withName(current, event.target.value, existing))} />
        </Field>
        <Field data-invalid={Boolean(idError) || undefined}>
          <FieldLabel htmlFor="news-id">{t("源 ID（英文标识）")}</FieldLabel>
          <Input id="news-id" data-testid="news-field-id" value={draft.id} disabled={editing} maxLength={MAX_ID} aria-invalid={Boolean(idError) || undefined} aria-describedby="news-id-hint" placeholder={t("例如：cls-telegraph 或 wsj-markets-rss")} className="font-mono" onChange={event => patch({ id: event.target.value, idTouched: true })} />
          <FieldDescription id="news-id-hint">{t(editing ? "已有新闻源的 ID 不能改。" : "按名称自动生成，可以改。")}</FieldDescription>
          {idError && <FieldError data-testid="news-id-error">{idError}</FieldError>}
        </Field>
        <Field>
          <FieldLabel htmlFor="news-kind">{t("类型")}</FieldLabel>
          <Select value={draft.kind} onValueChange={kind => patch({ kind: kind as NewsDraft["kind"] })}>
            <SelectTrigger id="news-kind" data-testid="news-field-kind" className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>{KINDS.map(kind => <SelectItem key={kind} value={kind}>{t(KIND_LABELS[kind])}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <Field data-invalid={Boolean(urlError) || undefined}>
          <FieldLabel htmlFor="news-url">{t("抓取地址（URL）")}</FieldLabel>
          <Input id="news-url" data-testid="news-field-url" type="url" inputMode="url" value={draft.url} aria-invalid={Boolean(urlError) || undefined} placeholder="https://finance.yahoo.com/news/rssindex" onChange={event => patch({ url: event.target.value })} />
          {urlError && <FieldError data-testid="news-url-error">{urlError}</FieldError>}
        </Field>
        <Field>
          <FieldLabel htmlFor="news-homepage">{t("站点主页（可选，供 REA 发现备用订阅源）")}</FieldLabel>
          <Input id="news-homepage" data-testid="news-field-homepage" type="url" inputMode="url" value={draft.homepage} placeholder="https://finance.yahoo.com/news/" onChange={event => patch({ homepage: event.target.value })} />
        </Field>
        <Field>
          <FieldLabel htmlFor="news-markets">{t("市场")}</FieldLabel>
          <TagInput id="news-markets" testid="news-field-markets" value={draft.markets} onChange={markets => patch({ markets })} normalize={normalizeMarket} invalidLabel={t("不是有效项")} placeholder="US, CN, HK" label={t("市场")} describedBy="news-tags-hint" />
        </Field>
        <Field>
          <FieldLabel htmlFor="news-tags">{t("标签")}</FieldLabel>
          <TagInput id="news-tags" testid="news-field-tags" value={draft.tags} onChange={tags => patch({ tags })} normalize={normalizeTag} invalidLabel={t("不是有效项")} placeholder="macro, flash, us-stocks" label={t("标签")} describedBy="news-tags-hint" />
        </Field>
        <Field>
          <FieldLabel htmlFor="news-alternates">{t("备用地址（可选）")}</FieldLabel>
          <TagInput id="news-alternates" testid="news-field-alternates" value={draft.alternates} onChange={alternates => patch({ alternates })} normalize={normalizeTag} invalidLabel={t("不是有效项")} placeholder="https://..." label={t("备用地址（可选）")} describedBy="news-tags-hint" />
          <FieldDescription id="news-tags-hint">{t("回车或逗号加入，退格删除最后一个。")}</FieldDescription>
        </Field>
        <Field orientation="horizontal" className="items-center justify-between">
          <FieldLabel htmlFor="news-enabled">{t("立即启用")}</FieldLabel>
          <Switch id="news-enabled" data-testid="news-field-enabled" checked={draft.enabled} onCheckedChange={enabled => patch({ enabled })} />
        </Field>
        <Field orientation="horizontal" className="items-center justify-between">
          <FieldLabel htmlFor="news-rea">{t("允许 REA 自动诊断修复")}</FieldLabel>
          <Switch id="news-rea" data-testid="news-field-rea" checked={draft.reaRepair} onCheckedChange={reaRepair => patch({ reaRepair })} />
        </Field>
      </div>
      <div className="flex flex-col gap-2 border-t border-line p-4">
        {failure != null && <ErrorBar error={failure} />}
        <div className="flex items-center justify-end gap-2">
          <Button type="button" variant="ghost" data-testid="news-cancel" className="max-sm:h-11" onClick={() => onOpenChange(false)}>{t("取消")}</Button>
          <StatefulButton type="button" data-testid="news-save" className="max-sm:h-11" onClick={press}>{t("保存")}</StatefulButton>
        </div>
      </div>
    </DrawerContent>
  </Drawer>;
}
