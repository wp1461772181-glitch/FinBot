// legacy markup, moved as-is in P3.1; restyled in P3.2–P3.4
import { useEffect, useState } from "react";
import { getChatMode } from "../../api/base";
import { getTelegramBind, saveTelegramToken, startTelegramBind, unbindTelegram, type TelegramBindStatus } from "../../api/integrations";
import { useLocale } from "../../i18n";
import { confirm } from "@/components/state/confirm";

export function TelegramBindCard() {
  const { t } = useLocale();
  const [tg, setTg] = useState<TelegramBindStatus | null>(null);
  const [token, setToken] = useState("");
  const [code, setCode] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getTelegramBind()
      .then((value) => { if (!cancelled) setTg(value); })
      .catch((error: unknown) => { if (!cancelled) setStatus(error instanceof Error ? error.message : t("Telegram 设置暂时无法读取。")); });
    return () => { cancelled = true; };
  }, []);
  if (getChatMode() !== "personal") return null;

  async function saveToken() {
    if (!token.trim()) return;
    setBusy(true);
    setStatus("");
    try {
      const next = await saveTelegramToken(token.trim());
      setTg(next);
      setToken("");
      setStatus(t("Bot Token 已保存。"));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : t("保存失败，请重试。"));
    } finally {
      setBusy(false);
    }
  }
  async function start() {
    setBusy(true);
    setStatus("");
    try {
      const next = await startTelegramBind();
      setCode(next.code);
      setStatus(t("绑定码已生成，30 分钟内有效。"));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : t("操作失败，请重试。"));
    } finally {
      setBusy(false);
    }
  }
  async function doUnbind() {
    if (!(await confirm({ title: t("解除 Telegram 绑定？"), description: t("解除绑定后，Telegram 消息不再被处理。"), confirmLabel: t("解除绑定"), cancelLabel: t("取消"), tone: "danger", hold: true }))) return;
    setBusy(true);
    setStatus("");
    try {
      const next = await unbindTelegram();
      setTg(next);
      setCode("");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : t("操作失败，请重试。"));
    } finally {
      setBusy(false);
    }
  }

  let summary = t("尚未配置");
  if (tg?.configured && tg.bound) {
    summary = `${t("已绑定")}${tg.bot_username ? ` @${tg.bot_username}` : ""}${tg.chat_id ? ` (chat ${tg.chat_id})` : ""}`;
  } else if (tg?.configured && tg.has_token) {
    summary = `${t("Token 已保存")}${tg.bot_username ? ` @${tg.bot_username}` : ""}${tg.bind_code_active ? ` · ${t("正在等待绑定")}` : ""}`;
  }

  return <section className="agent-settings-card" aria-labelledby="telegram-bind-title">
    <h2 id="telegram-bind-title">{t("Telegram 随身入口")}</h2>
    <p>{t("绑定 Telegram 账号后：直接发的消息进默认 bot「助理」的那条线，回复哪个 bot 的消息就进哪个 bot，也可以用「@名字」点名。bot 按自己的说明调用「发 Telegram 通知」，每个 bot 每天有上限（在 bot 档案里设）。确认卡变成按钮。")}</p>
    <p><strong>{t("状态")}：</strong>{summary}</p>
    {(!tg?.configured || !tg.has_token) && <><label>{t("Bot Token（从 @BotFather 获取）")}<input type="password" value={token} maxLength={256} placeholder="1234567890:AA..." onChange={e => setToken(e.target.value)} /></label>
    <div className="chat-archive-tools"><button type="button" className="primary-action" disabled={busy || !token.trim()} onClick={() => void saveToken()}>{busy ? t("正在保存…") : t("保存 Token")}</button></div></>}
    {tg?.configured && tg.has_token && !tg.bound && <><p>{t("请先生成一个绑定码，然后在 Telegram 上向你的 Bot 发送 /bind 命令加这个码。")}</p>
    {code && <p className="bind-code">{t("绑定码")}: <code>{code}</code><br/>{t("在 Telegram 上发送")}: <code>/bind {code}</code></p>}
    <div className="chat-archive-tools"><button type="button" className="primary-action" disabled={busy} onClick={() => void start()}>{busy ? t("正在生成…") : code ? t("重新生成") : t("生成绑定码")}</button></div></>}
    {tg?.configured && tg.bound && <div className="chat-archive-tools"><button type="button" className="secondary-action" disabled={busy} onClick={() => void doUnbind()}>{t("解除绑定")}</button></div>}
    {status && <p role="status">{status}</p>}
  </section>;
}
