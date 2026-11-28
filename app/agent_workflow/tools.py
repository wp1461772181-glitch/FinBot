"""Real service adapters; routing and natural-language argument inference do not live here."""
from __future__ import annotations
import asyncio,json,logging,os,uuid
from datetime import UTC,datetime,timedelta
from sqlalchemy import select,text,or_
from ..database import SessionLocal
from ..agent_chat_identity import owner_credential_matches
from ..agent_chat_store import owner_hash
from ..agent_tool_catalog import definitions,validate
from ..knowledge.runtime import research_context
from .models import AgentWebSource
from .fp_flags import flag

logger=logging.getLogger(__name__)


def safe(value):return json.loads(json.dumps(value,default=str,ensure_ascii=False))
def result(rows,source):return {'ok':True,'data':safe(rows),'source':source,'as_of':datetime.now(UTC).isoformat()}
def publication_time(value):
    """A date-only value is UTC midnight: the source gave a calendar day, not a local clock time."""
    if isinstance(value,datetime):
        parsed=value
    else:
        try:parsed=datetime.fromisoformat(str(value or '').strip().replace('Z','+00:00'))
        except ValueError:raise ValueError('invalid_published_at')
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
ARGUMENT_PROBLEMS={'extra_forbidden':'这个工具没有这个参数','missing':'缺少这个必填参数'}

def argument_error(name,exc):
    """``invalid_arguments`` that says what was wrong: each offending argument and why, and the arguments this tool takes, so the
    model can correct the call instead of giving up on the tool (11-27: ``days_back`` sent to search_configured_news)."""
    out=error('invalid_arguments')
    problems=[]
    for item in (exc.errors() if hasattr(exc,'errors') else [])[:8]:
        field='.'.join(str(part) for part in item.get('loc') or ()) or '(整体)'
        problems.append({'argument':field,'problem':ARGUMENT_PROBLEMS.get(item.get('type'),str(item.get('msg') or '')[:120])})
    policy=definitions().get(name)
    if policy is not None:
        schema=policy.args_schema.model_json_schema()
        required=set(schema.get('required') or ())
        out['accepted_arguments']=[f'{key}（必填）' if key in required else key for key in (schema.get('properties') or {})]
    if problems:out['problems']=problems
    out['hint']='按 problems 改正参数后重新调用；这个工具能用的参数见 accepted_arguments。'
    return out

def error(code):
    hint='请修正参数或选择已返回的来源；没有资料时可先联网查找。'
    if code=='write_tool_not_granted':hint='用 request_action 请求用户批准'
    elif code=='sec_form_outside_scope':hint='这一轮的范围只含 10-K/10-Q（财报），你点名的表格类型不在其中；要取该份申报请同时给出它的 accession_number。'
    return {'ok':False,'data':[],'error_code':code,'hint':hint}
def rate_alert_refusal(about,symbol):
    """Nothing within 48 hours fits what he said; the brief has no stock, so none is named for it."""
    reason="最近 48 小时里没找到发给你的早间简报。" if about=='brief' else f"最近 48 小时里没找到发给你的{symbol + ' ' if symbol else ''}提醒。"
    return {'ok':False,'data':[],'error_code':'feedback_target_not_found','reason':reason,'hint':reason}
def rate_alert_line(match,verdict):
    """What was recorded, naming the message it matched: symbol, Beijing time, its first line, the verdict."""
    from ..alert_feedback import VERDICT_WORDS,when_text
    return f"{match.get('symbol') or ''} {when_text(match.get('at'))}「{match.get('text') or ''}」——{VERDICT_WORDS[verdict]}".lstrip()
ANSWER_NOT_FOUND="这段对话里还没有之前的回答可以评价。"
def rate_answer_refusal():
    """The conversation has no answer before this turn: there is nothing he can mean."""
    return {'ok':False,'data':[],'error_code':'answer_not_found','reason':ANSWER_NOT_FOUND,'hint':ANSWER_NOT_FOUND}
def rate_answer_line(match,verdict,reason=None):
    """What was recorded, naming the answer it matched: Beijing time, its first line, the verdict, and his reason when he gave one."""
    from ..answer_feedback import VERDICT_WORDS,when_text
    said=f"（原因：{reason}）" if reason else ""
    return f"{when_text(match.get('at'))}「{match.get('text') or ''}」——{VERDICT_WORDS[verdict]}{said}".lstrip()


async def search_knowledge(args,context):
    """A's mandatory saved-data prelude; explicit structured selectors only."""
    from ..agent_tools import query_materials,query_sec_filings,query_research_faq
    rows=[];citations=[];read_error=None;symbol=args.get('symbol');query=args['query'];limit=args.get('limit',5);filing_meta=None
    with research_context(context.owner_hash,citations=citations):
        if symbol:
            if args.get('latest') or args.get('form'):
                filing=await query_sec_filings.ainvoke({'symbol':symbol,'limit':1 if args.get('latest') else limit,
                    'form':args.get('form'),'financial_only':args.get('financial_only',False),'source_id':args.get('source_id')})
                filing_meta=filing.get('meta')   # the filing read's coverage receipt (SW1), handed on to the turn
                rows.extend({**r,'symbol':symbol,'source_type':'official_filing'} for r in filing.get('data') or [])
                if not filing.get('ok'):read_error=filing.get('error_code') or 'knowledge_unavailable'
            else:
                found=await query_materials.ainvoke({'symbol':symbol,'keyword':query[:80],'source_id':args.get('source_id'),'limit':limit})
                rows.extend(found.get('data') or [])
                if not found.get('ok'):read_error=found.get('error_code') or 'knowledge_unavailable'
        elif not args.get('company'):
            found=await query_research_faq.ainvoke({'keyword':query[:80]})
            rows.extend({**r,'source_type':'research_faq'} for r in found.get('data') or [])
            if not found.get('ok'):read_error=found.get('error_code') or 'knowledge_unavailable'
        # Captured web sources are available in lexical saved-data reads even while
        # embeddings warm up. Dense retrieval uses the same snapshots and owner gate.
        from ..knowledge.models import KnowledgeDocument
        with SessionLocal() as db:
            terms=[AgentWebSource.owner_hash==context.owner_hash]
            # With a stock, query_materials already read a page filed in 资料库: one copy, not two.
            if symbol:terms.extend((AgentWebSource.symbol==symbol,AgentWebSource.uploaded_evidence_id.is_(None)))
            elif args.get('company'):terms.append(AgentWebSource.company.ilike(args['company']))
            elif not args.get('source_id'):terms.append(AgentWebSource.excerpt.contains(query,autoescape=True))
            if args.get('source_id'):terms.append(AgentWebSource.id==uuid.UUID(args['source_id']))
            saved=db.scalars(select(AgentWebSource).where(*terms).order_by(AgentWebSource.published_at.desc().nullslast()).limit(limit)).all()
            rows.extend({'id':str(r.id),'symbol':r.symbol,'title':r.title,'excerpt':r.excerpt,'source_type':'web_news',
                'source_url':r.source_url,'published_at':r.published_at.isoformat() if r.published_at else None,
                'fetched_at':r.fetched_at.isoformat(),'content_hash':r.content_hash} for r in saved)
    if not rows and read_error:return error(read_error)
    out={**result(rows[:limit],'saved knowledge'),'_citations':citations}
    if filing_meta:out['meta']=filing_meta
    return out


async def invoke(name,args,context,*,emit=None,page_chars=None):
    scope=getattr(context,'tool_scope',None)
    if scope is not None and name not in scope:return error('tool_not_in_bot_scope')
    try:args=validate(name,args)
    except Exception as exc:return argument_error(name,exc)
    policy=definitions()[name];is_owner=owner_credential_matches(context.identity_credential)
    if not is_owner and not policy.guest:return error('owner_login_required')
    if policy.level=='costly' or (policy.level=='reversible' and is_owner):return error('confirmation_required')
    return await _dispatch(name,args,context,is_owner,emit,page_chars=page_chars)


async def execute_reversible(operation,key,context,*,emit=None,overrides=None):
    """Require the exact durable operation currently executing under consent's lock."""
    from . import consent
    try:
        request_id,index=key.rsplit('.',1)
        saved=consent.lookup(context.identity_credential,context.conversation_id,request_id)
        if saved['status']!='executing' or saved['operations'][int(index)]!=operation:raise ValueError('confirmation_parameter_mismatch')
        name=operation['name'];args=validate(name,operation['arguments'])
        if definitions()[name].level!='reversible':raise ValueError('invalid_action_tool')
        if name=='remember':args['_source_message_id']=operation.get('source_message_id');args['_bot_id']=operation.get('bot_id')
        if name=='create_routine':args['_bot_id']=operation.get('bot_id')
        if name=='record_view':args['_source_message_id']=operation.get('source_message_id');args['_conversation_id']=operation.get('conversation_id');args['_turn_id']=operation.get('turn_id')
        # The message the card named, frozen when it was made: the press rates that one, not whatever is newest by then.
        if name=='rate_alert':args['_match']=operation.get('match')
        # The answer the card named, the same way.
        if name=='rate_answer':args['_match']=operation.get('match')
        # A bot card freezes the fields it showed (the focus carried over from the bot as it was): the press writes exactly those.
        if name in {'create_bot','update_bot','apply_role_template','undo_role_template','set_watch_rule','set_watch_preset','set_alert_settings'}:args['_fields']=operation.get('fields')
        # The old state the card showed: a press whose card is no longer true is refused (directory_ops.is_stale).
        if operation.get('expect') is not None:args['_expect']=operation['expect']
        # The press, not the frozen operation, says whether a skill starts enabled or as a draft.
        if name=='save_skill':args['_status']=(overrides or {}).get('status') or 'active'
    except (ValueError,IndexError,KeyError,TypeError):return error('confirmation_required')
    return await _dispatch(name,args,context,True,emit)


# What a routine card may set (what POST/PATCH /tasks take besides the tickers and the bot); one list for create and update.
ROUTINE_FIELDS=('name','kind','instruction','schedule_kind','schedule_time','every_value','every_unit','max_runs','channel','skill_id','config','enabled')


def _memory_actor(context,args):
    """Who a remember / forget / record_view / drop_view press is, for the memory change log: this conversation, and the turn and his message
    when the frozen operation carries them (record_view carries all three, remember the message, the others neither)."""
    from .. import memory_events
    return memory_events.chat(args.get('_conversation_id') or context.conversation_id,args.get('_turn_id'),args.get('_source_message_id'))


async def _dispatch(name,args,context,is_owner,emit,page_chars=None):
    if args.get('_expect') is not None and is_owner:
        from . import directory_ops
        if await asyncio.to_thread(directory_ops.is_stale,name,args,context.owner_hash):
            stale=directory_ops.stale_refusal(name);return {'ok':False,'data':[],'error_code':stale.code,'reason':stale.reason,'hint':stale.reason}
    if name=='list_work':
        # The owner's own work in one list (chat turns, routines, card jobs, archive builds); nothing of another owner, nothing for a guest.
        from .. import work
        if not is_owner:return error('owner_login_required')
        return result(await asyncio.to_thread(work.list_for,context.owner_hash),'work')
    if name=='list_models':
        # The catalog and the roles as the owner may see them: names and whether a key is set, never a key, a hint of one or where it is kept.
        from .. import agent_model_catalog as catalog
        from .. import agent_model_roles as roles
        if not is_owner:return error('owner_login_required')
        def overview():
            listed,default=catalog.entries()
            chosen=roles.all_roles(context.owner_hash)
            names={item['name'] for item in listed}
            notes={'earnings':'unset: the server default model','forecast':'unset: the server default model','judge':'unset: the configured judge','fallback':'unset: no backup model','helper':"unset: the turn's own model",'memory':'unset: the server default model'}
            return {'default_model':default,
                    'models':[{'name':item['name'],'display_name':item['display_name'],'provider':item['provider'],'model':item['model'],
                               'key_set':bool(catalog._key_for(item)),'is_default':item['name']==default} for item in listed],
                    'roles':{role:({'model':chosen[role],'in_catalog':chosen[role] in names} if chosen.get(role) else {'model':None,'note':notes[role]}) for role in roles.ROLES}}
        return result([await asyncio.to_thread(overview)],'model catalog')
    if name=='read_turn':
        # One earlier turn of THIS conversation, as said; a guest reads its own conversation's only.  Memory, not evidence.
        from .. import agent_recall as recall
        from ..agent_chat_store import read_turn
        value=await read_turn(context.conversation_id,context.identity_credential,args['turn_id'])
        if value is None:return {**error('turn_not_found'),'hint':'这个 turn_id 不在本会话里；用摘要或引用标记里给出的 turn_id。'}
        return {**result([value],'earlier turn'),'label':recall.LABEL,'note':'这是那一轮当时说过的原话，只用来知道说过什么；它不是证据，不编号，数字和事实仍要在本轮重新读取。'}
    if name=='read_history_citation':
        from .history_citations import read_history_citation
        return await read_history_citation(args,context,**({'page_chars':page_chars} if page_chars is not None else {}))
    if name=='recall_conversations':
        # The owner's own conversations, never another credential's; memory, not evidence (agent_recall).
        from .. import agent_recall as recall
        if not is_owner:return error('owner_login_required')
        # A bot recalls its own line (its older, summarized part too); the default bot every bot's line.
        bot=getattr(context,'bot_id',None)
        if bot:
            rows=await asyncio.to_thread(recall.search,context.owner_hash,args['query'],args.get('limit',3),
                                         bot_ids=None if context.bot_is_default else [bot])
            # Details a summary no longer holds: the original messages of this bot's own lines (with the
            # turn_id, so a citation there can be fetched with read_history_citation).
            hits=await asyncio.to_thread(recall.search_messages,context.owner_hash,args['query'],args.get('limit',3),bot_ids=[bot])
            rows=recall.attach_matches(rows,hits)
        else:rows=await asyncio.to_thread(recall.search,context.owner_hash,args['query'],args.get('limit',3),exclude=context.conversation_id)
        return {**result(rows,'past conversations'),'label':recall.LABEL,'note':recall.note()}
    if name=='read_past_conversation':
        # Any bot's line of this owner (the default bot reads the research bot's analysis); memory, not evidence.
        from .. import agent_recall as recall
        if not is_owner:return error('owner_login_required')
        value=await asyncio.to_thread(recall.read,context.owner_hash,args['conversation_id'],limit=args['limit'],include_user=args['include_user'])
        if value is None:return error('conversation_not_found')
        return {**result([value],'past conversation'),'label':recall.LABEL,'note':recall.note()}
    if context.executor:
        value=context.executor(name,args)
        return await value if hasattr(value,'__await__') else value
    from ..agent_tools import TOOL_REGISTRY
    if name in TOOL_REGISTRY:
        citations=[]
        with research_context(context.owner_hash,citations=citations):value=await TOOL_REGISTRY[name].ainvoke(args)
        return {**value,'_citations':citations}
    if name=='search_knowledge':return await search_knowledge(args,context)
    if name=='test_retrieval_diagnostics':
        from ..knowledge.retrieval import retrieve_materials,retrieve_analysis,retrieve_faq
        citations=[]
        symbol=(args.get('symbol') or '').upper()
        query=args['query']
        kind=args.get('kind') or ('material' if symbol else 'faq')
        limit=args.get('top_k',5)
        with research_context(context.owner_hash,citations=citations):
            if kind=='analysis' and symbol:
                res=await retrieve_analysis(symbol,query,limit=limit)
            elif kind=='material' and symbol:
                res=await retrieve_materials(symbol,query,limit=limit)
            else:
                res=await retrieve_faq(query)
        return {**res,'_citations':citations}
    if name=='read_workspace':
        from .workspace_tools import read_workspace
        return await asyncio.to_thread(read_workspace,args,context)
    if name=='query_system_status':
        kind=args['kind']
        with SessionLocal() as db:
            if kind=='jobs':
                # The durable action ledger is owner scoped; guests cannot infer owner tasks.
                if not is_owner:return error('owner_login_required')
                filters=' AND (CAST(id AS text)=:job_id OR CAST(job_id AS text)=:job_id)' if args.get('job_id') else ''
                if args.get('symbol'):
                    # Resolve symbol from stored results, underlying jobs or the exact
                    # frozen operation. Filter before LIMIT, never relabel another job.
                    filters+=''' AND (result->>'symbol'=:symbol
                        OR job_id IN (SELECT id FROM forecast_jobs_v2 WHERE symbol=:symbol)
                        OR job_id IN (SELECT j.id FROM material_analysis_jobs j
                            LEFT JOIN sec_filing_inventory f ON j.source_type='official_filing' AND f.id=j.source_id
                            LEFT JOIN uploaded_evidence u ON j.source_type='uploaded_media' AND u.id=j.source_id
                            WHERE f.symbol=:symbol OR u.symbol=:symbol)
                        OR EXISTS (SELECT 1 FROM agent_consents c,
                            jsonb_array_elements(CAST(c.operations AS jsonb)) WITH ORDINALITY AS operation(value,position)
                            WHERE c.owner_hash=:owner
                            AND agent_action_requests.request_key=CAST(c.id AS text)||'.'||CAST(operation.position-1 AS text)
                            AND operation.value->'arguments'->>'symbol'=:symbol))'''
                rows=db.execute(text('SELECT * FROM agent_action_requests WHERE owner_hash=:owner'+filters+' ORDER BY created_at DESC LIMIT :limit'),{**args,'owner':context.owner_hash}).mappings().all()
            elif kind=='knowledge':
                from ..knowledge.models import KnowledgeDocument
                statement=select(KnowledgeDocument).where(or_(KnowledgeDocument.scope=='public',KnowledgeDocument.owner_hash==context.owner_hash))
                if args.get('symbol'):statement=statement.where(KnowledgeDocument.symbol==args['symbol'])
                if args.get('job_id'):statement=statement.where(KnowledgeDocument.id==uuid.UUID(args['job_id']))
                rows=[{'id':str(r.id),'title':r.title,'status':r.status,'source_type':r.source_type} for r in db.scalars(statement.limit(args['limit']))]
            else:
                table={'monitor':'official_monitor_runs_v2','evaluations':'forecast_evaluations_v2','replays':'forecast_jobs_v2','revisions':'forecast_jobs_v2'}[kind]
                from sqlalchemy import inspect
                available={c['name'] for c in inspect(db.bind).get_columns(table)}
                columns=[n for n in ('id','symbol','status','created_at','started_at','completed_at','evaluated_at','target_date') if n in available]
                filters=' WHERE symbol=:symbol' if args.get('symbol') and 'symbol' in available else ''
                if args.get('symbol') and 'symbol' not in available:
                    if kind=='monitor':filters+=(' AND ' if filters else ' WHERE ')+"jsonb_exists(per_symbol_results,:symbol)"
                    else:return error('symbol_filter_unavailable')
                if args.get('job_id'):filters+=(' AND ' if filters else ' WHERE ')+"CAST(id AS text)=:job_id"
                if kind=='replays':filters+=(' AND ' if filters else ' WHERE ')+"time_mode='historical_research'"
                # "Is the revision done?": the manual revisions of a forecast, newest first.
                if kind=='revisions':filters+=(' AND ' if filters else ' WHERE ')+"kind='manual_revision'"
                rows=db.execute(text('SELECT '+','.join(columns)+' FROM '+table+filters+' ORDER BY '+('created_at' if 'created_at' in available else 'id')+' DESC LIMIT :limit'),args).mappings().all()
            if kind=='jobs':
                from .actions import _status
                rows=[{'id':str(r['id']),**_status(db,dict(r))} for r in rows]
            return result([dict(r) for r in rows],kind)
    if name in {'query_research_queue','add_to_research_queue','remove_from_research_queue'}:
        if not is_owner:
            action={'event':'client_action','id':str(uuid.uuid4()),'action':{'query_research_queue':'show_queue','add_to_research_queue':'queue_add','remove_from_research_queue':'queue_remove'}[name],**args}
            if emit:await emit(action)
            return result([{'client_action':action,'status':'client_requested'}],'browser')
        from ..agent_chat_models import AgentResearchQueue
        with SessionLocal() as db:
            # Concurrent add/remove cannot lose one another's queue changes.
            db.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'),{'key':'queue:'+context.owner_hash})
            row=db.get(AgentResearchQueue,context.owner_hash);symbols=list(row.symbols if row else [])
            if name!='query_research_queue':
                symbol=args['symbol']
                if name=='add_to_research_queue' and symbol not in symbols:
                    if len(symbols)>=30:return error('queue_full')
                    symbols.append(symbol)
                if name=='remove_from_research_queue':symbols=[s for s in symbols if s!=symbol]
                if row:row.symbols=symbols
                else:db.add(AgentResearchQueue(owner_hash=context.owner_hash,symbols=symbols))
                db.commit()
            action={'event':'client_action','id':str(uuid.uuid4()),'action':'queue_sync','symbols':symbols}
            if emit:await emit(action)
            return result([{'symbols':symbols}],'owner queue')
    if name in {'select_stock','open_page'}:
        action={'event':'client_action','id':str(uuid.uuid4()),'action':name,**args}
        if emit:await emit(action)
        return result([{'client_action':action}],'browser')
    if name=='review_filing':
        from ..models import SecFilingInventory
        from ..sec_filings import review_inventory_filing
        with SessionLocal() as db:
            row=db.get(SecFilingInventory,uuid.UUID(args['source_id']))
            if not row:return error('source_not_found')
            review_inventory_filing(symbol=row.symbol,accession_number=row.accession_number,decision=args['decision'],note=args['note'],db=db)
            db.commit();return result([{'source_id':args['source_id'],'decision':args['decision']}],'relevance review')
    if name=='list_watch_rules':
        from .. import watch_rules_view
        if not is_owner:return error('owner_login_required')
        return result(await asyncio.to_thread(watch_rules_view.rows,context.owner_hash),'watch rules')
    if name in {'set_watch_rule','delete_watch_rule'}:
        # Only reached through execute_reversible: the owner pressed the card; the fields are the ones the card showed.
        from .. import watch_rules
        if not is_owner:return error('owner_login_required')
        try:
            if name=='delete_watch_rule':
                gone=await asyncio.to_thread(watch_rules.delete,context.owner_hash,args['rule_id'])
                return result([{'status':'deleted','symbol':gone['symbol'],'rule_id':gone['id'],'title':gone['text']}],'watch rule')
            fields=args.get('_fields')
            if not fields:return error('confirmation_required')
            if args.get('rule_id'):saved=await asyncio.to_thread(lambda:watch_rules.update(context.owner_hash,args['rule_id'],fields,args['quote'],replace=True))
            else:saved=await asyncio.to_thread(watch_rules.create,context.owner_hash,fields,args['quote'])
        except watch_rules.WatchRuleError as exc:return {'ok':False,'data':[],'error_code':exc.code,'reason':exc.reason,'hint':exc.reason}
        return result([{'status':'saved','symbol':saved['symbol'],'rule_id':saved['id'],'title':saved['text']}],'watch rule')
    if name in {'set_watch_preset','set_alert_settings'}:
        # Only reached through execute_reversible: the owner pressed the card; the values are the ones the card showed.
        from .. import watch_presets,watch_rules
        if not is_owner:return error('owner_login_required')
        fields=args.get('_fields')
        if not fields:return error('confirmation_required')
        try:
            if name=='set_alert_settings':
                saved=await asyncio.to_thread(watch_presets.set_settings,context.owner_hash,fields['sensitivity'],fields['short_moves'])
                return result([{'status':'saved','sensitivity':saved['sensitivity'],'short_moves':saved['short_moves']}],'alert settings')
            row=await asyncio.to_thread(watch_presets.put,context.owner_hash,fields['key'],fields['enabled'],fields['levels'])
        except watch_rules.WatchRuleError as exc:return {'ok':False,'data':[],'error_code':exc.code,'reason':exc.reason,'hint':exc.reason}
        return result([{'status':'saved','key':row['key'],'enabled':row['enabled'],'title':row['text']}],'watch preset')
    if name=='list_routines':
        # A bot lists its own routines; all_bots (or the default bot) lists every bot's, each with its bot.
        from .. import agent_tasks as tasks
        from .. import agent_bots as bots
        if not is_owner:return error('owner_login_required')
        bot=getattr(context,'bot_id',None)
        every=args['all_bots'] or not bot or getattr(context,'bot_is_default',False)
        rows=await asyncio.to_thread(tasks.list_tasks,context.owner_hash,None if every else bot)
        names={b['id']:b['name'] for b in await asyncio.to_thread(bots.list_bots,context.owner_hash)}
        return result([{'id':t['id'],'name':t['name'],'bot':names.get(t['bot_id']) or '','kind':t['kind'],
                        'schedule_kind':t['schedule_kind'],'schedule_time':t['schedule_time'],'schedule':tasks.schedule_text(t),'enabled':t['enabled'],
                        'instruction':(t['instruction'] or '')[:300],'symbols':t['symbols'],'next_run_at':t['next_run_at'],
                        'last_status':t['last_status_label']} for t in rows],'routines')
    if name in {'update_routine','delete_routine'}:
        # Only reached through execute_reversible: the owner pressed the card naming this routine.
        from .. import agent_tasks as tasks
        if not is_owner:return error('owner_login_required')
        if name=='delete_routine':
            done=await asyncio.to_thread(tasks.delete_task,context.owner_hash,args['routine_id'])
            return result([{'status':'deleted','routine_id':args['routine_id']}],'bot routine') if done else error('routine_not_found')
        fields={k:args[k] for k in ROUTINE_FIELDS if args.get(k) is not None}
        if args.get('symbols') is not None:fields.update(symbols=args['symbols'],scope='symbols' if args['symbols'] else 'research_queue')
        try:task=await asyncio.to_thread(tasks.update_task,context.owner_hash,args['routine_id'],fields)
        except tasks.TaskError as exc:return error(str(exc))
        if task is None:return error('routine_not_found')
        return result([{'status':'updated','name':task['name'],'schedule_kind':task['schedule_kind'],'enabled':task['enabled'],
                        'next_run_at':task.get('next_run_at')}],'bot routine')
    if name=='save_skill':
        # Only reached through execute_reversible: the card was pressed and the frozen operation matched.
        from .. import agent_skills as skills
        if not is_owner:return error('owner_login_required')
        fields={k:v for k,v in args.items() if not k.startswith('_')}
        try:saved=await asyncio.to_thread(skills.save,context.owner_hash,fields,status=args.get('_status') or 'active')
        except skills.SkillError as exc:return error(str(exc))
        return result([{'status':'saved','id':saved['id'],'name':saved['name'],'skill_status':saved['status'],'link':'#skills/'+saved['id']}],'skill library')
    if name in {'create_bot','update_bot','manage_skill','set_default_model','set_model_role','set_channel_prefs','apply_role_template','undo_role_template'}:
        # Only reached through execute_reversible: the owner pressed the card; each is the service function its HTTP route calls.
        from . import directory_ops
        if not is_owner:return error('owner_login_required')
        try:data,source=await asyncio.to_thread(directory_ops.execute,name,args,context.owner_hash)
        except directory_ops.Refusal as exc:return {'ok':False,'data':[],'error_code':exc.code,'reason':exc.reason,'hint':exc.hint}
        return result([data],source)
    if name in {'record_trade','set_available_funds','set_position_plan','delete_transaction'}:
        # Only reached through execute_reversible: the owner pressed the card, and the frozen operation matched.
        from .. import portfolio
        if not is_owner:return error('owner_login_required')
        try:value=await asyncio.to_thread(portfolio.apply_tool,name,context.owner_hash,args)
        except portfolio.PortfolioError as exc:return {'ok':False,'data':[],'error_code':exc.code,'reason':exc.reason,'hint':exc.reason}
        # The sentinel's copy of positions and plans follows every portfolio write.
        from ..sentinel_bridge import refresh_sentinel_snapshot
        await asyncio.to_thread(refresh_sentinel_snapshot)
        return result([{k:v for k,v in value.items() if k!='ok'}],'portfolio')
    if name=='create_routine':
        # Only reached through execute_reversible; the bot is the proposing turn's, frozen in the operation.
        from .. import agent_tasks as tasks
        if not is_owner:return error('owner_login_required')
        fields={**{k:args[k] for k in ROUTINE_FIELDS if args.get(k) is not None},'scope':'symbols' if args['symbols'] else 'research_queue',
                'symbols':args['symbols'],'bot_id':args.get('_bot_id')}
        fields.setdefault('kind','brief')
        try:task=await asyncio.to_thread(tasks.create_task,context.owner_hash,fields)
        except tasks.TaskError as exc:return error(str(exc))
        return result([{'status':'created','name':task['name'],'schedule_kind':task['schedule_kind'],
                        'next_run_at':task.get('next_run_at')}],'bot routine')
    if name in {'remember','forget'}:
        # Only reached through execute_reversible: the card was pressed and the frozen operation matched.
        from .. import agent_profile as profile
        if not is_owner:return error('owner_login_required')
        if name=='forget':
            item=await asyncio.to_thread(profile.archive_item,context.owner_hash,args['item_id'],by=_memory_actor(context,args))
            if not item:return error('profile_item_not_found')
            # A monthly-review guess is reduced to a fingerprint when forgotten: its text is gone, so only the handle comes back.
            gone=item.get('status')=='rejected'
            return result([{'status':'forgotten','handle':item['handle'],**({} if gone else {'text':item['text']})}],'owner profile')
        # The quote was checked against the user's message when the card was made (Turn.propose), and
        # the operation carrying it is frozen under the confirmation token; here only its shape is checked.
        # The layer is the frozen bot_id the server set from the proposing turn (None: global).
        if args.get('basis')=='noticed':
            # A guess the model wrote on the spot: the quote was checked against his words when the operation was prepared (kernel act).
            try:value=await asyncio.to_thread(profile.add_noticed,context.owner_hash,kind=args['kind'],text=args['text'],quote=args['quote'],
                                              bot_id=args.get('_bot_id'),message_id=args.get('_source_message_id'),by=_memory_actor(context,args))
            except profile.ProfileError as exc:return error(str(exc))
            if value['status']!='added':return error('already_noticed' if value['status']=='duplicate' else 'rejected_before')
            return result([{'status':'noticed','text':value['item']['text'],'handle':value['item']['handle']}],'owner profile')
        try:value=await asyncio.to_thread(profile.add_item,context.owner_hash,origin='explicit',message=args['quote'],
                                          source_message_id=args.get('_source_message_id'),bot_id=args.get('_bot_id'),by=_memory_actor(context,args),
                                          **{k:args[k] for k in ('kind','topic','text','quote')})
        except profile.ProfileError as exc:return error(str(exc))
        if value.get('status')=='skipped':return error(value.get('reason') or 'profile_write_skipped')
        return result([{'status':'remembered','text':value['item']['text'],'handle':value['item']['handle']}],'owner profile')
    if name in {'record_view','drop_view'}:
        # Only reached through execute_reversible (the kernel's tier 1 or a pressed card): the owner's own view of one company, in his words.
        from .. import owner_views
        if not is_owner:return error('owner_login_required')
        if name=='drop_view':
            dropped=await asyncio.to_thread(owner_views.drop,context.owner_hash,args['symbol'],by=_memory_actor(context,args))
            return result([{'status':'dropped','symbol':dropped['symbol'],'text':dropped['text']}],'owner view') if dropped else error('view_not_found')
        try:value=await asyncio.to_thread(owner_views.record,context.owner_hash,args['symbol'],args['text'],args['quote'],
                                          args.get('_source_message_id'),args.get('_conversation_id'),args.get('_turn_id'),by=_memory_actor(context,args))
        except owner_views.ViewError as exc:return error(str(exc))
        return result([{'status':value['status'],'symbol':value['view']['symbol'],'text':value['view']['text'],
                        'replaced':(value['replaced'] or {}).get('text')}],'owner view')
    if name=='rate_alert':
        # Only reached through execute_reversible (the kernel's tier 1 or a pressed card): his verdict on a message he got, in his words.
        from .. import alert_feedback as feedback
        if not is_owner:return error('owner_login_required')
        match=args.get('_match')
        if not isinstance(match,dict):
            found=await asyncio.to_thread(feedback.resolve,context.owner_hash,about=args['about'],symbol=args.get('symbol'))
            if found is None:return rate_alert_refusal(args['about'],args.get('symbol'))
            match=feedback.frozen(found)
        try:await asyncio.to_thread(feedback.record,context.owner_hash,match['target'],match['target_id'],args['verdict'],'chat',
                                    symbol=match.get('symbol'),kind=match.get('kind'),text=match.get('text'))
        except ValueError as exc:return error(str(exc))
        acknowledged=None
        if match['target']=='sentinel':
            # A verdict on an alert also says he has seen it, as the button does: the sentinel stops escalating.  It runs at once only
            # when nothing from outside was read this turn (query_alerts is his own state), or he pressed the card himself.
            try:
                from sentinel.store import Store,db_path
                await asyncio.to_thread(lambda:Store(db_path()).ack_alert(int(match['target_id'])))
                acknowledged=True
            except Exception:
                logger.exception('rate_alert ack failed alert=%s',match['target_id'])
                acknowledged=False
        row={'status':'recorded','recorded':rate_alert_line(match,args['verdict']),'target':match['target'],'target_id':match['target_id']}
        if acknowledged is False:row['note']='这条提醒没能顺带算作「收到」，如果它还在提醒，请在 Telegram 上按「收到」。'
        return result([row],'alert feedback')
    if name=='rate_answer':
        # Only reached through execute_reversible (the kernel's tier 1 or a pressed card): his 「好／不好」 on an earlier answer, in his words.
        # The match is frozen by act.prepare; without one there is no turn to exclude, so nothing is guessed.
        from .. import answer_feedback
        if not is_owner:return error('owner_login_required')
        match=args.get('_match')
        if not isinstance(match,dict) or not match.get('turn_id'):return rate_answer_refusal()
        try:row=await asyncio.to_thread(answer_feedback.record,context.owner_hash,match.get('conversation_id'),match['turn_id'],args['verdict'],'chat',args.get('reason'))
        except ValueError as exc:return error(str(exc))
        if row is None:return rate_answer_refusal()
        return result([{'status':'recorded','recorded':rate_answer_line(match,args['verdict'],row.get('reason')),'message_id':row['message_id']}],'answer feedback')
    if name=='search_configured_news':
        from .. import fin_news_engine as news
        call=asyncio.to_thread(
            news.search_configured_news,
            query=args.get('query'),
            tickers=args.get('tickers'),
            keywords=args.get('keywords'),
            source_ids=args.get('source_ids'),
            since=args.get('since'),
            until=args.get('until'),
            limit=args.get('limit',10),
            refresh_first=bool(args.get('refresh_first',False)),
        )
        if not flag('FINBOT_NEWS_REFRESH_BOUND',True):return await call
        # Backstop above the refresh limit: one call may never hang the turn for minutes.
        try:limit=max(1.0,float(os.environ.get('FINBOT_NEWS_SEARCH_TOOL_TIMEOUT_SECONDS') or 30))
        except ValueError:limit=30.0
        try:return await asyncio.wait_for(call,timeout=limit)
        except TimeoutError:return error('tool_timeout')
    if name=='search_x':
        from .. import x_search
        if not is_owner:return error('owner_login_required')
        if getattr(context,'unattended',False):return error('unattended_read_only')
        return await x_search.search(args,owner_hash=context.owner_hash)
    if name=='manage_news_source':
        from .. import fin_news_engine as news
        action=args['action'];source_id=args.get('source_id')
        if action=='list':return await asyncio.to_thread(news.list_news_sources)
        if action=='dry_run':return await asyncio.to_thread(news.dry_run_news_source,source_id)
        if action=='diagnose':return await asyncio.to_thread(news.diagnose_news_source,source_id)
        if not is_owner:return error('owner_login_required')
        if action=='upsert':
            spec={k:v for k,v in args.items() if k not in {'action','source_id','require_confirm_on_major_change','enabled','switch_to_first','require_confirm'} and v is not None}
            if args.get('enabled') is not None:spec['enabled']=args['enabled']
            return await asyncio.to_thread(
                news.upsert_news_source,{**spec,'id':source_id},
                require_confirm_on_major_change=bool(args.get('require_confirm_on_major_change')),
                owner_hash=context.owner_hash)
        if action=='set_enabled':return await asyncio.to_thread(news.disable_news_source,source_id,enabled=bool(args['enabled']))
        if action=='set_alternate':
            return await asyncio.to_thread(
                news.set_news_source_alternate,source_id,args.get('alternates') or [],
                switch_to_first=bool(args.get('switch_to_first')),require_confirm=bool(args.get('require_confirm')),
                owner_hash=context.owner_hash)
        if action=='repair':
            return await asyncio.to_thread(
                news.repair_news_source_with_rea,source_id,
                require_confirm=args.get('require_confirm') is not False,owner_hash=context.owner_hash)
    return error('unknown_tool')


def execute_costly(operation,key,context):
    """Only called inside consent.execute after capability and payload validation."""
    name=operation['name'];args=operation['arguments'];credential=context.identity_credential
    if not owner_credential_matches(credential):raise ValueError('owner_login_required')
    if name in {'fetch_sec','refresh_sec'} and operation.get('discovery'):
        from .sec_sources import register_confirmed
        register_confirmed(operation)
    if name in {'fetch_sec','refresh_sec','analyze','import','index','forecast'}:
        from .actions import execute_action
        payload={k:v for k,v in args.items() if v is not None and k!='form'}
        value=execute_action(credential=credential,request_key=key,action=name,payload=payload)
        return {'ok':value.get('status') not in {'failed','blocked_data'},**value}
    if name in {'start_historical_replay','revise_forecast','retry_document_index','translate_content','review_knowledge_candidate','import_sources','withdraw_knowledge_document'}:
        from .workspace_tools import write_workspace
        return write_workspace(name,args,key,context)
    if name=='save_material_evidence':
        from ..manual_evidence import create_uploaded_evidence
        from ..knowledge.models import KnowledgeUploadOwner
        raw_pub=args['published_at']
        pub_dt=publication_time(raw_pub)
        content_bytes=args['content'].encode('utf-8')
        title=args['title']
        filename=f"{title[:50].replace('/','_')}.md"
        with SessionLocal() as db:
            evidence,created=create_uploaded_evidence(
                symbol=args['symbol'],
                title=title,
                source_url=args['source_url'],
                published_at=pub_dt,
                credibility_stars=args.get('credibility_stars',3),
                credibility_reason=args.get('credibility_reason',''),
                impact_severity=args.get('impact_severity','medium'),
                filename=filename,
                content=content_bytes,
                db=db,
            )
            if created and context.identity_credential:
                db.add(KnowledgeUploadOwner(upload_id=evidence.id,owner_hash=context.owner_hash))
                db.commit()
            return {
                'ok':True,
                'data':[{
                    'id':str(evidence.id),
                    'symbol':evidence.symbol,
                    'title':evidence.title,
                    'created':created,
                    'status':'created' if created else 'already_exists'
                }]
            }
    if name=='ingest_web_source':
        from .web_sources import freeze_snapshot,save_snapshot,canonical_url
        snapshot=operation.get('snapshot')
        if not isinstance(snapshot,dict):raise ValueError('confirmation_snapshot_missing')
        page=freeze_snapshot(snapshot)
        if page['content_hash']!=snapshot.get('content_hash') or canonical_url(args['url'])!=page['url']:raise ValueError('confirmation_snapshot_mismatch')
        from .evidence import gate_row
        aliases = list(operation.get('entity_aliases', []))
        if args.get('company') and args['company'] not in aliases: aliases.append(args['company'])
        if args.get('symbol') and args['symbol'] not in aliases: aliases.append(args['symbol'])
        accepted,gated=gate_row('',{**page,'source_type':'web'},company=args.get('company'),symbol=args.get('symbol'),metrics=[],entity_aliases=aliases)
        if not accepted:raise ValueError(gated)
        if operation.get('condition'):
            from .web_sources import timestamp
            before=timestamp(operation['condition'].get('saved_date'));after=timestamp(page.get('published_at'))
            if not before or not after or after<before:
                return {'ok':True,'status':'completed_without_write','reason':'not_newer'}
        with SessionLocal() as db:
            value=save_snapshot(db,context.owner_hash,page,symbol=args.get('symbol'),company=args.get('company'),library=not args.get('knowledge_only'));db.commit()
            # The report names the material the user reviewed, not just its ticker.
            return {**value,'title':str(page.get('title') or args['url']).strip()[:300] or args['url']}
    if name=='initialize_prices':
        from ..market_data_ingestion import ingest_market_data
        now=datetime.now(UTC);value=ingest_market_data([args['symbol']],(now-timedelta(days=args['days'])).date(),now.date(),now)
        return {'ok':value.status=='completed','run_id':str(value.run_id),'status':value.status,'inserted':value.inserted_count}
    if name=='scan_official':
        from ..official_monitor_v2 import scan_only
        days=args.get('days')
        with SessionLocal() as db:
            # A confirmed scan reports its own SEC outcome inside the chat request, so the
            # scheduled monitor's evaluator and learner are not part of this effect.
            # A backfill reads one SEC submissions page per covered year, so the page
            # budget follows the requested range instead of a fixed three pages.
            pages=max(3,(days+364)//365+1) if days else 3
            value=scan_only(db=db,symbols=[args['symbol']],max_pages=min(12,pages),
                            lookback_days=days);db.commit()
            scanned=[{'symbol':item.symbol,'status':item.status,'discovered':item.discovered_count,
                      'created':item.created_count,'queued':item.queued_count,
                      **({'error':item.error} if item.error else {})} for item in value.symbols]
            return {'ok':value.status=='succeeded','run_id':str(value.run_id),'status':value.status,'scanned':scanned}
    raise ValueError('unknown_tool')
