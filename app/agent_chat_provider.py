from __future__ import annotations
import asyncio
import json
import httpx
import os
import re
from contextlib import AsyncExitStack,asynccontextmanager
from contextvars import ContextVar
from fastapi import HTTPException
from .agent_chat_api import PROVIDERS, BASE_URLS, PinnedPublicTransport, model_transport
from .agent_progress import progress_watchdog, mark_progress
from .agent_workflow.fp_flags import flag

_DECISION_SESSION=ContextVar('agent_decision_session',default=None)

@asynccontextmanager
async def decision_session(base_url=None):
    # One lazy pool per turn. Headers/keys remain on individual requests, and
    # ContextVar prevents concurrent conversations from sharing session state.
    async with AsyncExitStack() as stack:
        token=_DECISION_SESSION.set({'base_url':base_url,'stack':stack,'client':None})
        try:yield
        finally:_DECISION_SESSION.reset(token)

@asynccontextmanager
async def _decision_client(base_url):
    options={'timeout':httpx.Timeout(PROVIDER_REQUEST_SECONDS),'follow_redirects':False,'trust_env':False}
    if base_url:options['transport']=model_transport(base_url)
    session=_DECISION_SESSION.get()
    if session is not None and session['base_url']==base_url:
        if session['client'] is None:
            session['client']=await session['stack'].enter_async_context(httpx.AsyncClient(**options))
        yield session['client']
    else:
        async with httpx.AsyncClient(**options) as client:yield client

def _bounded_seconds(name: str, default: float, low: float, high: float) -> float:
    try:
        return min(high, max(low, float(os.getenv(name, default))))
    except ValueError:
        return default


# One request to the model service (a stage of the workflow, a tool decision). These only catch a hung
# provider: a thinking model on a busy route can legitimately take minutes, so the defaults are generous.
PROVIDER_REQUEST_SECONDS = _bounded_seconds("AGENT_PROVIDER_TIMEOUT_SECONDS", 180.0, 10.0, 600.0)
# Maximum inactivity of a streamed answer, renewed only by semantic model deltas.
PROVIDER_STREAM_SECONDS = _bounded_seconds("AGENT_PROVIDER_STREAM_SECONDS", 600.0, 30.0, 1200.0)
# Thinking output counts against max_tokens, so a small cap can run out before any visible text or
# tool call; one generous cap for every call keeps a long think from ending as a truncated response.
MAX_OUTPUT_TOKENS = 32768

# A reasoning model thinks before it answers: hundreds to thousands of hidden tokens, a minute or two on a busy
# route.  One turn of this workflow makes several calls one after the other, and a stage of it (a JSON
# classification, a plan) does not need deep thinking, so left at the default such a model makes a turn take
# minutes and runs into the request timeout.  OpenRouter takes one unified parameter for the effort (a model
# without reasoning ignores it).  "default" sends nothing and leaves it to the model.
REASONING_EFFORT = os.getenv("AGENT_REASONING_EFFORT", "low").strip().lower()
# The full set OpenRouter documents for ``reasoning.effort`` (reasoning-tokens guide, 2026-11).  A bot may
# name any of them (agent_bots); the environment default is read from the same set.
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
_REASONING_EFFORTS = frozenset(REASONING_EFFORTS)


def sent_effort(effort: str | None = None) -> str | None:
    """The effort a request carries: the given one (a bot's setting), else the environment default.  None when
    nothing is sent (the environment says "default", or the value is not a known tier)."""
    value = REASONING_EFFORT if effort is None else effort
    return value if value in _REASONING_EFFORTS else None


# SiliconFlow (docs.siliconflow.cn, chat-completions reference, 2026-11): the thinking control depends on the model.
# Family "effort": reasoning_effort takes only "high" and "max" (the server folds low/medium onto high, xhigh onto max).
# Family "budget": the hybrid models take enable_thinking (on/off) and thinking_budget (128-32768 tokens).
# Any other model gets nothing, as before: the docs do not say an unknown field is ignored rather than refused.
# DeepSeek-V3.1 is left out on purpose: its function calling needs enable_thinking off, and FinBot's decisions carry tools.
_SF_EFFORT_MODEL = re.compile(r"^(deepseek-v4-(flash|pro)|glm-5\.2)$")
_SF_BUDGET_MODEL = re.compile(r"^(qwen3-(8b|14b|32b|30b-a3b|235b-a22b)|deepseek-v3\.2(-exp)?|hunyuan-a13b-instruct|glm-4\.5v|glm-4\.6v|glm-5v-turbo)$")
_SF_BUDGETS = {"low": 1024, "medium": 4096, "high": 16384, "max": 32768}


def _siliconflow_family(model: str | None) -> str | None:
    if not flag("FINBOT_SF_EFFORT", True):
        return None
    name = str(model or "").strip().lower().rsplit("/", 1)[-1]
    if _SF_EFFORT_MODEL.match(name):
        return "effort"
    if _SF_BUDGET_MODEL.match(name):
        return "budget"
    return None


def siliconflow_efforts(model: str | None) -> tuple[str, ...]:
    """The tiers a SiliconFlow model really takes, as reasoning_options sends them (the strength list reads this)."""
    family = _siliconflow_family(model)
    if family == "effort":
        return ("high", "max")
    if family == "budget":
        return ("none", "low", "medium", "high", "max")
    return ()


def reasoning_options(provider: str, effort: str | None = None, model: str | None = None) -> dict:
    value = sent_effort(effort)
    if value is None:
        return {}
    if provider == "siliconflow":
        family = _siliconflow_family(model)
        if family == "effort":
            # Only the two tiers the model has are sent.  A lower tier (the environment default "low" of a bot that chose
            # nothing, and the background calls) sends nothing and keeps the model's own default, as before this branch.
            if value in ("xhigh", "max"):
                return {"reasoning_effort": "max"}
            return {"reasoning_effort": "high"} if value == "high" else {}
        if family == "budget":
            if value == "none":
                return {"enable_thinking": False}
            tier = {"minimal": "low", "xhigh": "max"}.get(value, value)
            return {"enable_thinking": True, "thinking_budget": _SF_BUDGETS[tier]}
        return {}
    if provider == "deepseek":
        # DeepSeek's own levels are high and max.  low and medium keep their existing mapping (the server
        # folds them into high); minimal stays low as before; xhigh is max; none turns thinking off.
        if value == "none":
            return {"thinking": {"type": "disabled"}}
        mapped = {"minimal": "low", "medium": "high", "xhigh": "max"}.get(value, value)
        return {"thinking": {"type": "enabled"}, "reasoning_effort": mapped}
    if provider == "zhipu":
        # Zhipu's GLM-5.3 / GLM-5.3-Flash accept only low, high and max, and thinking cannot be
        # disabled on them (sending "disabled" or any other tier is a 400).  Fold the internal
        # tiers onto those three; "none" cannot turn thinking off, so it lands on the lightest
        # tier instead of sending a value the API would reject.  Without this branch the effort
        # was silently dropped and GLM ran at the platform default, which is max.
        mapped = {"none": "low", "minimal": "low", "medium": "high", "xhigh": "max"}.get(value, value)
        return {"thinking": {"type": "enabled"}, "reasoning_effort": mapped}
    if provider == "openrouter":
        return {"reasoning": {"effort": value}}
    return {}


# The tiers each provider's own API distinguishes, as reasoning_options really sends them.  The browser's strength
# list reads this for every provider but OpenRouter (agent_model_catalog._reasoning_fields), so the list and the
# request come from one place.  Keep it in step with reasoning_options: a change there goes here too.  () means no
# effort is sent for that provider at all; a provider not listed here gets no tier list (the browser offers every tier).
NATIVE_EFFORTS = {
    "zhipu": ("low", "high", "max"),           # GLM-5.3 / GLM-5.3-Flash; none, minimal, medium, xhigh fold onto these
    "deepseek": ("none", "high", "max"),       # none turns thinking off; medium is sent as high, low as low (folded)
    "siliconflow": (),                         # per model: siliconflow_efforts(model) (the catalogue asks it); () without a model
    # Every other provider the model dialog offers: reasoning_options has no branch for it, so nothing is sent and the
    # browser must say "takes no effort" instead of offering seven tiers that do nothing.  A bot's stored
    # reasoning_effort is left as it is; the settings page only flags it as outside the model's tiers.
    **{provider: () for provider in ("kimi", "minimax", "qwen", "doubao", "hunyuan", "baidu", "openai",
                                     "gemini", "xai", "mistral", "groq", "custom")},
    # Native Messages API (anthropic_native): output_config.effort, one-to-one.  The catalogue prefers what the Models API
    # reports per model (anthropic_native.display_efforts); this is the table it falls back to.
    "anthropic": ("low", "medium", "high", "xhigh", "max"),
}


class ProviderFailure(HTTPException):
    def __init__(self, code: str, *, stage: str, provider_status: int | None = None,
                 request_id: str | None = None, retryable: bool = False):
        super().__init__(429 if provider_status == 429 else 502, code)
        self.stage = stage
        self.provider_status = provider_status
        self.request_id = request_id
        self.retryable = retryable


class ResponseCheckFailed(HTTPException):
    """A response check that did not pass: which one (check) and where in the stream (event), never the text."""
    def __init__(self, code, check, *, event=None, tool_index=None):
        super().__init__(502, code)
        self.check=check; self.event=event; self.tool_index=tool_index


# SW1D: the parser's own bound on tool-call index.  Memory only (a runaway stream could add entries without end); a step
# is bounded separately, by Turn.step_call_cap, and a batch past this bound is a FinBot limit, not a provider fault.
TOOL_CALL_STREAM_GUARD = 128


async def _provider_error(response, stage: str) -> ProviderFailure:
    status = response.status_code
    request_id = next((response.headers.get(name) for name in ("x-request-id", "x-ds-request-id", "cf-ray")
                       if response.headers.get(name)), None)
    if request_id and not __import__("re").fullmatch(r"[A-Za-z0-9_.:-]{1,100}", request_id):
        request_id = None
    code = {400: "provider_model_unavailable_or_invalid_request", 401: "provider_invalid_key",
            403: "provider_model_access_denied", 404: "provider_model_unavailable_or_invalid_request",
            422: "provider_model_unavailable_or_invalid_request", 429: "provider_rate_or_quota_error"}.get(status, "provider_error")
    if status == 400:
        raw=b''
        async for chunk in response.aiter_bytes():
            raw+=chunk[:4096-len(raw)]
            if len(raw)>=4096:break
        # Only classify a known protocol phrase; never return arbitrary provider
        # text because it can echo private prompts or headers.
        if b"reasoning_content" in raw or b"tool_call_id" in raw:
            code = "provider_protocol_incompatible"
    return ProviderFailure(code, stage=stage, provider_status=status,
                           request_id=request_id, retryable=status in {429, 500, 502, 503, 504})

def endpoint(provider, base_url=None):
    if base_url is None: return PROVIDERS[provider]
    base=base_url.rstrip("/")
    return base if base.endswith("/chat/completions") else base+"/chat/completions"
async def decision_request(provider, model, api_key, messages, schemas, base_url=None, reasoning_effort=None):
    if provider=="anthropic":
        from . import anthropic_native
        if anthropic_native.use_native(provider):return await anthropic_native.decision_request(model,api_key,messages,schemas,reasoning_effort)
    if any(isinstance(m,dict) and "cache_point" in m for m in messages):messages=[{k:v for k,v in m.items() if k!="cache_point"} for m in messages]  # kernel-private mark
    body={"model":model,"messages":messages,"max_tokens":MAX_OUTPUT_TOKENS,"stream":True}
    if schemas: body.update(tools=schemas,tool_choice="auto")
    if provider=="minimax":body["reasoning_split"]=True
    body.update(reasoning_options(provider,reasoning_effort,model))
    return await _post(provider,api_key,body,base_url)
async def stream_decision(provider,model,api_key,messages,schemas,*,base_url=None,reasoning_effort=None,on_text=None,keep_thinking=True,cache=True):
    """decision_request with the answer text reported through ``await on_text(piece)`` as it is generated (Anthropic native);
    other providers answer first and report the whole text once.  Same (data, message) return as decision_request."""
    if provider=="anthropic":
        from . import anthropic_native
        if anthropic_native.use_native(provider):
            return await anthropic_native.stream_decision(model,api_key,messages,schemas,reasoning_effort,on_text=on_text,keep_thinking=keep_thinking,cache=cache)
    data,message=await decision_request(provider,model,api_key,messages,schemas,base_url,reasoning_effort)
    if on_text is not None and isinstance(message,dict) and message.get("content"):await on_text(message["content"])
    return data,message
def _semantic_delta(delta):
    return (any(isinstance(delta.get(k),str) and delta[k] for k in ('content','reasoning_content'))
            or bool(delta.get('reasoning_details'))
            or any(isinstance(c,dict) and isinstance(c.get('function'),dict)
                   and any(c['function'].get(k) for k in ('name','arguments'))
                   for c in (delta.get('tool_calls') or [])))


# Memory guards only: a long think in Chinese (every character a six-byte \u escape) easily passes 1 MB
# well before max_tokens, so these sit far above any real response and only stop a runaway stream.
MAX_RESPONSE_BYTES=20_000_000
MAX_LINE_BYTES=4_000_000
MAX_REASONING_BYTES=4_000_000


async def _events(response):
    """Bounded SSE parser. Transport keepalives never renew the progress clock."""
    buffer=b''; total=0; done=False
    # Data events yielded so far.  A check that fails on the next event reports that event's number (1-based).
    produced=0
    async for chunk in response.aiter_bytes():
        total+=len(chunk)
        if total>MAX_RESPONSE_BYTES:raise HTTPException(502,'provider_response_too_large')
        buffer+=chunk
        if len(buffer)>MAX_LINE_BYTES and b'\n' not in buffer:raise HTTPException(502,'provider_response_too_large')
        while b'\n' in buffer:
            line,buffer=buffer.split(b'\n',1)
            if len(line)>MAX_LINE_BYTES:raise HTTPException(502,'provider_response_too_large')
            try:line=line.rstrip(b'\r').decode('utf-8')
            except UnicodeDecodeError as exc:raise ResponseCheckFailed('provider_incompatible_response','utf8_decode',event=produced+1) from exc
            if not line or not line.startswith('data:'):continue
            raw=line[5:].strip()
            if raw=='[DONE]':done=True;break
            try:event=json.loads(raw)
            except ValueError as exc:raise ResponseCheckFailed('provider_incompatible_response','non_json_line',event=produced+1) from exc
            try:
                if not isinstance(event,dict):raise ValueError()
                if 'error' in event:raise HTTPException(502,'provider_error')
                choices=event.get('choices')
                if choices==[] and isinstance(event.get('usage'),dict):
                    produced+=1;yield event;continue
                choice=choices[0];delta=choice['delta']
                if not isinstance(delta,dict):raise ValueError()
                if _semantic_delta(delta):mark_progress()
            except HTTPException:raise
            except (ValueError,KeyError,IndexError,TypeError,AttributeError) as exc:
                raise ResponseCheckFailed('provider_incompatible_response','choice_shape',event=produced+1) from exc
            produced+=1
            yield event
        if done:break
    if not done or buffer.strip():raise HTTPException(502,'provider_incomplete_stream')


def _merge_delta(message, calls, delta, cap=12, over_cap_code='provider_incompatible_response'):
    for key in ('content','reasoning_content'):
        part=delta.get(key)
        if part is not None:
            if not isinstance(part,str):raise ResponseCheckFailed('provider_incompatible_response','text_not_string')
            message[key]=message.get(key,'')+part
    details=delta.get('reasoning_details')
    if details is not None:
        if not isinstance(details,list):raise ResponseCheckFailed('provider_incompatible_response','reasoning_details_shape')
        message.setdefault('reasoning_details',[]).extend(details)
    # Measured with JSON escapes (six bytes a Chinese character); a memory guard, not a thinking budget.
    if len(json.dumps({k:v for k,v in message.items() if k.startswith('reasoning_')}).encode())>MAX_REASONING_BYTES:
        raise HTTPException(502,'provider_protocol_too_large')
    parts=delta.get('tool_calls',[])
    if not isinstance(parts,list):raise ResponseCheckFailed('provider_incompatible_response','tool_calls_shape')
    for part in parts:
        if not isinstance(part,dict) or type(part.get('index')) is not int or part['index']<0:
            raise ResponseCheckFailed('provider_incompatible_response','tool_part_shape')
        if part['index']>=cap:
            raise ResponseCheckFailed(over_cap_code,'tool_index',tool_index=part['index'])
        target=calls.setdefault(part['index'],{'id':'','type':'function','function':{'name':'','arguments':''}})
        if part.get('type') not in (None,'function'):raise ResponseCheckFailed('provider_incompatible_response','tool_part_type')
        fn=part.get('function',{})
        if not isinstance(fn,dict):raise ResponseCheckFailed('provider_incompatible_response','tool_function_shape')
        for container, key, value in ((target,'id',part.get('id')),
                (target['function'],'name',fn.get('name')),(target['function'],'arguments',fn.get('arguments'))):
            if value is not None:
                if not isinstance(value,str):raise ResponseCheckFailed('provider_incompatible_response','tool_field_not_string')
                container[key]+=value


async def _post(provider,key,body,base_url=None):
    headers={'Authorization':f'Bearer {key}','Content-Type':'application/json'}
    if provider=='openrouter':headers['X-Title']='FinBot'
    # SW1D: read once per request.  On, the parser accepts tool-call indexes below the stream guard; off, the 4290d8b bound (12).
    sw1d=flag('FINBOT_SW1D_TOOLCALL_CAP',True)
    merge_kw={'cap':TOOL_CALL_STREAM_GUARD,'over_cap_code':'tool_call_batch_too_large'} if sw1d else {}
    try:
        async with progress_watchdog(PROVIDER_REQUEST_SECONDS):
          async with _decision_client(base_url) as client:
            async with client.stream('POST',endpoint(provider,base_url),headers=headers,json=body) as r:
                if 300<=r.status_code<400:raise HTTPException(502,'provider_redirect_rejected')
                if r.status_code>=400:raise await _provider_error(r,'tool_decision' if body.get('tools') else 'classification')
                if 'text/event-stream' in r.headers.get('content-type',''):
                    message={'role':'assistant','content':''};calls={};finish=None;usage={};number=0
                    try:
                        async for event in _events(r):
                            number+=1
                            if isinstance(event.get('usage'),dict):usage=event['usage']
                            if not event.get('choices'):continue
                            choice=event['choices'][0]
                            if finish is not None and _semantic_delta(choice['delta']):raise ResponseCheckFailed('provider_incompatible_response','post_finish_delta')
                            _merge_delta(message,calls,choice['delta'],**merge_kw)
                            reason=choice.get('finish_reason')
                            if reason is not None:
                                if reason not in {'stop','tool_calls','length'}:raise HTTPException(502,'provider_incomplete_response')
                                finish=reason
                    except ResponseCheckFailed as exc:
                        # The event this check failed on: the data event being read when it was raised (1-based).
                        if exc.event is None:exc.event=number
                        raise
                    if finish is None:raise HTTPException(502,'provider_incomplete_stream')
                    # Out of output tokens: the text written so far is still an answer, a cut tool call is not.
                    if finish=='length' and (calls or not str(message.get('content') or '').strip()):raise HTTPException(502,'provider_incomplete_response')
                    if calls:
                        if finish!='tool_calls' or sorted(calls)!=list(range(len(calls))):raise HTTPException(502,'provider_incomplete_stream')
                        message['tool_calls']=[calls[i] for i in sorted(calls)]
                        if any(not c['id'] or not c['function']['name'] or not c['function']['arguments'] for c in message['tool_calls']):
                            raise HTTPException(502,'provider_incomplete_stream')
                    elif finish=='tool_calls':raise HTTPException(502,'provider_incomplete_stream')
                    data={'choices':[{'message':message,'finish_reason':finish}],'usage':usage}
                else:
                    # Some compatible endpoints ignore stream=True. A complete JSON
                    # response is supported but partial bytes are not proof of progress.
                    chunks=[];total=0
                    async for chunk in r.aiter_bytes():
                        total+=len(chunk)
                        if total>MAX_RESPONSE_BYTES:raise HTTPException(502,'provider_response_too_large')
                        chunks.append(chunk)
                    try:
                        data=json.loads(b''.join(chunks));choice=data['choices'][0];message=choice['message']
                    except (ValueError,KeyError,IndexError,TypeError) as exc:raise ResponseCheckFailed('provider_incompatible_response','json_body') from exc
                    if not isinstance(message,dict):raise ResponseCheckFailed('provider_incompatible_response','json_message_shape')
                    if choice.get('finish_reason')=='content_filter' or (choice.get('finish_reason')=='length' and (message.get('tool_calls') or not str(message.get('content') or '').strip())):
                        raise HTTPException(502,'provider_incomplete_response')
                mark_progress()
                return data,message
    except HTTPException:raise
    except (httpx.TimeoutException,TimeoutError) as exc:raise HTTPException(504,'provider_timeout') from exc
    except httpx.HTTPError as exc:raise HTTPException(502,'provider_network_error') from exc

async def stream_answer(provider,model,api_key,messages,reasoning_collector=None,base_url=None):
    if provider=='anthropic':
        from . import anthropic_native
        if anthropic_native.use_native(provider):
            async for piece in anthropic_native.stream_answer(model,api_key,messages,reasoning_collector):yield piece
            return
    body={'model':model,'messages':messages,'max_tokens':MAX_OUTPUT_TOKENS,'stream':True}
    if provider=='minimax':body['reasoning_split']=True
    body.update(reasoning_options(provider,model=model))
    headers={'Authorization':f'Bearer {api_key}','Content-Type':'application/json'}
    if provider=='openrouter':headers['X-Title']='FinBot'
    try:
        async with progress_watchdog(PROVIDER_STREAM_SECONDS):
          async with _decision_client(base_url) as client:
            async with client.stream('POST',endpoint(provider,base_url),headers=headers,json=body) as r:
                if 300<=r.status_code<400:raise HTTPException(502,'provider_redirect_rejected')
                if r.status_code>=400:raise await _provider_error(r,'final_answer')
                message={};calls={};finished=False;number=0
                async for event in _events(r):
                    number+=1
                    if isinstance(reasoning_collector,dict) and isinstance(event.get('usage'),dict):reasoning_collector['_usage']=event['usage']
                    if not event.get('choices'):continue
                    choice=event['choices'][0];delta=choice['delta'];reason=choice.get('finish_reason')
                    if finished and _semantic_delta(delta):raise ResponseCheckFailed('provider_incompatible_response','post_finish_delta',event=number)
                    if reason is not None:
                        if reason not in {'stop','length'}:raise HTTPException(502,'provider_incomplete_stream')
                        finished=True
                    if delta.get('tool_calls'):raise HTTPException(502,'provider_incomplete_stream')
                    try:_merge_delta(message,calls,delta)
                    except ResponseCheckFailed as exc:
                        if exc.event is None:exc.event=number
                        raise
                    if reasoning_collector is not None:
                        if isinstance(reasoning_collector,dict):
                            for key in ('reasoning_content','reasoning_details'):
                                if delta.get(key):reasoning_collector.setdefault(key,[]).extend([delta[key]] if key=='reasoning_content' else delta[key])
                        elif delta.get('reasoning_content'):reasoning_collector.append(delta['reasoning_content'])
                    if delta.get('content'):yield delta['content']
                if not finished:raise HTTPException(502,'provider_incomplete_stream')
    except HTTPException:raise
    except (httpx.TimeoutException,TimeoutError) as exc:raise HTTPException(504,'provider_timeout') from exc
    except httpx.HTTPError as exc:raise HTTPException(502,'provider_network_error') from exc
