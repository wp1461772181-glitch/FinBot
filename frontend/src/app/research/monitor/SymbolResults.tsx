import { StatusBadge } from "@/components/StatusBadge";
import type { V2MonitorRun } from "../../../types";
import { formatDateTime, translatePhrase, useLocale } from "../../../i18n";
import { SYMBOL_STATUS_KIND, SYMBOL_STATUS_PHRASE, symbolRows } from "./monitor-model.mjs";

/**
 * The last run, company by company: code, result, time, note.  A table from the `sm` width, cards on a phone.  A failed company is listed first.  The server records no
 * time per company, so the time column is the run's own (when it finished).
 */
export function SymbolResults({ run }: { run: V2MonitorRun }) {
  const { t, locale } = useLocale();
  const rows = symbolRows(run);
  const time = run.completed_at ?? run.started_at;
  const shown = formatDateTime(time, locale, "UTC");
  const note = (row: (typeof rows)[number]) => row.error ?? `${t("发现")} ${row.discovered} · ${t("新增")} ${row.created} · ${t("入队")} ${row.queued}`;
  const result = (row: (typeof rows)[number]) => <StatusBadge kind={SYMBOL_STATUS_KIND[row.status]} className="h-5">{translatePhrase(SYMBOL_STATUS_PHRASE[row.status])}</StatusBadge>;
  return <section data-testid="monitor-symbols" aria-labelledby="monitor-symbols-title" className="flex min-w-0 flex-col gap-3">
    <h2 id="monitor-symbols-title" className="text-title-s text-ink">{t("逐股结果")}</h2>
    {rows.length === 0
      ? <p className="m-0 text-small text-muted-foreground">{t("本次运行没有返回逐股结果。")}</p>
      : <>
        <table className="hidden w-full border-collapse text-small sm:table">
          <thead><tr className="border-b border-line text-left text-caption text-muted-foreground">
            <th scope="col" className="py-2 pr-3 font-normal">{t("股票代码")}</th><th scope="col" className="px-3 py-2 font-normal">{t("结果")}</th><th scope="col" className="px-3 py-2 font-normal">{t("时间")}</th><th scope="col" className="py-2 pl-3 font-normal">{t("说明")}</th>
          </tr></thead>
          <tbody>{rows.map(row => <tr key={row.ticker} data-testid="monitor-row" data-status={row.status} className="border-b border-line align-top">
            <th scope="row" className="py-2 pr-3 text-left font-mono font-medium text-ink">{row.ticker}</th>
            <td className="px-3 py-2">{result(row)}</td>
            <td className="whitespace-nowrap px-3 py-2 font-mono text-caption tabular-nums text-muted-foreground">{shown}</td>
            <td className="py-2 pl-3 text-ink-2 [overflow-wrap:anywhere]">{note(row)}</td>
          </tr>)}</tbody>
        </table>
        <ul className="m-0 flex list-none flex-col gap-2 p-0 sm:hidden">{rows.map(row => <li key={row.ticker} data-testid="monitor-row" data-status={row.status} className="flex min-w-0 flex-col gap-1 rounded-md border border-line bg-surface p-3">
          <div className="flex items-center gap-2"><strong className="font-mono text-body font-medium text-ink">{row.ticker}</strong>{result(row)}<span className="ml-auto font-mono text-caption text-muted-foreground">{shown}</span></div>
          <p className="m-0 text-small text-ink-2 [overflow-wrap:anywhere]">{note(row)}</p>
        </li>)}</ul>
      </>}
  </section>;
}
