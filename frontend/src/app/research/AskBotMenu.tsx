import { useNavigate } from "react-router";
import { Bot as BotIcon, ChevronsUpDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import type { Bot } from "../../api/bots";
import { askBots, askDraft, prepareAsk } from "../../company-page.mjs";
import { useLocale } from "../../i18n";
import { paths } from "../../routes.mjs";

/**
 * 问 bot (the company page's title row): the bots that follow this company, or the default bot when none does.  Choosing one makes the company that bot's
 * current stock and starts its draft with 「关于 <代码>：」 (the reader's own draft, if there is one, is left alone), then opens its line.  Nothing is sent:
 * the reader finishes the question and presses send.
 */
export function AskBotMenu({ symbol, bots }: { symbol: string; bots: Bot[] }) {
  const { t, locale } = useLocale();
  const navigate = useNavigate();
  const { bots: choices, following } = askBots(symbol, bots);
  if (!choices.length) return null;
  const ask = (bot: Bot) => {
    prepareAsk({ bot, symbol, draftText: askDraft(symbol, locale === "en-US" ? { about: "About", colon: ": " } : { about: "关于", colon: "：" }) });
    navigate(bot.is_default ? paths.chat() : paths.chat(bot.id));
  };
  return <DropdownMenu>
    <DropdownMenuTrigger asChild>
      <Button type="button" variant="outline" data-testid="ask-bot"><BotIcon aria-hidden="true" />{t("问 bot")}<ChevronsUpDown aria-hidden="true" /></Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end" className="min-w-48" data-testid="ask-bot-menu">
      <DropdownMenuLabel className="text-caption text-muted-foreground">{following ? (locale === "en-US" ? `Bots following ${symbol}` : `关注 ${symbol} 的 bot`) : t("默认 bot")}</DropdownMenuLabel>
      {choices.map(bot => <DropdownMenuItem key={bot.id} data-testid="ask-bot-item" data-bot={bot.id} onSelect={() => ask(bot)}>{bot.name}</DropdownMenuItem>)}
    </DropdownMenuContent>
  </DropdownMenu>;
}
