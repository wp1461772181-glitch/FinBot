import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ErrorBar } from "@/components/state/ErrorBar";
import { confirm } from "@/components/state/confirm";
import { notify } from "@/components/state/notify";
import { LegacyFrame } from "../../LegacyFrame";
import { TaskManager } from "../../BotRoutines";
import { deleteBot } from "../../api/bots-admin";
import { updateBot, type Bot } from "../../api/bots";
import { message } from "../../bot-message";
import { useLocale } from "../../i18n";
import { motionOff } from "../../motion-store.mjs";
import { paths } from "../../routes.mjs";
import { SECTIONS, draftOf, fieldsToSave, hasChanges, sectionFromSearch, sectionsChanged, validate, type BotDraft, type SectionId } from "../../bot-settings-form.mjs";
import { useNarrowViewport } from "@/components/ui/sidebar";
import { FocusFields, ModelFields, NotifyCapField, ProfileFields, ToolFields } from "./FormSections";
import { LookSection } from "./LookSection";
import { SaveBar } from "./SaveBar";
import { SettingsSection } from "./Section";
import { SkillsSection } from "./SkillsSection";
import { TelegramPanel } from "./TelegramPanel";
import { useBotOptions } from "./use-bot-options";
import { useLeaveGuard } from "./use-leave-guard";

const HINTS: Partial<Record<SectionId, string>> = {
  look: "外形（形状、颜色、头像）随保存栏保存；性格即改即存，只存在这个浏览器里。",
  routines: "这个 bot 的任务和最近的运行；任务的改动当场保存。",
};

/** The bot settings page (design 4.3): a section list on the left and the sections in one column (a folding column on a phone), one save bar for what is not saved at once. */
export default function BotSettingsPage({ bot, others, onChanged, onDeleted }: { bot: Bot; others: ReadonlyArray<Bot>; onChanged: () => void; onDeleted: () => void }) {
  const { t } = useLocale();
  const options = useBotOptions();
  const narrow = useNarrowViewport(); // the shell's own breakpoint (1024): below it the sidebar is the tab bar and the sections fold
  const location = useLocation(), [, setParams] = useSearchParams();

  // `server` is the bot as the server holds it (after a save, what the save answered); the draft is the form.
  const [server, setServer] = useState(bot), [draft, setDraft] = useState<BotDraft>(() => draftOf(bot));
  useEffect(() => { setServer((now) => (now.updated_at && bot.updated_at && bot.updated_at < now.updated_at ? now : bot)); }, [bot]);
  const [saving, setSaving] = useState(false), [saveError, setSaveError] = useState(""), [epoch, setEpoch] = useState(0);
  const dirty = hasChanges(draft, server);
  const unsaved = useMemo(() => sectionsChanged(draft, server), [draft, server]);
  const errors = validate(draft);
  const { allowLeave } = useLeaveGuard(dirty);

  async function save() {
    setSaving(true); setSaveError("");
    try {
      const next = await updateBot(bot.id, fieldsToSave(draft, server));
      setServer(next); setDraft(draftOf(next)); onChanged();
      notify.success(t("已保存。下一轮按新设置运行。"), { id: "bot-settings-saved" });
    } catch (err) { setSaveError(message(err, t("保存失败，请重试。"))); throw err; } finally { setSaving(false); }
  }
  function discard() { setDraft(draftOf(server)); setSaveError(""); setEpoch((n) => n + 1); }

  // Which section is shown: the address says (`?section=`), the nav and the scroll keep it up to date; a refresh stays on it.
  const requested = sectionFromSearch(location.search);
  const [active, setActive] = useState<SectionId>(requested);
  const [open, setOpen] = useState<Set<SectionId>>(() => new Set([requested]));
  const spyLocked = useRef(false);
  const remember = useCallback((id: SectionId) => setParams((prev) => { const next = new URLSearchParams(prev); next.set("section", id); return next; }, { replace: true }), [setParams]);
  const scrollTo = (id: SectionId) => requestAnimationFrame(() => document.getElementById(`section-${id}`)?.scrollIntoView({ block: "start", behavior: motionOff() ? "auto" : "smooth" }));
  function go(id: SectionId) {
    setActive(id); spyLocked.current = true; remember(id);
    setOpen((now) => new Set(now).add(id));
    scrollTo(id);
  }
  // An address that names a section scrolls to it, and the list keeps that choice (as after a click) until the reader scrolls by hand.  The content above the
  // section is still arriving (the options, the personality studio): the page lines the section up again as the column grows, for the first few seconds or
  // until a hand is on the scroll.
  useEffect(() => {
    if (requested === "profile") return;
    spyLocked.current = true;
    const target = () => document.getElementById(`section-${requested}`);
    const align = () => { if (spyLocked.current) target()?.scrollIntoView({ block: "start", behavior: "auto" }); };
    const column = target()?.parentElement;
    const watch = column && typeof ResizeObserver !== "undefined" ? new ResizeObserver(align) : null;
    watch?.observe(column as Element);
    const frame = requestAnimationFrame(align);
    const stop = () => watch?.disconnect();
    const timer = window.setTimeout(stop, 4000);
    window.addEventListener("wheel", stop, { passive: true }); window.addEventListener("touchmove", stop, { passive: true }); window.addEventListener("keydown", stop);
    return () => { cancelAnimationFrame(frame); window.clearTimeout(timer); stop(); window.removeEventListener("wheel", stop); window.removeEventListener("touchmove", stop); window.removeEventListener("keydown", stop); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // While the reader scrolls, the nav follows the section at the top of the page (and the address with it).  After a click on the nav the
  // click's choice stands until the reader scrolls by hand: the last sections are too short to reach the top and would otherwise take it back.
  useEffect(() => {
    if (narrow) return;
    let frame = 0;
    const unlock = () => { spyLocked.current = false; };
    const follow = () => {
      if (spyLocked.current) return;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const atEnd = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2;
        let current: SectionId = SECTIONS[0].id as SectionId;
        for (const section of SECTIONS) { const node = document.getElementById(`section-${section.id}`); if (node && node.getBoundingClientRect().top <= 120) current = section.id as SectionId; }
        if (atEnd && window.scrollY > 0) current = SECTIONS[SECTIONS.length - 1].id as SectionId;
        setActive((now) => { if (now !== current) remember(current); return current; });
      });
    };
    window.addEventListener("wheel", unlock, { passive: true }); window.addEventListener("touchmove", unlock, { passive: true }); window.addEventListener("keydown", unlock);
    window.addEventListener("scroll", follow, { passive: true });
    return () => { cancelAnimationFrame(frame); window.removeEventListener("wheel", unlock); window.removeEventListener("touchmove", unlock); window.removeEventListener("keydown", unlock); window.removeEventListener("scroll", follow); };
  }, [narrow, remember]);

  const [deleteError, setDeleteError] = useState(""), [deleting, setDeleting] = useState(false);
  async function remove() {
    if (!(await confirm({ title: `${t("删除")} ${bot.name}？`, description: t("它的设置会删掉，这条线的对话归档保留；其他 bot 不受影响。"), confirmLabel: t("删除"), cancelLabel: t("取消"), tone: "danger", hold: true }))) return;
    setDeleting(true); setDeleteError("");
    try { await deleteBot(bot.id); allowLeave.current = true; onDeleted(); } catch (err) { setDeleteError(message(err, t("删除失败，请重试。"))); setDeleting(false); }
  }

  const form = { draft, update: setDraft, disabled: saving };
  const body = (id: SectionId) => {
    switch (id) {
      case "profile": return <ProfileFields {...form} nameError={errors.name} isDefault={bot.is_default} />;
      case "focus": return <FocusFields key={epoch} {...form} bot={server} />;
      case "look": return <LookSection {...form} bot={server} others={others} studio={!narrow || open.has("look")} />;
      case "model": return <ModelFields {...form} bot={server} catalog={options.catalog} />;
      case "tools": return <ToolFields {...form} tools={options.tools} loaded={options.loaded} />;
      case "skills": return <SkillsSection bot={bot} onSaved={onChanged} />;
      case "routines": return <LegacyFrame><div className="agent-page" data-testid="bot-routines"><TaskManager botId={bot.id} /></div></LegacyFrame>;
      case "notify": return <><NotifyCapField {...form} /><TelegramPanel bot={bot} /></>;
      case "danger": return <div className="grid gap-3">
        {bot.is_default ? <p data-testid="default-undeletable" className="text-small text-muted-foreground">{t("默认 bot 可以改名和说明，不能删除。没指明给谁的消息进它。")}</p>
          : <p className="text-small text-muted-foreground">{t("它的设置会删掉，这条线的对话归档保留；其他 bot 不受影响。")}</p>}
        <div><Button type="button" variant="destructive" data-testid="delete-bot" disabled={bot.is_default || deleting} aria-describedby={bot.is_default ? "default-undeletable" : undefined} onClick={() => void remove()}>{t("删除这个 bot")}</Button></div>
        {deleteError && <ErrorBar message={deleteError} />}
      </div>;
    }
  };

  return <main data-slot="bot-settings" data-testid="bot-settings-page" data-default={bot.is_default || undefined} aria-labelledby="bot-settings-title" className="mx-auto w-full max-w-[1040px] px-4 pt-4 pb-10 lg:px-6 lg:pt-6">
    <header className="mb-5 grid gap-1">
      <Link to={bot.is_default ? paths.chat() : paths.chat(bot.id)} data-testid="back-to-chat" className="inline-flex min-h-9 w-fit items-center gap-1.5 rounded-sm text-small text-muted-foreground outline-none hover:text-ink focus-visible:ring-2 focus-visible:ring-ring max-md:min-h-11">
        <ArrowLeft aria-hidden="true" className="size-4" />{t("返回对话")}
      </Link>
      <h1 id="bot-settings-title" className="text-title-m text-ink">{bot.name} · {t("设置")}</h1>
    </header>
    {options.error && <ErrorBar message={options.error} onRetry={options.retry} className="mb-4" />}
    <div className="grid gap-8 lg:grid-cols-[176px_minmax(0,720px)]">
      {!narrow && <nav aria-label={t("设置分节")} data-testid="section-nav" className="sticky top-6 self-start">
        <ul className="m-0 grid list-none gap-0.5 p-0">
          {SECTIONS.map((section) => <li key={section.id}>
            <a href={`#section-${section.id}`} data-section-link={section.id} aria-current={active === section.id ? "true" : undefined}
              onClick={(event) => { event.preventDefault(); go(section.id as SectionId); }}
              className="flex min-h-9 items-center gap-2 rounded-sm px-2.5 text-small text-ink-2 outline-none hover:bg-accent hover:text-ink focus-visible:ring-2 focus-visible:ring-ring aria-[current=true]:bg-accent aria-[current=true]:font-medium aria-[current=true]:text-ink">
              <span className="min-w-0 flex-1">{t(section.label)}</span>
              {unsaved.has(section.id as SectionId) && <span aria-hidden="true" className="size-2 rounded-full bg-brand" />}
            </a>
          </li>)}
        </ul>
      </nav>}
      <div className="min-w-0">
        {SECTIONS.map((section) => <SettingsSection key={section.id} id={section.id as SectionId} title={t(section.label)} hint={HINTS[section.id as SectionId] && t(HINTS[section.id as SectionId] as string)} narrow={narrow}
          open={open.has(section.id as SectionId)} onOpenChange={(next) => { setOpen((now) => { const copy = new Set(now); if (next) copy.add(section.id as SectionId); else copy.delete(section.id as SectionId); return copy; }); if (next) { setActive(section.id as SectionId); remember(section.id as SectionId); } }}
          unsaved={unsaved.has(section.id as SectionId)}>{body(section.id as SectionId)}</SettingsSection>)}
      </div>
    </div>
    {(dirty || saveError) && <SaveBar error={saveError} canSave={dirty && !saving && Object.keys(errors).length === 0} saving={saving} onDiscard={discard} onSave={save} />}
  </main>;
}
