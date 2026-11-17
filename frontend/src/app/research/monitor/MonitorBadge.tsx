import { StatusBadge } from "@/components/StatusBadge";
import { useLocale } from "../../../i18n";
import { monitorState } from "./monitor-model.mjs";

/** The monitor's health as a badge: one small component for the chips (watchlist, forecast home) and the monitor page's health card, so the four states look the same everywhere. */
export function MonitorBadge({ health, className }: { health: unknown; className?: string }) {
  const { t } = useLocale();
  const state = monitorState(health);
  return <StatusBadge kind={state.kind} className={className}><span data-monitor-state={state.id}>{t(state.phrase)}</span></StatusBadge>;
}
