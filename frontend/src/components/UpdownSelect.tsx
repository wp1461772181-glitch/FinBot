// The up/down colour choice on the settings page (green up / red up).  Lives here, not in AgentChatPanel.tsx,
// because Tailwind only scans src/components, src/app and src/dev (see styles/index.css).  Sized and bordered to sit
// next to the old native selects of the same card; the shadcn Select is used so no new native <select> appears.
import { useState } from "react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useLocale } from "../i18n";
import { applyUpdown, saveUpdown, storedUpdown, type UpdownChoice } from "../updown.mjs";

export function UpdownSelect() {
  const { t } = useLocale();
  const [choice, setChoice] = useState<UpdownChoice>(() => storedUpdown());
  const change = (value: string) => {
    const saved = saveUpdown(value as UpdownChoice);
    setChoice(saved);
    applyUpdown(saved);
  };
  return (
    <label htmlFor="updown">{t("涨跌配色")}
      <Select value={choice} onValueChange={change}>
        <SelectTrigger id="updown" className="h-10 w-full rounded-[4px] border-line bg-surface px-2.5 text-[13px] text-ink data-[size=default]:h-10 dark:bg-surface dark:hover:bg-surface">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="green-up">{t("绿涨红跌")}</SelectItem>
          <SelectItem value="red-up">{t("红涨绿跌")}</SelectItem>
        </SelectContent>
      </Select>
    </label>
  );
}
