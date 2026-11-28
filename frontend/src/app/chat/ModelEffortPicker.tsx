import { lazy, useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import { logoUrl } from "@/components/ai-elements/provider-logos";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { OptionalChunk } from "../../OptionalChunk";
import { getModelCatalog, updateBot, type Bot, type ModelCatalog } from "../../api/bots";
import { useLocale } from "../../i18n";
import { effectiveEntry, patchFor, triggerView } from "../../model-effort.mjs";
import "../../styles/model-picker.css";

// The list (search, the models by provider) is a chunk of its own, fetched when the badge is first pressed, hovered or focused.
const loadPanel = () => import("./ModelEffortPanel");
const ModelEffortPanel = lazy(loadPanel);

/**
 * The model badge of the composer: the model's logo and name; on click a list opens right above it, in the composer itself (a popover on
 * every screen, no card of its own: owner 11-28).  A choice is saved at once and closes the list; a failed save keeps it open with the
 * reason and the badge unchanged.  The owner decides: nothing is disabled, and nothing switches on its own.
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

  async function openChange(next: boolean) {
    setError("");
    if (next) setMounted(true);
    setOpen(next);
    if (next && !catalog && !(await readCatalog())) setError(t("模型目录暂时无法读取。"));
  }

  async function choose(kind: "model", value: string | null) {
    const current = shown.model;
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
    <Popover open={open} onOpenChange={(next) => void openChange(next)}>
      <PopoverTrigger asChild>
        <button type="button" ref={badge} data-testid="model-badge" aria-label={`${t("模型")} · ${view.name ?? t("服务器默认模型")}`}
          title={t("快速切换模型")} disabled={busy} onPointerEnter={() => void loadPanel()} onFocus={() => void loadPanel()}
          data-open={open || undefined}
          className="model-trigger inline-flex h-8 max-lg:h-11 max-w-full min-w-0 items-center gap-1.5 rounded-md pl-1.5 pr-2 text-caption font-medium text-ink-2 outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 data-[open]:bg-accent">
          <span className="picker-tile picker-tile-sm" aria-hidden="true"><img src={logoUrl(view.logo)} alt="" width={12} height={12} className="size-3 dark:invert" /></span>
          <span className="truncate">{view.name ?? t("服务器默认模型")}</span>
          <ChevronDown className={`size-3 shrink-0 text-faint transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
        </button>
      </PopoverTrigger>
      <PopoverContent side="top" align="start" sideOffset={8} data-testid="model-picker" aria-label={t("模型")}
        className="picker-glass w-[min(22rem,calc(100vw-2rem))] overflow-hidden rounded-lg p-0">
        {mounted && <OptionalChunk>
          <ModelEffortPanel open={open} catalog={catalog} shown={shown} entry={entry} busy={busy} error={error} onChoose={(kind, value) => void choose(kind, value)} />
        </OptionalChunk>}
      </PopoverContent>
    </Popover>
  );
}
