// Following a streaming answer: when the transcript sticks to the newest line and when it lets go.
// The page follows only while the reader is at the bottom; one scroll up stops it and offers 回到底部.

/** How far from the bottom (px) still counts as being at the bottom (a line of slack for subpixel layout and a growing last line). */
export const FOLLOW_SLACK = 90;

/** `metrics` is { scrollHeight, scrollTop, clientHeight } of the scroll box. */
export function distanceFromBottom(metrics) {
  return metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight;
}

/** True while the reader is at (or within the slack of) the bottom: new text keeps the bottom in view. */
export function isFollowing(metrics, slack = FOLLOW_SLACK) {
  return distanceFromBottom(metrics) < slack;
}

/** 回到底部 shows when the reader has left the bottom, i.e. exactly when following has stopped. */
export function showJumpToBottom(metrics, slack = FOLLOW_SLACK) {
  return !isFollowing(metrics, slack);
}

/** The scrollTop that puts the bottom in view. */
export function bottomScrollTop(metrics) {
  return Math.max(0, metrics.scrollHeight - metrics.clientHeight);
}

/** After older messages were put above: the scrollTop that keeps the same line where it was. */
export function keepPositionAfterPrepend(before, afterScrollHeight) {
  return afterScrollHeight - before.scrollHeight + before.scrollTop;
}
