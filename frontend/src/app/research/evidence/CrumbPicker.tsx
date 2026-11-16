import { useState } from "react";
import { Check } from "lucide-react";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { useLocale } from "../../../i18n";
import { Chevron } from "../forecasts/icons";

export type Crumb = { id: string; label: string; hint?: string };

/**
 * One level of the breadcrumb (design 4.7): the current choice as a button that opens a short list to pick another (a combobox).  The list searches when it
 * is long.  Picking the choice that is already there only closes the list.  The button says what level it is for screen readers (`level`).
 */
export function CrumbPicker({ level, current, options, selectedId, onPick, testid, mono = false, searchAfter = 7 }: {
  level: string;
  current: string;
  options: Crumb[];
  selectedId: string | null;
  onPick: (id: string) => void;
  testid: string;
  mono?: boolean;
  searchAfter?: number;
}) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  return <Popover open={open} onOpenChange={setOpen}>
    <PopoverTrigger asChild>
      <button type="button" role="combobox" aria-expanded={open} aria-label={`${level}：${current}`} data-testid={testid} disabled={options.length === 0}
        className={cn("inline-flex h-9 min-w-0 max-w-full items-center gap-1.5 rounded-sm px-2 text-title-s text-ink outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default disabled:hover:bg-transparent max-sm:min-h-11", mono && "font-mono")}>
        <span className="truncate">{current}</span>
        <Chevron className="text-muted-foreground" />
      </button>
    </PopoverTrigger>
    <PopoverContent align="start" className="w-72 max-w-[calc(100vw-2rem)] p-0">
      <Command>
        {options.length > searchAfter && <CommandInput placeholder={t("搜索")} />}
        <CommandList>
          <CommandEmpty>{t("没有匹配项")}</CommandEmpty>
          <CommandGroup>
            {options.map(option => <CommandItem key={option.id} value={`${option.label} ${option.hint ?? ""} ${option.id}`} data-crumb={option.id} onSelect={() => { setOpen(false); if (option.id !== selectedId) onPick(option.id); }} className="items-start">
              <span className="flex min-w-0 flex-1 flex-col"><span className={cn("truncate", mono && "font-mono")}>{option.label}</span>{option.hint && <span className="truncate text-caption text-muted-foreground">{option.hint}</span>}</span>
              {option.id === selectedId && <Check aria-hidden="true" className="mt-0.5 size-4 shrink-0" />}
            </CommandItem>)}
          </CommandGroup>
        </CommandList>
      </Command>
    </PopoverContent>
  </Popover>;
}
