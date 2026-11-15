import { Link } from "react-router";
import { Ellipsis, Eye, EyeOff, Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { BotAvatar } from "@/components/bot/BotAvatar";
import { ARCHETYPE_NAMES } from "@/components/bot/PersonaPicker";
import { useOverrides } from "@/components/bot/use-persona";
import type { Bot, ModelCatalog } from "../../api/bots";
import { agoParts, cardModel, cardStatus } from "../../all-bots-items.mjs";
import { countLabel } from "../../bot-marker.mjs";
import { derivePersona } from "../../bot-persona.mjs";
import { BOT_AVATAR_SIZE } from "../../bot-sizes.mjs";
import { sourceOfClick } from "../../handoff.mjs";
import { useLocale } from "../../i18n";
import { paths } from "../../routes.mjs";
import { beginHandoff } from "../chat/handoff-intent";

/**
 * One bot of the 全部 bot page (design 4.11): its avatar with the status mark the sidebar draws, name and title, and three facts (personality archetype, model,
 * last activity) over the last line it said.  The whole card opens the bot's line (the name is the link, stretched over the card); 设置 and the menu sit above that.
 * A hidden bot says so and offers 取消隐藏; one that is shown has 在侧栏隐藏 in its menu (the default bot can not be hidden, so it has no menu).
 */
export function BotCard({ bot, catalog, lineStatus, now, busy, onSetHidden }: {
  bot: Bot; catalog: ModelCatalog | null; lineStatus: { running: string[]; unseen: string[]; waiting: string[] }; now: number; busy: boolean; onSetHidden: (bot: Bot, hidden: boolean) => void;
}) {
  const { t, locale } = useLocale();
  const status = cardStatus(bot, lineStatus);
  const overrides = useOverrides(bot.id);
  const archetype = derivePersona(bot, { overrides }).archetype;
  const model = cardModel(bot, catalog);
  const parts = agoParts(bot.last_at, now);
  const when = !parts ? null : "now" in parts ? t("刚刚") : new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(parts.value, parts.unit);
  const hidden = bot.hidden && !bot.is_default;
  const fact = "flex min-w-0 items-baseline gap-2";
  const label = "w-14 shrink-0 text-caption text-muted-foreground";
  return <li data-testid="bot-card" data-bot-id={bot.id} data-hidden={hidden || undefined} data-status={status.status}>
    <article className={`relative flex h-full flex-col gap-3 rounded-md border border-line bg-surface p-4 transition-colors hover:bg-accent/40 has-[[data-card-link]:focus-visible]:ring-[3px] has-[[data-card-link]:focus-visible]:ring-ring/50 ${hidden ? "bg-sunken" : ""}`}>
      <div className="flex items-start gap-3">
        <span className="mt-0.5 grid shrink-0 place-items-center"><BotAvatar status={status.status} avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={BOT_AVATAR_SIZE.emoji} /></span>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-body font-medium text-ink">
            <Link to={bot.is_default ? paths.chat() : paths.chat(bot.id)} data-card-link="" className="text-ink no-underline outline-none after:absolute after:inset-0 after:content-[''] hover:no-underline"
              onClick={(event) => { if (!event.metaKey && !event.ctrlKey && !event.shiftKey && event.button === 0) beginHandoff({ to: bot.id, source: sourceOfClick(event.detail) }); }}>{bot.name}</Link>
          </h2>
          <p className="truncate text-caption text-muted-foreground">{bot.title || (bot.is_default ? t("默认") : " ")}</p>
        </div>
        <div className="relative z-10 flex shrink-0 items-center gap-1.5">
          {hidden && <span data-testid="bot-card-hidden" className="rounded-full border border-line bg-surface px-2 py-0.5 text-caption text-muted-foreground">{t("已隐藏")}</span>}
          {status.word === "running" && <span className="text-caption text-muted-foreground">{t("回答中")}</span>}
          {status.word === "waiting" && <span className="text-caption font-medium text-action">{t("等你")}</span>}
          {status.count > 0 && <span data-count="" aria-label={`${status.count} ${t("条未读")}`} className="min-w-5 rounded-full bg-brand px-1.5 text-center text-caption leading-5 font-medium text-primary-foreground">{countLabel(status.count)}</span>}
          {!bot.is_default && !hidden && <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button type="button" variant="ghost" size="icon-sm" aria-label={`${t("更多操作")}：${bot.name}`} disabled={busy}><Ellipsis aria-hidden="true" /></Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => onSetHidden(bot, true)}><EyeOff aria-hidden="true" />{t("在侧栏隐藏")}</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>}
        </div>
      </div>
      <dl className="flex flex-col gap-1 text-small">
        <div className={fact}><dt className={label}>{t("性格原型")}</dt><dd data-testid="bot-card-archetype" className="min-w-0 truncate text-ink">{t(ARCHETYPE_NAMES[archetype])}</dd></div>
        <div className={fact}><dt className={label}>{t("模型")}</dt><dd data-testid="bot-card-model" className="min-w-0 truncate text-ink">{model ?? t("目录默认")}</dd></div>
        <div className={fact}><dt className={label}>{t("最近活动")}</dt><dd data-testid="bot-card-last" className="min-w-0 truncate text-ink">{when ?? t("还没有对话")}</dd></div>
      </dl>
      {bot.last_message && <p className="line-clamp-2 text-small text-muted-foreground">{bot.last_message}</p>}
      <div className="relative z-10 mt-auto flex items-center gap-2 pt-1">
        <Button asChild variant="outline" size="sm"><Link to={paths.chatSettings(bot.id)}><Settings aria-hidden="true" />{t("设置")}<span className="sr-only"> · {bot.name}</span></Link></Button>
        {hidden && <Button type="button" variant="outline" size="sm" disabled={busy} data-testid="bot-card-unhide" onClick={() => onSetHidden(bot, false)}><Eye aria-hidden="true" />{t("取消隐藏")}<span className="sr-only"> · {bot.name}</span></Button>}
      </div>
    </article>
  </li>;
}
