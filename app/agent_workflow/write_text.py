"""What the kernel's writes show and report, kept from the old turn (``direct.py``, removed in stage 6b): the card titles of each
operation, the words of a routine card, a revision card's notices, the facts of an executed write, and the two lists other modules
read (the provider failures worth one more try, the prefixes of a card button's value).  Moved here unchanged."""
import os
import uuid

from . import tools

RETRYABLE_PROVIDER={'provider_protocol_too_large','provider_incomplete_stream','provider_incomplete_response',
 'provider_timeout','provider_network_error','provider_error','provider_incompatible_response'}

CONTROL_PREFIXES=('confirm:','authorize:','cancel:','change:')

# Display copy only: these never choose a route or a tool.  The confirmation card used to show the
# tool identifier and the raw arguments, so the user read "title: analyze" and a bare UUID.
WRITE_TITLES={
 'analyze':'AI 材料分析','import':'导入知识库','index':'构建向量索引','fetch_sec':'拉取 SEC 原文',
 'refresh_sec':'刷新 SEC 原文','forecast':'生成研究预测','revise_forecast':'修正预测',
 'start_historical_replay':'历史回放','ingest_web_source':'保存网页为来源',
 'save_material_evidence':'保存上传材料','withdraw_knowledge_document':'撤回知识文档',
 'initialize_prices':'初始化历史行情','scan_official':'扫描官方申报目录',
 'translate_content':'翻译内容','review_knowledge_candidate':'审核知识候选',
 'retry_document_index':'重试文档索引','import_sources':'批量导入来源',
 'add_to_research_queue':'加入研究队列','remove_from_research_queue':'移出研究队列',
 'remember':'记住这条偏好','forget':'忘掉这条偏好','create_routine':'新建例行任务','update_routine':'修改例行任务','delete_routine':'删除例行任务','save_skill':'保存技能',
 'review_filing':'申报相关性核验',
 'record_trade':'记录持仓','set_available_funds':'设置可用资金','set_position_plan':'保存持仓计划',
}

def routine_when(schedule):
    from ..agent_tasks import schedule_text
    return schedule_text(schedule)

def routine_fields(args):
    """The fields of a routine call as ``POST``/``PATCH /tasks`` take them (what ``tools`` writes on the press)."""
    fields={k:args[k] for k in tools.ROUTINE_FIELDS if args.get(k) is not None}
    if args.get('symbols') is not None:fields.update(symbols=args['symbols'],scope='symbols' if args['symbols'] else 'research_queue')
    return fields

def skill_names(owner):
    """The owner's skills by id, for a card that names one; a lookup that fails names none."""
    try:
        from ..agent_skills import list_skills
        return {s['id']:s['name'] for s in list_skills(owner)}
    except Exception:return {}

def _config_words(config):
    """An alerts routine's checks in words: what it looks at and the price lines."""
    config=config or {}
    lines=[f'{l["symbol"]} '+'、'.join(([f'高于 {l["above"]:g}'] if l.get('above') is not None else [])+([f'低于 {l["below"]:g}'] if l.get('below') is not None else []))
           for l in config.get('price_lines') or []]
    return '；'.join([f'新申报 {"开" if config.get("filings",True) else "关"}',f'新闻 {"开" if config.get("news",True) else "关"}',
                      '价位线 '+('、'.join(lines) if lines else '无')])

def _scope_words(task):
    return '、'.join(task.get('symbols') or []) or '研究队列'

def _cut(text,limit=80):
    text=' '.join(str(text or '').split())
    return text if len(text)<=limit else text[:limit]+'…'

def _skill_words(skill_id,skills):
    return '无' if not skill_id else (skills or {}).get(skill_id) or '一个已选的技能'

def routine_changes(args,task,new=None,skills=None):
    """What an update_routine card changes, each line old → new, in the owner's words.  ``new`` is the task as the press
    would leave it (``agent_tasks.preview_task``); without it the arguments are laid over the saved task."""
    new=new or {**task,**{k:v for k,v in args.items() if v is not None and k in task}}
    parts=[]
    if args.get('name') and new['name']!=task['name']:parts.append(f'名称：{task["name"]} → {new["name"]}')
    if args.get('kind') and new['kind']!=task['kind']:parts.append(f'类型：{KIND_WORDS.get(task["kind"],task["kind"])} → {KIND_WORDS.get(new["kind"],new["kind"])}')
    if any(args.get(k) is not None for k in ('schedule_kind','schedule_time','every_value','every_unit','max_runs')) and routine_when(new)!=routine_when(task):
        parts.append(f'频率：{routine_when(task)} → {routine_when(new)}')
    if args.get('symbols') is not None and _scope_words(new)!=_scope_words(task):parts.append(f'范围：{_scope_words(task)} → {_scope_words(new)}')
    if args.get('instruction') and new.get('instruction')!=task.get('instruction'):parts.append(f'每次运行：{_cut(task.get("instruction")) or "无"} → {new["instruction"]}')
    if args.get('enabled') is not None and bool(new['enabled'])!=bool(task['enabled']):parts.append('状态：运行中 → 暂停' if not new['enabled'] else '状态：暂停 → 运行中')
    if args.get('channel') is not None and new['channel']!=task['channel']:parts.append(f'通知渠道：{CHANNEL_WORDS.get(task["channel"],task["channel"])} → {CHANNEL_WORDS.get(new["channel"],new["channel"])}')
    if args.get('skill_id') is not None and new.get('skill_id')!=task.get('skill_id'):parts.append(f'技能：{_skill_words(task.get("skill_id"),skills)} → {_skill_words(new.get("skill_id"),skills)}')
    if args.get('config') is not None and new.get('config')!=task.get('config'):parts.append(f'检查项：{_config_words(task.get("config"))} → {_config_words(new.get("config"))}')
    return '；'.join(parts) or '没有实际变化（和现在一样）'

def routine_created(new,skills=None):
    """What a create_routine card says each run does, who is told, and how to undo it."""
    if new['kind']=='alerts':lines=['每次运行：检查'+_config_words(new.get('config'))+'（不调用模型）']
    else:lines=[f'每次运行：{new["instruction"]}']
    if new.get('scope')=='symbols' or new.get('symbols'):lines.append('范围：'+_scope_words(new))
    if new['kind']=='alerts' and new['channel']=='telegram':lines.append('通知：也发 Telegram')
    if new.get('skill_id'):lines.append('技能：'+_skill_words(new['skill_id'],skills))
    return '；'.join(lines)+'（可在「例行任务」页暂停、修改或删除）'

KIND_WORDS={'brief':'简报','alerts':'盯盘（不调用模型）'}

CHANNEL_WORDS={'inbox':'只在对话里','telegram':'也发 Telegram'}

REVISION_CARD_LIMIT=10

SOURCE_KIND_TITLES={'official_filing':'SEC 申报','uploaded_media':'上传材料','ai_analysis':'已保存的 AI 分析',
 'faq':'研究问答','upload':'上传材料','sec':'SEC 申报','analysis':'AI 分析'}

def source_display_title(source_type,source_id):
    """The saved title of a source, for the confirmation card.  Never a bare identifier."""
    from ..database import SessionLocal
    try:identity=uuid.UUID(str(source_id))
    except (TypeError,ValueError):return None
    try:
        with SessionLocal() as db:
            if source_type=='uploaded_media':
                from ..models import UploadedEvidence
                row=db.get(UploadedEvidence,identity);return row.title if row else None
            if source_type=='official_filing':
                from ..models import SecFilingInventory
                row=db.get(SecFilingInventory,identity)
                return (row.content_document_name or row.primary_document or row.form) if row else None
            if source_type=='ai_analysis':
                from ..material_analysis_models import MaterialAnalysisVersion
                row=db.get(MaterialAnalysisVersion,identity);return f"AI 分析 v{row.version_no}" if row else None
    except Exception:return None
    return None

EXECUTION_FACT_KEYS=('action','status','ok','error_code','title','filename','source_url','symbol','created','inserted',
                     'indexed','queued_chunks','job_id','reason','message','scanned')

def ticked_positions(value: str,card: dict) -> list[int]:
    """The options the user ticked on a revision card: distinct, on the card, within its limits."""
    options={str(o.get('value')) for o in card.get('options') or [] if isinstance(o,dict)}
    limits=card.get('select') or {}
    picks=value.split('.') if value else []
    if not picks or len(set(picks))!=len(picks) or not set(picks)<=options:raise ValueError('confirmation_parameter_mismatch')
    if not int(limits.get('min',1))<=len(picks)<=int(limits.get('max',REVISION_CARD_LIMIT)):raise ValueError('confirmation_parameter_mismatch')
    return [int(p) for p in picks]

def material_words(material: dict) -> str:
    """A material as the user knows it: its title, what it is and when it was published."""
    title=material.get('title') or '这份材料'
    detail='，'.join(x for x in (material.get('kind'),(str(material.get('published_at') or '')[:10]+' 发布') if material.get('published_at') else '') if x)
    return f'《{title}》'+(f'（{detail}）' if detail else '')

def revision_notice(plan: dict) -> str:
    """Why a forecast cannot be revised now, in the user's terms, with the next step to take."""
    symbol=plan.get('symbol') or '这只股票'
    status=plan.get('status')
    if status=='no_forecast':
        return f'{symbol} 还没有已保存的预测，所以没有可以修订的对象。可以让我先生成一个预测。'
    if status=='version_not_found':
        return f'没有找到要修订的 {symbol} 预测版本，可能已经不存在。可以先问我「{symbol} 现在的预测是什么」，再说要修订哪一版。'
    version=f'v{plan.get("version_no")}';decided=str(plan.get('decision_at',''))[:10]
    if status in {'target_expired','version_not_revisable'}:
        target=plan.get('target_end_date')
        when=f'目标日 {target} 已经过了' if status=='target_expired' and target else '目标设置无效'
        return f'{symbol} 这份预测（{version}，{decided} 作出）的{when}，不能再修订。可以查看它的评估结果，或让我生成一个新预测。'
    start=str(plan.get('window_start',''))[:10];end=str(plan.get('window_end',''))[:10]
    named=[f'- 你提到的{material_words(m)}：{m["reason_text"]}。' for m in plan.get('mentioned') or [] if not m.get('category')]
    named_ids={m.get('source_id') for m in plan.get('mentioned') or []}
    recent=[f'- {material_words(m)}：{m["reason_text"]}。' for m in plan.get('excluded') or [] if m.get('source_id') not in named_ids]
    why=('\n\n'+'\n'.join(named) if named else '')+('\n\n资料库里最近的材料为什么不算：\n'+'\n'.join(recent) if recent else '')
    return (f'{symbol} 当前的预测是 {version}（{decided} 作出）。能用来修订它的材料有两类：\n'
            f'- 预测后 7 天内（{decided} 至 {end}）发布的新材料；\n'
            f'- 预测前 30 天内（{start} 起）发布、但在这次预测之后才收录进资料库的材料。\n'
            '已经用在这次预测里、内容和核验状态都没有变化的材料不算。资料库里目前没有符合条件的材料，所以现在还不能修订。'
            +why+'\n\n'
            '有了新材料（例如保存一篇新闻、上传材料或拉取新的 SEC 申报）后再来修订；如果想按最新的行情和资料重新预测，可以让我生成一个新预测。')

def execution_facts(value: dict,operations: list|None=None) -> list[dict]:
    """The facts of a confirmed execution, flattened, with no prose of any kind.

    A consent result is ``{data:[{outcome:{data:[...]}}]}`` for batched writes and a flat row for a
    single one, so each fact is merged most-specific-last.  The model narrates these; the key list
    above is the whole vocabulary it may use, so a report cannot invent an outcome.  A handler that
    reports only ``ok`` (the research queue) still names what ran: the card's operation at the same
    position supplies the action and the symbol.
    """
    rows=[]
    for index,item in enumerate(value.get('data') or []):
        if not isinstance(item, dict):continue
        operation=operations[index] if operations and index<len(operations) and isinstance(operations[index],dict) else {}
        arguments=operation.get('arguments') if isinstance(operation.get('arguments'),dict) else {}
        known={k:v for k,v in {'action':operation.get('name'),'symbol':arguments.get('symbol')}.items() if v}
        outcome=item.get('outcome') if isinstance(item.get('outcome'),dict) else {}
        data=item.get('data')
        # A handler that reports one object (a queued job) is one row, not "no status, so done".
        nested=outcome.get('data') if isinstance(outcome.get('data'),list) else (
            data if isinstance(data,list) else [data] if isinstance(data,dict) else [])
        for entry in nested or [{}]:
            source=entry if isinstance(entry,dict) else {}
            merged={**known,**item,**outcome,**source}
            fact={k:merged[k] for k in EXECUTION_FACT_KEYS if merged.get(k) is not None}
            if fact:rows.append(fact)
    return rows or [{'status':'complete','ok':value.get('ok',True)}]

def library_note(value: dict,language: str='Chinese') -> str:
    """Where a confirmed save landed in 资料库, as a link the web page opens on that row (UX batch 2, P1).

    ``FINBOT_WEB_URL`` (the deployed page, e.g. the Pages address) makes the link absolute, so a Telegram
    reply carries one too; without it the link is the page's own hash route."""
    import os
    base=os.getenv('FINBOT_WEB_URL','').strip()
    links=[]
    for row in execution_rows(value):
        link=row.get('material_link') if isinstance(row,dict) else None
        if isinstance(link,str) and link.startswith('#materials?') and (row.get('symbol'),link) not in links:links.append((row.get('symbol'),link))
    if not links:return ''
    label='在资料库查看' if language=='Chinese' else 'Open in the library'
    return '\n\n'+'\n'.join(f'{label}：[资料库 · {symbol}]({base}{link})' for symbol,link in links[:4])

def execution_rows(value: dict) -> list[dict]:
    """The handler rows of a consent result, whether they sit at the top level or under ``data``."""
    rows=[]
    for item in value.get('data') or []:
        if not isinstance(item,dict):continue
        outcome=item.get('outcome') if isinstance(item.get('outcome'),dict) else item
        nested=outcome.get('data') if isinstance(outcome.get('data'),list) else [outcome]
        rows.extend(row for row in nested if isinstance(row,dict))
    return rows
