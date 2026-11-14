import { needToaster } from "./toast-store";

/** How long a plain toast stays (design 4.0: 2 seconds).  One that offers 撤销 stays longer so the button can be reached, by keyboard too. */
export const TOAST_MS = 2000;
export const TOAST_UNDO_MS = 6000;

export type NotifyOptions = {
  /** A second line under the message. */
  description?: string;
  /** 撤销: the toast carries the button; pressing it runs `onClick` and closes the toast. */
  undo?: { label: string; onClick: () => void };
  /** A button that takes the reader somewhere (查看): like 撤销, it keeps the toast long enough to be reached.  The toast closes when it is pressed. */
  action?: { label: string; onClick: () => void };
  /** Replace a toast made earlier with the same id (a repeated save does not stack). */
  id?: string | number;
  duration?: number;
};

// sonner and its Toaster come in one chunk, fetched the first time anything is announced.
const load = () => { needToaster(); return import("./toast-impl").then(async (impl) => { await impl.toasterReady; return impl.toast; }); };

function build(options: NotifyOptions = {}) {
  const { undo, action, duration, ...rest } = options;
  const button = undo ?? action;
  return { ...rest, duration: duration ?? (button ? TOAST_UNDO_MS : TOAST_MS), ...(button ? { action: { label: button.label, onClick: button.onClick } } : {}) };
}

/**
 * The one way to announce an outcome (design 4.0, 操作成功): bottom right, gone after two seconds.  Everything in the app sends
 * its toasts from here, so the position, timing and look are in one place.
 */
export const notify = {
  success: (message: string, options?: NotifyOptions) => { void load().then((toast) => toast.success(message, build(options))); },
  error: (message: string, options?: NotifyOptions) => { void load().then((toast) => toast.error(message, { ...build(options), duration: options?.duration ?? 5000 })); },
  info: (message: string, options?: NotifyOptions) => { void load().then((toast) => toast(message, build(options))); },
  /**
   * Follow a promise: a loading toast that turns into the success or the error one.  Returns the promise itself, so the caller
   * can still await it.
   */
  promise<T>(promise: Promise<T>, messages: { loading: string; success: string | ((value: T) => string); error: string | ((error: unknown) => string) }, options?: NotifyOptions): Promise<T> {
    void load().then((toast) => { toast.promise(promise, { ...messages, ...build(options) }); });
    return promise;
  },
  dismiss: (id?: string | number) => { void load().then((toast) => toast.dismiss(id)); },
};
