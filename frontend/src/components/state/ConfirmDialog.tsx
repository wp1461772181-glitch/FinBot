import { useRef } from "react";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { useLocale } from "../../i18n";
import type { ConfirmAsk } from "../../confirm-queue.mjs";
import { confirmQueue } from "./confirm";
import { HoldButton } from "./HoldButton";

/**
 * The confirmation (design 4.0 / 5.4): AlertDialog, so Esc and a click outside cancel, focus starts on 取消 and stays inside, and
 * focus goes back to what had it when the ask was made.  `hold` swaps the confirm button for press-and-hold.  Layer: dialogs are 50;
 * the toaster (60) sits above.
 */
export default function ConfirmDialog({ ask }: { ask: ConfirmAsk }) {
  const { t } = useLocale();
  const settled = useRef(false);
  const answer = (value: boolean) => {
    if (settled.current) return;
    settled.current = true;
    const target = ask.returnFocus;
    confirmQueue.answer(value);
    // Back to where the reader was.  Not before the dialog has left: its focus trap would pull focus back in.  Only when no other ask follows.
    if (confirmQueue.size() === 0) window.setTimeout(() => { if (target?.isConnected) target.focus(); }, 0);
  };
  const danger = ask.tone === "danger";
  const label = ask.confirmLabel ?? t("确认");
  return <AlertDialog open onOpenChange={(open) => { if (!open) answer(false); }}>
    <AlertDialogContent size="default" onCloseAutoFocus={(event) => event.preventDefault()} data-hold={ask.hold ? "" : undefined}>
      <AlertDialogHeader>
        <AlertDialogTitle>{ask.title}</AlertDialogTitle>
        <AlertDialogDescription className={ask.description ? undefined : "sr-only"}>{ask.description ?? ask.title}</AlertDialogDescription>
      </AlertDialogHeader>
      <AlertDialogFooter className="items-center">
        <AlertDialogCancel>{ask.cancelLabel ?? t("取消")}</AlertDialogCancel>
        {ask.hold
          ? <HoldButton label={label} danger={danger} onConfirmed={() => answer(true)} />
          : <AlertDialogAction variant={danger ? "destructive" : "default"} onClick={() => answer(true)}>{label}</AlertDialogAction>}
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>;
}
