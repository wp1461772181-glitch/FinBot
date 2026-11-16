import { Link } from "react-router";
import { StatusBadge } from "@/components/StatusBadge";
import { NOT_RECORDED } from "../../../forecast-model.mjs";
import type { JudgmentRowModel } from "../../../forecast-home.mjs";
import { Parts, formatTime } from "../../../ForecastShared";
import { useLocale } from "../../../i18n";
import { paths } from "../../../routes.mjs";

/**
 * One earnings judgment in the right lane of the home page: 偏涨 or 偏跌 and 把握, when, which model, and the result once the first session has closed.
 * It takes no probabilities and cannot draw a probability bar (design §2 rules 1 and 2): this is one question about one day, and the formal forecast's
 * row (FormalForecastRow.tsx) is a different question; the two never share a row component.
 */
export function JudgmentRow({ model, mark }: { model: JudgmentRowModel; mark: string | null }) {
  const { t } = useLocale();
  return <li data-slot="judgment-row">
    <Link to={paths.judgment(model.id)} className="flex min-w-0 flex-col gap-2 rounded-md border border-line bg-surface p-3 outline-none hover:bg-hover focus-visible:ring-2 focus-visible:ring-ring">
      <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <strong className="font-mono text-body text-ink">{model.symbol}</strong>
        {mark && <StatusBadge kind="neutral" className="h-5">{t(mark)}</StatusBadge>}
        <StatusBadge kind="opinion" className="h-5">{t(model.direction)}{model.confidence ? ` · ${t(model.confidence)}` : ""}</StatusBadge>
        <span className="ml-auto text-caption text-muted-foreground">{formatTime(model.time)}</span>
      </span>
      <span className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1 text-small text-ink-2">
        <span>{t(model.result)}</span>
        {model.afterHours && <span className="text-muted-foreground"><Parts parts={model.afterHours.parts} /></span>}
      </span>
      <span className="text-caption text-muted-foreground [overflow-wrap:anywhere]">{t("决策模型")} <span className="font-mono text-ink">{model.model ?? t(NOT_RECORDED)}</span>{model.modelFirstStage ? ` (${t("首条消息时的模型")})` : ""}</span>
    </Link>
  </li>;
}
