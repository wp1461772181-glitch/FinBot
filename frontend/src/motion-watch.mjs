// The frame-time watch behind the automatic drop to "lite" (design 6.9 P10): over any 2 seconds of frames of the avatar's loop the average
// frame takes more than 24 ms.  Pure: it is fed the interval of each frame (ms).  An interval over 250 ms (the tab came back, a breakpoint, the
// page was still mounting) is not a measurement of the animation: it is left out and the count starts again; so is an interval of 0 (the loop
// has just started).  Lazy: only the live avatar loads it, and only while the level could still drop.
export const SLOW_FRAME_MS = 24;
export const WATCH_WINDOW_MS = 2000;
export const GAP_MS = 250;

export function createFrameWatch({ slow = SLOW_FRAME_MS, window = WATCH_WINDOW_MS, gap = GAP_MS } = {}) {
  let frames = [], sum = 0;
  const reset = () => { frames = []; sum = 0; };
  return {
    /** Feed one frame interval (ms); true when the last `window` ms of frames average more than `slow` ms. */
    step(ms) {
      if (!Number.isFinite(ms) || ms <= 0 || ms > gap) { reset(); return false; }
      frames.push(ms); sum += ms;
      // slide: the oldest frames go while what is left still covers the whole window
      while (frames.length > 1 && sum - frames[0] >= window) sum -= frames.shift();
      return sum >= window && sum / frames.length > slow;
    },
    reset,
    get span() { return sum; }
  };
}
