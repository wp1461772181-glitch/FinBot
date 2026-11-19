import { useEffect, useRef, useState } from "react";
import { FileUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Drawer, DrawerContent, DrawerDescription, DrawerHeader, DrawerTitle } from "@/components/ui/drawer";
import { Field, FieldLabel } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";
import { ErrorBar } from "@/components/state/ErrorBar";
import { StatefulButton } from "@/components/state/StatefulButton";
import type { SkillImportPreview } from "../../../api/skills-core";
import { useLocale } from "../../../i18n";
import { ToolChips } from "./ToolChip";
import { IMPORT_MAX } from "./skill-form.mjs";

/**
 * 导入技能 (design 4.11): paste the skill's Markdown or choose a .md file (it is read into the box), 预览, then 导入.  The import cannot be pressed before there is a preview of the text that is in the box, and any change
 * to the text withdraws the preview.  The preview says the name and the one-line description, every tool the skill may use (a tool that writes is marked), and — when one does — that a confirmation card is still needed.
 * The file box is a plain button and a hidden file input, not the evidence page's Dropzone (whose type list and wording are for TXT / Markdown / PDF materials).
 */
export function ImportDrawer({ open, onOpenChange, preview, doImport, returnFocus }: {
  open: boolean; onOpenChange: (open: boolean) => void;
  preview: (markdown: string) => Promise<SkillImportPreview>;
  doImport: (markdown: string) => Promise<void>;
  returnFocus?: () => void;
}) {
  const { t } = useLocale();
  const [markdown, setMarkdown] = useState("");
  const [shown, setShown] = useState<SkillImportPreview | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const [busy, setBusy] = useState<"" | "preview" | "import">("");
  const file = useRef<HTMLInputElement>(null);
  useEffect(() => { if (open) { setMarkdown(""); setShown(null); setFailure(null); setBusy(""); } }, [open]);

  const edit = (text: string) => { setMarkdown(text); setShown(null); setFailure(null); };
  async function pick(chosen: File | undefined) {
    if (!chosen) return;
    try { edit(await chosen.text()); } catch { setFailure(t("文件无法读取。")); }
    if (file.current) file.current.value = "";
  }
  async function runPreview() {
    setBusy("preview"); setFailure(null); setShown(null);
    try { setShown(await preview(markdown)); } catch (error) { setFailure(error); } finally { setBusy(""); }
  }
  const writes = new Set((shown?.tools ?? []).filter(tool => tool.write).map(tool => tool.name));
  return <Drawer open={open} onOpenChange={onOpenChange} direction="right" autoFocus>
    <DrawerContent data-testid="skill-import-drawer" aria-describedby="skill-import-description" onCloseAutoFocus={event => { event.preventDefault(); returnFocus?.(); }}
      className="data-[vaul-drawer-direction=right]:w-full data-[vaul-drawer-direction=right]:sm:max-w-lg">
      <DrawerHeader className="gap-2 border-b border-line">
        <DrawerTitle className="text-title-s">{t("导入技能")}</DrawerTitle>
        <DrawerDescription id="skill-import-description">{t("技能只能是文字步骤，不能带代码。")}</DrawerDescription>
      </DrawerHeader>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
        <Field>
          <FieldLabel htmlFor="skill-import-text">{t("技能文件（Markdown）")}</FieldLabel>
          <Textarea id="skill-import-text" data-testid="skill-import-text" rows={10} value={markdown} maxLength={IMPORT_MAX} className="font-mono text-small" onChange={event => edit(event.target.value)} />
        </Field>
        <div className="flex flex-wrap items-center gap-2">
          <input ref={file} type="file" accept=".md,text/markdown,text/plain" hidden data-testid="skill-import-file" onChange={event => void pick(event.target.files?.[0])} />
          <Button type="button" variant="outline" className="max-sm:h-11" onClick={() => file.current?.click()}><FileUp aria-hidden="true" />{t("选择 .md 文件")}</Button>
          <Button type="button" variant="outline" data-testid="skill-import-preview" disabled={busy !== "" || !markdown.trim()} className="max-sm:h-11" onClick={() => void runPreview()}>{t("预览")}</Button>
        </div>
        {shown && <section data-testid="skill-preview" aria-label={t("预览")} className="flex min-w-0 flex-col gap-3 rounded-md border border-line bg-sunken p-3.5">
          <div className="flex min-w-0 flex-col gap-1"><h3 data-testid="skill-preview-name" className="text-body font-medium text-ink [overflow-wrap:anywhere]">{shown.skill.name}</h3><p className="text-small text-ink-2 [overflow-wrap:anywhere]">{shown.skill.description}</p></div>
          <p className="text-small text-muted-foreground">{t("这个技能能用这些工具：")}</p>
          <ToolChips names={shown.tools.map(tool => tool.name)} writes={writes} label={t("这个技能能用这些工具：")} />
          {writes.size > 0 && <p data-testid="skill-preview-write-note" className="text-small text-action">{t("写操作：仍需确认卡")}</p>}
        </section>}
      </div>
      <div className="flex flex-col gap-2 border-t border-line p-4">
        {failure != null && <ErrorBar {...(typeof failure === "string" ? { message: failure } : { error: failure })} />}
        <div className="flex items-center justify-end gap-2">
          <Button type="button" variant="ghost" className="max-sm:h-11" onClick={() => onOpenChange(false)}>{t("取消")}</Button>
          <StatefulButton type="button" data-testid="skill-import-confirm" disabled={!shown || busy !== ""} className="max-sm:h-11" onClick={async () => { setFailure(null); try { await doImport(markdown); } catch (error) { setFailure(error); throw error; } }}>{t("导入")}</StatefulButton>
        </div>
      </div>
    </DrawerContent>
  </Drawer>;
}
