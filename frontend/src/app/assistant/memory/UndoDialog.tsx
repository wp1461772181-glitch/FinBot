import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ErrorBar } from "@/components/state/ErrorBar";
import { StatefulButton } from "@/components/state/StatefulButton";
import { undoRoleTemplate, type RoleTemplateApplication, type UndoResult } from "../../../api/role-templates";
import { useLocale } from "../../../i18n";
import { applicationLine, applicationRows, stillThereLine, templateLabel, undoLeaveOut, undoTicked } from "../../../role-templates.mjs";
import { ApplicationRowList } from "./ApplicationRows";

/**
 * 撤掉 (4f): every thing the application wrote and that is still there, with its current text and a checkbox (all ticked; untick what he wants to keep).  Only what the application recorded
 * is ever taken back; what he added himself is not in the list and is never touched.  The server answers what it removed and what was already gone.
 */
export function UndoDialog({ application, onClose, onDone, returnFocus }: { application: RoleTemplateApplication; onClose: () => void; onDone: (result: UndoResult) => void | Promise<void>; returnFocus: () => void }) {
  const { t, locale } = useLocale();
  const rows = useMemo(() => applicationRows(application), [application]);
  const [ticked, setTicked] = useState<Set<string>>(() => undoTicked(rows));
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const listed = rows.length > 0;
  const nothingTicked = listed && undoLeaveOut(rows, ticked).length === rows.filter(row => !row.gone).length;
  const toggle = (id: string, on: boolean) => setTicked(current => { const next = new Set(current); if (on) next.add(id); else next.delete(id); return next; });

  async function undo() {
    if (busy || nothingTicked) return;
    setBusy(true); setFailure(null);
    try { await onDone(await undoRoleTemplate(application.id, listed ? undoLeaveOut(rows, ticked) : [])); }
    catch (error) { setFailure(error); setBusy(false); }
  }

  return <Dialog open onOpenChange={next => { if (!next && !busy) onClose(); }}>
    <DialogContent data-testid="template-undo-dialog" closeLabel={t("关闭")} aria-describedby="template-undo-description" onCloseAutoFocus={event => { event.preventDefault(); returnFocus(); }} onInteractOutside={event => { if (busy) event.preventDefault(); }}
      className="flex max-h-[92dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-xl">
      <DialogHeader className="gap-1 border-b border-line p-4 pr-12 sm:p-5 sm:pr-12">
        <DialogTitle className="text-title-s">{t("撤掉模板")} · {templateLabel(application.label, locale)}</DialogTitle>
        <DialogDescription id="template-undo-description" className="text-small">{applicationLine(application, locale)} · {stillThereLine(application, locale)}</DialogDescription>
      </DialogHeader>
      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-4 sm:p-5">
        <p data-testid="template-undo-note" className="m-0 text-small text-ink-2">{t("只会拿走这次应用写进去的、现在还在的；你自己加的，一概不动。不想撤的，取消勾选。")}</p>
        {listed
          ? <ApplicationRowList rows={rows} ticked={ticked} onToggle={toggle} disabled={busy} />
          : <p data-testid="template-undo-unlisted" className="m-0 text-small text-muted-foreground">{t("这次应用没有带回明细，没法逐项列出；撤掉会拿走它写进去的、还在的全部内容。")}</p>}
        {failure != null && <ErrorBar error={failure} />}
      </div>
      <DialogFooter className="border-t border-line p-4 sm:p-5">
        <Button type="button" variant="ghost" data-testid="template-undo-cancel" disabled={busy} className="max-md:h-11" onClick={onClose}>{t("取消")}</Button>
        <StatefulButton type="button" data-testid="template-undo-submit" phase={busy ? "loading" : "idle"} disabled={nothingTicked} className="max-md:h-11" onClick={() => void undo()}>{listed ? t("撤掉选中的") : t("撤掉")}</StatefulButton>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
