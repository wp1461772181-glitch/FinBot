import { useEffect, useState } from "react";
import { useLocale } from "./i18n";
import { getV2MonitorStatus } from "./api";
import type { V2MonitorStatus } from "./types";
import { MonitorCard, MonitorDetail } from "./ForecastMonitor";
import { errorMessage } from "./ForecastJob";
import type { ResourceState } from "./ForecastShared";

/** `#forecast/monitor`: the automatic monitor's records, one click from the home page instead of above the forecasts. */
export function ForecastMonitorPage({ onHome }: { onHome: () => void }) {
  const { t } = useLocale();
  const [monitor, setMonitor] = useState<ResourceState<V2MonitorStatus>>({ kind: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    setMonitor({ kind: "loading" });
    getV2MonitorStatus(controller.signal)
      .then((next) => { if (!controller.signal.aborted) setMonitor({ kind: "ready", data: next }); })
      .catch((error: unknown) => { if (!controller.signal.aborted) setMonitor({ kind: "error", message: errorMessage(error, "暂时无法读取自动监控记录。") }); });
    return () => controller.abort();
  }, []);
  return <section className="v2-desk" aria-labelledby="forecast-monitor-title">
    <header className="v2-desk-heading">
      <div><p className="eyebrow">{t("预测")}</p><h2 id="forecast-monitor-title">{t("监控状态")}</h2></div>
      <button className="secondary-action" type="button" onClick={onHome}>{t("回到预测首页")}</button>
    </header>
    <div className="v2-status-grid"><MonitorCard monitor={monitor} /></div>
    <MonitorDetail monitor={monitor} />
  </section>;
}
