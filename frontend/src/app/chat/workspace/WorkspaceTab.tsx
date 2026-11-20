import { useId, useState } from "react";
import { Plus, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { Bot } from "../../../api/bots";
import { useLocale, colon } from "../../../i18n";
import { CARDS, addCard, loadLayout, moveCard, pinCardSymbol, removeCard, resetLayout, resizeCard, saveLayout, symbolChoices, type CardId, type LayoutItem } from "../../../workspace-cards.mjs";
import { CardControls } from "./CardControls";
import { WorkspaceCard } from "./WorkspaceCard";

const TICKER = /^[A-Z]{1,5}(?:[.-][A-Z]{1,2})?$/;

/**
 * The 工作区 tab: where the line's work points — its focus companies and the research pages they open.  预测 (forecast, revision, maturity review, replay) lives on the company
 * pages, never as price talk in the line.  The layout (which cards, their order, sizes and pinned stocks) is kept in this browser per bot (workspace-cards.mjs).
 */
export function WorkspaceTab({ bot, symbol, watchlist, wide, onPickSymbol }: { bot: Bot; symbol: string; watchlist: string[]; wide: boolean; onPickSymbol: (symbol: string) => void }) {
  const { t } = useLocale();
  const stockId = useId();
  const [layout, setLayoutState] = useState<LayoutItem[]>(() => loadLayout(bot.id));
  const [editing, setEditing] = useState(false), [typed, setTyped] = useState("");
  const setLayout = (next: LayoutItem[]) => setLayoutState(saveLayout(bot.id, next));
  const choices = symbolChoices(bot, watchlist, symbol);
  const pickTyped = () => { const clean = typed.trim().toUpperCase(); if (TICKER.test(clean)) { onPickSymbol(clean); setTyped(""); } };
  const missing = CARDS.filter(c => !layout.some(x => x.card === c.id));
  return <div data-testid="workspace-tab" data-wide={wide || undefined} className="grid gap-3 text-small text-ink">
    <div className="flex flex-wrap items-center gap-2">
      <div className="inline-flex items-center gap-1.5 text-muted-foreground">
        <label htmlFor={stockId}>{t("当前股票")}</label>
        <Select value={symbol} onValueChange={onPickSymbol}>
          <SelectTrigger id={stockId} size="sm" className="w-28 font-mono text-small"><SelectValue /></SelectTrigger>
          <SelectContent position="popper">{choices.map(s => <SelectItem key={s} value={s} className="font-mono">{s}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      <Input value={typed} maxLength={8} placeholder={t("其他代码")} aria-label={t("其他代码")} className="h-8 w-28 font-mono text-small"
        onChange={event => setTyped(event.target.value)} onKeyDown={event => { if (event.key === "Enter") pickTyped(); }} />
      <Button type="button" variant="outline" size="sm" aria-pressed={editing} onClick={() => setEditing(!editing)}>{editing ? t("完成") : <><SlidersHorizontal aria-hidden="true" />{t("编辑卡片")}</>}</Button>
    </div>
    {editing && <div className="flex flex-wrap items-center gap-2">
      {missing.length > 0 && <Select value="" onValueChange={value => { if (value) setLayout(addCard(layout, value as CardId)); }}>
        <SelectTrigger size="sm" aria-label={t("添加卡片")} className="w-36 text-small"><SelectValue placeholder={<span className="inline-flex items-center gap-1.5"><Plus aria-hidden="true" className="size-3.5" />{t("添加卡片")}</span>} /></SelectTrigger>
        <SelectContent position="popper">{missing.map(c => <SelectItem key={c.id} value={c.id}>{t(c.title)}</SelectItem>)}</SelectContent>
      </Select>}
      <Button type="button" variant="outline" size="sm" onClick={() => setLayoutState(resetLayout(bot.id))}>{t("恢复默认")}</Button>
    </div>}
    <div data-testid="workspace-grid" className={cn("grid gap-2.5", wide ? "grid-cols-2" : "grid-cols-1")}>{layout.map((item, index) => <WorkspaceCard key={`${item.card}:${index}`} item={item} bot={bot} symbol={symbol} wide={wide} editing={editing} onPickSymbol={onPickSymbol}
      controls={editing ? <CardControls item={item} index={index} last={index === layout.length - 1} onMove={delta => setLayout(moveCard(layout, index, delta))}
        onSize={size => setLayout(resizeCard(layout, index, size))} onPin={value => setLayout(pinCardSymbol(layout, index, value))} onRemove={() => setLayout(removeCard(layout, index))} /> : undefined} />)}</div>
    {bot.focus.theme && <p className="m-0 text-caption text-muted-foreground">{t("关注主题")}{colon()}{bot.focus.theme}</p>}
    <p className="m-0 text-caption text-muted-foreground">{t("隔离的是记忆和注意力，不是数据：任何 bot 都能查所有公司的数据，工具范围限定的除外。")}</p>
  </div>;
}
