import { useCallback, useEffect, useRef, useState } from "react";
import { notify } from "@/components/state/notify";
import { useLocale } from "../../i18n";

export type CopyState = { copied: number | null; failed: number | null; copyText: (text: string, index: number) => Promise<void> };

/**
 * Copy a message's text.  The outcome is a toast (design 4.0, S7), not a line inserted into the thread; the button of the copied
 * message shows a check for a moment.  When the browser refuses, the message's text is selected so Ctrl/Cmd+C finishes the job.
 */
export function useCopy(): CopyState {
  const { t } = useLocale();
  const [copied, setCopied] = useState<number | null>(null);
  const [failed, setFailed] = useState<number | null>(null);
  const reset = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(reset.current), []);
  const copyText = useCallback(async (text: string, index: number) => {
    setCopied(null); setFailed(null);
    let timer: number | undefined;
    try {
      const clipboard = navigator.clipboard?.writeText(text);
      if (!clipboard) throw Error("clipboard_unavailable");
      await Promise.race([clipboard, new Promise<never>((_, reject) => { timer = window.setTimeout(() => reject(Error("clipboard_timeout")), 1800); })]);
      setCopied(index);
      notify.success(t("已复制"), { id: "chat-copy" });
    } catch {
      setFailed(index);
      notify.error(t("复制失败；请选中回答后手动复制。"), { id: "chat-copy" });
      const article = document.getElementById(`chat-message-${index}`);
      const target = article?.querySelector("[data-testid=message-body], [data-testid=user-bubble]") ?? article;
      if (target) { const range = document.createRange(); range.selectNodeContents(target); window.getSelection()?.removeAllRanges(); window.getSelection()?.addRange(range); }
    } finally {
      if (timer) window.clearTimeout(timer);
      window.clearTimeout(reset.current);
      reset.current = window.setTimeout(() => { setCopied(null); setFailed(null); }, 2000);
    }
  }, [t]);
  return { copied, failed, copyText };
}
