import { chatCredential, requestJson } from "./base";
import type { AgentCitation } from "./conversations";

export type KnowledgeDocumentSummary = { id:string; title:string; symbol:string|null; source_type:string; observed_at:string|null; available_at:string|null; status:string; active:boolean; owner_scope:string; chunks:number };
export type KnowledgeChunkDetail = { id:string; ordinal:number; section:string; answer:string; status:string; needs_review:boolean };

export async function getKnowledgeDocuments(): Promise<KnowledgeDocumentSummary[]> {
  const result=await requestJson<{items:KnowledgeDocumentSummary[]}>('/api/knowledge/documents',{headers:{'X-Chat-Session':chatCredential()}});
  return result.items;
}
export async function getKnowledgeChunks(documentId:string):Promise<{document:{id:string;title:string;source_text:string;source_url:string|null;status:string};chunks:KnowledgeChunkDetail[]}> {
  return requestJson(`/api/knowledge/documents/${encodeURIComponent(documentId)}/chunks`,{headers:{'X-Chat-Session':chatCredential()}});
}
export async function importKnowledge(source_type:'faq'|'upload'|'sec'|'analysis',source_ids:string[]):Promise<{ok:boolean;accepted_sources:number;chunks:number;needs_review:number}> {
  return requestJson('/api/knowledge/import',{method:'POST',headers:{'X-Chat-Session':chatCredential(),'Content-Type':'application/json'},body:JSON.stringify({source_type,source_ids})});
}
export async function runKnowledgeIndex():Promise<{ok:boolean;indexed:number;failed:number;idle:number}> {
  return requestJson('/api/knowledge/index',{method:'POST',headers:{'X-Chat-Session':chatCredential(),'Content-Type':'application/json'},body:JSON.stringify({max_tasks:100})});
}
export async function testKnowledgeRetrieval(kind:'faq'|'material'|'analysis',keyword:string,symbol?:string):Promise<{result:{ok:boolean;data:unknown[]|null;error_code?:string};citations:AgentCitation[]}> {
  return requestJson('/api/knowledge/retrieval-test',{method:'POST',headers:{'X-Chat-Session':chatCredential(),'Content-Type':'application/json'},body:JSON.stringify({kind,keyword,...(symbol?{symbol}:{})})});
}
export async function retryKnowledgeDocument(documentId:string):Promise<{ok:boolean;queued_chunks:number}> {
  return requestJson(`/api/knowledge/documents/${encodeURIComponent(documentId)}/retry`,{method:'POST',headers:{'X-Chat-Session':chatCredential()}});
}
export async function withdrawKnowledgeDocument(documentId:string):Promise<{ok:boolean;status:string}> {
  return requestJson(`/api/knowledge/documents/${encodeURIComponent(documentId)}/withdraw`,{method:'POST',headers:{'X-Chat-Session':chatCredential()}});
}
export async function getKnowledgeCandidates():Promise<Array<{id:string;question:string;answer:string;category:string;evidence_quote:string}>> {
  const result=await requestJson<{items:Array<{id:string;question:string;answer:string;category:string;evidence_quote:string}>}>('/api/knowledge/candidates',{headers:{'X-Chat-Session':chatCredential()}});return result.items;
}
export async function reviewKnowledgeCandidate(id:string,approved:boolean,reviewer:string):Promise<void> {
  await requestJson(`/api/knowledge/candidates/${encodeURIComponent(id)}/review`,{method:'POST',headers:{'X-Chat-Session':chatCredential(),'Content-Type':'application/json'},body:JSON.stringify({approved,reviewer})});
}
export async function getKnowledgeImportable(source:'faq'|'upload'|'sec'|'analysis',symbol:string):Promise<Array<{id:string;title:string;symbol:string|null;source_type:string}>> {
  const result=await requestJson<{items:Array<{id:string;title:string;symbol:string|null;source_type:string}>}>(`/api/knowledge/importable/${source}?symbol=${encodeURIComponent(symbol)}`,{headers:{'X-Chat-Session':chatCredential()}});return result.items;
}
