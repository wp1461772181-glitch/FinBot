// The queue behind `await confirm({...})` (design 4.0, 破坏性确认).  Pure: the dialog that shows the front of the queue is a component.
//
// A call returns a promise of true (the reader confirmed) or false (they cancelled, pressed Esc or clicked away).  Calls made
// while a dialog is open wait their turn, so two asks never stack.  When nothing is listening (no dialog host mounted) the ask
// is cancelled rather than left hanging: a destructive action must never go ahead without the reader's answer.

export function createConfirmQueue() {
  const queue = [];
  const listeners = new Set();
  let hosts = 0;
  let snapshot = null;
  const publish = () => { snapshot = queue[0] ? { ...queue[0].options, id: queue[0].id } : null; for (const listener of [...listeners]) listener(); };
  let counter = 0;
  return {
    /** Ask.  `options`: { title, description?, confirmLabel?, cancelLabel?, tone?: "danger" | "default", hold?: boolean, returnFocus?: HTMLElement | null }. */
    ask(options) {
      if (hosts === 0) return Promise.resolve(false);
      return new Promise((resolve) => { counter += 1; queue.push({ id: counter, options: { ...options }, resolve }); if (queue.length === 1) publish(); });
    },
    /** The ask on screen, or null.  The same object until the front of the queue changes. */
    getSnapshot: () => snapshot,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    /** Answer the ask on screen. */
    answer(value) {
      const front = queue.shift();
      if (!front) return;
      front.resolve(Boolean(value));
      publish();
    },
    /** A dialog host mounted (true) or went away (false).  When the last one goes, every waiting ask is cancelled. */
    attachHost(on) {
      hosts = Math.max(0, hosts + (on ? 1 : -1));
      if (hosts === 0) { while (queue.length) queue.shift().resolve(false); publish(); }
    },
    size: () => queue.length,
  };
}
