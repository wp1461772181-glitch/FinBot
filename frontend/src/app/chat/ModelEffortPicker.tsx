import { useState, useEffect } from "react";
import { Check, ChevronDown } from "lucide-react";
import { PopPanel } from "@/components/PopPanel";
import { getModelCatalog, updateBot, type Bot, type ModelCatalog } from "../../api/bots";
import { useLocale } from "../../i18n";
import { badgeText, effectiveEntry, effortChoices, modelChoices, noEffort, patchFor } from "../../model-effort.mjs";

const optionClass = "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-body text-ink outline-none hover:bg-accent focus-visible:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";
const headClass = "px-2 pb-1 pt-2 text-caption font-medium text-muted-foreground first:pt-0";

/**
 * The model badge of the composer: the bot's model and reasoning effort, and on click the quick select.  A choice is saved at
 * once; a failed save keeps the panel open with the reason and the badge unchanged.  The owner decides: nothing is disabled,
 * and nothing switches on its own.  (Logic as before; the panel is now a dropdown above the badge, a sheet on a phone.)
 */
export function ModelEffortPicker({ bot, onBotChanged }: { bot: Bot; onBotChanged: () => void }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [shown, setShown] = useState<Bot>(bot);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // The strength tiers follow the model the badge shows: the bot's own, or the server default when it has none.
  const entry = effectiveEntry(catalog, shown.model);

  // A reloaded bot (the list changed) is the truth again.
  useEffect(() => setShown(bot), [bot]);

  async function toggle() {
    const next = !open;
    setOpen(next);
    setError("");
    if (next && !catalog) {
      try { setCatalog(await getModelCatalog()); }
      catch { setError(t("模型目录暂时无法读取。")); }
    }
  }

  async function choose(kind: "model" | "effort", value: string | null) {
    const current = kind === "model" ? shown.model : shown.reasoning_effort;
    if ((value ?? null) === (current ?? null)) { setOpen(false); return; }
    setBusy(true);
    setError("");
    try {
      const saved = await updateBot(bot.id, patchFor(kind, value));
      setShown(saved);
      // A model choice stays open: the strength list below is the new model's now, so the owner sees it in this visit.
      if (kind === "effort") setOpen(false);
      onBotChanged();
    } catch (exc) {
      setError(exc instanceof Error && exc.message ? exc.message : t("保存失败，请重试。"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="relative inline-flex min-w-0" data-testid="model-badge-host">
      <button type="button" data-testid="model-badge" aria-haspopup="dialog" aria-expanded={open}
        title={t("快速切换模型与推理强度")} disabled={busy} onClick={() => void toggle()}
        className="inline-flex h-8 max-lg:h-11 max-w-full min-w-0 items-center gap-1 rounded-sm px-2 text-caption text-muted-foreground outline-none hover:bg-accent hover:text-ink focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60">
        <span className="truncate">{badgeText(shown, t)}</span><ChevronDown className="size-3.5 shrink-0" aria-hidden="true" />
      </button>
      <PopPanel open={open} onClose={() => setOpen(false)} label={t("模型与推理强度")}>
        <p className={headClass}>{t("模型")}</p>
        {!catalog ? (!error && <p className="px-2 py-1 text-small text-muted-foreground">{t("正在读取模型目录…")}</p>) : (
          <div role="radiogroup" aria-label={t("模型")}>
            {modelChoices(catalog, shown.model).map((choice) => (
              <button key={`m:${choice.value ?? "default"}`} type="button" role="radio" aria-checked={choice.checked} className={optionClass} disabled={busy} onClick={() => void choose("model", choice.value)}>
                <Check className={`size-4 shrink-0 ${choice.checked ? "" : "invisible"}`} aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate">{choice.value === null ? `${t("服务器默认模型")}${catalog.default ? ` (${catalog.default})` : ""}` : choice.label}</span>
                {choice.keyMissing && <small className="text-caption text-muted-foreground">{t("缺 key")}</small>}
              </button>
            ))}
          </div>
        )}
        <p className={headClass}>{t("推理强度")}</p>
        {noEffort(entry) && <p className="px-2 py-1 text-small text-muted-foreground">{t("该模型不支持思考强度")}</p>}
        <div role="radiogroup" aria-label={t("推理强度")}>
          {effortChoices(shown.reasoning_effort, entry).map((choice) => (
            <button key={`e:${choice.value ?? "default"}`} type="button" role="radio" aria-checked={choice.checked} className={optionClass} disabled={busy} onClick={() => void choose("effort", choice.value)}>
              <Check className={`size-4 shrink-0 ${choice.checked ? "" : "invisible"}`} aria-hidden="true" />
              <span className="min-w-0 flex-1">{t(choice.label)}</span>
              {choice.unsupported && <small className="text-caption text-muted-foreground">{t("不在该模型的档位内")}</small>}
            </button>
          ))}
        </div>
        {error && <p role="alert" className="px-2 py-1 text-small text-danger">{error}</p>}
        <p className="mt-2 border-t border-line px-2 pt-2 text-caption text-muted-foreground">{t("模型和 key 只在服务器上，浏览器不保存 key。")}</p>
      </PopPanel>
    </span>
  );
}
