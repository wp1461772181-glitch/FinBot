import type { ReactNode } from "react";
import { Link } from "react-router";
import { CircleAlert, LoaderCircle } from "lucide-react";
import { useLocale } from "../../i18n";
import { paths } from "../../routes.mjs";
import { errorReason } from "./error-message";

/**
 * The error of one block (design 4.0, 局部错误): what went wrong in the block's own place, with 重试 and, when the way out is a
 * setting, 去设置.  The reason is the existing friendlyError mapping.  It is a statement, not an alarm: `role="alert"` so a
 * screen reader hears it, a quiet surface with the danger colour on the icon only.  Give either `error` (anything thrown) or
 * `message` (text already fit to show).
 */
export function ErrorBar({ error, message, onRetry, retrying = false, settings = false, settingsTo = paths.settings("models"), className = "", children }: {
  error?: unknown;
  message?: string;
  onRetry?: () => void;
  retrying?: boolean;
  /** Show 去设置 (the way out is a setting: a missing key, a model that is not set up). */
  settings?: boolean;
  settingsTo?: string;
  className?: string;
  children?: ReactNode;
}) {
  const { t } = useLocale();
  const reason = message ?? errorReason(error, t);
  const action = "inline-flex h-8 items-center gap-1.5 rounded-sm border border-line-strong bg-background px-3 text-small font-medium text-ink outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";
  return <div data-slot="error-bar" role="alert" className={`flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-line bg-sunken px-3 py-2.5 text-small text-ink ${className}`}>
    <CircleAlert aria-hidden="true" className="size-4 shrink-0 text-danger" />
    <p className="min-w-0 flex-1 break-words">{reason}</p>
    {children}
    {onRetry && <button type="button" onClick={onRetry} disabled={retrying} aria-busy={retrying} className={action}>
      {retrying && <LoaderCircle aria-hidden="true" className="size-3.5 motion-safe:animate-spin" />}{t("重试")}
    </button>}
    {settings && <Link to={settingsTo} className={action}>{t("去设置")}</Link>}
  </div>;
}
