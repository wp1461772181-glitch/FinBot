import { useState, type FormEvent } from "react";
import { Check, ChevronsUpDown, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useLocale } from "../../i18n";

/**
 * Where the old top bar's company controls went (design P2.2 §3): the research pages still take the company from the
 * shell, so a thin bar above them holds the company switcher (a Combobox over the watchlist; choosing a company opens
 * the same kind of page for it) and the field that adds a code to the watchlist.  Temporary: the company page (P6)
 * brings its own switcher in the title row.  Loaded only on the research pages.
 */
export default function ResearchBar({ symbol, symbols, onSelectStock, watchInput, setWatchInput, addWatchSymbol, watchError, setWatchError }: {
  symbol: string; symbols: string[]; onSelectStock: (ticker: string) => void; watchInput: string; setWatchInput: (value: string) => void; addWatchSymbol: () => void; watchError: string; setWatchError: (value: string) => void;
}) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const choices = symbols.includes(symbol) ? symbols : [symbol, ...symbols];
  const submit = (event: FormEvent) => { event.preventDefault(); addWatchSymbol(); };
  return <div data-slot="research-bar" className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-4 py-2 lg:px-6">
    <p className="text-small text-muted-foreground">{t("公司研究")}</p>
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" role="combobox" aria-expanded={open} aria-label={`${t("切换股票")}：${symbol}`} className="h-9 min-w-32 justify-between font-mono">
          {symbol}<ChevronsUpDown aria-hidden="true" className="opacity-60" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-56 p-0">
        <Command>
          <CommandInput placeholder={t("搜索代码")} />
          <CommandList>
            <CommandEmpty>{t("关注列表里没有这个代码")}</CommandEmpty>
            <CommandGroup heading={t("关注列表")}>
              {choices.map(ticker => <CommandItem key={ticker} value={ticker} onSelect={() => { setOpen(false); if (ticker !== symbol) onSelectStock(ticker); }}>
                <span className="font-mono">{ticker}</span>{ticker === symbol && <><span className="text-caption text-muted-foreground">{t("当前")}</span><Check aria-hidden="true" className="ml-auto" /></>}
              </CommandItem>)}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
    <form className="flex items-center gap-2" onSubmit={submit}>
      <label className="sr-only" htmlFor="watch-add">{t("添加股票")}</label>
      <Input id="watch-add" value={watchInput} onChange={event => { setWatchInput(event.target.value); setWatchError(""); }} placeholder={t("添加代码，如 AMD")} maxLength={10} className="h-9 w-44" />
      <Button type="submit" variant="outline" size="icon" aria-label={t("添加股票")}><Plus aria-hidden="true" /></Button>
      {watchError && <span role="alert" className="text-small text-danger">{t(watchError)}</span>}
    </form>
  </div>;
}
