import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { FileUp, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/state/EmptyState";
import { ErrorBar } from "@/components/state/ErrorBar";
import { DelayedSkeleton, Skeleton } from "@/components/state/Skeleton";
import { confirm } from "@/components/state/confirm";
import { errorReason } from "@/components/state/error-message";
import { notify } from "@/components/state/notify";
import { copySkill, createSkill, deleteSkill, exportSkill, importSkill, previewSkillImport, setSkillEnabled, updateSkill } from "../../../api/skills-admin";
import { listSkills, type Skill } from "../../../api/skills-core";
import { useLocale } from "../../../i18n";
import { paths } from "../../../routes.mjs";
import { skillGroups } from "../../../skill-items.mjs";
import { useLoad } from "../../use-load";
import { ImportDrawer } from "./ImportDrawer";
import { SkillCard } from "./SkillCard";
import { SkillDrawer } from "./SkillDrawer";
import { exportName, isWriteLevel, linkTarget, saveOf, type SkillEditor } from "./skill-form.mjs";

/**
 * 技能 (#/assistant/skills, design 4.11): recipes (steps and the tools they may use), never code.  Cards in three groups (drafts the agent wrote, built-ins, the owner's own and imported ones), a switch on each active one,
 * 导出 / 复制 / 删除 in 「…」; new and edit are one side drawer, import is another (paste or choose a file, preview, then import).  `skillId` is the skill an address (/assistant/skills/<id>, which a draft links to) asks to open.
 * Every request is the old page's (src/api/skills-admin.ts, unchanged): the same bodies, which skill-form.mjs makes.
 */
export function SkillsPage({ skillId = null }: { skillId?: string | null }) {
  const { t } = useLocale();
  const navigate = useNavigate();
  const data = useLoad(signal => listSkills(signal));
  const skills = data.data?.skills ?? null;
  const writes = useMemo(() => new Set((data.data?.tools ?? []).filter(tool => isWriteLevel(tool.level)).map(tool => tool.name)), [data.data]);
  const [actionError, setActionError] = useState<unknown>(null);
  const [notFound, setNotFound] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [flipped, setFlipped] = useState<Record<string, boolean>>({});
  const [editor, setEditor] = useState<{ open: boolean; skill: Skill | null }>({ open: false, skill: null });
  const [importing, setImporting] = useState(false);
  const opener = useRef<HTMLElement | null>(null);
  const newButton = useRef<HTMLButtonElement>(null), importButton = useRef<HTMLButtonElement>(null);
  const returnFocus = (fallback: React.RefObject<HTMLButtonElement | null>) => () => { const back = opener.current?.isConnected ? opener.current : fallback.current; back?.focus(); };

  // An address that names a skill opens its editor once the list is in (a built-in has none; a missing one is said).  Once per address: closing the drawer takes the address back to the list.
  const opened = useRef<string | null>(null);
  useEffect(() => {
    if (!skillId) { opened.current = null; setNotFound(false); return; }
    if (!skills || opened.current === skillId) return;
    opened.current = skillId;
    const target = linkTarget(skills, skillId);
    setNotFound(target.kind === "missing");
    if (target.kind === "editor") { opener.current = null; setImporting(false); setEditor({ open: true, skill: target.skill }); }
  }, [skillId, skills]);

  const groups = skillGroups(skills ?? []) as { drafts: Skill[]; builtin: Skill[]; mine: Skill[] };
  const openEditor = (skill: Skill | null, from: HTMLElement | null) => { opener.current = from; setImporting(false); setEditor({ open: true, skill }); };
  const closeEditor = (open: boolean) => { if (open) return; setEditor(current => ({ ...current, open: false })); if (skillId) navigate(paths.assistant("skills")); };
  const here = () => (document.activeElement instanceof HTMLElement ? document.activeElement : null);

  async function act(id: string, work: () => Promise<unknown>, done?: string) {
    setBusy(id); setActionError(null);
    try { await work(); await data.reload(); if (done) notify.success(t(done), { id: "skills:done" }); }
    catch (error) { setActionError(error); }
    finally { setBusy(null); }
  }
  async function toggle(skill: Skill, enabled: boolean) {
    setFlipped(current => ({ ...current, [skill.id]: enabled }));
    await act(skill.id, () => setSkillEnabled(skill.id, enabled));
    setFlipped(({ [skill.id]: _gone, ...rest }) => rest);
  }
  async function remove(skill: Skill, from: HTMLElement | null) {
    const yes = await confirm({ ...(from ? { returnFocus: from } : {}), title: `${t("删除")} ${skill.name}？`, description: t("删除后这个技能不能恢复。"), confirmLabel: t("删除"), cancelLabel: t("取消"), tone: "danger", hold: true });
    if (yes) await act(skill.id, () => deleteSkill(skill.id), "已删除。");
  }
  const download = (skill: Skill) => act(skill.id, async () => {
    const text = await exportSkill(skill.id);
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = exportName(skill); document.body.append(link); link.click(); link.remove(); URL.revokeObjectURL(url);
  });
  async function save(editorValue: SkillEditor) {
    const request = saveOf(editorValue);
    if (request.create) await createSkill(request.body); else await updateSkill(request.id, request.body);
    await data.reload();
    notify.success(t("已保存。"), { id: "skills:done" });
    closeEditor(false);
  }
  async function runImport(markdown: string) {
    await importSkill(markdown);
    await data.reload();
    notify.success(t("已导入。"), { id: "skills:done" });
    setImporting(false);
  }

  const card = (skill: Skill) => <li key={skill.id}>
    <SkillCard skill={skill} writes={writes} enabled={flipped[skill.id] ?? skill.enabled} busy={busy === skill.id}
      onToggle={enabled => void toggle(skill, enabled)} onEdit={from => openEditor(skill, from)} onCopy={() => void act(skill.id, () => copySkill(skill.id), "已复制，可以在「我的」里编辑。")} onExport={() => void download(skill)} onDelete={from => void remove(skill, from)} />
  </li>;
  const group = (key: string, title: string, list: Skill[], note?: string) => list.length > 0 && <section key={key} data-testid="skill-group" data-group={key} aria-label={t(title)} className="flex min-w-0 flex-col gap-2.5">
    <div className="flex flex-col gap-0.5"><h2 className="text-title-s text-ink">{t(title)}<span className="ml-2 font-mono text-caption font-normal text-muted-foreground">{list.length}</span></h2>{note && <p data-testid="skill-group-note" className="text-small text-muted-foreground">{t(note)}</p>}</div>
    <ul className="m-0 grid list-none gap-3 p-0 sm:grid-cols-2 xl:grid-cols-3">{list.map(card)}</ul>
  </section>;

  return <main data-testid="skills-page" aria-labelledby="skills-title" className="mx-auto flex w-full min-w-0 max-w-[1100px] flex-1 flex-col gap-5 p-4 lg:p-6">
    <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
      <div className="flex min-w-0 flex-col gap-1">
        <h1 id="skills-title" className="text-title-m text-ink">{t("技能")}</h1>
        <p data-testid="skills-intro" className="max-w-2xl text-small text-muted-foreground">{t("技能是做事的步骤，不是代码。在 bot 对话里输入「/技能名」使用；技能里的工具清单只对旧流程的 bot 起限制作用，写操作照样要你确认。")}</p>
      </div>
      <div className="flex items-center gap-2">
        <Button ref={importButton} type="button" variant="outline" data-testid="skill-import-open" className="max-sm:h-11" onClick={() => { opener.current = here(); setEditor(current => ({ ...current, open: false })); setImporting(true); }}><FileUp aria-hidden="true" />{t("导入")}</Button>
        <Button ref={newButton} type="button" data-testid="skill-new" className="max-sm:h-11" onClick={() => openEditor(null, here())}><Plus aria-hidden="true" />{t("新建技能")}</Button>
      </div>
    </header>
    {notFound && <ErrorBar message={t("这个技能不存在。")} />}
    {actionError != null && <ErrorBar error={actionError} />}
    {data.error != null && <ErrorBar error={data.error} onRetry={() => void data.reload()} retrying={data.loading} />}
    {!skills && data.loading && <DelayedSkeleton><div role="status" aria-busy="true" data-testid="skills-skeleton" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3"><span className="sr-only">{t("正在读取")}</span>{[0, 1, 2].map(i => <Skeleton key={i} className="h-40 w-full" />)}</div></DelayedSkeleton>}
    {skills && skills.length === 0 && <div data-testid="skills-empty" className="rounded-md border border-line bg-surface"><EmptyState title={t("还没有技能。")} action={{ label: t("新建技能"), onClick: () => openEditor(null, newButton.current) }} /></div>}
    {skills && skills.length > 0 && <div className="flex min-w-0 flex-col gap-6">
      {group("drafts", "草稿", groups.drafts, "Agent 起草的草稿：核对后保存才会生效。")}
      {group("builtin", "内置", groups.builtin)}
      {group("mine", "我的 / 导入的", groups.mine)}
    </div>}
    <SkillDrawer open={editor.open} onOpenChange={closeEditor} skill={editor.skill} tools={data.data?.tools ?? []} save={save} returnFocus={returnFocus(newButton)} />
    <ImportDrawer open={importing} onOpenChange={setImporting} preview={previewSkillImport} doImport={runImport} returnFocus={returnFocus(importButton)} />
  </main>;
}
