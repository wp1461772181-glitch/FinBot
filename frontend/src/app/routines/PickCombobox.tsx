import { useState, type ReactNode } from "react";
import { Check, ChevronsUpDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { useLocale } from "../../i18n";

export type PickOption = { value: string; label: ReactNode; /** What a search matches. */ search: string; /** The choice as plain text (the button names its value for a screen reader); the search text when not given. */ text?: string; group?: string };

/**
 * A button that opens a short searchable list (a combobox, design 5.4): the bot of a task, the bot filter of the list, the time zone.  The value is always one of the
 * options; the button shows the label of the chosen one.  Groups are drawn in the order their first option appears.
 */
export function PickCombobox({ value, options, onChange, label, searchLabel, emptyLabel, id, disabled, className, testId, contentClassName, align = "start" }: {
  value: string; options: PickOption[]; onChange: (value: string) => void;
  /** The accessible name of the button. */
  label: string; searchLabel: string; emptyLabel: string;
  id?: string; disabled?: boolean; className?: string; testId?: string; contentClassName?: string; align?: "start" | "center" | "end";
}) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const chosen = options.find(option => option.value === value);
  const groups = options.reduce<Array<{ name: string; items: PickOption[] }>>((all, option) => {
    const name = option.group ?? "";
    const found = all.find(group => group.name === name);
    if (found) found.items.push(option); else all.push({ name, items: [option] });
    return all;
  }, []);
  return <Popover open={open} onOpenChange={setOpen}>
    <PopoverTrigger asChild>
      <Button id={id} type="button" variant="outline" role="combobox" aria-expanded={open} aria-label={`${label}：${chosen ? chosen.text ?? chosen.search : t("请选择")}`} data-testid={testId} disabled={disabled} className={cn("w-full justify-between font-normal", className)}>
        <span className="flex min-w-0 items-center gap-2 truncate">{chosen?.label ?? t("请选择")}</span><ChevronsUpDown aria-hidden="true" className="opacity-60" />
      </Button>
    </PopoverTrigger>
    <PopoverContent align={align} className={cn("w-[var(--radix-popover-trigger-width)] min-w-56 p-0", contentClassName)}>
      <Command>
        <CommandInput placeholder={searchLabel} />
        <CommandList>
          <CommandEmpty>{emptyLabel}</CommandEmpty>
          {groups.map(group => <CommandGroup key={group.name} heading={group.name || undefined}>
            {group.items.map(option => <CommandItem key={option.value} value={option.value} keywords={[option.search]} data-value={option.value} onSelect={() => { onChange(option.value); setOpen(false); }}>
              <span className="flex min-w-0 items-center gap-2">{option.label}</span>{option.value === value && <Check aria-hidden="true" className="ml-auto" />}
            </CommandItem>)}
          </CommandGroup>)}
        </CommandList>
      </Command>
    </PopoverContent>
  </Popover>;
}
