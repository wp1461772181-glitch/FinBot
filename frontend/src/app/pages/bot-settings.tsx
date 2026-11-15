import { Suspense, lazy } from "react";
import { useParams } from "react-router";
import { DelayedSkeleton, SkeletonRows } from "@/components/state/Skeleton";
import { OptionalChunk } from "../../OptionalChunk";
import { translatePhrase } from "../../i18n";
import { useWorkspace } from "../workspace";

// The page itself (the form, the section list, the personality studio, the routine manager) is a chunk of its own: the chat page's first screen does not carry it.
const BotSettingsPage = lazy(() => import("../bot-settings/BotSettingsPage"));

const shell = (children: React.ReactNode) => <main className="mx-auto w-full max-w-[1040px] flex-1 p-4 lg:p-6">{children}</main>;
const loading = shell(<DelayedSkeleton><SkeletonRows rows={6} /></DelayedSkeleton>);

/** /chat/:botId/settings: the bot's settings as a page of its own.  The bot comes from the workspace's list (the sidebar's); a bot that is not there says so. */
export function BotSettingsRoute() {
  const ws = useWorkspace();
  const botId = (useParams().botId ?? "").toLowerCase();
  const bot = ws.personal ? ws.bots.bots.find((b) => b.id === botId) ?? null : null;
  if (!bot) return ws.bots.loaded || !ws.personal ? shell(<p role="status" className="text-body text-muted-foreground">{translatePhrase("bot 不存在或已删除。")}</p>) : loading;
  const changed = () => void ws.bots.reload();
  return <OptionalChunk><Suspense fallback={loading}>
    <BotSettingsPage key={bot.id} bot={bot} others={ws.bots.bots} onChanged={changed} onDeleted={() => { changed(); ws.go("agent"); }} />
  </Suspense></OptionalChunk>;
}
