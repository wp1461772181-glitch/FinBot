import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ErrorBar } from "@/components/state/ErrorBar";
import { StatefulButton } from "@/components/state/StatefulButton";
import { confirm } from "@/components/state/confirm";
import { notify } from "@/components/state/notify";
import { Stepper } from "@/components/Stepper";
import { StatusBadge } from "@/components/StatusBadge";
import { clearPushover, getChannelSettings, getPushover, listChannelDeliveries, saveChannelPrefs, getTelegramBind, savePushover, saveTelegramToken, startTelegramBind, unbindTelegram, type ChannelSettings, type PushoverStatus, type TelegramBindStatus } from "../../../api/integrations";
import { CHANNEL_OPTIONS, deliveryRow, deliveryStatusText, fallbackWarning, optionForPrefs, prefsForOption, rawOrderText, type DeliveryItem } from "../../../channel-prefs.mjs";
import { message } from "../../../bot-message";
import { formatDateTime, useLocale } from "../../../i18n";
import { useWorkspace } from "../../workspace";
import { SettingsCard } from "../SettingsCard";
import { SettingsGuestNote } from "../SettingsGuestNote";
import { TELEGRAM_POLL_MS, TELEGRAM_STEPS, sharedTelegramStep } from "./telegram-step";

/**
 * 通知 (#/settings/notifications, design 4.12): the shared Telegram bot in three steps (save the token, make a code, wait for the message) and the Pushover emergency alert.
 * The requests are the old page's (src/api/integrations.ts, unchanged).  Every secret is typed into a password box, sent once and cleared; the page keeps only the words 已配置 / 尚未配置.
 * One difference from the old page, on purpose: while a code made here is out and nobody has bound yet, the page reads the binding again every 5 seconds (the bot settings page does the same), so 「等待绑定」 ends by itself.
 */
export function NotificationsPage() {
  const { t } = useLocale();
  const { personal } = useWorkspace();
  if (!personal) return <SettingsGuestNote text={t("登录个人聊天后才能设置通知：Telegram 和 Pushover 都只对个人模式开放。")} />;
  return <div data-testid="settings-notifications-body" className="flex flex-col gap-5">
    <ChannelsCard />
    <TelegramCard />
    <PushoverCard />
  </div>;
}

function TelegramCard() {
  const { t } = useLocale();
  const [tg, setTg] = useState<TelegramBindStatus | null>(null), [readError, setReadError] = useState(""), [token, setToken] = useState(""), [code, setCode] = useState(""), [busy, setBusy] = useState(false), [failure, setFailure] = useState("");
  const load = useCallback(async (signal?: AbortSignal) => {
    try { setTg(await getTelegramBind(signal)); setReadError(""); } catch (err) { if (!signal?.aborted) setReadError(message(err, t("Telegram 设置暂时无法读取。"))); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load]);
  // Waiting for the message: ask again every 5 s while a code made on this page is out and the binding is not done.  Gone when it is bound or the page is left.
  const waiting = Boolean(code) && !tg?.bound;
  useEffect(() => {
    if (!waiting) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => { getTelegramBind(controller.signal).then((next) => { if (!controller.signal.aborted) setTg(next); }).catch(() => {}); }, TELEGRAM_POLL_MS);
    return () => { window.clearInterval(timer); controller.abort(); };
  }, [waiting]);
  async function act(work: () => Promise<void>, fallback: string) {
    setBusy(true); setFailure("");
    try { await work(); } catch (err) { setFailure(message(err, t(fallback))); throw err; } finally { setBusy(false); }
  }
  const step = sharedTelegramStep(tg, code);
  const summary = tg?.configured && tg.bound ? `${t("已绑定")}${tg.bot_username ? ` @${tg.bot_username}` : ""}${tg.chat_id ? ` (chat ${tg.chat_id})` : ""}`
    : tg?.configured && tg.has_token ? `${t("Token 已保存")}${tg.bot_username ? ` @${tg.bot_username}` : ""}${tg.bind_code_active ? ` · ${t("正在等待绑定")}` : ""}` : t("尚未配置");
  const kind = tg?.bound ? "success" : tg?.has_token ? "progress" : "neutral";
  return <SettingsCard id="telegram" title={t("Telegram 随身入口")} testid="telegram-card" description={t("绑定 Telegram 账号后：直接发的消息进默认 bot「助理」的那条线，回复哪个 bot 的消息就进哪个 bot，也可以用「@名字」点名。bot 按自己的说明调用「发 Telegram 通知」，每个 bot 每天有上限（在 bot 档案里设）。确认卡变成按钮。")}>
    {readError && <ErrorBar message={readError} onRetry={() => void load()} />}
    <div className="flex flex-wrap items-center gap-2"><span className="text-small font-medium text-ink">{t("状态")}</span><span data-testid="telegram-status" data-kind={kind}><StatusBadge kind={kind}>{tg ? summary : t("正在读取")}</StatusBadge></span></div>
    <Stepper label={t("Telegram 绑定的三步")} steps={TELEGRAM_STEPS.map((s) => ({ id: s, label: t(s) }))} current={step} waiting={step === 2} />
    <div data-testid="telegram-steps" data-step={step} className="flex flex-col gap-3">
      {tg && !tg.bound && !tg.has_token && <Field>
        <FieldLabel htmlFor="telegram-token">{t("Bot Token（从 @BotFather 获取）")}</FieldLabel>
        <div className="flex flex-wrap items-center gap-2">
          <Input id="telegram-token" type="password" className="max-w-96 flex-1 max-sm:h-11" value={token} maxLength={256} autoComplete="off" disabled={busy} onChange={(e) => setToken(e.target.value)} />
          <StatefulButton type="button" data-testid="telegram-save-token" className="max-sm:h-11" disabled={busy || !token.trim()}
            onClick={() => act(async () => { setTg(await saveTelegramToken(token.trim())); setToken(""); notify.success(t("Bot Token 已保存。"), { id: "settings:telegram" }); }, "保存失败，请重试。")}>{t("保存 Token")}</StatefulButton>
        </div>
        <FieldDescription>{t("token 只在这里输入，保存后不会再显示。")}</FieldDescription>
      </Field>}
      {tg && tg.has_token && !tg.bound && <>
        <p className="text-small text-ink-2">{t("请先生成一个绑定码，然后在 Telegram 上向你的 Bot 发送 /bind 命令加这个码。")}</p>
        {code && <p data-testid="telegram-code-line" className="m-0 text-small text-ink">{t("绑定码")}: <code data-testid="telegram-code" className="rounded-sm border border-line bg-sunken px-1.5 py-0.5 font-mono">{code}</code><br />{t("在 Telegram 上发送")}: <code className="rounded-sm border border-line bg-sunken px-1.5 py-0.5 font-mono">/bind {code}</code></p>}
        {waiting && <p data-testid="telegram-waiting" role="status" className="m-0 text-small text-muted-foreground">{t("绑定码已生成，30 分钟内有效。")}</p>}
        <div><StatefulButton type="button" variant={code ? "outline" : "default"} data-testid="telegram-make-code" className="max-sm:h-11" disabled={busy}
          onClick={() => act(async () => { const next = await startTelegramBind(); setCode(next.code); }, "操作失败，请重试。")}>{code || tg.bind_code_active ? t("重新生成") : t("生成绑定码")}</StatefulButton></div>
      </>}
      {tg?.configured && tg.bound && <div><Button type="button" variant="outline" data-testid="telegram-unbind" className="max-sm:h-11" disabled={busy} onClick={async (event) => {
        const from = event.currentTarget;
        if (!(await confirm({ returnFocus: from, title: t("解除 Telegram 绑定？"), description: t("解除绑定后，Telegram 消息不再被处理。"), confirmLabel: t("解除绑定"), cancelLabel: t("取消"), tone: "danger", hold: true }))) return;
        await act(async () => { setTg(await unbindTelegram()); setCode(""); }, "操作失败，请重试。").catch(() => {});
      }}>{t("解除绑定")}</Button></div>}
      {failure && <ErrorBar message={failure} />}
    </div>
    <p data-testid="telegram-own-bot" className="text-small text-muted-foreground">{t("每个 bot 自己的 Telegram 在它的 bot 设置页里设置。")}</p>
  </SettingsCard>;
}

function PushoverCard() {
  const { t } = useLocale();
  const [saved, setSaved] = useState<PushoverStatus | null>(null), [readError, setReadError] = useState(""), [userKey, setUserKey] = useState(""), [appToken, setAppToken] = useState(""), [busy, setBusy] = useState(false), [failure, setFailure] = useState("");
  const load = useCallback(async (signal?: AbortSignal) => {
    try { setSaved(await getPushover(signal)); setReadError(""); } catch (err) { if (!signal?.aborted) setReadError(message(err, t("Pushover 设置暂时无法读取。"))); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load]);
  async function act(work: () => Promise<void>, fallback: string) {
    setBusy(true); setFailure("");
    try { await work(); } catch (err) { setFailure(message(err, t(fallback))); throw err; } finally { setBusy(false); }
  }
  return <SettingsCard id="pushover" title={t("紧急提醒（Pushover）")} testid="pushover-card" description={t("急跌等提醒发到 Telegram 后，1 分钟内没点「收到」，就用 Pushover 紧急级通知响铃（每分钟一次，最多 30 分钟）；在 Pushover 里确认或在 Telegram 点「收到」都会停。两个值加密保存，保存后不会再显示。")}>
    {readError && <ErrorBar message={readError} onRetry={() => void load()} />}
    <div className="flex flex-wrap items-center gap-2"><span className="text-small font-medium text-ink">{t("状态")}</span><span data-testid="pushover-status" data-kind={saved?.configured ? "success" : "neutral"}><StatusBadge kind={saved?.configured ? "success" : "neutral"}>{saved?.configured ? t("已配置") : t("尚未配置")}</StatusBadge></span></div>
    <div className="grid gap-4 sm:grid-cols-2">
      <Field><FieldLabel htmlFor="pushover-user">{t("Pushover User Key")}</FieldLabel><Input id="pushover-user" type="password" value={userKey} maxLength={64} autoComplete="off" disabled={busy} className="max-sm:h-11" onChange={(e) => setUserKey(e.target.value)} /></Field>
      <Field><FieldLabel htmlFor="pushover-app">{t("Pushover App Token")}</FieldLabel><Input id="pushover-app" type="password" value={appToken} maxLength={64} autoComplete="off" disabled={busy} className="max-sm:h-11" onChange={(e) => setAppToken(e.target.value)} /></Field>
    </div>
    <div className="flex flex-wrap items-center gap-2">
      <StatefulButton type="button" data-testid="pushover-save" className="max-sm:h-11" disabled={busy || !userKey.trim() || !appToken.trim()}
        onClick={() => act(async () => { setSaved(await savePushover(userKey.trim(), appToken.trim())); setUserKey(""); setAppToken(""); notify.success(t("Pushover 已保存。"), { id: "settings:pushover" }); }, "保存失败，请重试。")}>{t("保存 Pushover")}</StatefulButton>
      {saved?.configured && <Button type="button" variant="outline" data-testid="pushover-clear" className="max-sm:h-11" disabled={busy}
        onClick={() => void act(async () => { setSaved(await clearPushover()); notify.success(t("Pushover 已清除。"), { id: "settings:pushover" }); }, "操作失败，请重试。").catch(() => {})}>{t("清除 Pushover")}</Button>}
    </div>
    {failure && <ErrorBar message={failure} />}
  </SettingsCard>;
}

const LOCAL_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

/** 主动消息发到哪里: one choice among three, saved the moment it is made, the state of each channel, and the last 20 messages sent proactively. */
function ChannelsCard() {
  const { t, locale } = useLocale();
  const [settings, setSettings] = useState<ChannelSettings | null>(null), [deliveries, setDeliveries] = useState<DeliveryItem[] | null>(null), [readError, setReadError] = useState(""), [busy, setBusy] = useState(false), [failure, setFailure] = useState("");
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const [next, items] = await Promise.all([getChannelSettings(signal), listChannelDeliveries(20, signal)]);
      setSettings(next); setDeliveries(items); setReadError("");
    } catch (err) { if (!signal?.aborted) setReadError(message(err, t("主动消息的设置暂时无法读取。"))); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load]);
  async function choose(id: string) {
    const next = prefsForOption(id);
    if (!next || busy) return;
    setBusy(true); setFailure("");
    try { const saved = await saveChannelPrefs(next); setSettings((current) => current && { ...current, prefs: saved }); notify.success(t("已保存。"), { id: "settings:channels" }); }
    catch (err) { setFailure(message(err, t("保存失败，请重试。"))); } finally { setBusy(false); }
  }
  const selected = settings ? optionForPrefs(settings.prefs) : "";
  const available = settings?.available;
  return <SettingsCard id="channels" title={t("主动消息发到哪里")} testid="channels-card" description={t("bot 主动找你时（提醒、简报、通知）发到哪个聊天；选了就保存。")}>
    {readError && <ErrorBar message={readError} onRetry={() => void load()} />}
    {settings && <>
      <Select value={selected} disabled={busy} onValueChange={(id) => void choose(id)}>
        <SelectTrigger aria-label={t("主动消息发到哪里")} data-testid="channels-select" className="w-full max-w-md max-sm:h-11"><SelectValue placeholder={rawOrderText(settings.prefs)} /></SelectTrigger>
        <SelectContent>{CHANNEL_OPTIONS.map((o) => <SelectItem key={o.id} value={o.id}>{t(o.label)}</SelectItem>)}</SelectContent>
      </Select>
      {!selected && <p data-testid="channels-raw" className="m-0 text-small text-muted-foreground">{t("当前设置不是上面三种之一：")}{rawOrderText(settings.prefs)}</p>}
      {available && <p data-testid="channels-available" className="m-0 text-small text-ink-2">{t("微信")}{locale === "en-US" ? ": " : "："}{available.wechat ? t("已连接") : t("未连接")}{" · "}{t("Telegram")}{locale === "en-US" ? ": " : "："}{available.telegram ? t("已绑定") : t("未绑定")}</p>}
      {fallbackWarning(selected, available) && <p data-testid="channels-warning" role="status" className="m-0 text-small text-ink">{t("微信还没有连接，消息会改发 Telegram。")}</p>}
      {failure && <ErrorBar message={failure} />}
      <div className="flex flex-col gap-2">
        <h3 className="m-0 text-small font-medium text-ink">{t("最近的发送")}</h3>
        {deliveries && deliveries.length === 0 && <p data-testid="channels-empty" className="m-0 text-small text-muted-foreground">{t("还没有主动消息。")}</p>}
        {deliveries && deliveries.length > 0 && <ul data-testid="channels-deliveries" className="m-0 grid list-none divide-y divide-line p-0">
          {deliveries.map((item) => {
            const row = deliveryRow(item);
            return <li key={item.id} data-testid="channels-delivery" data-status={item.status} className="flex min-w-0 flex-col gap-0.5 py-2 first:pt-0 last:pb-0">
              <span className="text-small text-ink-2">{formatDateTime(item.created_at, locale, LOCAL_ZONE)} · {t(row.channelLabel)} · {deliveryStatusText(item, t)}{row.acked ? ` · ${t("你之后来过")}` : ""}</span>
              {row.firstLine && <span className="truncate text-small text-ink">{row.firstLine}</span>}
            </li>;
          })}
        </ul>}
      </div>
    </>}
  </SettingsCard>;
}
