// legacy markup, moved as-is in P3.1; restyled in P3.2–P3.4
import { Fragment, useEffect, useRef, useState, type RefObject } from "react";
import { isTaskPostHead } from "../../task-posts.mjs";
import { chatTurnPreviews } from "../../chat-thread.mjs";
import { QuestionRail } from "../../QuestionRail";
import { useLocale } from "../../i18n";
import { noticesAfter } from "../../context-usage.mjs";
import { isActiveClarification } from "../../chat-clarification.mjs";
import { toolLabel } from "../../agent-tool-labels.mjs";
import { ThinkingPanel } from "../../ThinkingPanel";
import { CopyIcon, CheckIcon, ThumbUpIcon, ThumbDownIcon } from "./icons";
import { ClarificationCard } from "./ClarificationCard";
import { MessageBody, CitationDrawer, useCitations } from "./Citations";
import { useChat } from "./ChatSessionProvider";

function toolResultSummary(value:unknown):string {
  if (!value || typeof value!=="object") return "";
  const result=value as {data?:unknown;job_status?:unknown;status?:unknown;error_code?:unknown};
  if (typeof result.job_status==="string") return `任务 ${result.job_status.slice(0,32)}`;
  if (Array.isArray(result.data)) return `${result.data.length} 条结果`;
  if (typeof result.error_code==="string") return result.error_code.slice(0,48);
  return "";
}

export function Thread({ draftBox }: { draftBox: RefObject<HTMLTextAreaElement | null> }) {
  const { t } = useLocale(), c = useChat(), transcriptRef = useRef<HTMLElement>(null);
  const turnPreviews=chatTurnPreviews(c.messages);
  const railTurns=turnPreviews.map(turn=>({...turn,turnId:c.messages[turn.userIndex]?.turn_id}));
  const followTranscript=useRef(true);
  useEffect(()=>{const el=transcriptRef.current;if(!el)return;const update=()=>{followTranscript.current=el.scrollHeight-el.scrollTop-el.clientHeight<90};el.addEventListener("scroll",update,{passive:true});return()=>el.removeEventListener("scroll",update)},[]);
  const [copied,setCopied]=useState<number|null>(null),[copyStatus,setCopyStatus]=useState(""),[,setFeedbackTick]=useState(0);
  const { citationDetails, openCitationTurn, setOpenCitationTurn, openCitationAt, showCitation } = useCitations();
  const [activeTurn,setActiveTurn]=useState(0);
  useEffect(()=>{const el=transcriptRef.current;if(!el)return;const update=()=>{const top=el.getBoundingClientRect().top;const turns=el.querySelectorAll<HTMLElement>(".agent-message.is-user");let active=0;turns.forEach((item,i)=>{if(item.getBoundingClientRect().top<=top+100)active=i});setActiveTurn(active)};el.addEventListener("scroll",update,{passive:true});update();return()=>el.removeEventListener("scroll",update)},[c.messages]);
  async function loadEarlierAtTop(){
    const el=transcriptRef.current; if(!el||!c.historyHasMore||c.loadingEarlier||c.archiveView)return;
    const height=el.scrollHeight, top=el.scrollTop;
    await c.loadEarlier();
    requestAnimationFrame(()=>{if(el)el.scrollTop=el.scrollHeight-height+top;});
  }
  async function copyAnswer(text:string,index:number){setCopied(null);setCopyStatus(t("正在复制…"));let timer:number|undefined;try{const clipboard=navigator.clipboard?.writeText(text);if(!clipboard)throw Error("clipboard_unavailable");await Promise.race([clipboard,new Promise<never>((_,reject)=>{timer=window.setTimeout(()=>reject(Error("clipboard_timeout")),1800)})]);setCopied(index);setCopyStatus(t("已复制"));}catch{setCopied(-index-1);setCopyStatus(t("复制失败；请选中回答后手动复制。"));const article=document.getElementById(`chat-message-${index}`);const range=document.createRange();if(article){range.selectNodeContents(article.querySelector(".markdown-body")??article);window.getSelection()?.removeAllRanges();window.getSelection()?.addRange(range);}}finally{if(timer)window.clearTimeout(timer);window.setTimeout(()=>{setCopied(null);setCopyStatus("")},3500)}}
  function feedbackOf(turnId:string):string{try{return localStorage.getItem(`market-evidence-agent:feedback:${turnId}`)??""}catch{return ""}}
  function giveFeedback(turnId:string,value:"up"|"down"){const key=`market-evidence-agent:feedback:${turnId}`;try{if(localStorage.getItem(key)===value)localStorage.removeItem(key);else localStorage.setItem(key,value)}catch{}setFeedbackTick(x=>x+1)}
  useEffect(() => {
    const transcript = transcriptRef.current;
    if (transcript&&followTranscript.current) transcript.scrollTop = transcript.scrollHeight;
  }, [c.messages, c.state]);
  const lastIndex=c.messages.length-1;
  return (
        <section ref={transcriptRef} className="agent-transcript" aria-live="polite" onScroll={e=>{if(e.currentTarget.scrollTop<32)void loadEarlierAtTop();}}>
          {!c.archiveView&&c.historyHasMore&&<div className="agent-earlier"><button type="button" className="secondary-action" onClick={()=>void loadEarlierAtTop()} disabled={c.loadingEarlier}>{c.loadingEarlier?t("正在加载更早消息…"):t("加载更早消息")}</button></div>}
          {c.restoring&&<p role="status">{t("正在恢复对话…")}</p>}
          {copyStatus&&<p className="copy-status" role="status">{copyStatus}</p>}
          {c.messages.length === 0 ? <div className="agent-welcome"><h2>{t("从一个问题开始")}</h2><p>{t(c.verified ? "连接已就绪，可以输入问题或选择下方建议。" : "登录个人聊天后才能对话：模型由服务器模型目录提供。")}</p><div>{["查看 AAPL 最近行情", "AAPL 已保存的最新财报有哪些", "可信度星级是什么"].map(x => <button type="button" key={x} onClick={() => c.setDraft(t(x))}>{t(x)} <span aria-hidden="true">↗</span></button>)}</div></div> :
          <div className="agent-thread-grid">
            <QuestionRail turns={railTurns} activeTurn={activeTurn} transcriptRef={transcriptRef} conversationId={c.conversationId} />
            <div className="agent-thread">{c.messages.map((m, i) => <Fragment key={i}><article data-turn-index={m.role==="user"?turnPreviews.findIndex(turn=>turn.userIndex===i):undefined} id={`chat-message-${i}`} className={`agent-message is-${m.role}${m.role==="user"&&isTaskPostHead(m.content)?" is-task-post":""}${i===lastIndex?" is-last":""}`}>
              {m.role === "assistant"&&<ThinkingPanel trace={m.trace} thinkingMs={m.thinking_ms} startedAt={m.started_at} running={i === lastIndex && c.state === "sending"} />}
              {m.role !== "user"&&<div className="agent-tool-badges">{m.reused_sources&&<span className="tool-badge status-complete">{t("复用已核实来源")}</span>}{!m.trace?.length&&m.tool_trace?.map((tool,j)=><span key={`${tool.name}-${j}`} className={`tool-badge status-${tool.status}`}>{t(toolLabel(tool.name))} · {t(tool.status === "complete" ? (tool.card ? "执行完成" : "已完成") : tool.status === "not_found" ? "没有匹配记录" : tool.status === "failed" ? "查询失败" : tool.status === "cancelled" ? "已取消" : tool.status === "submitted" ? "已提交" : "执行中")}{toolResultSummary(tool.result)&&` · ${toolResultSummary(tool.result)}`}</span>)}</div>}
              <MessageBody m={m} i={i} copied={copied} copyAnswer={copyAnswer} draftBox={draftBox} openCitationAt={openCitationAt} setOpenCitationTurn={setOpenCitationTurn} showCitation={showCitation} />
              {m.role==="assistant"&&m.clarification&&<ClarificationCard clarification={m.clarification} active={isActiveClarification(c.messages,i,Boolean(c.archiveView))&&!c.restoring&&c.verified&&c.state!=="sending"&&c.state!=="testing"} onChoose={value=>c.choose(value,m.clarification!.request_id)} onChooseMany={values=>c.chooseOptions(values,m.clarification!.request_id)} onReply={value=>c.replyToCard(value,m.clarification!.request_id)} />}
              {m.role === "assistant" && m.status && m.status !== "complete" && m.status !== "succeeded" && <small>{t(m.status === "cancelled" ? "本轮已取消，未生成完整回答。" : m.status === "waiting_for_input" ? "等待选择后继续" : m.status === "running" ? "任务运行中，可稍后查询状态" : m.status === "partially_succeeded" ? "部分来源可用；缺项已标出" : "本轮失败；已保留已生成内容。")}</small>}
              {m.role === "assistant"&&m.content&&<>
                <div className="agent-answer-actions">
                  <button type="button" className="agent-action-button" aria-label={copied===i?t("已复制"):copied===-i-1?t("复制失败"):t("复制回答")} title={t("复制回答")} onClick={()=>void copyAnswer(m.content,i)}>{copied===i?<CheckIcon />:<CopyIcon />}</button>
                  {m.turn_id&&(["up","down"] as const).map(value=>{const saved=feedbackOf(m.turn_id!);return <button type="button" key={value} className="agent-action-button" aria-pressed={saved===value} aria-label={value==="up"?t("有帮助"):t("没有帮助")} title={value==="up"?t("有帮助"):t("没有帮助")} onClick={()=>giveFeedback(m.turn_id!,value)}>{value==="up"?<ThumbUpIcon />:<ThumbDownIcon />}</button>})}
                  {copied===i&&<span className="agent-action-note" role="status">{t("已复制")}</span>}
                </div>
                <CitationDrawer m={m} i={i} openCitationTurn={openCitationTurn} citationDetails={citationDetails} showCitation={showCitation} />
              </>}
            </article>{m.role==="assistant"&&noticesAfter(c.notices,m.turn_id).map(notice=><details className="agent-compaction" key={`compaction-${notice.id}`}><summary>{t("已压缩")} {notice.turns} {t("轮")}{notice.focus?` · ${notice.focus}`:""}</summary><pre>{notice.summary||t("（摘要为空）")}</pre></details>)}</Fragment>)}</div>
          </div>}
        </section>
  );
}
