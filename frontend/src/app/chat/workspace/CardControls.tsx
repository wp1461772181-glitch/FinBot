import { MoveDown, MoveUp, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useLocale } from "../../../i18n";
import type { LayoutItem } from "../../../workspace-cards.mjs";
import { PER_STOCK } from "./WorkspaceCard";

type Size = "s" | "m" | "l";

/**
 * What a card offers while the layout is edited: up, down, its size, the stock it is pinned to (the four that follow a stock) and delete.  The pin is taken when the box loses the focus
 * (an empty box unpins), the size and the order at once.  Choosing 默认 for the size changes nothing (the old menu behaved so: only S, M and L are sizes; 恢复默认 puts the sizes back).
 */
export function CardControls({ item, index, last, onMove, onSize, onPin, onRemove }: {
  item: LayoutItem; index: number; last: boolean; onMove: (delta: number) => void; onSize: (size: Size) => void; onPin: (symbol: string) => void; onRemove: () => void;
}) {
  const { t } = useLocale();
  return <span className="inline-flex flex-wrap items-center gap-1">
    <Button type="button" variant="ghost" size="icon-sm" disabled={index === 0} aria-label={t("上移")} onClick={() => onMove(-1)}><MoveUp aria-hidden="true" /></Button>
    <Button type="button" variant="ghost" size="icon-sm" disabled={last} aria-label={t("下移")} onClick={() => onMove(1)}><MoveDown aria-hidden="true" /></Button>
    <Select value={item.size ?? "default"} onValueChange={value => onSize((value === "default" ? "" : value) as Size)}>
      <SelectTrigger size="sm" aria-label={t("大小")} className="w-24 text-small"><SelectValue /></SelectTrigger>
      <SelectContent position="popper"><SelectItem value="default">{t("默认")}</SelectItem><SelectItem value="s">S</SelectItem><SelectItem value="m">M</SelectItem><SelectItem value="l">L</SelectItem></SelectContent>
    </Select>
    {PER_STOCK.includes(item.card) && <Input defaultValue={item.symbol ?? ""} maxLength={8} placeholder={t("固定股票")} aria-label={t("固定股票")} className="h-8 w-24 font-mono text-small"
      onBlur={event => onPin(event.target.value)} />}
    <Button type="button" variant="ghost" size="icon-sm" aria-label={t("删除")} onClick={onRemove}><Trash2 aria-hidden="true" /></Button>
  </span>;
}
