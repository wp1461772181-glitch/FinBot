// legacy markup, moved as-is in P3.1; restyled in P3.2–P3.4
import { useState } from "react";
import { type AgentChatMessage } from "../../api";
import { useLocale } from "../../i18n";
import { clarificationTitle } from "../../chat-clarification.mjs";

// What a confirmation card may show, in words.  The card used to print the raw field names of the
// tool arguments, so the user read "source_id: c2462639-…" and "title: analyze".
const TARGET_FIELD_LABELS:Record<string,string>={
  symbol:"公司代码",title:"材料",url:"链接",source_type:"来源类型",accession_number:"申报编号",
  form:"表单类型",days:"天数",max_tasks:"最多处理",decision_date:"决策日",kind:"类型",
  record_id:"记录",document_id:"文档",version_id:"版本",candidate_id:"候选",
  approved:"审核结果",saved_date:"知识库日期",web_date:"网页日期",source_refs:"来源",
};
const HIDDEN_TARGET_FIELDS=new Set(["source_id","record_id","document_id","version_id","candidate_id","source_refs"]);

const WRITE_CARDS = new Set(["write_confirmation", "confirm_write", "choose_write_action", "choose_revision_sources"]);

export function ClarificationCard({clarification,active,onChoose,onChooseMany,onReply}:{clarification:NonNullable<AgentChatMessage["clarification"]>;active:boolean;onChoose:(value:string)=>Promise<void>;onChooseMany:(values:string[])=>Promise<void>;onReply:(value:string)=>Promise<void>}) {
  const { t } = useLocale();
  const [reply,setReply]=useState("");
  const [picked,setPicked]=useState<string[]>([]);
  const options=clarification.options??[], limits=clarification.select??{min:1,max:options.length};
  const write=WRITE_CARDS.has(clarification.reason), confirm=["write_confirmation","confirm_write","choose_revision_sources"].includes(clarification.reason);
  const title=t(clarificationTitle(clarification));
  return <div className={`agent-clarification-card${write?" is-write":""}${active?"":" is-locked"}`} role="group" aria-label={title}>
    <strong>{title}</strong>
    {clarification.display?.agent_suggestion&&<p>{t("这是 agent 的建议，不是你的要求。批准后才会继续。")}</p>}
    {clarification.question&&<p>{clarification.question}</p>}
    {clarification.display&&<div className="agent-confirmation-details">
      <p><strong>{clarification.display.title}</strong></p>
      {clarification.display.saved_date&&<p>{t("知识库日期")}：{clarification.display.saved_date}</p>}
      {clarification.display.web_date&&<p>{t("网页日期")}：{clarification.display.web_date}</p>}
      {clarification.display.url&&<p><a href={clarification.display.url} target="_blank" rel="noopener noreferrer">{clarification.display.url}</a></p>}
      {clarification.display.targets?.map((target,index)=><p key={index}>{Object.entries(target).filter(([key])=>!HIDDEN_TARGET_FIELDS.has(key)).map(([key,value])=>`${t(TARGET_FIELD_LABELS[key]??key)}：${value}`).join(" · ")}</p>)}
      {clarification.display.alternative&&<p>{clarification.display.alternative}</p>}
      {write&&<small>{t("确认有效期为十分钟；改变目标需要重新确认。")}</small>}
    </div>}
    {options.length>0&&<fieldset className="agent-clarification-picks" disabled={!active}>
      {options.map(option=><label key={option.value}>
        <input type="checkbox" checked={picked.includes(option.value)}
          onChange={event=>setPicked(current=>event.target.checked?(current.length<limits.max?[...current,option.value]:current):current.filter(value=>value!==option.value))} />
        <span><span className="agent-pick-title">{option.label}</span>{option.detail&&<small>{option.detail}</small>}</span>
      </label>)}
      {active&&picked.length<limits.min&&<small className="agent-pick-hint">{t("至少勾选一份材料")}</small>}
    </fieldset>}
    <div className="agent-clarification-options">{clarification.choices.map((choice,index)=>{
      const cancel=/^cancel:/.test(choice.value);
      const ticks=options.length>0&&/^confirm:/.test(choice.value);
      const kind=write&&confirm&&index===0?"is-primary":write&&(cancel||(confirm&&index===clarification.choices.length-1))?"is-quiet":"";
      return <button type="button" className={kind} key={choice.value} disabled={!active||(ticks&&picked.length<limits.min)}
        onClick={()=>void (ticks?onChooseMany(picked):onChoose(choice.value))}>{t(choice.label)}</button>;
    })}</div>
    {!write&&<form className="agent-clarification-reply" onSubmit={event=>{event.preventDefault();if(active&&reply.trim())void onReply(reply)}}>
      <label>{t("手动输入")}<input value={reply} onChange={event=>setReply(event.target.value)} maxLength={4000} disabled={!active} placeholder={t("也可以输入自己的回答")} /></label>
      <button type="submit" disabled={!active||!reply.trim()}>{t("发送")}</button>
    </form>}
  </div>;
}
