import { useRef, useState, type FormEvent } from "react";
import { StatefulButton } from "@/components/state/StatefulButton";
import { Input } from "@/components/ui/input";
import { ApiError } from "../../../api/base";
import { createV2HistoricalReplayJob } from "../../../api/forecast-v2";
import type { V2ForecastJob } from "../../../types";
import { translatePhrase, useLocale } from "../../../i18n";
import { SymbolCombobox } from "../forecasts/SymbolCombobox";
import { localDate, validateReplayForm } from "./replay-model.mjs";

/**
 * The row above the replays (design 4.8): company, historical decision day, 生成.  The checks are the old form's (a company; a day that is set and not after today), now
 * written under the field instead of in the browser's own bubble; the request is the old one (`createV2HistoricalReplayJob`: symbol and decision_date).  The button
 * waits while a replay is running, as it did.
 */
export function ReplayForm({ symbol, choices, onSymbol, date, onDate, running, onStarted }: {
  symbol: string; choices: string[]; onSymbol: (symbol: string) => void; date: string; onDate: (date: string) => void; running: boolean; onStarted: (job: V2ForecastJob) => void;
}) {
  const { t } = useLocale();
  const [submitting, setSubmitting] = useState(false);
  const [problem, setProblem] = useState<{ field: "symbol" | "date" | "request"; phrase: string } | null>(null);
  const dateField = useRef<HTMLInputElement>(null);
  const today = localDate(new Date());
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting || running) return;
    const check = validateReplayForm({ symbol, date }, today);
    if (!check.ok) { setProblem({ field: check.field, phrase: check.phrase }); if (check.field === "date") dateField.current?.focus(); return; }
    setProblem(null);
    setSubmitting(true);
    try { onStarted(await createV2HistoricalReplayJob(symbol, date)); }
    catch (error) { setProblem({ field: "request", phrase: error instanceof ApiError ? error.message : "无法提交历史回放。" }); }
    finally { setSubmitting(false); }
  }
  const label = "text-small font-medium text-ink";
  const dateBad = problem?.field === "date";
  return <form noValidate onSubmit={submit} data-testid="replay-form" aria-label={t("生成历史回放")} className="flex min-w-0 flex-wrap items-end gap-x-4 gap-y-3 rounded-md border border-line bg-surface p-4">
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor="replay-symbol" className={label}>{t("股票代码")}</label>
      <SymbolCombobox id="replay-symbol" testId="replay-symbol" value={symbol} choices={choices} onChange={onSymbol} disabled={submitting} className="max-sm:h-11" />
    </div>
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor="replay-date" className={label}>{t("历史决策日")}</label>
      <Input ref={dateField} id="replay-date" data-testid="replay-date" type="date" value={date} max={today} required aria-invalid={dateBad || undefined} aria-describedby={dateBad ? "replay-date-error" : "replay-hint"} disabled={submitting}
        onChange={event => { onDate(event.target.value); if (dateBad) setProblem(null); }} className="w-44 max-sm:h-11" />
    </div>
    <StatefulButton type="submit" data-testid="replay-generate" phase={submitting ? "loading" : "idle"} disabled={running} className="max-sm:h-11">{t("生成历史回放")}</StatefulButton>
    <p id="replay-hint" className="m-0 basis-full text-caption text-muted-foreground">{running ? `${t("已有一条回放正在生成。")} ` : ""}{t("只能选择已收盘的 XNYS 交易日，并且该日之后的 20 个交易日必须已经结束。默认日期选在约一个月前；若遇到较长假期，请再选早一些。")}</p>
    {problem && <p id={dateBad ? "replay-date-error" : undefined} role="alert" data-testid="replay-form-error" className="m-0 basis-full text-small text-ink">{translatePhrase(problem.phrase)}</p>}
  </form>;
}
