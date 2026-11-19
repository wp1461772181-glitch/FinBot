import type { TelegramBindStatus } from "../../../api/integrations";

export const TELEGRAM_STEPS = ["保存 token", "生成绑定码", "等待绑定"] as const;

/**
 * The step the shared Telegram bot's binding is on, 0 to 3: 0 no token yet, 1 token saved (a code can be made), 2 a code is out (the page waits for the message), 3 bound.
 * `code` is the code this page made.  After a reload the server may still say a code is live though the page no longer holds it: that is step 2 as well (the page then offers 重新生成).
 */
export function sharedTelegramStep(state: TelegramBindStatus | null, code: string): 0 | 1 | 2 | 3 {
  if (state?.bound) return 3;
  if (!state?.has_token) return 0;
  return code || state.bind_code_active ? 2 : 1;
}

/** How often the page asks the server for the binding while it waits: only with a code made on this page and not yet bound (the bot settings page's rule). */
export const TELEGRAM_POLL_MS = 5000;
