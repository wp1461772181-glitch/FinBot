// legacy markup, moved as-is in P3.1; restyled in P3.2–P3.4
import { useEffect, useState } from "react";
import { getChatMode, getPushover, savePushover, clearPushover, type PushoverStatus } from "../../api";
import { useLocale } from "../../i18n";

export function PushoverCard() {
  const { t } = useLocale();
  const [saved, setSaved] = useState<PushoverStatus | null>(null);
  const [userKey, setUserKey] = useState("");
  const [appToken, setAppToken] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getPushover()
      .then((value) => { if (!cancelled) setSaved(value); })
      .catch((error: unknown) => { if (!cancelled) setStatus(error instanceof Error ? error.message : t("Pushover 设置暂时无法读取。")); });
    return () => { cancelled = true; };
  }, []);
  if (getChatMode() !== "personal") return null;
  async function save() {
    setBusy(true); setStatus("");
    try { setSaved(await savePushover(userKey.trim(), appToken.trim())); setUserKey(""); setAppToken(""); setStatus(t("Pushover 已保存。")); }
    catch (error) { setStatus(error instanceof Error ? error.message : t("保存失败，请重试。")); }
    finally { setBusy(false); }
  }
  async function clear() {
    setBusy(true); setStatus("");
    try { setSaved(await clearPushover()); setStatus(t("Pushover 已清除。")); }
    catch (error) { setStatus(error instanceof Error ? error.message : t("操作失败，请重试。")); }
    finally { setBusy(false); }
  }
  return <section className="agent-settings-card" aria-labelledby="pushover-title">
    <h2 id="pushover-title">{t("紧急提醒（Pushover）")}</h2>
    <p>{t("急跌等提醒发到 Telegram 后，1 分钟内没点「收到」，就用 Pushover 紧急级通知响铃（每分钟一次，最多 30 分钟）；在 Pushover 里确认或在 Telegram 点「收到」都会停。两个值加密保存，保存后不会再显示。")}</p>
    <p><strong>{t("状态")}：</strong>{saved?.configured ? t("已配置") : t("尚未配置")}</p>
    <label>{t("Pushover User Key")}<input type="password" value={userKey} maxLength={64} autoComplete="off" onChange={e => setUserKey(e.target.value)} /></label>
    <label>{t("Pushover App Token")}<input type="password" value={appToken} maxLength={64} autoComplete="off" onChange={e => setAppToken(e.target.value)} /></label>
    <div className="chat-archive-tools">
      <button type="button" className="primary-action" disabled={busy || !userKey.trim() || !appToken.trim()} onClick={() => void save()}>{t("保存 Pushover")}</button>
      {saved?.configured && <button type="button" className="secondary-action" disabled={busy} onClick={() => void clear()}>{t("清除 Pushover")}</button>}
    </div>
    {status && <p role="status">{status}</p>}
  </section>;
}
