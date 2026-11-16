import { Link } from "react-router";
import { StatusBadge } from "@/components/StatusBadge";
import { getV2MonitorStatus } from "../../api/forecast-v2";
import { monitorChip } from "../../data-display.mjs";
import { useLocale } from "../../i18n";
import { paths } from "../../routes.mjs";
import { useRead } from "./use-read";

/** The small chip at the top right: is the automatic monitor well?  It is a link to the monitor page. */
export function MonitorChip() {
  const { t } = useLocale();
  const [monitor] = useRead("monitor", signal => getV2MonitorStatus(signal));
  const chip = monitor.kind === "ready" ? monitorChip(monitor.value.health) : null;
  return <Link to={paths.monitor()} data-testid="monitor-chip" className="rounded-full outline-none focus-visible:ring-2 focus-visible:ring-ring">
    {monitor.kind === "loading" && <StatusBadge kind="neutral">{t("正在读取")}</StatusBadge>}
    {monitor.kind === "error" && <StatusBadge kind="neutral">{t("监控状态暂不可用")}</StatusBadge>}
    {chip && <StatusBadge kind={chip.kind}>{t(chip.phrase)}</StatusBadge>}
  </Link>;
}
