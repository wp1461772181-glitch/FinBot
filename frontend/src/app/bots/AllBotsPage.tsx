import { useCallback, useEffect, useMemo, useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DelayedSkeleton, SkeletonCard } from "@/components/state/Skeleton";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { notify } from "@/components/state/notify";
import { getModelCatalog, updateBot, type Bot, type ModelCatalog } from "../../api/bots";
import { orderAllBots } from "../../all-bots-items.mjs";
import { message } from "../../bot-message";
import { useLocale } from "../../i18n";
import { useLineStatus } from "../chat/ChatSessionProvider";
import { useWorkspace } from "../workspace";
import { BotCard } from "./BotCard";

/**
 * 全部 bot (#/assistant/bots, design 4.11): every bot as a card, the hidden ones too (they come last, marked, with 取消隐藏).  Hiding and unhiding is the bot update
 * request's `hidden` field; the sidebar reads the same list, so it changes at once, and a toast says what happened with 撤销.  The page is the owner's: a guest meets
 * 需要登录 at the shell before this is drawn.
 */
export function AllBotsPage() {
  const { t } = useLocale();
  const ws = useWorkspace();
  const { bots, loaded, error, reload } = ws.bots;
  const lineStatus = useLineStatus();
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [retrying, setRetrying] = useState(false);
  // The model's display name is the catalog's; without it a card names the model's id, which is as true.
  useEffect(() => {
    const controller = new AbortController();
    getModelCatalog(controller.signal).then(setCatalog).catch(() => { /* the ids are shown */ });
    return () => controller.abort();
  }, []);
  const ordered = useMemo(() => orderAllBots(bots), [bots]);
  const hiddenCount = ordered.filter(bot => bot.hidden && !bot.is_default).length;
  const retry = () => { setRetrying(true); void reload().finally(() => setRetrying(false)); };

  const setHidden = useCallback(async (bot: Bot, hidden: boolean) => {
    setBusy(prev => new Set(prev).add(bot.id));
    try {
      await updateBot(bot.id, { hidden });
      await reload();
      notify.success(hidden ? `${t("已在侧栏隐藏")}：${bot.name}` : `${t("已取消隐藏")}：${bot.name}`, {
        id: `bot-hidden:${bot.id}`,
        undo: { label: t("撤销"), onClick: () => { void setHidden(bot, !hidden); } },
      });
    } catch (failure) {
      notify.error(message(failure, "保存失败，请重试。"), { id: `bot-hidden:${bot.id}` });
    } finally {
      setBusy(prev => { const next = new Set(prev); next.delete(bot.id); return next; });
    }
  }, [reload, t]);

  const now = Date.now();
  return <main data-testid="all-bots" aria-labelledby="all-bots-title" className="mx-auto flex w-full max-w-[1120px] flex-1 flex-col gap-5 p-4 lg:p-6">
    <header className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <h1 id="all-bots-title" className="text-title-m text-ink">{t("全部 bot")}</h1>
      {loaded && ordered.length > 0 && <span data-testid="all-bots-count" className="rounded-full bg-sunken px-2 py-0.5 font-mono text-caption text-muted-foreground" aria-label={`${ordered.length} bot${hiddenCount ? `, ${hiddenCount} ${t("已隐藏")}` : ""}`}>{ordered.length}</span>}
      <Button type="button" className="ml-auto" onClick={ws.openNewBot} data-testid="all-bots-new"><Plus aria-hidden="true" />{t("新建 bot")}</Button>
    </header>
    {error && <ErrorBar message={t(error)} onRetry={retry} retrying={retrying} />}
    {!loaded
      ? <DelayedSkeleton><div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2, 3, 4, 5].map(i => <SkeletonCard key={i} />)}</div></DelayedSkeleton>
      : ordered.length === 0
        ? !error && <EmptyState title={t("还没有 bot")} description={t("默认 bot 会在第一次对话时自动出现；也可以现在新建一个。")} action={{ label: t("新建 bot"), onClick: ws.openNewBot }} />
        : <ul data-testid="bot-grid" className="m-0 grid list-none gap-4 p-0 sm:grid-cols-2 xl:grid-cols-3">
          {ordered.map(bot => <BotCard key={bot.id} bot={bot} catalog={catalog} lineStatus={lineStatus} now={now} busy={busy.has(bot.id)} onSetHidden={(b, hidden) => void setHidden(b, hidden)} />)}
        </ul>}
  </main>;
}
