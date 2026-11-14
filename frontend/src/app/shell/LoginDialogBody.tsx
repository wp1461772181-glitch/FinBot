import { useEffect, useState, type FormEvent, type MutableRefObject } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { personalChatLogin, setChatMode } from "../../api";
import { completePersonalLogin } from "../../chat-mode-switch.mjs";
import { useLocale } from "../../i18n";
import type { ModeChange } from "./account";

/** The dialog itself (Radix Dialog, Input): fetched the first time the login is asked for, so the first screen does not carry it. */
export default function LoginDialogBody({ open, onOpenChange, manual, returnFocus, onModeChange }: { open: boolean; onOpenChange: (open: boolean) => void; manual: boolean; returnFocus: MutableRefObject<HTMLElement | null>; onModeChange: ModeChange }) {
  const { t } = useLocale();
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setCode(""); setError(""); } }, [open]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!code || busy) return;
    setBusy(true); setError("");
    try {
      const credential = await personalChatLogin(code);
      completePersonalLogin(credential, setChatMode, onModeChange);
      onOpenChange(false); setCode("");
    } catch (failure) {
      setError(failure instanceof Error && failure.message && failure.message !== "个人登录暂不可用。" ? failure.message : "登录暂不可用。");
    } finally { setBusy(false); }
  }

  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent closeLabel={t("关闭")} onCloseAutoFocus={event => { event.preventDefault(); returnFocus.current?.focus(); }}>
      <DialogHeader>
        <p className="text-caption text-muted-foreground">{t("站点写入操作")}</p>
        <DialogTitle>{t("请登录个人账户")}</DialogTitle>
        <DialogDescription>{t(manual ? "登录后可以对话、使用 bot、查看持仓和任务。" : "登录后可继续进行站点操作。登录完成后，请手动重试刚才未完成的操作。")}</DialogDescription>
      </DialogHeader>
      <form className="grid gap-4" onSubmit={submit}>
        <label className="grid gap-1.5 text-sm">
          {t("个人登录密码或口令")}
          <Input type="password" value={code} autoComplete="current-password" maxLength={256} aria-invalid={error ? true : undefined} aria-describedby={error ? "login-dialog-error" : undefined} onChange={event => setCode(event.target.value)} />
        </label>
        {error && <p id="login-dialog-error" role="alert" className="text-sm text-danger">{t(error)}</p>}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>{t("稍后")}</Button>
          <Button type="submit" disabled={!code || busy}>{t(busy ? "正在登录…" : "登录并授权")}</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}
