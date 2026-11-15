import { useEffect, useState } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { ErrorBar } from "@/components/state/ErrorBar";
import { Skeleton } from "@/components/state/Skeleton";
import { EmptyState } from "@/components/state/EmptyState";
import { updateBot, type Bot } from "../../api/bots";
import { listSkills, type Skill } from "../../api/skills-core";
import { message } from "../../bot-message";
import { useLocale } from "../../i18n";
import { toggleUsual } from "../../bot-form-items.mjs";
import { usableSkills } from "../../skill-items.mjs";

/** 常用技能: a checklist of the enabled active skills, saved on its own at each tick (the bot PATCH `skills`: the request is the old one). */
export function SkillsSection({ bot, onSaved }: { bot: Bot; onSaved: (bot: Bot) => void }) {
  const { t } = useLocale();
  const [skills, setSkills] = useState<Skill[] | null>(null), [busy, setBusy] = useState(false), [status, setStatus] = useState(""), [attempt, setAttempt] = useState(0);
  const [usual, setUsual] = useState<string[]>(bot.skills ?? []);
  useEffect(() => { setUsual(bot.skills ?? []); }, [bot.skills]);
  useEffect(() => {
    const ctrl = new AbortController();
    setStatus("");
    listSkills(ctrl.signal).then(d => setSkills(d.skills)).catch(err => { if (!ctrl.signal.aborted) setStatus(message(err, t("技能暂时无法读取。"))); });
    return () => ctrl.abort();
  }, [attempt]); // eslint-disable-line react-hooks/exhaustive-deps
  const options = usableSkills(skills ?? []);
  async function toggle(id: string) {
    setBusy(true); setStatus("");
    try { const next = await updateBot(bot.id, { skills: toggleUsual(usual, id) }); setUsual(next.skills ?? []); onSaved(next); } catch (err) { setStatus(message(err, t("保存失败，请重试。"))); } finally { setBusy(false); }
  }
  return <div data-testid="skills-list" className="grid gap-3">
    <p className="text-small text-muted-foreground">{t("常用技能排在列表前面，也排在「/」菜单前面。")} {t("勾选即保存。")}</p>
    {skills === null && !status ? <div className="grid gap-2" aria-busy="true"><Skeleton className="h-8" /><Skeleton className="h-8" /></div>
      : options.length === 0 && !status ? <EmptyState title={t("还没有可用的技能。")} />
      : <ul className="m-0 grid list-none gap-1 p-0">{options.map(skill => <li key={skill.id} className="flex min-h-9 items-start gap-3 rounded-sm px-1 py-1 max-md:min-h-11">
        <Checkbox id={`skill-${skill.id}`} className="mt-0.5" checked={usual.includes(skill.id)} disabled={busy} onCheckedChange={() => void toggle(skill.id)} />
        <label htmlFor={`skill-${skill.id}`} className="min-w-0 flex-1 cursor-pointer text-small text-ink">{skill.name}{skill.description && <span className="text-muted-foreground"> · {skill.description}</span>}</label>
      </li>)}</ul>}
    {status && <ErrorBar message={status} onRetry={skills === null ? () => setAttempt(n => n + 1) : undefined} />}
  </div>;
}
