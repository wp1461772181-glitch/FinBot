import { useRef, type ReactNode } from "react";
import { Ellipsis, FlaskConical, LoaderCircle, SquarePen, Trash2, Wrench } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/utils";
import type { NewsDryRunResult, NewsSource } from "../../../api/news-sources";
import { useLocale } from "../../../i18n";
import { fill } from "../fill";
import { HEALTH_LABELS, KIND_SHORT, dryRunView, healthKind } from "./news-form.mjs";

/** The six columns of the table (from a desktop's width); below `xl` the same cells are a card, two to a line. */
export const NEWS_COLUMNS = "xl:grid-cols-[minmax(11rem,2.2fr)_minmax(6.5rem,1fr)_minmax(4rem,0.7fr)_minmax(6rem,1.3fr)_minmax(6.5rem,1fr)_minmax(6rem,0.9fr)]";

const Label = ({ children }: { children: ReactNode }) => <span className="text-caption text-muted-foreground xl:hidden">{children}</span>;
function Cell({ label, children, className, testid }: { label: ReactNode; children: ReactNode; className?: string; testid?: string }) {
  return <div role="cell" data-testid={testid} className={cn("flex min-w-0 flex-col gap-0.5", className)}><Label>{label}</Label><span className="min-w-0 text-small text-ink [overflow-wrap:anywhere]">{children}</span></div>;
}

export function NewsHeader() {
  const { t } = useLocale();
  const head = "text-caption text-muted-foreground";
  return <div role="rowgroup" className="hidden xl:block">
    <div role="row" className={cn("grid items-center gap-x-4 border-b border-line px-3 py-2", NEWS_COLUMNS)}>
      <span role="columnheader" className={head}>{t("名称")}</span><span role="columnheader" className={head}>{t("类型")}</span><span role="columnheader" className={head}>{t("市场")}</span><span role="columnheader" className={head}>{t("标签")}</span>
      <span role="columnheader" className={head}>{t("健康状态")}</span><span role="columnheader" className={cn(head, "text-right")}>{t("启用")}</span>
    </div>
  </div>;
}

const DOT = { ok: "bg-success", degraded: "bg-action", failed: "bg-danger", other: "bg-muted-foreground" } as const;

/** The health of a source: a dot and the words (never the dot alone); a value the page does not know is shown as the server gave it. */
export function Health({ health }: { health: string }) {
  const { t } = useLocale();
  const kind = healthKind(health);
  return <span data-testid="news-health" data-health={health} data-kind={kind} className="inline-flex items-center gap-1.5">
    <span aria-hidden="true" className={cn("size-2 shrink-0 rounded-full", DOT[kind])} />{kind === "other" ? health : t(HEALTH_LABELS[health])}
  </span>;
}

/**
 * One news source (design 4.11, P7.1's shape): a row of the table on a desktop, a card below it, the same cells either way and the same one node (the grid lays them out), so what is open under it — the test fetch, the repair
 * answer — stays when the window is resized.  Under the row: the address (a link), what REA can do, the spare addresses, the last error as the server gave it.
 */
export function NewsRow({ source, enabled, busy, probing, probe, repair, onToggle, onTest, onRepair, onEdit, onDelete }: {
  source: NewsSource; enabled: boolean; busy: boolean; probing: boolean; probe: NewsDryRunResult | undefined; repair: { ok: boolean; count: number; reason: string } | undefined;
  onToggle: (enabled: boolean) => void; onTest: () => void; onRepair: () => void; onEdit: (opener: HTMLElement | null) => void; onDelete: (opener: HTMLElement | null) => void;
}) {
  const { t } = useLocale();
  const menu = useRef<HTMLButtonElement>(null);
  const opening = useRef(false);
  const result = probe ? dryRunView(probe) : null;
  return <div role="rowgroup" data-testid="news-row" data-source={source.id} data-enabled={enabled ? "true" : "false"} aria-label={source.name || source.id} className="flex flex-col rounded-md border border-line bg-surface xl:rounded-none xl:border-0 xl:border-b xl:bg-transparent xl:last:border-b-0">
    <div role="row" className={cn("grid grid-cols-2 items-start gap-x-3 gap-y-2 p-3 xl:items-center xl:gap-x-4", NEWS_COLUMNS)}>
      <div role="cell" className="col-span-2 flex min-w-0 flex-col gap-0.5 xl:col-span-1">
        <strong data-testid="news-name" className="text-body font-medium text-ink [overflow-wrap:anywhere]">{source.name || source.id}</strong>
        <span data-testid="news-id" className="font-mono text-caption text-muted-foreground [overflow-wrap:anywhere]">{source.id}</span>
      </div>
      <Cell label={t("类型")} testid="news-kind">{KIND_SHORT[source.kind] ?? source.kind}</Cell>
      <Cell label={t("市场")} testid="news-markets">{source.markets && source.markets.length ? <span className="font-mono">{source.markets.join(" · ")}</span> : <span className="text-muted-foreground">—</span>}</Cell>
      <Cell label={t("标签")} testid="news-tags">{source.tags && source.tags.length ? source.tags.join(" · ") : <span className="text-muted-foreground">—</span>}</Cell>
      <Cell label={t("健康状态")}><Health health={source.health} /></Cell>
      <div role="cell" className="col-span-2 flex items-center justify-between gap-2 xl:col-span-1 xl:justify-end">
        <span className="flex items-center gap-2"><span className="text-caption text-muted-foreground xl:hidden">{t("启用")}</span>
          <Switch checked={enabled} disabled={busy} aria-label={`${t(enabled ? "暂停" : "启用")} ${source.name || source.id}`} data-testid="news-switch" onCheckedChange={onToggle} className="max-sm:scale-110" /></span>
        <DropdownMenu modal={false}>
          <DropdownMenuTrigger asChild><Button ref={menu} type="button" variant="ghost" size="icon" disabled={busy} aria-label={`${t("更多操作")} ${source.name || source.id}`} data-testid="news-menu" className="size-9 max-sm:size-11"><Ellipsis aria-hidden="true" /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end" onCloseAutoFocus={event => { if (opening.current) { event.preventDefault(); opening.current = false; } }}>
            <DropdownMenuItem data-testid="news-test" onSelect={onTest}><FlaskConical aria-hidden="true" />{t("测试抓取")}</DropdownMenuItem>
            {source.rea_repair && <DropdownMenuItem data-testid="news-repair" onSelect={onRepair}><Wrench aria-hidden="true" />{t("REA 修复")}</DropdownMenuItem>}
            <DropdownMenuItem data-testid="news-edit" onSelect={() => { opening.current = true; onEdit(menu.current); }}><SquarePen aria-hidden="true" />{t("编辑")}</DropdownMenuItem>
            <DropdownMenuItem data-testid="news-delete" variant="destructive" onSelect={() => { opening.current = true; onDelete(menu.current); }}><Trash2 aria-hidden="true" />{t("删除")}</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
    <div role="row"><div role="cell" className="flex min-w-0 flex-col gap-1.5 px-3 pb-3 text-small">
      <p className="m-0 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-ink-2">
        <span className="text-muted-foreground">{t("抓取地址")}</span><a data-testid="news-url" href={source.url} target="_blank" rel="noreferrer" className="min-w-0 rounded-sm text-brand outline-none [overflow-wrap:anywhere] hover:underline focus-visible:ring-2 focus-visible:ring-ring">{source.url}</a>
        {source.rea_repair && <span data-testid="news-rea"><StatusBadge kind="neutral" className="h-5">{t("支持 REA 自动诊断")}</StatusBadge></span>}
      </p>
      {source.alternates && source.alternates.length > 0 && <p data-testid="news-alternates" className="m-0 text-ink-2"><span className="text-muted-foreground">{t("备用源")}</span> <span className="font-mono text-caption [overflow-wrap:anywhere]">{source.alternates.join(" , ")}</span></p>}
      {source.last_error && <p data-testid="news-last-error" className="m-0 text-ink-2"><span className="text-muted-foreground">{t("最近错误")}</span> <span className="font-mono text-caption [overflow-wrap:anywhere]">{source.last_error}</span></p>}
      {repair && <p data-testid="news-repair-note" data-ok={repair.ok ? "true" : "false"} role="status" className="m-0 text-ink-2">{repair.ok ? fill(t("REA 修复成功（抽样 {n} 条有效新闻）"), { n: repair.count }) : `${t("REA 暂未自动修复：")}${repair.reason || t("未发现可用备源")}`}</p>}
      {probing && <p data-testid="news-probing" role="status" className="m-0 inline-flex items-center gap-1.5 text-muted-foreground"><LoaderCircle aria-hidden="true" className="size-3.5 motion-safe:animate-spin" />{t("正在测试抓取…")}</p>}
      {result && !probing && <div data-testid="news-test-result" data-ok={result.ok ? "true" : "false"} className="material-fact m-0 flex min-w-0 flex-col gap-1 px-3 py-2 text-small text-ink">
        {result.ok
          ? <><p className="m-0">{fill(t("测试抓取成功：共抓取 {raw} 条，有效标准化 {valid} 条。"), { raw: result.raw, valid: result.valid })}</p>
              {result.samples.length > 0 && <ul className="m-0 flex list-none flex-col gap-0.5 p-0">{result.samples.map((sample, i) => <li key={i} data-testid="news-sample" className="text-caption text-ink-2"><a href={sample.url} target="_blank" rel="noreferrer" className="rounded-sm text-brand outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">{sample.title}</a> <span className="font-mono text-muted-foreground">{sample.at}</span></li>)}</ul>}</>
          : <p className="m-0">{t("测试抓取未通过：")}{result.reason || t("无有效条目")}</p>}
      </div>}
    </div></div>
  </div>;
}

