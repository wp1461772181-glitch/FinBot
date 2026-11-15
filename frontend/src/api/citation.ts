import { chatCredential, requestJson } from "./base";

export type KnowledgeCitationDetail={title:string;section:string;excerpt:string;source_url:string|null;observed_at:string|null;coverage:string;start_offset:number;end_offset:number;derived?:boolean;analysis_version?:string;version_no?:number|null;model?:string;classification?:string;original_source_type?:string;original_quotes?:string[]};
export async function getKnowledgeCitation(chunkId:string):Promise<KnowledgeCitationDetail>{return requestJson(`/api/knowledge/citations/${encodeURIComponent(chunkId)}`,{headers:{'X-Chat-Session':chatCredential()}})}
