import { BotAvatar } from "@/components/bot/BotAvatar";
import type { Bot } from "../../api/bots";
import { useLocale } from "../../i18n";
import { PickCombobox, type PickOption } from "./PickCombobox";

const ALL = "";

/** Narrow the tab to one bot (the address keeps it: ?bot=).  The first choice is every bot. */
export function BotFilter({ bots, value, onChange }: { bots: Bot[]; value: string; onChange: (botId: string) => void }) {
  const { t } = useLocale();
  const options: PickOption[] = [{ value: ALL, search: t("全部 bot"), text: t("全部 bot"), label: <span>{t("全部 bot")}</span> },
    ...bots.map(bot => ({ value: bot.id, search: `${bot.name} ${bot.title}`, text: bot.name, label: <><BotAvatar avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={20} /><span className="truncate">{bot.name}</span></> }))];
  return <div className="w-full sm:w-60"><PickCombobox testId="bot-filter" value={value} options={options} onChange={onChange} label={t("按 bot 筛选")} searchLabel={t("搜索 bot")} emptyLabel={t("没有这个 bot")} /></div>;
}
