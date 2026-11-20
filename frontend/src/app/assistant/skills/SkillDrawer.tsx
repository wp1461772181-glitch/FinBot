import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer";
import { Field, FieldDescription, FieldLabel, FieldLegend, FieldSet } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ErrorBar } from "@/components/state/ErrorBar";
import { StatefulButton } from "@/components/state/StatefulButton";
import type { Skill, SkillTool } from "../../../api/skills-core";
import { toolLabel } from "../../../agent-tool-labels.mjs";
import { useLocale } from "../../../i18n";
import { BODY_MAX, DESCRIPTION_MAX, LEVEL_LABELS, NAME_MAX, TEMPLATE_MAX, blankEditor, editorOf, isWriteLevel, toggleTool, type SkillEditor } from "./skill-form.mjs";

/**
 * 新建 / 编辑技能 (design 4.11): a side drawer (the whole screen on a phone; one drawer at every width) with the old editor's fields: 名字, 一句话说明什么时候用, 步骤, 输出模板, 允许用的工具.
 * Each tool says its level (只读 / 可撤销 / 耗费较大 / 写操作); a tool that changes something adds 写操作：仍需确认卡.  A draft the agent wrote carries its one sentence at the top and saves as 保存为技能.
 * `save` makes the request (the old page's body) and may throw: the reason shows under the form and the drawer stays.
 */
export function SkillDrawer({ open, onOpenChange, skill, tools, save, returnFocus }: {
  open: boolean; onOpenChange: (open: boolean) => void;
  /** The skill being edited; null for a new one. */
  skill: Skill | null;
  tools: SkillTool[];
  save: (editor: SkillEditor) => Promise<void>;
  returnFocus?: () => void;
}) {
  const { t } = useLocale();
  const [editor, setEditor] = useState<SkillEditor>(blankEditor);
  const [failure, setFailure] = useState<unknown>(null);
  useEffect(() => { if (open) { setEditor(skill ? editorOf(skill) : blankEditor()); setFailure(null); } }, [open, skill?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const patch = (next: Partial<SkillEditor>) => setEditor(current => ({ ...current, ...next }));
  const submit = async () => {
    setFailure(null);
    try { await save(editor); } catch (error) { setFailure(error); throw error; }
  };
  return <Drawer open={open} onOpenChange={onOpenChange} direction="right" autoFocus>
    <DrawerContent data-testid="skill-drawer" data-draft={editor.draft ? "true" : "false"} aria-describedby="skill-drawer-description" onCloseAutoFocus={event => { event.preventDefault(); returnFocus?.(); }}
      className="data-[vaul-drawer-direction=right]:w-full data-[vaul-drawer-direction=right]:sm:max-w-lg">
      <DrawerHeader className="gap-2 border-b border-line">
        <DrawerTitle className="text-title-s">{t(skill ? "编辑技能" : "新建技能")}</DrawerTitle>
        <DrawerDescription id="skill-drawer-description">{t("技能只能是文字步骤，不能带代码。")}</DrawerDescription>
      </DrawerHeader>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4" data-testid="skill-drawer-body">
        {editor.draft && <p data-testid="skill-draft-note" className="rounded-md border border-action/40 bg-action-soft px-3 py-2 text-small text-ink">{t("Agent 起草的草稿：核对后保存才会生效。")}</p>}
        <Field>
          <FieldLabel htmlFor="skill-name">{t("名字")}</FieldLabel>
          <Input id="skill-name" value={editor.name} maxLength={NAME_MAX} onChange={event => patch({ name: event.target.value })} />
        </Field>
        <Field>
          <FieldLabel htmlFor="skill-description">{t("一句话说明什么时候用")}</FieldLabel>
          <Input id="skill-description" value={editor.description} maxLength={DESCRIPTION_MAX} onChange={event => patch({ description: event.target.value })} />
        </Field>
        <Field>
          <FieldLabel htmlFor="skill-body">{t("步骤")}</FieldLabel>
          <Textarea id="skill-body" rows={10} value={editor.body} maxLength={BODY_MAX} onChange={event => patch({ body: event.target.value })} />
        </Field>
        <Field>
          <FieldLabel htmlFor="skill-template">{t("输出模板（可选）")}</FieldLabel>
          <Textarea id="skill-template" rows={4} value={editor.template} maxLength={TEMPLATE_MAX} onChange={event => patch({ template: event.target.value })} />
        </Field>
        <FieldSet>
          <FieldLegend variant="label">{t("允许用的工具")}</FieldLegend>
          <FieldDescription>{t("技能只会减少可用工具；写操作照样要你确认。")}</FieldDescription>
          <ul className="m-0 flex list-none flex-col gap-1 p-0" data-testid="skill-tool-list">
            {tools.map(tool => {
              const write = isWriteLevel(tool.level), id = `skill-tool-${tool.name}`;
              return <li key={tool.name} data-tool={tool.name} data-write={write ? "true" : "false"}>
                <Field orientation="horizontal" className="min-h-9 items-start gap-2.5 rounded-sm px-1 py-1 max-sm:min-h-11">
                  <Checkbox id={id} checked={editor.tools.includes(tool.name)} onCheckedChange={on => patch({ tools: toggleTool(editor.tools, tool.name, on === true) })} className="mt-0.5" />
                  <FieldLabel htmlFor={id} className="flex-wrap gap-x-2 gap-y-0.5 font-normal">
                    <span className="text-ink">{t(toolLabel(tool.name))}</span>
                    <span className="text-caption text-muted-foreground">{t(LEVEL_LABELS[tool.level] ?? tool.level)}{write ? ` · ${t("写操作：仍需确认卡")}` : ""}</span>
                  </FieldLabel>
                </Field>
              </li>;
            })}
          </ul>
        </FieldSet>
      </div>
      <div className="flex flex-col gap-2 border-t border-line p-4">
        {failure != null && <ErrorBar error={failure} />}
        <div className="flex items-center justify-end gap-2">
          <Button type="button" variant="ghost" data-testid="skill-cancel" className="max-sm:h-11" onClick={() => onOpenChange(false)}>{t("取消")}</Button>
          <StatefulButton type="button" data-testid="skill-save" className="max-sm:h-11" onClick={submit}>{t(editor.draft ? "保存为技能" : "保存")}</StatefulButton>
        </div>
      </div>
    </DrawerContent>
  </Drawer>;
}
