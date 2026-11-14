import { Link } from "react-router";
import type { CSSProperties } from "react";
import { SidebarMenuButton, SidebarMenuItem, useSidebar } from "@/components/ui/sidebar";
import type { Bot } from "../../api";
import { RailBotOrb } from "../../BotOrb";
import { BOT_AVATAR_SIZE } from "../../bot-sizes.mjs";
import { botMarker, countLabel } from "../../bot-marker.mjs";
import { resolveLook } from "../../bloub-look.mjs";
import { COLOR_BY_ID } from "../../bloub/skins";
import { useLocale } from "../../i18n";
import { paths } from "../../routes.mjs";

/** The bot's signature colour as a CSS colour; the ink-black and cream bodies take theme colours so the ring shows on both themes. */
function ringColor(bot: Pick<Bot, "id" | "avatar" | "look">): string {
  const colour = resolveLook(bot.id, bot.avatar, bot.look).color;
  if (colour === "encre") return "var(--ink)";
  if (colour === "creme") return "var(--muted)";
  return COLOR_BY_ID.get(colour)?.hex ?? "var(--ink)";
}

/**
 * One bot in the sidebar.  The four marks sit in fixed places (bot-marker.mjs says which hold at once and in what
 * order): the ring around the avatar turns while the bot is answering; an amber dot on the avatar's corner means the
 * bot waits for you; the number at the far right is the unread count; a quiet bot has none of them.  The avatar is the
 * small kind (design 6.2, S): a still frame with a CSS breath, no per-frame work, so the state is drawn with CSS here.
 */
export function BotRow({ bot, active, running, waiting, unseen, onNavigate }: { bot: Bot; active: boolean; running: boolean; waiting: boolean; unseen: boolean; onNavigate?: () => void }) {
  const { t } = useLocale();
  const { state } = useSidebar();
  const collapsed = state === "collapsed";
  const marker = botMarker({ running, waiting, unread: (bot.unread > 0 ? bot.unread : 0) + (unseen ? 1 : 0), active });
  const status = marker.word === "running" ? t("回答中") : marker.word === "waiting" ? t("等你") : "";
  const unreadText = marker.count > 0 ? `${marker.count} ${t("条未读")}` : "";
  const label = [bot.name, status, unreadText].filter(Boolean).join("，");
  const colour = ringColor(bot);
  return <SidebarMenuItem>
    <SidebarMenuButton asChild isActive={active} tooltip={label} className="h-10 gap-3 group-data-[collapsible=icon]:size-10! group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:p-0!">
      <Link to={bot.is_default ? paths.chat() : paths.chat(bot.id)} data-bot-row="" data-marker={marker.kind} aria-label={label} aria-current={active ? "page" : undefined} onClick={onNavigate}>
        <span className="relative grid shrink-0 place-items-center" style={{ width: BOT_AVATAR_SIZE.sidebar, height: BOT_AVATAR_SIZE.sidebar, "--ring-colour": colour } as CSSProperties}>
          {marker.ring && <span data-ring="" aria-hidden="true" className="pointer-events-none absolute -inset-0.5 rounded-full border-2 border-transparent border-t-[color:var(--ring-colour)] motion-safe:animate-spin motion-reduce:border-[color:var(--ring-colour)]" />}
          <RailBotOrb avatar={bot.avatar} look={bot.look} name={bot.name} seed={bot.id} size={BOT_AVATAR_SIZE.sidebar - 4} />
          {marker.dot && <span data-dot="" aria-hidden="true" className="absolute -top-0.5 -right-0.5 size-2.5 rounded-full bg-action ring-2 ring-sidebar" />}
          {collapsed && marker.count > 0 && <span aria-hidden="true" className="absolute -right-1 -bottom-1 grid min-w-4 place-items-center rounded-full bg-brand px-1 text-caption leading-4 text-primary-foreground ring-2 ring-sidebar">{countLabel(marker.count)}</span>}
        </span>
        {!collapsed && <>
          <span className="min-w-0 flex-1 truncate text-sm">{bot.name}</span>
          <span className="flex shrink-0 items-center gap-1.5">
            {marker.word === "running" && <span className="text-caption text-muted-foreground">{t("回答中")}</span>}
            {marker.word === "waiting" && <span className="text-caption font-medium text-action">{t("等你")}</span>}
            {!marker.word && bot.is_default && marker.count === 0 && <span className="text-caption text-muted-foreground">{t("默认")}</span>}
            {marker.count > 0 && <span data-count="" aria-hidden="true" className="min-w-5 rounded-full bg-brand px-1.5 text-center text-caption leading-5 font-medium text-primary-foreground">{countLabel(marker.count)}</span>}
          </span>
        </>}
      </Link>
    </SidebarMenuButton>
  </SidebarMenuItem>;
}
