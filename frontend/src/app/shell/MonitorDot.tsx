import { useLocale } from "../../i18n";
import { useMonitorDot } from "../monitor-health";

/**
 * The dot beside 研究 when the automatic monitor is late (action colour) or failing (failure colour); nothing at all otherwise.  Its words are for a screen reader: the colour is
 * never the only sign.  The monitor is read when the reader enters the research area (`pages/research-root.tsx`); the pages and chips that read it later keep the dot fresh.
 */
export function MonitorDot({ className = "" }: { className?: string }) {
  const { t } = useLocale();
  const kind = useMonitorDot();
  const late = kind === "action";
  return kind && <span role="img" aria-label={t(late ? "监控延迟" : "监控异常")} data-testid="monitor-dot" className={`size-2 shrink-0 rounded-full ${late ? "bg-action" : "bg-danger"} ${className}`} />;
}
