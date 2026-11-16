import { Link } from "react-router";
import { StatusBadge } from "@/components/StatusBadge";
import { ProbabilityBar } from "@/components/ProbabilityBar";
import { attentionLabel } from "../../../forecast-home.mjs";
import type { AttentionTier, FormalRowModel } from "../../../forecast-home.mjs";
import { NOT_RECORDED } from "../../../forecast-model.mjs";
import { useLocale } from "../../../i18n";
import { paths } from "../../../routes.mjs";

/**
 * One formal forecast in the left lane of the home page: the company, the three probabilities as a bar with their numbers, the target date, the deciding
 * model and the version.  It takes no judgment and has no direction word (design §2 rules 1 and 2): a judgment is another problem with another
 * row, in JudgmentRow.tsx; the two never share a row component.
 */
export function FormalForecastRow({ model, tier }: { model: FormalRowModel; tier: AttentionTier }) {
  const { t } = useLocale();
  const why = attentionLabel(tier);
  return <li data-slot="formal-row" data-tier={tier}>
    <Link to={paths.forecast(model.id)} className="flex min-w-0 flex-col gap-2 rounded-md border border-line bg-surface p-3 outline-none hover:bg-hover focus-visible:ring-2 focus-visible:ring-ring">
      <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <strong className="font-mono text-body text-ink">{model.symbol}</strong>
        {model.mark && <StatusBadge kind="neutral" className="h-5">{t(model.mark)}</StatusBadge>}
        {why && <StatusBadge kind={tier === 1 ? "progress" : "neutral"} className="h-5">{t(why)}</StatusBadge>}
        {model.expired && <StatusBadge kind="neutral" className="h-5">{t("已到期")}</StatusBadge>}
        <span className="ml-auto font-mono text-caption text-muted-foreground">{t("第")} {model.versionNo} {t("版")}</span>
      </span>
      <ProbabilityBar probabilities={model.probabilities} status={model.modelStatus} />
      <span className="flex flex-wrap gap-x-4 gap-y-1 text-caption text-muted-foreground">
        <span>{t("目标日")} <span className="font-mono tabular-nums text-ink">{model.targetDate ?? t(NOT_RECORDED)}</span></span>
        <span className="min-w-0 [overflow-wrap:anywhere]">{t("决策模型")} <span className="font-mono text-ink">{model.model ?? t(NOT_RECORDED)}</span></span>
      </span>
    </Link>
  </li>;
}
