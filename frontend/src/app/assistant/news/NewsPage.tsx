import { useMemo, useRef, useState } from "react";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import { confirm } from "@/components/state/confirm";
import { notify } from "@/components/state/notify";
import { deleteNewsSource, dryRunNewsSource, getNewsSourcesConfig, repairNewsSource, saveNewsPushSettings, setNewsSourceEnabled, upsertNewsSource, type NewsDryRunResult, type NewsSource, type NewsSourceInput } from "../../../api/news-sources";
import { useLocale } from "../../../i18n";
import { useLoad } from "../../use-load";
import { NewsDrawer } from "./NewsDrawer";
import { NewsHeader, NewsRow } from "./NewsRow";
import { repairView } from "./news-form.mjs";

const TOKENS = [{ value: 128, label: "短（128 tokens）" }, { value: 256, label: "中（256 tokens）" }, { value: 512, label: "长（512 tokens）" }];

/**
 * 新闻源 (#/assistant/news, design 4.11): the sources the agent searches and checks, as a table on a desktop and cards below it (the same rows either way).  Each row has the health as a dot and words, the switch
 * (saved as it is flipped) and 「…」 (测试抓取, REA 修复 only where the source allows it, 编辑, 删除); a test fetch and a repair answer open under their row.  New and edit are one side drawer.  The length of a news push's digest is top right.
 * Every request is the old page's (src/api/news-sources.ts, unchanged); the body of a save is news-form.mjs's.
 */
export function NewsPage() {
  const { t } = useLocale();
  const data = useLoad(signal => getNewsSourcesConfig(signal));
  const sources = data.data?.sources ?? null;
  const [tokens, setTokens] = useState<number | null>(null);
  const pushed = tokens ?? data.data?.push?.summary_max_tokens ?? 256;
  const [actionError, setActionError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [probing, setProbing] = useState<string | null>(null);
  const [flipped, setFlipped] = useState<Record<string, boolean>>({});
  const [probes, setProbes] = useState<Record<string, NewsDryRunResult>>({});
  const [repairs, setRepairs] = useState<Record<string, { ok: boolean; count: number; reason: string }>>({});
  const [drawer, setDrawer] = useState<{ open: boolean; source: NewsSource | null }>({ open: false, source: null });
  const [pushBusy, setPushBusy] = useState(false);
  const opener = useRef<HTMLElement | null>(null);
  const newButton = useRef<HTMLButtonElement>(null);
  const ids = useMemo(() => (sources ?? []).map(source => source.id), [sources]);
  const returnFocus = () => { const back = opener.current?.isConnected ? opener.current : newButton.current; back?.focus(); };

  async function run(id: string, work: () => Promise<void>) {
    setBusy(id); setActionError(null);
    try { await work(); } catch (error) { setActionError(error); } finally { setBusy(null); }
  }
  const toggle = (source: NewsSource, enabled: boolean) => {
    setFlipped(current => ({ ...current, [source.id]: enabled }));
    return run(source.id, async () => { try { await setNewsSourceEnabled(source.id, enabled); await data.reload(); } finally { setFlipped(({ [source.id]: _gone, ...rest }) => rest); } });
  };
  const test = (source: NewsSource) => run(source.id, async () => {
    setProbing(source.id);
    try { const result = await dryRunNewsSource(source.id); setProbes(current => ({ ...current, [source.id]: result })); } finally { setProbing(null); }
  });
  const repair = (source: NewsSource) => run(source.id, async () => {
    const result = await repairNewsSource(source.id);
    const view = repairView(result);
    setRepairs(current => ({ ...current, [source.id]: { ok: view.ok, count: view.ok ? view.count : 0, reason: view.ok ? "" : view.reason } }));
    if (result.ok) await data.reload();
  });
  async function remove(source: NewsSource, from: HTMLElement | null) {
    const yes = await confirm({ ...(from ? { returnFocus: from } : {}), title: `${t("删除新闻源")}「${source.name || source.id}」？`, description: t("删除后不再从这个源读取新闻，不能恢复。"), confirmLabel: t("删除"), cancelLabel: t("取消"), tone: "danger", hold: true });
    if (!yes) return;
    await run(source.id, async () => { await deleteNewsSource(source.id); setProbes(({ [source.id]: _p, ...rest }) => rest); setRepairs(({ [source.id]: _r, ...rest }) => rest); await data.reload(); });
  }
  async function save(input: NewsSourceInput) {
    await upsertNewsSource(input);
    await data.reload();
    notify.success(t("新闻源已保存。"), { id: "news:saved" });
    setDrawer(current => ({ ...current, open: false }));
  }
  async function setPush(value: number) {
    setPushBusy(true); setActionError(null);
    try { const result = await saveNewsPushSettings(value); setTokens(result.push.summary_max_tokens); } catch (error) { setActionError(error); } finally { setPushBusy(false); }
  }
  const openDrawer = (source: NewsSource | null, from: HTMLElement | null) => { opener.current = from; setDrawer({ open: true, source }); };
  const here = () => (document.activeElement instanceof HTMLElement ? document.activeElement : null);

  return <main data-testid="news-page" aria-labelledby="news-title" className="mx-auto flex w-full min-w-0 max-w-[1280px] flex-1 flex-col gap-5 p-4 lg:p-6">
    <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
      <div className="flex min-w-0 flex-col gap-1">
        <h1 id="news-title" className="text-title-m text-ink">{t("新闻源")}</h1>
        <p data-testid="news-intro" className="max-w-xl text-small text-muted-foreground">{t("配置公开新闻与快讯源（RSS / Atom / JSON / HTML）。Agent 查询最新动态或运行例行简报时优先检索已启用的配置源；无命中或全部停用时自动回退网页搜索。你也可以在对话里直接让 Agent 开启、停用或添加新闻源。")}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2">
          <label id="news-push-label" className="text-small text-ink-2">{t("新闻推送摘要长度上限")}</label>
          <Select value={String(pushed)} disabled={pushBusy || !data.data} onValueChange={value => void setPush(Number(value))}>
            <SelectTrigger aria-labelledby="news-push-label" data-testid="news-push" className="w-44 max-sm:h-11"><SelectValue /></SelectTrigger>
            <SelectContent>{TOKENS.map(option => <SelectItem key={option.value} value={String(option.value)}>{t(option.label)}</SelectItem>)}</SelectContent>
          </Select>
        </div>
        <Button ref={newButton} type="button" data-testid="news-new" className="max-sm:h-11" onClick={() => openDrawer(null, here())}><Plus aria-hidden="true" />{t("新建新闻源")}</Button>
      </div>
    </header>
    {actionError != null && <ErrorBar error={actionError} />}
    {data.error != null && <ErrorBar error={data.error} onRetry={() => void data.reload()} retrying={data.loading} />}
    {!sources && data.loading && <DelayedSkeleton><div role="status" aria-busy="true" data-testid="news-skeleton" className="flex flex-col gap-3"><span className="sr-only">{t("正在读取")}</span>{[0, 1, 2, 3].map(i => <Skeleton key={i} className="h-24 w-full" />)}</div></DelayedSkeleton>}
    {sources && sources.length === 0 && <div data-testid="news-empty" className="rounded-md border border-line bg-surface"><EmptyState title={t("还没有配置任何新闻源。")} action={{ label: t("新建新闻源"), onClick: () => openDrawer(null, newButton.current) }} /></div>}
    {sources && sources.length > 0 && <div role="table" aria-label={t("新闻源")} data-testid="news-table" className="flex min-w-0 flex-col xl:rounded-md xl:border xl:border-line xl:bg-surface">
      <NewsHeader />
      <div className="flex flex-col gap-3 xl:gap-0">
        {sources.map(source => <NewsRow key={source.id} source={source} enabled={flipped[source.id] ?? source.enabled} busy={busy === source.id} probing={probing === source.id} probe={probes[source.id]} repair={repairs[source.id]}
          onToggle={enabled => void toggle(source, enabled)} onTest={() => void test(source)} onRepair={() => void repair(source)} onEdit={from => openDrawer(source, from)} onDelete={from => void remove(source, from)} />)}
      </div>
    </div>}
    <NewsDrawer open={drawer.open} onOpenChange={open => setDrawer(current => ({ ...current, open }))} source={drawer.source} existing={ids} save={save} returnFocus={returnFocus} />
  </main>;
}
