import { lazy, useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { logoUrl } from "@/components/ai-elements/provider-logos";
import { OptionalChunk } from "../../OptionalChunk";
import { getModelCatalog, updateBot, type Bot, type ModelCatalog } from "../../api/bots";
import { useLocale } from "../../i18n";
import { effectiveEntry, patchFor, triggerView } from "../../model-effort.mjs";
import "../../styles/model-picker.css";

// The panel (the command palette, the drawer, the strength control) is a chunk of its own, fetched when the badge is first pressed, hovered or focused.
const loadPanel = () => import("./ModelEffortPanel");
const ModelEffortPanel = lazy(loadPanel);

/**
 * The model badge of the composer: the model's logo and name, the strength's bars and word, and on click the selector (a centred palette on a wide screen, a drawer on a phone).
 * A choice is saved at once; a failed save keeps the panel open with the reason and the badge unchanged.  The owner decides: nothing is disabled, and nothing switches on its own.
 * Choosing a model leaves the panel open (the strength row is the new model's now); choosing a strength closes it.
 */
export function ModelEffortPicker({ bot, onBotChanged }: { bot: Bot; onBotChanged: () => void }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [shown, setShown] = useState<Bot>(bot);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const badge = useRef<HTMLButtonElement>(null);
  // The strength tiers follow the model the badge shows: the bot's own, or the server default when it has none.
  const entry = effectiveEntry(catalog, shown.model);

  // A reloaded bot (the list changed) is the truth again.
  useEffect(() => setShown(bot), [bot]);

  // The badge draws the model's logo and name, which only the catalog knows: read it once the badge is there (a failure shows the id and is retried when the panel opens).
  const readCatalog = useCallback(async (signal?: AbortSignal) => {
    try { const next = await getModelCatalog(signal); if (!signal?.aborted) setCatalog(next); return true; }
    catch { return false; }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void readCatalog(controller.signal);
    return () => controller.abort();
  }, [readCatalog]);

  async function toggle() {
    const next = !open;
    setError("");
    if (next) setMounted(true);
    setOpen(next);
    if (next && !catalog && !(await readCatalog())) setError(t("模型目录暂时无法读取。"));
  }

  async function choose(kind: "model" | "effort", value: string | null) {
    const current = kind === "model" ? shown.model : shown.reasoning_effort;
    if ((value ?? null) === (current ?? null)) { setOpen(false); return; }
    setBusy(true);
    setError("");
    try {
      const saved = await updateBot(bot.id, patchFor(kind, value));
      setShown(saved);
      setOpen(false);      // the panel holds the model only (no effort row since 11-28): a choice closes it
      onBotChanged();
    } catch (exc) {
      setError(exc instanceof Error && exc.message ? exc.message : t("保存失败，请重试。"));
    } finally {
      setBusy(false);
    }
  }

  const view = triggerView(shown, entry);
  return (
    <span className="relative inline-flex min-w-0" data-testid="model-badge-host">
      <button type="button" ref={badge} data-testid="model-badge" aria-haspopup="dialog" aria-expanded={open} aria-label={`${t("模型")} · ${view.name ?? t("服务器默认模型")}`}
        title={t("快速切换模型")} disabled={busy} onClick={() => void toggle()} onPointerEnter={() => void loadPanel()} onFocus={() => void loadPanel()}
        data-open={open || undefined}
        className="model-trigger inline-flex h-8 max-lg:h-11 max-w-full min-w-0 items-center gap-1.5 rounded-md pl-1.5 pr-2 text-caption font-medium text-ink-2 outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 data-[open]:bg-accent">
        <span className="picker-tile picker-tile-sm" aria-hidden="true"><img src={logoUrl(view.logo)} alt="" width={12} height={12} className="size-3 dark:invert" /></span>
        <span className="truncate">{view.name ?? t("服务器默认模型")}</span>
        <ChevronDown className={`size-3 shrink-0 text-faint transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {mounted && <OptionalChunk>
        <ModelEffortPanel open={open} onOpenChange={(next) => { if (!next) setOpen(false); }} catalog={catalog} shown={shown} entry={entry} busy={busy} error={error} onChoose={(kind, value) => void choose(kind, value)} returnFocus={() => badge.current?.focus({ preventScroll: true })} />
      </OptionalChunk>}
    </span>
  );
}
