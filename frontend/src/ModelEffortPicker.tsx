import { useRef, useState, useEffect } from "react";
import { getModelCatalog, updateBot, type Bot, type ModelCatalog } from "./api";
import { useLocale } from "./i18n";
import { badgeText, effectiveEntry, effortChoices, modelChoices, noEffort, patchFor } from "./model-effort.mjs";

/**
 * The chat badge as a quick select: the bot's model and reasoning effort.  A choice is saved at once; a failed
 * save keeps the panel open with the reason and the badge unchanged.  The owner decides: nothing is disabled,
 * and nothing switches on its own.
 */
export function ModelEffortPicker({ bot, onBotChanged }: { bot: Bot; onBotChanged: () => void }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null);
  const [shown, setShown] = useState<Bot>(bot);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const rootRef = useRef<HTMLSpanElement>(null);
  // The strength tiers follow the model the badge shows: the bot's own, or the server default when it has none.
  const entry = effectiveEntry(catalog, shown.model);

  // A reloaded bot (the list changed) is the truth again.
  useEffect(() => setShown(bot), [bot]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: MouseEvent) => { if (!rootRef.current?.contains(event.target as Node)) setOpen(false); };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onPointer); document.removeEventListener("keydown", onKey); };
  }, [open]);

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
    <span className="model-effort" ref={rootRef}>
      <button type="button" className="agent-connection is-ready model-effort-trigger" aria-haspopup="dialog" aria-expanded={open}
        title={t("快速切换模型与推理强度")} disabled={busy} onClick={() => void toggle()}>
        {badgeText(shown, t)}<span aria-hidden="true"> ▾</span>
      </button>
      {open && (
        <div className="model-effort-pop" role="dialog" aria-label={t("模型与推理强度")}>
          <p className="model-effort-head">{t("模型")}</p>
          {!catalog ? (!error && <p className="model-effort-note">{t("正在读取模型目录…")}</p>) : (
            <div role="radiogroup" aria-label={t("模型")}>
              {modelChoices(catalog, shown.model).map((choice) => (
                <button key={`m:${choice.value ?? "default"}`} type="button" role="radio" aria-checked={choice.checked}
                  className={`model-effort-option${choice.checked ? " is-current" : ""}`} disabled={busy} onClick={() => void choose("model", choice.value)}>
                  <span className="model-effort-mark" aria-hidden="true">{choice.checked ? "✓" : ""}</span>
                  <span>{choice.value === null ? `${t("服务器默认模型")}${catalog.default ? ` (${catalog.default})` : ""}` : choice.label}</span>
                  {choice.keyMissing && <small> · {t("缺 key")}</small>}
                </button>
              ))}
            </div>
          )}
          <p className="model-effort-head">{t("推理强度")}</p>
          {noEffort(entry) && <p className="model-effort-note">{t("该模型不支持思考强度")}</p>}
          <div role="radiogroup" aria-label={t("推理强度")}>
            {effortChoices(shown.reasoning_effort, entry).map((choice) => (
              <button key={`e:${choice.value ?? "default"}`} type="button" role="radio" aria-checked={choice.checked}
                className={`model-effort-option${choice.checked ? " is-current" : ""}`} disabled={busy} onClick={() => void choose("effort", choice.value)}>
                <span className="model-effort-mark" aria-hidden="true">{choice.checked ? "✓" : ""}</span>
                <span>{t(choice.label)}</span>
                {choice.unsupported && <small> · {t("不在该模型的档位内")}</small>}
              </button>
            ))}
          </div>
          {error && <p className="model-effort-error" role="alert">{error}</p>}
        </div>
      )}
    </span>
  );
}
