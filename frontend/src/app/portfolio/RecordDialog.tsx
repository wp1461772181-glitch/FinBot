import { useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { X } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Drawer, DrawerContent, DrawerDescription, DrawerTitle } from "@/components/ui/drawer";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Segmented } from "@/components/Segmented";
import { ErrorBar } from "@/components/state/ErrorBar";
import { StatefulButton } from "@/components/state/StatefulButton";
import { useLocale } from "../../i18n";
import { useFocusKeep } from "../use-focus-keep";
import { ENTRY_KINDS, KIND_LABELS, blankEntry, entryBody, type PortfolioEntryForm } from "../../portfolio-items.mjs";

/** The dialog's width from this on; below it the same form is a drawer from the bottom.  (Its own matchMedia hook, as the new-bot dialog has.) */
const WIDE_QUERY = "(min-width: 640px)";
const subscribeWide = (notify: () => void) => { const list = window.matchMedia?.(WIDE_QUERY); list?.addEventListener?.("change", notify); return () => list?.removeEventListener?.("change", notify); };
const useWide = () => useSyncExternalStore(subscribeWide, () => window.matchMedia?.(WIDE_QUERY).matches ?? false, () => false);

const TRADE = new Set(["opening", "buy", "sell"]);
const CASH = new Set(["deposit", "withdraw"]);
const label = "flex min-w-0 flex-col gap-1.5 text-small font-medium text-ink";

/**
 * 记一笔 (design 4.9, 5.4): a dialog on a desktop, a drawer on a phone, one form in both.  It writes a line in the reader's own ledger: the kinds are what
 * the reader did (买入, 卖出, 期初持仓, 分红, 拆股, 入金, 出金), a record of it and not an order; nothing here trades.  The draft (`entry`) and the error live in the
 * page, above both shells, so crossing the breakpoint with the dialog open keeps what was typed.  The rules are the old form's, in portfolio-items.mjs's entryBody:
 * the first one broken is said in the form and nothing is sent; a failed request is said in the form too (an ErrorBar) and the form stays.
 */
export function RecordDialog({ entry, setEntry, error, setError, onSubmit, onClose, returnFocus }: {
  entry: PortfolioEntryForm; setEntry: (next: PortfolioEntryForm) => void; error: string; setError: (text: string) => void;
  onSubmit: (body: Record<string, string>) => Promise<unknown>; onClose: () => void; returnFocus: () => void;
}) {
  const { t } = useLocale();
  const wide = useWide();
  const [busy, setBusy] = useState(false);
  const content = useRef<HTMLDivElement>(null);
  const keep = useFocusKeep("record-dialog");
  const close = (open: boolean) => { if (!open && !busy) onClose(); };
  const giveBackFocus = (event: Event) => { event.preventDefault(); returnFocus(); };
  const body = (title: ReactNode, description: ReactNode) => <RecordForm wide={wide} entry={entry} setEntry={setEntry} error={error} setError={setError} busy={busy} setBusy={setBusy} onSubmit={onSubmit} onClose={onClose} title={title} description={description} />;
  if (wide) {
    return <Dialog open onOpenChange={close}>
      <DialogContent data-testid="record-dialog" closeLabel={t("关闭")} className="max-h-[92dvh] gap-0 overflow-y-auto p-0 sm:max-w-xl"
        onOpenAutoFocus={event => { event.preventDefault(); keep(() => content.current?.querySelector<HTMLElement>("#record-symbol, #record-amount")); }}
        onCloseAutoFocus={giveBackFocus} onEscapeKeyDown={event => { if (busy) event.preventDefault(); }} onInteractOutside={event => { if (busy) event.preventDefault(); }} ref={content}>
        {body(<DialogTitle className="text-title-s font-semibold text-ink">{t("记一笔")}</DialogTitle>, <DialogDescription className="text-small text-muted-foreground">{t("记下你自己做过的一笔。这里只记账，不会下单。")}</DialogDescription>)}
      </DialogContent>
    </Dialog>;
  }
  return <Drawer open onOpenChange={close} dismissible={!busy} handleOnly>
    <DrawerContent data-testid="record-dialog" className="data-[vaul-drawer-direction=bottom]:max-h-[92dvh]" onOpenAutoFocus={event => { event.preventDefault(); keep(() => content.current); }} onCloseAutoFocus={giveBackFocus} ref={content}>
      {body(<DrawerTitle className="text-title-s font-semibold text-ink">{t("记一笔")}</DrawerTitle>, <DrawerDescription className="text-small text-muted-foreground">{t("记下你自己做过的一笔。这里只记账，不会下单。")}</DrawerDescription>)}
    </DrawerContent>
  </Drawer>;
}

function RecordForm({ wide, entry, setEntry, error, setError, busy, setBusy, onSubmit, onClose, title, description }: {
  wide: boolean; entry: PortfolioEntryForm; setEntry: (next: PortfolioEntryForm) => void; error: string; setError: (text: string) => void; busy: boolean; setBusy: (busy: boolean) => void;
  onSubmit: (body: Record<string, string>) => Promise<unknown>; onClose: () => void; title: ReactNode; description: ReactNode;
}) {
  const { t } = useLocale();
  const [failure, setFailure] = useState<unknown>(null);
  const kind = entry.kind;
  const set = (key: keyof PortfolioEntryForm, value: string) => { setError(""); setFailure(null); setEntry({ ...entry, [key]: value }); };
  const submit = () => {
    if (busy) return;
    const built = entryBody(entry);
    if ("error" in built) { setError(t(built.error)); return; }
    setError(""); setFailure(null); setBusy(true);
    return onSubmit(built.body).catch(cause => { setFailure(cause); throw cause; }).finally(() => setBusy(false));
  };
  const field = (key: keyof PortfolioEntryForm, text: string, extra: { id?: string; inputMode?: "decimal"; placeholder?: string; maxLength?: number; type?: string; mono?: boolean } = {}) =>
    <label className={label}>{t(text)}
      <Input id={extra.id} data-testid={`record-${key}`} type={extra.type ?? "text"} inputMode={extra.inputMode} autoComplete="off" disabled={busy} placeholder={extra.placeholder ? t(extra.placeholder) : undefined} maxLength={extra.maxLength}
        value={entry[key]} className={`max-sm:h-11 ${extra.mono === false ? "" : "font-mono tabular-nums"}`} onChange={event => set(key, event.target.value)} />
    </label>;
  return <form data-testid="record-form" noValidate className="flex min-h-0 flex-1 flex-col" onSubmit={event => event.preventDefault()}>
    <div className={`flex items-start justify-between gap-2 border-b border-line ${wide ? "px-6 py-4 pr-12" : "py-3 pr-2 pl-4"}`}>
      <div className="flex min-w-0 flex-col gap-1">{title}{description}</div>
      {!wide && <Button type="button" variant="ghost" size="icon" className="size-11 shrink-0" disabled={busy} onClick={onClose} aria-label={t("关闭")}><X aria-hidden="true" /></Button>}
    </div>
    <div className={`flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto ${wide ? "px-6 py-4" : "px-4 py-4"}`}>
      <div className="flex flex-col gap-1.5">
        <Segmented name="record-kind" legend={t("类型")} value={kind} disabled={busy} testid="record-kind" onChange={next => { setError(""); setFailure(null); setEntry(blankEntry(next)); }}
          options={ENTRY_KINDS.map(k => ({ value: k, label: t(KIND_LABELS[k]) }))} />
        {kind === "opening" && <p data-testid="record-opening-note" className="text-caption text-muted-foreground">{t("期初持仓是你已经持有的仓位，不会改变可用资金。")}</p>}
      </div>
      {!CASH.has(kind) && field("symbol", "股票代码", { id: "record-symbol", placeholder: "例如 INTC", maxLength: 12 })}
      {TRADE.has(kind) && <div className="grid grid-cols-2 gap-3">
        {field("quantity", "股数", { inputMode: "decimal" })}
        {field("price", kind === "opening" ? "平均成本（每股）" : "成交价", { inputMode: "decimal" })}
      </div>}
      {TRADE.has(kind) && kind !== "opening" && field("fee", "手续费（可不填）", { inputMode: "decimal" })}
      {kind === "split" && field("ratio", "拆股比例（1 拆 2 填 2）", { inputMode: "decimal" })}
      {(kind === "dividend" || CASH.has(kind)) && field("amount", "金额", { id: "record-amount", inputMode: "decimal" })}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {field("occurred_on", "日期（可不填，默认今天）", { type: "date", mono: false })}
        {field("note", "备注（可不填）", { maxLength: 200, mono: false })}
      </div>
    </div>
    <div className={`flex flex-col gap-3 border-t border-line ${wide ? "px-6 py-4" : "px-4 py-3"}`}>
      {error && <p role="alert" data-testid="record-error" className="text-small text-danger">{error}</p>}
      {failure !== null && <ErrorBar error={failure} />}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" className="max-sm:h-11" disabled={busy} onClick={onClose}>{t("取消")}</Button>
        <StatefulButton type="submit" data-testid="record-submit" className="max-sm:h-11" onClick={submit}>{t("记录")}</StatefulButton>
      </div>
    </div>
  </form>;
}
