// The bot's workspace pane (the right panel's 工作区 tab); split from BotPages.tsx in P3.1 so the sidebar's chunk does not carry it.
// The profile form that used to be here is the bot settings page now (app/bot-settings, P5.1), and the new-bot dialog is app/new-bot (P5.2).  Old markup, moved as-is.
import { useEffect, useRef, useState } from "react";
import type { Bot } from "./api/bots";
import { useLocale } from "./i18n";
import { WorkspaceCard } from "./WorkspaceCards";
import { CARDS, addCard, botSymbol, loadLayout, moveCard, pinCardSymbol, removeCard, resetLayout, resizeCard, saveLayout, storeBotSymbol, symbolChoices, type CardId, type LayoutItem } from "./workspace-cards.mjs";

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
