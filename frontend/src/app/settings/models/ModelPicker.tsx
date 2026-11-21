import { useState } from "react";
import { Check, ChevronsUpDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useLocale } from "../../../i18n";

export type Candidate = { id: string; name: string };

/** 服务商可用模型: a button that opens a searchable list of every model the provider returned (a combobox).  Typing filters by id and name; picking one hands its id back, it does not hold a value of its own. */
export function ModelPicker({ candidates, current, disabled, labelledBy, onPick }: { candidates: Candidate[]; current: string; disabled?: boolean; labelledBy: string; onPick: (id: string) => void }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  return <Popover open={open} onOpenChange={setOpen}>
    <PopoverTrigger asChild>
      <Button type="button" variant="outline" role="combobox" aria-expanded={open} aria-labelledby={labelledBy} data-testid="model-discovered" disabled={disabled || candidates.length === 0} className="min-w-0 flex-1 justify-between font-normal max-lg:h-11">
        <span className="truncate text-muted-foreground">{t("选择列表中的模型填入 Model ID")}</span><ChevronsUpDown aria-hidden="true" className="opacity-60" />
      </Button>
    </PopoverTrigger>
    <PopoverContent align="start" className="w-(--radix-popover-trigger-width) min-w-64 p-0">
      <Command>
        <CommandInput data-testid="model-discovered-search" placeholder={t("搜索模型")} />
        <CommandList>
          <CommandEmpty>{t("没有匹配的模型")}</CommandEmpty>
          <CommandGroup>
            {candidates.map((item) => <CommandItem key={item.id} value={`${item.name} ${item.id}`} data-model-id={item.id} onSelect={() => { onPick(item.id); setOpen(false); }} className="items-start">
              <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{item.name === item.id ? item.id : <>{item.name} <span className="font-mono text-muted-foreground">· {item.id}</span></>}</span>
              {item.id === current && <Check aria-hidden="true" className="mt-0.5 ml-auto" />}
            </CommandItem>)}
          </CommandGroup>
        </CommandList>
      </Command>
    </PopoverContent>
  </Popover>;
}
