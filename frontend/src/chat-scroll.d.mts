export type ScrollMetrics = { scrollHeight: number; scrollTop: number; clientHeight: number };
export const FOLLOW_SLACK: number;
export function distanceFromBottom(metrics: ScrollMetrics): number;
export function isFollowing(metrics: ScrollMetrics, slack?: number): boolean;
export function showJumpToBottom(metrics: ScrollMetrics, slack?: number): boolean;
export function bottomScrollTop(metrics: ScrollMetrics): number;
export function keepPositionAfterPrepend(before: { scrollHeight: number; scrollTop: number }, afterScrollHeight: number): number;
