import { useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useLocale } from "../../../i18n";

/** The company to forecast: a button that opens a short searchable list (a combobox).  The value is always one of the choices. */
export function SymbolCombobox({ value, choices, onChange, id, testId = "forecast-create-symbol", disabled, className = "" }: { value: string; choices: string[]; onChange: (symbol: string) => void; id?: string; testId?: string; disabled?: boolean; className?: string }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  return <Popover open={open} onOpenChange={setOpen}>
    <PopoverTrigger asChild>
      <Button id={id} type="button" variant="outline" role="combobox" aria-expanded={open} aria-label={t("选择股票")} data-testid={testId} disabled={disabled} className={`w-32 justify-between font-mono ${className}`}>
        {value}<ChevronsUpDown aria-hidden="true" className="opacity-60" />
      </Button>
    </PopoverTrigger>
    <PopoverContent align="start" className="w-40 p-0">
      <Command>
        <CommandInput placeholder={t("搜索代码")} />
        <CommandList>
          <CommandEmpty>{t("没有这个代码")}</CommandEmpty>
          <CommandGroup>
            {choices.map(symbol => <CommandItem key={symbol} value={symbol} data-symbol={symbol} onSelect={() => { onChange(symbol); setOpen(false); }} className="font-mono">
              {symbol}{symbol === value && <Check aria-hidden="true" className="ml-auto" />}
            </CommandItem>)}
          </CommandGroup>
        </CommandList>
      </Command>
    </PopoverContent>
  </Popover>;
}
