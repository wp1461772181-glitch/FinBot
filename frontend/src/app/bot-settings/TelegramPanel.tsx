import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FieldDescription, FieldLabel } from "@/components/ui/field";
import { StatefulButton } from "@/components/state/StatefulButton";
import { ErrorBar } from "@/components/state/ErrorBar";
import { confirm } from "@/components/state/confirm";
import { Stepper } from "@/components/Stepper";
import { deleteBotTelegram, getBotTelegram, saveBotTelegramToken, startBotTelegramBind, unbindBotTelegram, type BotTelegramStatus } from "../../api/integrations";
import type { Bot } from "../../api/bots";
import { message } from "../../bot-message";
import { useLocale } from "../../i18n";
import { TELEGRAM_STEPS, telegramStep } from "../../bot-settings-form.mjs";

/**
 * A bot's own Telegram bot (optional).  Without one its messages go through the shared bot (设置 › 通知) with 「【名字】」 in front.  Three steps: save the
 * token, make a binding code, wait for the message (the page asks again every 5 s while it waits).  The requests are the old ones.  The token is
 * a secret: the box is a password box, it is emptied once saved and never filled again; the page shows only @username and the last four characters.
 */
export function TelegramPanel({ bot }: { bot: Bot }) {
  const { t } = useLocale();
  const [state, setState] = useState<BotTelegramStatus | null>(null), [token, setToken] = useState(""), [busy, setBusy] = useState(false);
  const [note, setNote] = useState(""), [bind, setBind] = useState<{ code: string; link?: string | null } | null>(null);
  const load = useCallback(async () => { try { setState(await getBotTelegram(bot.id)); } catch (err) { setNote(message(err, t("Telegram 设置暂时无法读取。"))); } }, [bot.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!bot.is_default) void load(); }, [load, bot.is_default]);
  useEffect(() => { if (!bind || state?.bound) return; const timer = window.setInterval(() => void load(), 5000); return () => window.clearInterval(timer); }, [bind, state?.bound, load]);
  const act = async (run: () => Promise<unknown>) => { setBusy(true); setNote(""); try { await run(); await load(); } catch (err) { setNote(message(err, t("操作失败，请重试。"))); throw err; } finally { setBusy(false); } };
  if (bot.is_default) return <section data-testid="telegram-panel" className="grid gap-1.5"><h3 className="text-body font-medium text-ink">Telegram</h3>
    <p className="text-small text-muted-foreground">{t("默认 bot 用设置页里的共用 Telegram bot；没接自己 Telegram 的 bot 也经它收发，消息前带「【名字】」。")}</p></section>;
  const label = state?.status === "running" ? t("已绑定 · 运行中") : state?.status === "invalid" ? t("token 失效") : state?.status === "conflict" ? t("冲突：token 正在别处使用") : state?.has_token ? t("未绑定") : t("未接入");
  const step = telegramStep(state, bind);
  return <section data-testid="telegram-panel" data-step={step} className="grid gap-4">
    <h3 className="text-body font-medium text-ink">Telegram · {label}</h3>
    <Stepper label={t("Telegram 绑定的三步")} steps={TELEGRAM_STEPS.map((s) => ({ id: s, label: t(s) }))} current={step} waiting={step === 2} />
    {!state?.has_token ? <>
      <p className="text-small text-muted-foreground">{t("可选：在 BotFather 新建一个 Telegram bot，把 token 贴进来，这个 bot 就有自己的 Telegram。不接也行，消息走共用 bot。")}</p>
      <Field>
        <FieldLabel htmlFor="bot-tg-token">Bot token</FieldLabel>
        <div className="flex flex-wrap items-center gap-2">
          <Input id="bot-tg-token" type="password" className="max-w-72 flex-1" value={token} autoComplete="off" placeholder="123456:ABC…" disabled={busy} onChange={e => setToken(e.target.value)} />
          <StatefulButton type="button" disabled={busy || token.trim().length < 8} onClick={() => act(async () => { await saveBotTelegramToken(bot.id, token.trim()); setToken(""); })}>{t("保存 token")}</StatefulButton>
        </div>
        <FieldDescription>{t("token 只在这里输入，保存后不会再显示。")}</FieldDescription>
      </Field>
    </> : <>
      <p data-testid="telegram-identity" className="text-small text-ink">{state.bot_username ? `@${state.bot_username}` : t("（用户名稍后显示）")} · token …{state.token_tail ?? "????"}</p>
      {state.last_error && <p className="text-small text-ink">{state.last_error}</p>}
      {!state.bound && <div className="flex flex-wrap items-center gap-2">
        <StatefulButton type="button" variant="outline" disabled={busy} onClick={() => act(async () => setBind(await startBotTelegramBind(bot.id)))}>{bind ? t("重新生成绑定码") : t("生成绑定码")}</StatefulButton>
        {bind && (bind.link ? <Button asChild><a href={bind.link} target="_blank" rel="noreferrer">{t("在 Telegram 打开并发送")}</a></Button> : <code data-testid="telegram-code" className="rounded-sm border border-line bg-sunken px-2 py-1 font-mono text-small">/start {bind.code}</code>)}
      </div>}
      {bind && !state.bound && <p data-testid="telegram-waiting" role="status" className="text-small text-muted-foreground">{t("绑定码 30 分钟内有效。发送后最多 30 秒，这里会变成「已绑定 · 运行中」。")}</p>}
      <div className="flex flex-wrap items-center gap-2">
        {state.bound && <Button type="button" variant="outline" disabled={busy} onClick={() => void act(async () => { await unbindBotTelegram(bot.id); setBind(null); }).catch(() => {})}>{t("解绑")}</Button>}
        <Button type="button" variant="outline" disabled={busy} onClick={async () => { if (await confirm({ title: t("删除这个 bot 的 Telegram token？"), description: t("之后它的消息走共用 bot。也请到 BotFather 撤销这个 token。"), confirmLabel: t("删除"), cancelLabel: t("取消"), tone: "danger", hold: true })) void act(() => deleteBotTelegram(bot.id)).then(() => setBind(null)).catch(() => {}); }}>{t("换 token / 删除")}</Button>
      </div>
    </>}
    {note && <ErrorBar message={note} />}
  </section>;
}
