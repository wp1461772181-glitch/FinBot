import { getV2MonitorStatus } from "../../../api/forecast-v2";
import { setMonitorDot } from "../../monitor-health";
import { monitorDot } from "../../monitor-dot.mjs";
import type { V2MonitorStatus } from "../../../types";

let lastRead = 0;

/** The one read of GET /v2/monitor/status: the page, the chips and the navigation's dot all use it, so the dot follows whatever was read last. */
export async function readMonitorStatus(signal?: AbortSignal): Promise<V2MonitorStatus> {
  lastRead = Date.now();
  const status = await getV2MonitorStatus(signal);
  setMonitorDot(monitorDot(status.health));
  return status;
}

/** The read when the reader enters the research area (for the navigation's dot): skipped when a page or chip has just read the monitor itself, so entering costs no extra request there. */
export async function entered(): Promise<void> {
  if (Date.now() - lastRead < 10_000) return;
  await readMonitorStatus();
}
