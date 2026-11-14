// Sidebar rows: the hovered bot's eyes follow the pointer. Pure (no React, no engine) so node --test covers it.
// Only the row under the pointer holds move/leave listeners and only it has a `handle.pointer`; every other row's
// avatar stays the light prop-driven one. The per-frame work lives in the shared rAF loop of components/bot/BotBody, which only
// looks at a handle that is set.
import { aimFromPointer, pointerFresh } from "./bloub-gaze.mjs";

/**
 * Bind hover-follow to a row element. `handle.pointer` is written on every move (a plain object, no re-render);
 * `setActive` is called only on enter / leave. Mouse and pen only: touch has no hover. Returns `dispose`.
 */
export function bindRowGaze(host, { handle, setActive, now, reduced }) {
  if (!host || reduced()) return () => {};
  let hovering = false;
  const point = e => ({ x: e.clientX, y: e.clientY, at: now() });
  const onMove = e => { if (e.pointerType !== "touch") handle.pointer = point(e); };
  const stop = () => {
    host.removeEventListener("pointermove", onMove);
    host.removeEventListener("pointerleave", onLeave);
    host.removeEventListener("pointercancel", onLeave);
    if (hovering) { hovering = false; handle.pointer = null; setActive(false); }
  };
  function onLeave() { stop(); }
  const onEnter = e => {
    if (e.pointerType === "touch" || hovering) return;
    hovering = true;
    handle.pointer = point(e);
    host.addEventListener("pointermove", onMove, { passive: true });
    host.addEventListener("pointerleave", onLeave);
    host.addEventListener("pointercancel", onLeave);
    setActive(true);
  };
  host.addEventListener("pointerenter", onEnter);
  return () => { stop(); host.removeEventListener("pointerenter", onEnter); };
}

/** Where a row avatar looks: only on the idle base (work / notify keep their own animation) and while the pointer is fresh. */
export function rowAim(pointer, state, now, box, view) {
  if (state !== "idle" || !pointer || !pointerFresh(pointer.at, now)) return null;
  return aimFromPointer(pointer, box, view);
}
