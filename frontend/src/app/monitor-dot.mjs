/**
 * The dot beside 研究 in the navigation, from the monitor's health (the server's `health` of GET /v2/monitor/status): "action" (the amber action colour: the monitor is late),
 * "failure" (the failure colour: it is failing) or null.  A well monitor and one with no record yet show nothing at all.  Kept in a file of its own, without imports,
 * because the navigation (the first screen) reads it.
 */
export function monitorDot(health) {
  return health === "delayed" ? "action" : health === "degraded" ? "failure" : null;
}
