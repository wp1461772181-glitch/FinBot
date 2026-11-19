import { CopyPlus, Download, Ellipsis, SquarePen, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { StatusBadge } from "@/components/StatusBadge";
import { useRef } from "react";
import type { Skill } from "../../../api/skills-core";
import { useLocale } from "../../../i18n";
import { ToolChips } from "./ToolChip";
import { hasSwitch, isEditable } from "./skill-form.mjs";

const ORIGIN_LABELS = { builtin: "内置", mine: "我的", imported: "导入的" } as const;

/**
 * One skill (design 4.11): its name, where it comes from (a badge: a draft waits for a check, the others are plain), the version, the one-line description, the tools it may use and the switch.
 * The main button is 编辑 (or 核对并保存 for a draft); 导出, 复制 and 删除 are in 「…」.  A built-in has no 编辑 and no 删除.  The switch is only on an active skill.
 */
export function SkillCard({ skill, writes, enabled, busy, onToggle, onEdit, onCopy, onExport, onDelete }: {
  skill: Skill; writes: ReadonlySet<string>; enabled: boolean; busy: boolean;
  onToggle: (enabled: boolean) => void; onEdit: (opener: HTMLElement | null) => void; onCopy: () => void; onExport: () => void; onDelete: (opener: HTMLElement | null) => void;
}) {
  const { t } = useLocale();
  const edit = useRef<HTMLButtonElement>(null), menu = useRef<HTMLButtonElement>(null);
  const draft = skill.status === "draft";
  return <article data-testid="skill-card" data-skill={skill.id} data-origin={draft ? "draft" : skill.origin} aria-label={skill.name} className="flex min-w-0 flex-col gap-3 rounded-md border border-line bg-surface p-3.5">
    <div className="flex items-start gap-2">
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <h3 className="min-w-0 text-body font-medium text-ink [overflow-wrap:anywhere]">{skill.name}</h3>
        <div className="flex flex-wrap items-center gap-2">
          <span data-testid="skill-origin"><StatusBadge kind={draft ? "action" : "neutral"} className="h-5">{t(draft ? "草稿" : ORIGIN_LABELS[skill.origin])}</StatusBadge></span>
          <span className="font-mono text-caption text-muted-foreground">v{skill.version}</span>
        </div>
      </div>
      {hasSwitch(skill) && <Switch checked={enabled} disabled={busy} aria-label={`${t(enabled ? "停用" : "启用")} ${skill.name}`} data-testid="skill-switch" onCheckedChange={onToggle} className="mt-0.5 shrink-0 max-sm:scale-110" />}
    </div>
    <p className="text-small text-ink-2 [overflow-wrap:anywhere]">{skill.description}</p>
    <ToolChips names={skill.allowed_tools} writes={writes} label={t("允许用的工具")} />
    <div className="mt-auto flex items-center gap-2 pt-1">
      {isEditable(skill) && <Button ref={edit} type="button" variant={draft ? "default" : "outline"} size="sm" disabled={busy} data-testid="skill-edit" className="max-sm:h-11" onClick={() => onEdit(edit.current)}>{!draft && <SquarePen aria-hidden="true" />}{t(draft ? "核对并保存" : "编辑")}</Button>}
      <span className="ml-auto" />
      <DropdownMenu modal={false}>
        <DropdownMenuTrigger asChild><Button ref={menu} type="button" variant="ghost" size="icon" disabled={busy} aria-label={`${t("更多操作")} ${skill.name}`} data-testid="skill-menu" className="size-9 max-sm:size-11"><Ellipsis aria-hidden="true" /></Button></DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem data-testid="skill-export" onSelect={onExport}><Download aria-hidden="true" />{t("导出")}</DropdownMenuItem>
          <DropdownMenuItem data-testid="skill-copy" onSelect={onCopy}><CopyPlus aria-hidden="true" />{t("复制")}</DropdownMenuItem>
          {isEditable(skill) && <><DropdownMenuSeparator /><DropdownMenuItem data-testid="skill-delete" variant="destructive" onSelect={() => onDelete(menu.current)}><Trash2 aria-hidden="true" />{t("删除")}</DropdownMenuItem></>}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  </article>;
}
