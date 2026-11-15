// The bot's workspace pane (the right panel's 工作区 tab) and the new-bot dialog; split from BotPages.tsx in P3.1 so the sidebar's chunk does not carry them.
// The profile form that used to be here is the bot settings page now (app/bot-settings, P5.1).  Old markup, moved as-is; the new-bot dialog is restyled in P5.2.
import { useEffect, useRef, useState } from "react";
import { createBot, getBotTemplates } from "./api/bots-admin";
import type { Bot, BotTemplate, BotTool } from "./api/bots";
import { useLocale } from "./i18n";
import { newBotFields } from "./bot-form-items.mjs";
import { BotAvatar } from "./components/bot/BotAvatar";
import { BOT_AVATAR_SIZE } from "./bot-sizes.mjs";
import { BloubCustomizer } from "./BloubCustomizer";
import { randomLook, type BloubLook } from "./bloub-look.mjs";
import { DEFAULT_AVATAR } from "./orb.mjs";
import { WorkspaceCard } from "./WorkspaceCards";
import { CARDS, addCard, botSymbol, loadLayout, moveCard, pinCardSymbol, removeCard, resetLayout, resizeCard, saveLayout, storeBotSymbol, symbolChoices, type CardId, type LayoutItem } from "./workspace-cards.mjs";
import { message } from "./bot-message";

/** New bot: one step.  A name is all it needs; a template is an optional shortcut that only pre-fills what was
 * left blank.  Focus, model, tools, skills and the daily cap are set later on the bot's settings page. */
export function NewBotDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (bot: Bot) => void }) {
  const { t } = useLocale();
  const [templates, setTemplates] = useState<BotTemplate[]>([]), [tools, setTools] = useState<BotTool[]>([]);
  const [name, setName] = useState(""), [picked, setPicked] = useState<BotTemplate | null>(null);
  // A new bot starts from a random shape and colour of the catalog (shown, and stored on create): the customiser changes any of it.
  const [look, setLook] = useState<BloubLook>(() => randomLook());
  const [busy, setBusy] = useState(false), [status, setStatus] = useState("");
  const dialog = useRef<HTMLElement>(null), nameBox = useRef<HTMLInputElement>(null);
  useEffect(() => { nameBox.current?.focus(); const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); }; document.addEventListener("keydown", key); return () => document.removeEventListener("keydown", key); }, [onClose]);
  useEffect(() => {
    const controller = new AbortController();
    // Templates are only a shortcut: when they cannot be read, a name still creates the bot.
    getBotTemplates(controller.signal).then(v => { setTemplates(v.templates.filter(x => x.id !== "blank")); setTools(v.tools); }).catch(() => { /* create works without them */ });
    return () => controller.abort();
  }, []);
  const fields = { ...newBotFields(name, picked, tools), avatar: DEFAULT_AVATAR, look };
  async function save(event?: React.FormEvent) {
    event?.preventDefault();
    if (!fields.name || busy) return;
    setBusy(true); setStatus("");
    try { onCreated(await createBot(fields)); } catch (err) { setStatus(message(err, t("创建失败，请重试。"))); } finally { setBusy(false); }
  }
  return <div className="profile-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
    <section ref={dialog} className="profile-modal bot-dialog is-compact" role="dialog" aria-modal="true" aria-labelledby="new-bot-title">
      <button className="profile-close" onClick={onClose} aria-label={t("关闭")} disabled={busy}>×</button>
      <h2 id="new-bot-title">{t("新建 bot")}</h2>
      <form className="bot-create" onSubmit={e => void save(e)}>
        <div className="bot-orb-hero"><BotAvatar avatar={DEFAULT_AVATAR} look={look} name={name || "FinBot"} size={BOT_AVATAR_SIZE.createHero} /><small>{name || t("新 bot")}</small></div>
        <BloubCustomizer look={look} onChange={setLook} disabled={busy} />
        <label>{t("名字")}<input ref={nameBox} value={name} maxLength={40} disabled={busy} onChange={e => setName(e.target.value)} placeholder={picked?.name || t("例如：读财报")} /></label>
        {templates.length > 0 && <fieldset className="bot-template-chips" disabled={busy}><legend>{t("模板（可选）")}</legend>
          {templates.map(tpl => <button key={tpl.id} type="button" className="bot-chip" aria-pressed={picked?.id === tpl.id} title={tpl.description ? t(tpl.description) : undefined} onClick={() => setPicked(picked?.id === tpl.id ? null : tpl)}>{t(tpl.label)}</button>)}
        </fieldset>}
        <p className="fine-print">{picked ? t("模板只预填空着的头衔、说明和工具范围。") : ""}{t("关注公司、模型、工具、技能和通知上限，创建后都在 bot 设置里改。")}</p>
        {status && <p className="agent-chat-status is-error" role="alert">{status}</p>}
        <div className="chat-archive-tools"><button type="button" className="secondary-action" disabled={busy} onClick={onClose}>{t("取消")}</button>
          <button type="submit" className="primary-action" disabled={busy || !fields.name}>{busy ? t("正在保存…") : t("创建")}</button></div>
      </form>
    </section>
  </div>;
}

type OpenCompany = (ticker: string, section?: "overview" | "forecast") => void;

/** The 工作区 tab: where the line's work points — its focus companies and the research pages they open.  预测
 * (forecast, revision, maturity review, replay) lives on the company pages, never as price talk in the line. */
function BotWorkspaceTab({ bot, symbol, watchlist, wide, onPickSymbol, onOpenCompany }: { bot: Bot; symbol: string; watchlist: string[]; wide: boolean; onPickSymbol: (symbol: string) => void; onOpenCompany: OpenCompany }) {
  const { t } = useLocale();
  const [layout, setLayoutState] = useState<LayoutItem[]>(() => loadLayout(bot.id));
  const [editing, setEditing] = useState(false), [typed, setTyped] = useState("");
  const setLayout = (next: LayoutItem[]) => setLayoutState(saveLayout(bot.id, next));
  const choices = symbolChoices(bot, watchlist, symbol);
  const pickTyped = () => { const clean = typed.trim().toUpperCase(); if (/^[A-Z]{1,5}(?:[.-][A-Z]{1,2})?$/.test(clean)) { onPickSymbol(clean); setTyped(""); } };
  const missing = CARDS.filter(c => !layout.some(x => x.card === c.id));
  return <div className={`bot-workspace${wide ? " is-wide" : ""}`}>
    <div className="ws-toolbar">
      <label className="ws-symbol">{t("当前股票")}
        <select value={symbol} onChange={e => onPickSymbol(e.target.value)}>{choices.map(s => <option key={s} value={s}>{s}</option>)}</select>
      </label>
      <input className="ws-symbol-input" value={typed} maxLength={8} placeholder={t("其他代码")} aria-label={t("其他代码")} onChange={e => setTyped(e.target.value)} onKeyDown={e => { if (e.key === "Enter") pickTyped(); }} />
      <button type="button" className="text-button" aria-pressed={editing} onClick={() => setEditing(!editing)}>{editing ? t("完成") : `⚙ ${t("编辑卡片")}`}</button>
    </div>
    {editing && <div className="ws-edit-bar">
      {missing.length > 0 && <select value="" aria-label={t("添加卡片")} onChange={e => { if (e.target.value) setLayout(addCard(layout, e.target.value as CardId)); }}>
        <option value="">＋ {t("添加卡片")}</option>{missing.map(c => <option key={c.id} value={c.id}>{t(c.title)}</option>)}</select>}
      <button type="button" className="text-button" onClick={() => setLayoutState(resetLayout(bot.id))}>{t("恢复默认")}</button>
    </div>}
    <div className="ws-grid">{layout.map((item, index) => <WorkspaceCard key={`${item.card}:${index}`} item={item} bot={bot} symbol={symbol} wide={wide} editing={editing}
      onOpenCompany={onOpenCompany} onPickSymbol={onPickSymbol}
      controls={editing ? <span className="ws-card-controls">
        <button type="button" className="text-button" disabled={index === 0} aria-label={t("上移")} onClick={() => setLayout(moveCard(layout, index, -1))}>↑</button>
        <button type="button" className="text-button" disabled={index === layout.length - 1} aria-label={t("下移")} onClick={() => setLayout(moveCard(layout, index, 1))}>↓</button>
        <select value={item.size ?? ""} aria-label={t("大小")} onChange={e => setLayout(resizeCard(layout, index, e.target.value as "s" | "m" | "l"))}><option value="">{t("默认")}</option><option value="s">S</option><option value="m">M</option><option value="l">L</option></select>
        {["price", "forecast", "materials", "filings"].includes(item.card) && <input className="ws-pin" defaultValue={item.symbol ?? ""} maxLength={8} placeholder={t("固定股票")} aria-label={t("固定股票")} onBlur={e => setLayout(pinCardSymbol(layout, index, e.target.value))} />}
        <button type="button" className="text-button" aria-label={t("删除")} onClick={() => setLayout(removeCard(layout, index))}>✕</button>
      </span> : undefined} />)}</div>
    {bot.focus.theme && <p className="fine-print">{t("关注主题")}：{bot.focus.theme}</p>}
    <p className="fine-print">{t("隔离的是记忆和注意力，不是数据：任何 bot 都能查所有公司的数据，工具范围限定的除外。")}</p>
  </div>;
}

/**
 * The pane of the chat page's right panel that is this file's: 工作区 (the bot's data cards).  The panel itself (tabs, width, 来源 and 过程) is
 * app/chat/ContextPanel.tsx; this is the old pane it holds, moved as it was.  The current stock
 * is kept per bot and follows the page's stock, as the old right rail kept it.
 */
export function BotWorkspacePane({ bot, symbol, watchlist = [], onSelectSymbol, onOpenCompany, wide }: { bot: Bot; symbol: string; watchlist?: string[]; onSelectSymbol?: (symbol: string) => void; onOpenCompany: OpenCompany; wide: boolean }) {
  const [current, setCurrent] = useState(() => botSymbol(bot, symbol));
  const seenGlobal = useRef(symbol);
  useEffect(() => { if (current !== symbol) onSelectSymbol?.(current); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (symbol === seenGlobal.current) return;
    seenGlobal.current = symbol;
    if (symbol !== current) { setCurrent(symbol); storeBotSymbol(bot.id, symbol); }
  }, [symbol]); // eslint-disable-line react-hooks/exhaustive-deps
  const pick = (next: string) => { const clean = storeBotSymbol(bot.id, next); if (!clean) return; setCurrent(clean); seenGlobal.current = clean; onSelectSymbol?.(clean); };
  return <BotWorkspaceTab bot={bot} symbol={current} watchlist={watchlist} wide={wide} onPickSymbol={pick} onOpenCompany={onOpenCompany} />;
}
