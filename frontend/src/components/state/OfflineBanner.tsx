import { useState } from "react";
import { CloudOff, LoaderCircle } from "lucide-react";
import { useLocale } from "../../i18n";
import { connectivity, useBackendDown } from "./connectivity-store";

/**
 * 「连不上后端 · 重试」: the one banner for an unreachable backend, at the top of the page (design 4.0).  It is neutral, not an
 * alarm: nothing the reader has was lost.  The flag comes from the requests the app makes anyway (connectivity.mjs); 重试 runs
 * the last failed read again, and one success anywhere puts the banner out.  Plain elements only: it is in the first load.
 */
export function OfflineBanner() {
  const { t } = useLocale();
  const { down } = useBackendDown();
  const [retrying, setRetrying] = useState(false);
  if (!down) return null;
  const retry = async () => {
    setRetrying(true);
    try { await connectivity.retry((request) => window.fetch(request.input, request.init)); } finally { setRetrying(false); }
  };
  return <div data-slot="offline-banner" role="alert" className="sticky top-0 z-sticky flex items-center gap-3 border-b border-line bg-sunken px-4 py-2 text-small text-ink lg:px-6">
    <CloudOff aria-hidden="true" className="size-4 shrink-0 text-muted-foreground" />
    <span className="min-w-0 flex-1">{t("连不上后端")}</span>
    <button type="button" onClick={() => void retry()} disabled={retrying} aria-busy={retrying} className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-sm border border-line-strong bg-background px-3 text-small font-medium outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60">
      {retrying && <LoaderCircle aria-hidden="true" className="size-3.5 motion-safe:animate-spin" />}{t("重试")}
    </button>
  </div>;
}
