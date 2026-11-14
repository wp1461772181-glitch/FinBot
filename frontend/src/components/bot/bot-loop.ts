// One shared requestAnimationFrame loop for every avatar that runs frames, and the rule that at most one M or L avatar does so at a
// time (design 6.9 P3).
export type Tick = (dt: number) => void;
const subscribers = new Set<Tick>();
let raf = 0, lastMs = 0;
function loop(ms: number) {
  // Bounded step: a tab that was hidden resumes where it was instead of jumping ahead.
  const dt = lastMs ? Math.min((ms - lastMs) / 1000, 0.064) : 0;
  lastMs = ms;
  for (const tick of [...subscribers]) tick(dt);
  raf = subscribers.size ? requestAnimationFrame(loop) : 0;
  if (!raf) lastMs = 0;
}
export function subscribe(tick: Tick) {
  subscribers.add(tick);
  if (!raf) raf = requestAnimationFrame(loop);
  return () => { subscribers.delete(tick); };
}

interface Claim { rank: number; order: number; granted: boolean | null; grant: (on: boolean) => void; label: string }
const claims: Claim[] = [];
let sequence = 0;

/** Re-decide who runs: the largest avatar wins (the first to ask among equals); every other M / L avatar gets a still frame. */
function settle() {
  const ordered = [...claims].sort((a, b) => b.rank - a.rank || a.order - b.order);
  ordered.forEach((claim, i) => {
    const on = i === 0;
    if (claim.granted === on) return;
    claim.granted = on;
    if (!on && import.meta.env.DEV) console.warn(`[bot] a second M/L avatar asked for per-frame animation (${claim.label}); it stays a still frame while another runs`);
    claim.grant(on);
  });
}

/**
 * Ask to run per-frame as an M or L avatar. `grant(true/false)` tells the avatar when it may run and when it must drop to a still frame.
 * Returns the release function (call it on unmount: the next in line is granted).
 */
export function claimFullLoop(rank: number, label: string, grant: (on: boolean) => void): () => void {
  const claim: Claim = { rank, order: sequence++, granted: null, grant, label };
  claims.push(claim);
  settle();
  return () => { const i = claims.indexOf(claim); if (i >= 0) claims.splice(i, 1); settle(); };
}

/** For checks: how many M / L avatars currently hold the loop (always 0 or 1). */
export function fullLoopHolders() { return claims.filter(claim => claim.granted).length; }
