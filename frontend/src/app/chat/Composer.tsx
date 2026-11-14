// legacy markup, moved as-is in P3.1; restyled in P3.2–P3.4
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from "react";
import { listSkills, type Skill, getChatMode, type Bot } from "../../api";
import { slashMatches } from "../../skill-items.mjs";
import { useLocale } from "../../i18n";
import { ContextMeter } from "../../ContextMeter";
import { GuestComposerNotice } from "../../components/GuestComposerNotice";
import { SendIcon } from "./icons";
import { useChat } from "./ChatSessionProvider";

export function Composer({ bot, draftBox }: { bot?: Bot | null; draftBox: RefObject<HTMLTextAreaElement | null> }) {
  const { t } = useLocale(), c = useChat(), mode = getChatMode();
  const composerForm=useRef<HTMLFormElement>(null);
  // The composer grows with what is typed (up to its own cap) and shrinks back after sending.
  useLayoutEffect(()=>{const box=draftBox.current;if(!box)return;box.style.height="auto";box.style.height=`${Math.min(box.scrollHeight,220)}px`},[c.draft]);
  // The "/" picker: a draft like "/财" (no space yet) lists the bot's matching enabled skills, its usual ones first.
  const [skillList,setSkillList]=useState<Skill[]|null>(null),[pickIndex,setPickIndex]=useState(0),[pickClosed,setPickClosed]=useState(false);
  const slashActive=Boolean(bot)&&mode==="personal"&&c.draft.startsWith("/")&&!/\s/.test(c.draft);
  useEffect(()=>{if(!slashActive||skillList)return;let live=true;listSkills().then(d=>{if(live)setSkillList(d.skills)}).catch(()=>{if(live)setSkillList([])});return()=>{live=false}},[slashActive,skillList]);
  const slashItems=slashActive&&!pickClosed?slashMatches(skillList??[],c.draft,bot?.skills??[]):[];
  useEffect(()=>{setPickIndex(0);setPickClosed(false)},[c.draft]);
  function pickSkill(skill:Skill){c.setDraft(`/${skill.name} `);draftBox.current?.focus()}
  function onComposerKey(event:ReactKeyboardEvent<HTMLTextAreaElement>){
    if(slashItems.length){
      if(event.key==="ArrowDown"||event.key==="ArrowUp"){event.preventDefault();setPickIndex(i=>(i+(event.key==="ArrowDown"?1:-1)+slashItems.length)%slashItems.length);return}
      if((event.key==="Enter"||event.key==="Tab")&&!event.shiftKey&&!event.nativeEvent.isComposing){event.preventDefault();pickSkill(slashItems[Math.min(pickIndex,slashItems.length-1)]);return}
      if(event.key==="Escape"){event.preventDefault();setPickClosed(true);return}
    }
    // Enter sends, Shift+Enter breaks the line; a key that confirms an IME composition is left alone.
    if(event.key!=="Enter"||event.shiftKey||event.nativeEvent.isComposing||event.keyCode===229)return;
    event.preventDefault();
    if(c.draft.trim())composerForm.current?.requestSubmit();
  }
  const sendDisabled=Boolean(c.archiveView)||c.restoring||!c.verified||!c.draft.trim()||c.state==="sending"||c.state==="testing";
  const busy=c.state==="sending"||c.state==="testing"||c.restoring;
  return <>
        {!c.verified ? <GuestComposerNotice /> : <form ref={composerForm} className="agent-composer" onSubmit={c.send}>
          <label htmlFor="agent-draft">{t("输入消息")}</label>
          {slashItems.length>0&&<ul className="skill-picker" id="skill-picker" role="listbox" aria-label={t("技能")}>{slashItems.map((skill,i)=><li key={skill.id} id={`skill-option-${i}`} role="option" aria-selected={i===Math.min(pickIndex,slashItems.length-1)} onMouseDown={e=>{e.preventDefault();pickSkill(skill)}}><strong>/{skill.name}</strong><small>{skill.description}</small></li>)}</ul>}
          <textarea id="agent-draft" ref={draftBox} {...(slashItems.length>0?{role:"combobox","aria-expanded":true,"aria-controls":"skill-picker","aria-activedescendant":`skill-option-${Math.min(pickIndex,slashItems.length-1)}`}:{})} rows={1} value={c.draft} onChange={e => c.setDraft(e.target.value)} onKeyDown={onComposerKey} maxLength={4000} disabled={Boolean(c.archiveView)||c.restoring||!c.verified || c.state === "sending" || c.state === "testing"} placeholder={bot?`${t("给")} ${bot.name} ${t("发消息…")}`:t(c.verified?"给 Agent 发消息…":"登录个人聊天后才能对话")} />
          <div className="agent-composer-bottom">
            <span className="agent-composer-hint">{t("Enter 发送，Shift+Enter 换行")} · {t("模型和 key 只在服务器上，浏览器不保存 key。")}</span>
            <div className="agent-composer-tools">
              <ContextMeter conversationId={c.conversationId} botId={c.bot?.id??null} onCompact={()=>void c.compactNow("")} refreshKey={`${c.messages.length}:${c.state==="sending"?"sending":"settled"}`} />
              
              {busy&&<button className="agent-stop" type="button" onClick={c.cancel}>{t("取消请求")}</button>}
              <button className="agent-send" type="submit" aria-label={c.state === "sending" ? t("等待回复…") : t("发送")} title={t("发送")} disabled={sendDisabled}><SendIcon /></button>
            </div>
          </div>
        </form>}
  </>;
}
