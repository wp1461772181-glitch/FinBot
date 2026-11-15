import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { PopPanel } from "@/components/PopPanel";
import { getContextUsage, type ContextUsage } from "../../api/conversations";
import { useLocale } from "../../i18n";
import { barSegments, formatKb, formatTokens, meterTone } from "../../context-usage.mjs";

const PART_LABEL: Record<string, string> = {
  system: "系统提示", tools: "工具定义", summary: "早前摘要", compressed: "半压历史", recent: "近期原文", free: "剩余空间",
};
// One fill per part of the budget (the legend dot and the bar segment share it); the free part is the empty track.
const PART_FILL: Record<string, string> = {
  system: "bg-ink-2", tools: "bg-chart-1", summary: "bg-chart-4", compressed: "bg-chart-3", recent: "bg-chart-2", free: "bg-line",
};
const TONE_TEXT: Record<string, string> = { ok: "text-muted-foreground", warn: "text-action", full: "text-danger" };
const RING = 2 * Math.PI * 7;

/** The context the next message will carry, as a small ring in the composer: how much of the budget is
 *  left, and on click which parts of it are used.  It hides itself when the numbers cannot be read. */
export function ContextMeter({ conversationId, botId, refreshKey, onCompact }: { conversationId: string | null; botId?: string | null; refreshKey: string; onCompact?: () => void }) {
  const { t } = useLocale();
  const [usage, setUsage] = useState<ContextUsage | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    getContextUsage(conversationId, controller.signal, botId)
      .then(next => { if (!controller.signal.aborted) setUsage(next); })
      .catch(() => { if (!controller.signal.aborted) setUsage(null); });
    return () => controller.abort();
  }, [conversationId, botId, refreshKey]);

  if (!usage) return null;
  const tone = meterTone(usage);
  const used = Math.min(1, Math.max(0, usage.hasHistory ? usage.usedPercent / 100 : 1 - usage.remainingPercent / 100));
  const note = "text-caption text-muted-foreground";
  return <span className="relative inline-flex" data-testid="context-meter-host">
    <button type="button" data-testid="context-meter" aria-expanded={open} aria-haspopup="dialog" title={t("上下文用量")} onClick={() => setOpen(value => !value)}
      className={`inline-flex h-8 items-center gap-1.5 rounded-full px-2 max-lg:h-11 text-caption outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring ${TONE_TEXT[tone] ?? TONE_TEXT.ok}`}>
      <svg viewBox="0 0 18 18" className="size-4" aria-hidden="true">
        <circle cx="9" cy="9" r="7" fill="none" strokeWidth="2.5" className="stroke-line" />
        <circle cx="9" cy="9" r="7" fill="none" strokeWidth="2.5" strokeLinecap="round" stroke="currentColor" strokeDasharray={`${(RING * used).toFixed(1)} ${RING.toFixed(1)}`} transform="rotate(-90 9 9)" />
      </svg>
      <span className="tabular-nums">{usage.hasHistory ? usage.usedPercent : usage.remainingPercent}%</span>
      <span className="sr-only">{usage.hasHistory ? t("历史已用") : t("上下文剩余")}</span>
    </button>
    <PopPanel open={open} onClose={() => setOpen(false)} label={t("上下文用量")} align="end">
      <div className="flex items-baseline justify-between gap-3">
        <strong className="text-body font-semibold">{t("上下文用量")}</strong>
        <span className={note}>{t("已用")} {formatKb(usage.usedBytes)} / {formatKb(usage.capacityBytes)}</span>
      </div>
      <div className="mt-2 flex h-2 overflow-hidden rounded-full bg-line" role="img" aria-label={`${t("上下文剩余")} ${usage.remainingPercent}%`}>
        {barSegments(usage).filter((segment: { key: string }) => segment.key !== "free").map((segment: { key: string; percent: number }) => <i key={segment.key} className={`block h-full ${PART_FILL[segment.key] ?? "bg-ink-2"}`} style={{ width: `${segment.percent}%` }} />)}
      </div>
      <ul className="mt-3 flex flex-col gap-1.5">
        {usage.parts.map(part => <li key={part.key} className="flex items-center gap-2 text-small">
          <i className={`size-2 shrink-0 rounded-full ${PART_FILL[part.key] ?? "bg-ink-2"}`} aria-hidden="true" />
          <span className="min-w-0 flex-1">{t(PART_LABEL[part.key] ?? part.key)}
            {part.key === "summary" && part.segments ? <small className={`${note} ml-1`}>· {part.segments} {t("段摘要")}</small> : null}
            {(part.key === "compressed" || part.key === "recent") && part.turns ? <small className={`${note} ml-1`}>· {part.turns} {t("轮")}</small> : null}
          </span>
          <span className="shrink-0 tabular-nums">{formatKb(part.bytes)} <small className={note}>≈ {formatTokens(part.tokens)} token</small></span>
        </li>)}
      </ul>
      <p className={`${note} mt-3`}>{t("历史预算")} {usage.budgetKb} KB{usage.hasHistory ? <> · {t("已用")} {usage.usedPercent}% · {t("达到")} {usage.compactAtPercent}% {t("自动压缩")}</> : null}</p>
      {onCompact && conversationId && <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => { setOpen(false); onCompact(); }}>{t("现在压缩")}</Button>}
      {usage.compressing && <p className={`${note} mt-2`}>{t("更早的内容已压缩：半压历史保留你的原话和答复的开头，更早的只剩摘要。")}</p>}
      {usage.hiddenTurns > 0 && <p className="mt-2 text-caption text-action">{t("有更早的对话暂时不在上下文里，等待摘要。")}</p>}
      <p className={`${note} mt-2`}>{t("“剩余”指本产品的上下文预算，不是模型窗口；token 为按 字节÷3 的估算。")}</p>
    </PopPanel>
  </span>;
}
