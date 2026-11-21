import { useRef } from "react";
import { Ellipsis, SquarePen, Star, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { StatusBadge } from "@/components/StatusBadge";
import type { CatalogModel } from "../../../api/bots";
import { keyStatusLabel } from "../../../bot-form-items.mjs";
import { useLocale } from "../../../i18n";
import { CATALOG } from "../../../model-profiles.mjs";

/**
 * One model of the server's catalog (design 4.12): its name, provider and model ID, whether its key is there (the words, plus the head and tail the server sends as key_hint; never the whole key), whether it is the default and where it comes from.
 * A model saved on the server has 编辑 and, in 「…」, 设为默认 and 删除.  A model that comes from the server's catalog file has none of them and says why.
 */
export function ModelCard({ model, busy, onEdit, onDefault, onDelete }: { model: CatalogModel; busy: boolean; onEdit: (opener: HTMLElement | null) => void; onDefault: () => void; onDelete: (opener: HTMLElement | null) => void }) {
  const { t } = useLocale();
  const edit = useRef<HTMLButtonElement>(null), menu = useRef<HTMLButtonElement>(null);
  const mine = model.origin === "server";
  const ready = model.key_status === "configured";
  return <article data-testid="model-card" data-model={model.name} data-origin={model.origin} data-default={model.is_default || undefined} aria-label={model.display_name || model.name} className="flex min-w-0 flex-col gap-2.5 rounded-md border border-line bg-background p-3.5">
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <h3 className="min-w-0 text-body font-medium text-ink [overflow-wrap:anywhere]">{model.display_name || model.name}</h3>
      {model.is_default && <span data-testid="model-default-mark"><StatusBadge kind="neutral" className="h-5">{t("默认")}</StatusBadge></span>}
    </div>
    <p className="m-0 text-small text-ink-2 [overflow-wrap:anywhere]">{t(CATALOG.find((x) => x.provider === model.provider)?.label ?? model.provider)} · <span className="font-mono">{model.model}</span></p>
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-small text-muted-foreground">
      <span data-testid="model-key-status" data-status={model.key_status}><StatusBadge kind={ready ? "success" : "failure"} className="h-5">{t(keyStatusLabel(model))}</StatusBadge></span>
      {model.key_source === "env" && model.key_env && <span>{t("环境变量")} <span className="font-mono">{model.key_env}</span></span>}
      {model.key_source === "vault" && model.key_hint && <span data-testid="model-key-hint" className="font-mono">{model.key_hint}</span>}
      <span>· <span className="font-mono">{model.name}</span></span>
      <span data-testid="model-origin">· {t(mine ? "已保存" : "来自配置文件")}</span>
    </div>
    {mine
      ? <div className="mt-auto flex items-center gap-2 pt-1">
        <Button ref={edit} type="button" variant="outline" size="sm" disabled={busy} data-testid="model-edit" className="max-sm:h-11" onClick={() => onEdit(edit.current)}><SquarePen aria-hidden="true" />{t("编辑")}</Button>
        <span className="ml-auto" />
        <DropdownMenu modal={false}>
          <DropdownMenuTrigger asChild><Button ref={menu} type="button" variant="ghost" size="icon" disabled={busy} aria-label={`${t("更多操作")} ${model.display_name || model.name}`} data-testid="model-menu" className="size-9 max-sm:size-11"><Ellipsis aria-hidden="true" /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {!model.is_default && <DropdownMenuItem data-testid="model-set-default" onSelect={onDefault}><Star aria-hidden="true" />{t("设为默认")}</DropdownMenuItem>}
            {!model.is_default && <DropdownMenuSeparator />}
            <DropdownMenuItem data-testid="model-delete" variant="destructive" onSelect={() => onDelete(menu.current)}><Trash2 aria-hidden="true" />{t("删除")}</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      : <p data-testid="model-readonly-note" className="m-0 mt-auto pt-1 text-small text-muted-foreground">{t("服务器配置文件里的模型只能在服务器上改。")}</p>}
  </article>;
}
