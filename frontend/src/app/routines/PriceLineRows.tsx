import { Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { FieldError } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { useLocale } from "../../i18n";
import { MAX_PRICE_LINES } from "../../routine-form.mjs";
import { blankRow, isRawRow, parsePriceText, rowProblem, type PriceRow } from "../../price-lines.mjs";

/**
 * The price lines of an alert task, one row each: code, 高于 / 低于, price (design 4.10).  What was typed as "NVDA>150, AAPL<180" is these rows; a row that cannot be one
 * (an old task's odd text) stays as its own text, marked, until the reader writes it as a line or deletes it.  `shown`: the problems are told now (after a save was tried).
 */
export function PriceLineRows({ rows, onChange, shown, messages, disabled }: { rows: PriceRow[]; onChange: (rows: PriceRow[]) => void; shown: boolean; messages: Record<string, string>; disabled?: boolean }) {
  const { t } = useLocale();
  const set = (index: number, next: PriceRow) => onChange(rows.map((row, at) => at === index ? next : row));
  return <div data-testid="price-rows" className="flex flex-col gap-2">
    {rows.length === 0 && <p className="text-small text-muted-foreground">{t("还没有价格线。")}</p>}
    {rows.map((row, index) => {
      const found = rowProblem(row);
      // A row that is not a line at all (an old task's text) is said so at once, whether or not a save was tried; the other problems wait for the save.
      const problem = shown || found === "raw" ? found : null;
      const messageId = `price-row-${index}-message`;
      return <div key={index} data-testid="price-row" data-problem={problem ?? undefined} className="flex flex-col gap-1">
        {isRawRow(row)
          ? <div className="flex items-center gap-2">
            <Input value={row.raw} disabled={disabled} aria-label={`${t("价格线")} ${index + 1}`} aria-invalid={problem ? true : undefined} aria-describedby={problem ? messageId : undefined} data-field="raw" className="font-mono"
              onChange={(event) => { const parsed = parsePriceText(event.target.value); set(index, parsed.length === 1 && !isRawRow(parsed[0]) ? parsed[0] : { raw: event.target.value }); }} />
            <RemoveButton index={index} disabled={disabled} onClick={() => onChange(rows.filter((_, at) => at !== index))} />
          </div>
          : <div className="flex items-start gap-2">
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
            <Input value={row.symbol} disabled={disabled} placeholder="NVDA" autoCapitalize="characters" spellCheck={false} aria-label={`${t("价格线")} ${index + 1} ${t("代码")}`} data-field="symbol"
              aria-invalid={problem === "symbol" || problem === "incomplete" && !row.symbol.trim() ? true : undefined} aria-describedby={problem ? messageId : undefined} className="w-28 font-mono uppercase"
              onChange={(event) => set(index, { ...row, symbol: event.target.value })} />
            <div role="radiogroup" aria-label={`${t("价格线")} ${index + 1} ${t("方向")}`} data-testid="price-side" className="inline-flex shrink-0 gap-1.5">
              {(["above", "below"] as const).map((side) => <label key={side} data-option={side} className={cn("relative inline-flex min-h-9 max-sm:min-h-11 cursor-pointer items-center rounded-sm border px-2.5 text-small text-ink select-none",
                "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-brand", row.side === side ? "border-brand bg-brand-soft font-medium" : "border-line bg-surface hover:bg-sunken", disabled && "cursor-not-allowed opacity-55")}>
                <input type="radio" name={`price-side-${index}`} value={side} checked={row.side === side} disabled={disabled} onChange={() => set(index, { ...row, side })} className="sr-only" />
                {t(side === "above" ? "高于" : "低于")}
              </label>)}
            </div>
            <Input value={row.price} disabled={disabled} inputMode="decimal" placeholder="150" aria-label={`${t("价格线")} ${index + 1} ${t("价格")}`} data-field="price"
              aria-invalid={problem === "price" || problem === "incomplete" && !row.price.trim() ? true : undefined} aria-describedby={problem ? messageId : undefined} className="w-28 font-mono"
              onChange={(event) => set(index, { ...row, price: event.target.value })} />
            </div>
            <RemoveButton index={index} disabled={disabled} onClick={() => onChange(rows.filter((_, at) => at !== index))} />
          </div>}
        {problem && <FieldError id={messageId} data-testid="price-row-message">{messages[`priceRows:${index}`]}</FieldError>}
      </div>;
    })}
    <div><Button type="button" variant="outline" size="sm" disabled={disabled || rows.length >= MAX_PRICE_LINES} data-testid="price-add" className="max-sm:h-11" onClick={() => onChange([...rows, blankRow()])}><Plus aria-hidden="true" />{t("添加一行")}</Button></div>
    {rows.length >= MAX_PRICE_LINES && <p className="text-caption text-muted-foreground">{t("最多 30 条价格线。")}</p>}
  </div>;
}

function RemoveButton({ index, onClick, disabled }: { index: number; onClick: () => void; disabled?: boolean }) {
  const { t } = useLocale();
  return <Button type="button" variant="ghost" size="icon" disabled={disabled} aria-label={`${t("删除价格线")} ${index + 1}`} data-testid="price-remove" className="size-9 shrink-0 max-sm:size-11" onClick={onClick}><X aria-hidden="true" /></Button>;
}
