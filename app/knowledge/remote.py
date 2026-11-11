from __future__ import annotations
"""Retrieval runtime that talks to the remote retrieval service.

Never imports torch / FlagEmbedding / pymilvus: the Muse VM only forwards the
query (plus the access scope and time cutoff) and receives ranked chunk ids.
"""
import asyncio, logging, os
from datetime import datetime
import httpx

log=logging.getLogger(__name__)
CONNECT_TIMEOUT=2.0
TOTAL_TIMEOUT=15.0

class KnowledgeOffline(RuntimeError):
    """The remote retrieval service cannot be reached or answered in time."""
    code='knowledge_offline'
    hint='知识库检索服务当前不可用，本轮请不依赖知识库继续回答。'

class RemoteKnowledgeRuntime:
    ready=True
    health_error=None
    last_health_check=0.0
    index=None
    def __init__(self,settings,url:str,token:str|None=None,*,threshold:float=0.0):
        self.settings=settings; self.url=url.rstrip('/'); self.token=token or ''
        self.threshold=threshold
        self.embedder=None
    def _headers(self): return {'X-Retrieval-Token':self.token}
    async def _call(self,method:str,path:str,payload:dict|None=None):
        timeout=httpx.Timeout(TOTAL_TIMEOUT,connect=CONNECT_TIMEOUT)
        try:
            async def go():
                async with httpx.AsyncClient(timeout=timeout,trust_env=False) as client:
                    return await client.request(method,self.url+path,json=payload,headers=self._headers())
            response=await asyncio.wait_for(go(),TOTAL_TIMEOUT)
        except (httpx.HTTPError,asyncio.TimeoutError,OSError) as exc:
            raise KnowledgeOffline(f'retrieval service unreachable ({type(exc).__name__})') from exc
        if response.status_code>=400:
            raise KnowledgeOffline(f'retrieval service returned {response.status_code}')
        return response.json()
    def _scope(self):
        from .runtime import current_research_context
        context=current_research_context()
        if context is None: return {'owner_hash':None,'cutoff':None}
        cutoff=context.cutoff.isoformat() if isinstance(context.cutoff,datetime) else None
        return {'owner_hash':context.owner_hash,'cutoff':cutoff}
    async def search_strategy(self,strategy,query,filter_expr,limit):
        body={'strategy':strategy,'query':query,'filter':filter_expr,'limit':limit,
              'generation':self.settings.generation,**self._scope()}
        return (await self._call('POST','/retrieve',body))['hits']
    async def encode(self,text): raise NotImplementedError('embedding runs on the retrieval service')
    async def search(self,vector,filter_expr,limit): return await self.search_strategy('dense',None,filter_expr,limit)
    async def rerank(self,query,passages):
        out=await self._call('POST','/rerank',{'query':query,'passages':passages})
        return [(int(i),float(s)) for i,s in out['pairs']]
    def health(self):
        return {'ready':True,'generation':self.settings.generation,'remote':self.url}
    async def check(self):
        info=await self._call('GET','/health')
        if 'threshold' in info: self.threshold=float(info['threshold'])
        return info
    def close(self): pass

def remote_url()->str|None:
    value=os.getenv('RAG_REMOTE_URL','').strip()
    return value or None

def make_remote_runtime(settings)->RemoteKnowledgeRuntime:
    return RemoteKnowledgeRuntime(settings,remote_url(),os.getenv('RAG_REMOTE_TOKEN'))
