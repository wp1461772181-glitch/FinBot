// The four cards that are about the owner and this bot, not a stock: 例行任务, 简报, 自选, 我的持仓.
import { Button } from "@/components/ui/button";
import { type Bot } from "../../../api/bots";
import { listInbox, listTaskProposals } from "../../../api/inbox";
import { getPortfolio } from "../../../api/portfolio-ledger";
import { getResearchQueue } from "../../../api/queue";
import { listAgentTasks } from "../../../api/tasks";
import { useLocale } from "../../../i18n";
import { judgmentLink, waitingCount } from "../../../inbox-items.mjs";
import { formatMoney, formatPercent } from "../../../portfolio-items.mjs";
import { hashHref, paths } from "../../../routes.mjs";
import { Body, LIST, MoreLink, ROW, ROW_LINK, Signed, day } from "./parts";
import { useLoad } from "./use-load";

const MUTED = "text-caption text-muted-foreground";

// 例行任务 (it took in the 待你确认 card): this bot's routines, and how many of its cards wait for the owner — routine cards proposed in chat and writes its unattended runs suggested — with the way to the 例行任务 page.
export function RoutinesCard({ bot }: { bot: Bot }) {
  const { t } = useLocale();
  const [state] = useLoad(`routines:${bot.id}`, signal => Promise.all([listAgentTasks(signal, bot.id), listTaskProposals(signal),
    listInbox("confirm", signal, bot.id)]).then(([tasks, proposals, confirms]) => ({ tasks,
      waiting: waitingCount(bot.id, proposals, confirms) })));
  return <div className="grid gap-1.5">
    <Body state={state} empty={v => !v.tasks.length && !v.waiting}>{v => <>
      {v.waiting > 0 && <p className="m-0 text-small"><MoreLink href={hashHref(paths.routines({ tab: "confirm" }))}>{v.waiting} {t("项等你确认")}</MoreLink></p>}
      <ul className={LIST}>{v.tasks.slice(0, 5).map(task =>
        <li key={task.id} className={ROW}><span>{task.name}{task.enabled ? "" : ` · ${t("已停用")}`}</span>
          <small className={MUTED}>{t("下次")} {day(task.next_run_at)}{task.last_status_label ? ` · ${t("上次")} ${t(task.last_status_label)}` : ""}</small></li>)}</ul></>}</Body>
    <MoreLink href={hashHref(paths.routines({ tab: "tasks" }))}>{t("管理例行任务")}</MoreLink>
  </div>;
}

// 我的持仓: the owner's funds, total, P&L and the biggest positions; the full table is on the 持仓 page.  Owner only (a guest's read answers 403, which shows as the card's usual error line).
export function PortfolioCard() {
  const { t } = useLocale();
  const [state] = useLoad("portfolio", signal => getPortfolio(signal));
  const line = "flex min-w-0 flex-wrap items-baseline justify-between gap-x-2";
  return <div className="grid gap-1.5">
    <Body state={state} empty={v => !v.positions.length && Number(v.available_funds) === 0 && !v.transactions.length}>{v => <>
      <ul className={LIST}>
        <li className={line}><span>{t("可用资金")}</span> <strong className="font-mono tabular-nums">{formatMoney(v.available_funds)}</strong></li>
        <li className={line}><span>{t("总资产")}</span> <strong className="font-mono tabular-nums">{v.total_assets === null ? "—" : formatMoney(v.total_assets)}</strong></li>
        <li className={line}><span>{t("浮动盈亏")}</span> <Signed value={v.floating_pnl} /></li>
        <li className={line}><span>{t("今日盈亏")}{v.today_pnl_reference_only ? ` · ${t("仅供参考")}` : ""}</span> <Signed value={v.today_pnl} /></li>
      </ul>
      <ul className={LIST}>{[...v.positions].sort((a, b) => Number(b.weight_pct ?? 0) - Number(a.weight_pct ?? 0)).slice(0, 5).map(p =>
        <li key={p.symbol} className={ROW}><span className="font-mono">{p.symbol}</span><span className="inline-flex items-baseline gap-1.5 whitespace-nowrap"><small className={MUTED}>{t("仓位占比")} {formatPercent(p.weight_pct)} ·</small><Signed value={p.floating_pnl} /></span></li>)}</ul>
      {v.price_date && <small className={MUTED}>{t("行情数据日期")} {v.price_date}</small>}</>}</Body>
    <MoreLink href={hashHref(paths.portfolio())}>{t("管理持仓")}</MoreLink>
  </div>;
}

export function BriefCard({ bot }: { bot: Bot }) {
  const [state] = useLoad(`brief:${bot.id}`, signal => listInbox("brief", signal, bot.id));
  return <Body state={state} empty={v => !v.length}>{v => <ul className={LIST}>{v.slice(0, 3).map(item => {
    const link = judgmentLink(item);
    return <li key={item.id} className={ROW}>{link ? <a href={link} className={ROW_LINK}>{item.title}</a> : <span>{item.title}</span>}<small className={MUTED}>{day(item.created_at)}</small></li>;
  })}</ul>}</Body>;
}

export function WatchlistCard({ onPick }: { onPick: (symbol: string) => void }) {
  const [state] = useLoad("watchlist", signal => getResearchQueue(signal).then(v => v ?? []));
  return <Body state={state} empty={v => !v.length}>{v => <div className="flex flex-wrap gap-1.5">{v.map(s =>
    <Button key={s} type="button" variant="outline" size="sm" className="rounded-full font-mono" onClick={() => onPick(s)}>{s}</Button>)}</div>}</Body>;
}
