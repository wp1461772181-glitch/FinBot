// legacy markup, moved as-is in P3.1; restyled in P3.2–P3.4
import { useState, type RefObject } from "react";
import { getKnowledgeCitation, type KnowledgeCitationDetail, type AgentChatMessage } from "../../api";
import { citationOrdinal, citationsToShow, renderAnswerText } from "../../chat-citations.mjs";
import { evidenceText, followUpQuestion, hintText, markUnverified, parseFlagHref, reasonKey } from "../../chat-unverified.mjs";
import { PUBLIC_MARK_ARIA, PUBLIC_MARK_GLYPH, attachPublicMarks, normalizePublicMarks, parsePublicMarkHref, publicMarkOrdinal, publicMarkQuoteText } from "../../chat-public-marks.mjs";
import { useLocale } from "../../i18n";
import { MarkdownBody } from "./MarkdownBody";
import { useChat } from "./ChatSessionProvider";

export type CitationItem = NonNullable<AgentChatMessage["citations"]>[number];

// U9: a neutral marker on one sentence. Hover or tap shows the server's template and the verbatim source quote; the
// ordinal opens the source exactly as the citation list does (onOpenCitation).
export function PublicMarkBadge({view,citation,onOpenCitation,t}:{view:ReturnType<typeof normalizePublicMarks>[number];citation:CitationItem|undefined;onOpenCitation:(citation:CitationItem)=>void;t:(text:string)=>string}){
 const [open,setOpen]=useState(false);
 const ordinal=publicMarkOrdinal(view);
 return <span className={`public-mark${open?" is-open":""}`}>
  <button type="button" className="public-mark-button" aria-expanded={open} aria-label={t(PUBLIC_MARK_ARIA)} onClick={()=>setOpen(x=>!x)}>{PUBLIC_MARK_GLYPH}</button>
  <span className="public-mark-bubble" role="note">
   <span className="public-mark-template">{view.label}</span>
   <span className="public-mark-quote">{publicMarkQuoteText(view,t)}</span>
   {citation&&ordinal!==null&&<button type="button" className="public-mark-cite" onClick={()=>onOpenCitation(citation)}>{t("查看来源")} [{ordinal}]</button>}
  </span>
 </span>;
}

/** Which citation drawer is open, and the source excerpts fetched so far (state of the thread's answers). */
export function useCitations() {
  const { t } = useLocale();
  const [citationDetails,setCitationDetails]=useState<Record<string,KnowledgeCitationDetail>>({});
  const [openCitationTurn,setOpenCitationTurn]=useState<number|null>(null);
  // The same action as a citation link in the answer (see the `a` renderer): open the drawer and the source.
  function openCitationAt(turn:number, citation:CitationItem){setOpenCitationTurn(turn);if(["web","web_news","official_filing","saved_filing","saved_ai_analysis","reported_figure"].includes(citation.source_type)&&citation.source_url){window.open(citation.source_url,"_blank","noopener,noreferrer");return}if(citation.chunk_id)void showCitation(citation.chunk_id,citation.source_type==="unavailable")}
  async function showCitation(chunkId:string, unavailable:boolean){if(unavailable)return;try{const value=await getKnowledgeCitation(chunkId);setCitationDetails(x=>({...x,[chunkId]:value}))}catch{setCitationDetails(x=>({...x,[chunkId]:{title:t("来源已撤回或不可访问"),section:"",excerpt:"",source_url:null,observed_at:null,coverage:"unavailable",start_offset:0,end_offset:0}}))}}
  return { citationDetails, openCitationTurn, setOpenCitationTurn, openCitationAt, showCitation };
}

/** An answer's text: markdown with the citation, public-mark and unverified-line links (the renderer itself is a chunk of its own, see MarkdownBody). */
export function AnswerBody({ m, i, streaming, draftBox, openCitationAt, setOpenCitationTurn, showCitation }: { m: AgentChatMessage; i: number; streaming: boolean; draftBox: RefObject<HTMLTextAreaElement | null>; openCitationAt: (turn: number, citation: CitationItem) => void; setOpenCitationTurn: (turn: number | null) => void; showCitation: (chunkId: string, unavailable: boolean) => Promise<void> }) {
  const { t } = useLocale(), c = useChat();
  return <>
              <MarkdownBody plain={m.content} streaming={streaming} components={{table:({node,...props})=><div className="markdown-table-wrap"><table {...props}/></div>,a:({node,...props})=>{const href=String(props.href??"");const publicIndex=parsePublicMarkHref(href);if(publicIndex!==null){const view=normalizePublicMarks(m.public_marks)[publicIndex];if(!view)return null;const ordinal=publicMarkOrdinal(view);const cite=ordinal===null?undefined:m.citations?.find((item,index)=>citationOrdinal(item,index)===ordinal);return <PublicMarkBadge view={view} citation={cite} t={t} onOpenCitation={c=>openCitationAt(i,c)}/>}const flag=parseFlagHref(href);if(flag){const flagged=m.unverified_lines?.[flag.index];return <span className={flag.kind==="numbers"?"unverified-flag unverified-flag-number":"unverified-flag"} role="note">{props.children}{flag.kind==="insufficient"&&flagged&&<button type="button" className="unverified-ask" onClick={()=>{c.setDraft(followUpQuestion(flagged.line));draftBox.current?.focus()}}>{t("追问依据")}</button>}</span>}const match=href.match(/^#citation-(\d+)$/);const ordinal=match?Number(match[1]):null;const citation=ordinal?m.citations?.find((item,index)=>citationOrdinal(item,index)===ordinal):undefined;if(match&&!citation)return <span className="citation-unmatched">[{props.children}]</span>;const citationLabel=citation?t("引用来源")+" "+ordinal+" · "+citation.title:undefined;return <a {...props} className={citation?"citation-ref":undefined} aria-label={citationLabel} title={citationLabel} href={citation?href:props.href} onClick={event=>{if(!citation)return;event.preventDefault();setOpenCitationTurn(i);["web","web_news","official_filing","saved_filing","saved_ai_analysis","reported_figure"].includes(citation.source_type)&&citation.source_url?window.open(citation.source_url,"_blank","noopener,noreferrer"):citation.chunk_id?void showCitation(citation.chunk_id,citation.source_type==="unavailable"):undefined}} target={citation?undefined:"_blank"} rel={citation?undefined:"noopener noreferrer"}/>} }} text={renderAnswerText(attachPublicMarks(markUnverified(m.content,m.unverified_lines,{insufficient:t("证据不足"),numbers:t("数字未核实"),reason:code=>t(reasonKey(code)),hint:item=>hintText(item,t),evidence:item=>evidenceText(item,t)}),m.public_marks),m.citations,m.citation_protocol)} />
  </>;
}

/** The 引用来源 drawer under an answer. */
export function CitationDrawer({ m, i, openCitationTurn, citationDetails, showCitation }: { m: AgentChatMessage; i: number; openCitationTurn: number | null; citationDetails: Record<string, KnowledgeCitationDetail>; showCitation: (chunkId: string, unavailable: boolean) => Promise<void> }) {
  const { t } = useLocale();
  return <>
                {Boolean(citationsToShow(m.citation_protocol,m.citations,m.citation_nodes).length)&&<details className="citation-drawer" open={openCitationTurn===i}><summary>{t("引用来源")} · {citationsToShow(m.citation_protocol,m.citations,m.citation_nodes).length}</summary>{citationsToShow(m.citation_protocol,m.citations,m.citation_nodes).map((citation,j)=><div className="citation-item" key={citation.chunk_id??citation.source_url??citation.ordinal}><button type="button" onClick={()=>['web','web_news','official_filing','saved_filing','saved_ai_analysis','reported_figure'].includes(citation.source_type)&&citation.source_url?window.open(citation.source_url,"_blank","noopener,noreferrer"):citation.chunk_id?void showCitation(citation.chunk_id,citation.source_type==='unavailable'):undefined}><b>[{citation.ordinal??j+1}]</b><span>{citation.source_type==='ai_analysis'&&<strong>已保存 AI 分析（派生） · </strong>}{citation.source_type==='reported_figure'&&<strong>{t("SEC XBRL 披露值")} · </strong>}{citation.title}{citation.section?` · ${citation.section}`:""}</span><small>{['web','web_news'].includes(citation.source_type)?`网页 · ${citation.published_at||"发布日期未知"} · 抓取 ${citation.observed_at||"时间未知"}`:(citation.observed_at||t("观察时间未知"))}{citation.truncated?` · ${t("保存内容可能不完整")}`:""}</small>{['web','web_news'].includes(citation.source_type)&&citation.source_url&&<span style={{gridColumn:2}}>打开网页来源 ↗</span>}</button>{!citation.chunk_id&&citation.quote&&<details><summary>{t("引用来源")}</summary><p>{citation.quote}</p></details>}{citation.chunk_id&&citationDetails[citation.chunk_id]&&<div className="citation-detail"><div className="citation-detail-content"><p>{citationDetails[citation.chunk_id].derived&&<strong>已保存 AI 分析（派生内容） · v{citationDetails[citation.chunk_id].version_no ?? "?"} · {citationDetails[citation.chunk_id].analysis_version} · {citationDetails[citation.chunk_id].model}</strong>}{citationDetails[citation.chunk_id].excerpt||t("来源已撤回或不可访问")}</p>{(citationDetails[citation.chunk_id].original_quotes??[]).length>0&&<><strong>{t("原文引文：")}</strong><ul>{(citationDetails[citation.chunk_id].original_quotes??[]).map((quote,index)=><li key={index}>{quote}</li>)}</ul></>}</div>{citationDetails[citation.chunk_id].source_url&&<a href={citationDetails[citation.chunk_id].source_url!} target="_blank" rel="noreferrer">打开原始来源 ↗</a>}</div>}</div>)}</details>}
  </>;
}
