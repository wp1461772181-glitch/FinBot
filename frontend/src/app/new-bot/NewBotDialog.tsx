// The new-bot dialog (P5.2, design 4.4): a dialog on a desktop, a full-screen drawer on a phone, one body in both.  Two columns: the large preview of the bot on the
// left (it takes the shape and colour at once, and the personality its template gives), the three steps on the right in one screen: the name (the only thing
// that is needed), a template (optional, can be taken off again), the shape and colour (a random pair to begin with, the same picker as the bot's settings page).
// A fetched chunk of its own: the first screen only listens for the event that opens it (events.ts).
import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { Shuffle, X } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Drawer, DrawerContent, DrawerDescription, DrawerTitle } from "@/components/ui/drawer";
import { Button } from "@/components/ui/button";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/state/Skeleton";
import { ErrorBar } from "@/components/state/ErrorBar";
import { StatefulButton } from "@/components/state/StatefulButton";
import { BotPresence } from "@/components/bot/BotPresence";
import { LookPicker } from "@/components/bot/LookPicker";
import { ARCHETYPE_HINTS, ARCHETYPE_NAMES } from "@/components/bot/PersonaPicker";
import { usePersona } from "@/components/bot/use-persona";
import { createBot, getBotTemplates } from "../../api/bots-admin";
import { BOT_NAME_ERRORS } from "../../api/bot-errors";
import type { Bot, BotTemplate, BotTool } from "../../api/bots";
import { randomLook, type BloubLook } from "../../bloub-look.mjs";
import { BOT_AVATAR_SIZE } from "../../bot-sizes.mjs";
import { useLocale } from "../../i18n";
import { DEFAULT_AVATAR } from "../../orb.mjs";
import { createFields, createName, previewBot } from "../../new-bot-form.mjs";
import { useFocusKeep } from "../use-focus-keep";

/** The dialog's width from this on; below it the same body is a full-screen drawer.  (Its own matchMedia hook: the chat's one (app/chat/use-media) would be a shared chunk of its own for the first screen to load.) */
const WIDE_QUERY = "(min-width: 640px)";
const subscribeWide = (notify: () => void) => { const list = window.matchMedia?.(WIDE_QUERY); list?.addEventListener?.("change", notify); return () => list?.removeEventListener?.("change", notify); };
const useWide = () => useSyncExternalStore(subscribeWide, () => window.matchMedia?.(WIDE_QUERY).matches ?? false, () => false);

type Props = { onClose: () => void; onCreated: (bot: Bot) => void };

export default function NewBotDialog({ onClose, onCreated }: Props) {
  const { t } = useLocale();
  const wide = useWide();
  const [busy, setBusy] = useState(false);
  const content = useRef<HTMLDivElement>(null);
  const keep = useFocusKeep("new-bot-dialog");
  const draft = useNewBotDraft();
  // Where the focus was when the dialog came up (the sidebar's button, say): Radix hands it back to its trigger on closing, and this dialog is opened by state, so it has none.
  const [opener] = useState<HTMLElement | null>(() => (document.activeElement instanceof HTMLElement && document.activeElement !== document.body ? document.activeElement : null));
  const giveBackFocus = (event: Event) => { event.preventDefault(); if (opener?.isConnected) opener.focus(); };
  const close = (open: boolean) => { if (!open && !busy) onClose(); };
  const body = (title: ReactNode, description: ReactNode) => <NewBotBody wide={wide} busy={busy} setBusy={setBusy} onClose={onClose} onCreated={onCreated} title={title} description={description} draft={draft} />;
  if (wide) {
    return <Dialog open onOpenChange={close}>
      <DialogContent closeLabel={t("关闭")} data-testid="new-bot-dialog" className="gap-0 overflow-hidden p-0 sm:max-w-[820px]"
        onOpenAutoFocus={(event) => { event.preventDefault(); keep(() => content.current?.querySelector<HTMLElement>("#new-bot-name")); }}
        onCloseAutoFocus={giveBackFocus} onEscapeKeyDown={(event) => { if (busy) event.preventDefault(); }} onInteractOutside={(event) => { if (busy) event.preventDefault(); }}
        ref={content}>
        {body(<DialogTitle className="text-title-s font-semibold text-ink">{t("新建 bot")}</DialogTitle>, <DialogDescription className="sr-only">{t("起个名字就能创建；模板、形状和颜色都可以之后再改。")}</DialogDescription>)}
      </DialogContent>
    </Dialog>;
  }
  // A phone: the whole screen.  The keyboard must not open by itself over the preview, so the name field is not focused on opening.
  return <Drawer open onOpenChange={close} dismissible={!busy} handleOnly>
    <DrawerContent data-testid="new-bot-dialog" className="data-[vaul-drawer-direction=bottom]:mt-0 data-[vaul-drawer-direction=bottom]:h-dvh data-[vaul-drawer-direction=bottom]:max-h-dvh data-[vaul-drawer-direction=bottom]:rounded-none"
      onOpenAutoFocus={(event) => { event.preventDefault(); keep(() => content.current); }} onCloseAutoFocus={giveBackFocus} ref={content}>
      {body(<DrawerTitle className="text-title-s font-semibold text-ink">{t("新建 bot")}</DrawerTitle>, <DrawerDescription className="sr-only">{t("起个名字就能创建；模板、形状和颜色都可以之后再改。")}</DrawerDescription>)}
    </DrawerContent>
  </Drawer>;
}

const stepNo = "mr-1.5 inline-grid size-5 place-items-center rounded-full bg-sunken font-mono text-caption text-muted-foreground";

/**
 * The draft of the form, kept above both shells: a window dragged across 640px swaps the dialog for the drawer and back, and the body under either is mounted anew each time, so what
 * was typed, the template, the shape and colour (random to begin with) and the error must not live in it.
 */
function useNewBotDraft() {
  const [templates, setTemplates] = useState<BotTemplate[] | null>(null), [tools, setTools] = useState<BotTool[]>([]);
  const [name, setName] = useState(""), [picked, setPicked] = useState<BotTemplate | null>(null);
  // A new bot starts from a random shape and colour of the catalog (shown, and stored on create); 换一个 draws another pair.
  const [look, setLook] = useState<BloubLook>(() => randomLook());
  const [nameError, setNameError] = useState(""), [failure, setFailure] = useState<unknown>(null);
  useEffect(() => {
    const controller = new AbortController();
    // Templates are only a shortcut: when they cannot be read, a name still creates the bot.
    getBotTemplates(controller.signal).then(v => { setTemplates(v.templates.filter(x => x.id !== "blank")); setTools(v.tools); }).catch(() => { if (!controller.signal.aborted) setTemplates([]); });
    return () => controller.abort();
  }, []);
  return { templates, tools, name, setName, picked, setPicked, look, setLook, nameError, setNameError, failure, setFailure };
}
type Draft = ReturnType<typeof useNewBotDraft>;

function NewBotBody({ wide, busy, setBusy, onClose, onCreated, title, description, draft }: {
  wide: boolean; busy: boolean; setBusy: (busy: boolean) => void; onClose: () => void; onCreated: (bot: Bot) => void; title: ReactNode; description: ReactNode; draft: Draft;
}) {
  const { t } = useLocale();
  const { templates, tools, name, setName, picked, setPicked, look, setLook, nameError, setNameError, failure, setFailure } = draft;
  const finalName = createName(name, picked, tools);
  async function submit() {
    if (!finalName || busy) return;
    setBusy(true); setNameError(""); setFailure(null);
    try { onCreated(await createBot(createFields(name, picked, tools, look))); }
    catch (error) {
      // A name the server refuses (taken, or not 1–40 characters) belongs under the name; anything else is the dialog's own error.
      if (error instanceof Error && BOT_NAME_ERRORS.includes(error.message)) setNameError(error.message); else setFailure(error);
      setBusy(false);
    }
  }
  const nameBox = <Field data-invalid={Boolean(nameError) || undefined}>
    <FieldLabel htmlFor="new-bot-name"><span aria-hidden="true" className={stepNo}>1</span>{t("名字")}</FieldLabel>
    <Input id="new-bot-name" data-testid="new-bot-name" className="max-sm:h-11" value={name} maxLength={40} disabled={busy} autoComplete="off" aria-invalid={Boolean(nameError) || undefined} aria-describedby={nameError ? "new-bot-name-error" : undefined}
      placeholder={picked?.name || t("例如：读财报")} onChange={(e) => { setName(e.target.value); setNameError(""); }} />
    {nameError && <FieldError id="new-bot-name-error" data-testid="new-bot-name-error">{t(nameError)}</FieldError>}
  </Field>;
  return <form data-testid="new-bot-form" className={wide ? "grid min-h-0 grid-cols-[260px_1fr]" : "flex min-h-0 flex-1 flex-col"} noValidate
    onSubmit={(event) => { event.preventDefault(); void submit(); }}>
    {!wide && <div className="flex items-center justify-between gap-2 border-b border-line py-2 pr-2 pl-4">{title}{description}
      <Button type="button" variant="ghost" size="icon" className="size-11" disabled={busy} onClick={onClose} aria-label={t("关闭")}><X aria-hidden="true" /></Button></div>}
    <Preview wide={wide} name={name} look={look} template={picked} />
    <div className="flex min-h-0 flex-col">
      {wide && <div className="px-6 pt-5 pb-3 pr-12">{title}{description}</div>}
      <div className={`flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto ${wide ? "px-6 pb-4" : "px-4 pt-4 pb-4"}`}>
        {nameBox}
        <TemplateChips templates={templates} picked={picked} onPick={setPicked} disabled={busy} />
        <div className="flex flex-col gap-3" data-testid="new-bot-look">
          <div className="flex items-center justify-between gap-3">
            <p className="text-small font-medium text-ink"><span aria-hidden="true" className={stepNo}>3</span>{t("形状与颜色")}</p>
            <Button type="button" variant="outline" size="sm" className="max-sm:h-11" disabled={busy} onClick={() => setLook(randomLook())} data-testid="new-bot-reroll"><Shuffle aria-hidden="true" />{t("换一个")}</Button>
          </div>
          <LookPicker look={look} onChange={setLook} disabled={busy} compact name="new-bot" testidPrefix="new-bot-" />
        </div>
      </div>
      <div className="flex flex-col gap-3 border-t border-line px-4 py-3 sm:px-6">
        {failure !== null && <ErrorBar error={failure} onRetry={() => void submit()} retrying={busy} />}
        <p className="text-caption text-muted-foreground">{picked ? t("模板只预填空着的头衔、说明和工具范围。") : ""}{t("关注公司、模型、工具、技能和通知上限，创建后都在 bot 设置里改。")}</p>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" className="max-sm:h-11" disabled={busy} onClick={onClose}>{t("取消")}</Button>
          <StatefulButton type="submit" phase={busy ? "loading" : "idle"} disabled={!finalName && !busy} className="max-sm:h-11" data-testid="new-bot-create">{t("创建")}</StatefulButton>
        </div>
      </div>
    </div>
  </form>;
}

/** Step 2: the templates the server offers, as chips; one is on at most, and pressing it again takes it off. */
function TemplateChips({ templates, picked, onPick, disabled }: { templates: BotTemplate[] | null; picked: BotTemplate | null; onPick: (template: BotTemplate | null) => void; disabled: boolean }) {
  const { t } = useLocale();
  return <div role="group" aria-labelledby="new-bot-template-label" className="flex flex-col gap-2" data-testid="new-bot-templates">
    <p id="new-bot-template-label" className="text-small font-medium text-ink"><span aria-hidden="true" className={stepNo}>2</span>{t("模板（可选）")}</p>
    {templates === null ? <div className="flex gap-1.5"><Skeleton className="h-8 w-20 rounded-sm" /><Skeleton className="h-8 w-20 rounded-sm" /><Skeleton className="h-8 w-20 rounded-sm" /></div>
      : templates.length === 0 ? <p className="text-caption text-muted-foreground">{t("模板暂时读不到，只填名字也能创建。")}</p>
        : <div className="flex flex-wrap gap-1.5">{templates.map(template => <button key={template.id} type="button" disabled={disabled} aria-pressed={picked?.id === template.id} data-template={template.id}
          onClick={() => onPick(picked?.id === template.id ? null : template)}
          className="inline-flex min-h-8 items-center rounded-sm border border-line bg-surface px-2.5 py-1 text-small text-ink outline-none select-none hover:bg-sunken focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-not-allowed disabled:opacity-55 aria-pressed:border-brand aria-pressed:bg-brand-soft aria-pressed:font-medium max-sm:min-h-11">
          {t(template.label)}</button>)}</div>}
    {picked?.description && <FieldDescription>{t(picked.description)}</FieldDescription>}
  </div>;
}

/** The large preview (L tier: the live body of the chat, with the personality the template gives) and what it is: the name so far, and the archetype with its line. */
function Preview({ wide, name, look, template }: { wide: boolean; name: string; look: BloubLook; template: BotTemplate | null }) {
  const { t } = useLocale();
  const bot = useMemo(() => previewBot(template), [template?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const persona = usePersona(bot);
  return <div data-testid="new-bot-preview" data-archetype={persona.archetype} className={`flex flex-col items-center justify-center gap-2 bg-sunken text-center ${wide ? "px-5 py-8" : "px-4 py-4"}`}>
    <BotPresence avatar={DEFAULT_AVATAR} look={look} name={bot.name} seed={bot.id} arrivalKey="new-bot-preview" size={wide ? BOT_AVATAR_SIZE.createHero : BOT_AVATAR_SIZE.hero} chatState="idle" messages={[]} bot={bot} />
    <p data-testid="new-bot-preview-name" className="mt-2 max-w-full truncate text-body font-semibold text-ink">{name.trim() || t("新 bot")}</p>
    <p className="text-caption text-muted-foreground">{t("性格原型")} · <strong data-testid="new-bot-archetype" className="font-medium text-ink">{t(ARCHETYPE_NAMES[persona.archetype])}</strong></p>
    {wide && <p className="max-w-[200px] text-caption text-muted-foreground">{t(ARCHETYPE_HINTS[persona.archetype])}</p>}
  </div>;
}
