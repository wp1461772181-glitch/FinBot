"""Deterministic evidence validation; these parsers never select a route or tool."""
from __future__ import annotations
import copy
import functools
import hashlib
import itertools
import json
import math
import re
import unicodedata
from datetime import UTC, datetime
from ..agent_web_research import METRIC_GROUPS
from ..freshness import published_within


def contains(term: str, text: str) -> bool:
    pattern=re.escape(term)
    if term.isascii(): pattern=r'(?<![A-Za-z0-9])'+pattern+r'(?![A-Za-z0-9])'
    return bool(re.search(pattern,text,re.I))


_TITLE_PUNCTUATION=str.maketrans({'？':'','！':'','。':'','?':'','!':'','.':''})
_TITLE_RESTORED=str.maketrans({v:k for k,v in {'？':'','！':'','。':'','?':'','!':'','.':''}.items()})
# A quoted passage is one unit: a full stop inside the quotation (“……毛利率为 46.2%。” [1]) must not
# split the [1] away from the sentence it supports.
_QUOTE_PAIRS={'“':'”','「':'」','『':'』','‘':'’','"':'"'}


def _protect_passage_punctuation(match):
    return match.group(0).translate(_TITLE_PUNCTUATION)


def _protect_quotations(text):
    """Protect balanced quote punctuation in one pass, including long and nested quotes."""
    pieces=[];stack=[];start=0;last=0
    for index,char in enumerate(text):
        if char=='\n':
            stack.clear()
        elif stack and char==stack[-1]:
            stack.pop()
            if not stack:
                pieces.extend((text[last:start],text[start:index+1].translate(_TITLE_PUNCTUATION)))
                last=index+1
        elif char in _QUOTE_PAIRS:
            if not stack:start=index
            stack.append(_QUOTE_PAIRS[char])
    pieces.append(text[last:])
    return ''.join(pieces)


def cited_passages(answer):
    # A title in 《》 is one name even when it asks a question ("……哪一只更值得买入？"): its punctuation
    # does not end the sentence that cites it.
    protected=_protect_quotations(answer)
    protected=re.sub(r'《[^》\n]{0,300}》',_protect_passage_punctuation,protected)
    # Markdown block quotes have the same citation scope as quoted strings. Protect only
    # their own lines: a trailing source never authorizes surrounding ordinary prose.
    protected=re.sub(r'(?m)^\s*>[^\n]*',_protect_passage_punctuation,protected)
    # Both “fact[1]。” and “fact。[1]” bind the marker to the same sentence.
    normalized=re.sub(r'([。！？.!?])(\s*(?:\[\d+\]\s*)+)',lambda m:m[2].strip()+m[1],protected)
    return [part.translate(_TITLE_RESTORED) for part in re.split(r'[。！？\n]|(?<=[.!?])\s+',normalized)]


def normalized_period(text):
    text=unicodedata.normalize('NFKC',text).upper()
    for word,number in [('FIRST','1'),('SECOND','2'),('THIRD','3'),('FOURTH','4')]:
        text=re.sub(r'\b'+word+r' QUARTER\b','Q'+number,text)
    text=re.sub(r'第?([一二三四1-4])季度',lambda m:'Q'+dict(zip('一二三四','1234')).get(m[1],m[1]),text)
    text=re.sub(r'FISCAL\s+YEAR\s*','FY',text)
    return text


def period_pairs(text):
    text=normalized_period(text)
    pairs={(year,q) for q,year in re.findall(r'Q([1-4])(?:\s+OF)?[\s年,-]{0,5}((?:19|20)\d{2})',text)}
    pairs|={(year,q) for year,q in re.findall(r'((?:19|20)\d{2})[\s年,-]{0,5}Q([1-4])',text)}
    return pairs


def period_match(request: str, body: str) -> bool:
    request=normalized_period(request);body=normalized_period(body)
    from ..freshness import requested_years
    years=requested_years(request)
    if years and any(y not in body for y in years):return False
    requested_pairs=period_pairs(request)
    if requested_pairs and not requested_pairs<=period_pairs(body):
        quarters=set(re.findall(r'Q([1-4])',request))
        if quarters and not quarters<=set(re.findall(r'Q([1-4])',body)):return False
    return True


# The gate knows three structural metrics that are not synonyms of a text term.  When the classifier
# was limited to a fixed enum these arrived spelled exactly; now it copies the user's own wording, so
# "股价" and "已保存价格" must still reach the price branch and "提交日期" the date branch.
_STRUCTURAL_METRICS={
 'price':('price','close','收盘','股价','收盘价','价格','已保存价格','quote','ohlcv'),
 'date':('date','日期','时间','发布日期','提交日期','披露日期','filed_at','published_at'),
 'forecast':('forecast','预测','概率','probability','probabilities'),
}


def canonical_metric(name):
    """The gate's own name for a metric the user wrote in their own words."""
    text=' '.join(str(name or '').split()).strip()
    if not text:return ''
    folded=text.casefold()
    for canonical,terms in METRIC_GROUPS.items():
        if folded==canonical or any(folded==t.casefold() for t in terms):return canonical
    for canonical,terms in _STRUCTURAL_METRICS.items():
        if folded==canonical or any(folded==t.casefold() for t in terms):return canonical
    return text


# Which checks may only annotate a row instead of discarding it.  The course's rule is that recall
# answers "did we find it" and the model answers "is it enough": a source that is merely about a
# different period, or that words the metric differently, is evidence the model should see and judge.
# What stays a hard stop is data that cannot be trusted (a broken body) and a source about the wrong
# company, because attributing one company's numbers to another is the one error worth refusing.
# An explicit freshness window is the user's own constraint, not a relevance judgement, so it stays a
# hard filter.  What softens is wording: whether the text says 毛利率 or gross margin, whether the
# fiscal period is phrased the way the question phrased it.
SOFT_GATE_CHECKS={'requested_metric_missing','requested_period_missing','weak_question_coverage'}


def _gate_outcome(ok: bool,reason: str,soft: bool) -> tuple[bool,str]:
    """``soft`` turns the annotation-only checks into an accepted row that carries a note.

    The reason comes back prefixed with ``soft:`` so the caller can record the reservation on the
    row and the answer model can say the source is not on point instead of the source disappearing.
    """
    if ok:return True,reason
    if soft and reason.split(':',1)[0] in SOFT_GATE_CHECKS:return True,'soft:'+reason
    return False,reason


def _has_valid_http_url(value: object) -> bool:
    text = str(value or '').strip()
    return text.startswith(('http://', 'https://')) and '://' in text and len(text.split('://', 1)[1].strip('/')) >= 3


def gate_row(question: str, row: dict, *, symbol: str | None=None, company: str | None=None,
             metrics: list[str] | None=None, period: str | None=None, days_back: int | None=None,
             official_only: bool=False, now: datetime | None=None, entity_aliases: list[str] | None=None,
             soft: bool=False) -> tuple[bool,str]:
    kind=row.get('source_type','')
    is_configured_news=kind=='configured_news' or row.get('origin')=='configured_news'
    if is_configured_news and not _has_valid_http_url(row.get('url') or row.get('source_url')):
        return False,'missing_citation_url'
    web=kind in {'web','web_news','configured_news'} or 'url' in row
    if row.get('fetch_error') or row.get('body_hash_valid') is False:return False,'invalid_source_body'
    if official_only and kind not in {'official_filing','saved_filing'}:return False,'official_source_required'
    body=' '.join(str(row.get(k) or '') for k in ('excerpt','content','summary','text','answer','reasons'))
    title=str(row.get('title') or '')
    if not body.strip() and not any(k in row for k in ('close','first_close','last_close','probabilities','status','form')):
        metric=next((key for key,terms in METRIC_GROUPS.items() if any(contains(t,question) for t in terms)),None)
        return False,('requested_metric_missing:'+metric if metric else 'zero_evidence')
    if symbol and row.get('symbol') and row['symbol'].upper()!=symbol.upper():return False,'requested_entity_missing'
    allowed_entities = [x for x in (company, symbol, *(entity_aliases or [])) if x]
    if company:
        clean = re.sub(r'\b(Inc\.?|Corporation|Corp\.?|Platforms|Company|Co\.?|Ltd\.?|LLC|Group|Holdings|PLC)\b', '', company, flags=re.I).strip(' ,.')
        if clean and clean not in allowed_entities:
            allowed_entities.append(clean)
        for part in re.split(r'[,/·\s]+', clean):
            p = part.strip()
            if len(p) >= 2 and p not in allowed_entities:
                allowed_entities.append(p)
        c_lower = company.lower()
        if 'alphabet' in c_lower:
            allowed_entities.extend(['Google', '谷歌'])
        elif 'google' in c_lower:
            allowed_entities.extend(['Alphabet'])
        elif 'meta' in c_lower:
            allowed_entities.extend(['Facebook'])
    # Saved rows are verified by their query's symbol filter. Public pages must name the
    # entity in body text; a forged headline by itself is never sufficient.
    if web and (company or symbol) and not any(contains(x,body+' '+title) for x in allowed_entities):
        return False,'requested_entity_missing'
    if not web and symbol and not row.get('symbol') and not row.get('_verified_symbol') and not any(contains(x,body+' '+title) for x in allowed_entities):
        return False,'requested_entity_missing'
    needed=metrics if metrics is not None else [key for key,terms in METRIC_GROUPS.items() if any(contains(t,question) for t in terms)]
    for key in needed:
        if key=='price' and ('close' in row or 'last_close' in row):
            import math
            price_val=row.get('close') if 'close' in row else row.get('last_close')
            try:
                if not isinstance(price_val,bool) and math.isfinite(float(price_val)) and float(price_val)>=0:continue
            except (TypeError,ValueError):pass
            return _gate_outcome(False,'requested_metric_missing:price',soft)
        if key=='date' and any(row.get(field) for field in ('filed_at','published_at','trading_date','decision_at','start_date','end_date')):continue
        if key=='forecast' and row.get('probabilities'):continue
        terms=METRIC_GROUPS.get(key,(key,))
        passages=re.split(r'[。！？\n]|(?<=[.!?])\s+',body)
        relevant=[part for part in passages if any(contains(t,part) for t in terms) and (not web or not(company or symbol) or any(contains(x,part) for x in allowed_entities))]
        if not relevant:
            for i, part in enumerate(passages):
                if any(contains(t,part) for t in terms):
                    prev = passages[i-1] if i > 0 else ''
                    nxt = passages[i+1] if i + 1 < len(passages) else ''
                    combined = prev + ' ' + part + ' ' + nxt
                    if any(contains(x, combined) for x in allowed_entities) and not re.search(r'\b(?:Samsung|Google|Microsoft|Meta|Amazon|Intel|Nvidia|Tesla)\b', part, re.I):
                        relevant.append(combined)
        if not relevant:return _gate_outcome(False,'requested_metric_missing:'+key,soft)
        if not any(period_match(period or question,part) for part in relevant):return _gate_outcome(False,'requested_period_missing',soft)
    requested=period or question
    if not period_match(requested,body+' '+str(row.get('report_period') or '')+' '+str(row.get('filed_at') or row.get('trading_date') or row.get('decision_at') or row.get('start_date') or '')+' '+str(row.get('end_date') or '')):
        return _gate_outcome(False,'requested_period_missing',soft)
    if days_back is not None and not published_within(row.get('published_at') or row.get('filed_at'),days_back,now or datetime.now(UTC)):
        return _gate_outcome(False,'requested_time_window_missing',soft)
    query_without_url=re.sub(r'https://\S+',' ',question)
    from ..agent_web_research import _GENERIC_LATIN
    noise=set(_GENERIC_LATIN)|{'read','explain','summarize','summarise','verified','publication','dates','cite','citation','citations','briefly'}
    words=[t.casefold() for t in re.findall(r'[A-Za-z]{3,}',query_without_url) if t.casefold() not in noise]
    if not needed and not(company or symbol) and words and not any(contains(t,body) for t in words):return _gate_outcome(False,'weak_question_coverage',soft)
    return True,'sufficient_evidence'


def deterministic_confidence_gate(question: str,result: dict,citations=None,verified_symbols=None,**requirements):
    if not isinstance(result,dict) or not result.get('ok'):return False,(result or {}).get('error_code') or 'retrieval_unavailable'
    rows=result.get('data')
    if not isinstance(rows,list) or not rows:return False,'zero_evidence'
    if not any(isinstance(r,dict) and (r.get('id') or r.get('set_id') or r.get('source_id') or r.get('url') or r.get('source_url') or r.get('question') or 'close' in r or 'first_close' in r) for r in rows):return False,'missing_source_coverage'
    inferred=[t for t in re.findall(r'(?<![A-Za-z])[A-Z]{2,5}(?![A-Za-z])',question) if t not in {'SEC','FY','EPS','URL','HTTPS'}]
    explicit_symbol=requirements.pop('symbol',None)
    symbols=verified_symbols or ([explicit_symbol] if explicit_symbol else inferred or [None])
    for symbol in symbols:
        outcomes=[gate_row(question,{**r,**({'source_type':'web'} if result.get('source_type')=='web' or str(result.get('source','')).startswith('public web') else {})},symbol=symbol,**requirements) for r in rows if isinstance(r,dict)]
        if not any(ok for ok,_ in outcomes):
            reason=next((why for _,why in outcomes),'zero_evidence')
            if reason=='requested_time_window_missing' and any(not r.get('published_at') for r in rows):reason='publisher_date_unavailable'
            return False,reason
    if requirements.get('days_back') and any(not published_within(r.get('published_at'),requirements['days_back'],datetime.now(UTC)) for r in rows):return False,'publisher_date_unavailable'
    return True,'heuristic_coverage_pass'


def literal_titles(text,citations):
    """The text with bracketed numbers inside exact, server-known source titles made literal."""
    from .language import simplified
    titles={str(c.get('title') or '') for c in citations}
    for title in sorted(titles,key=len,reverse=True):
        if not re.search(r'\[\d+\]',title):continue
        for variant in {title,simplified(title)}:
            literal=re.sub(r'\[(\d+)\]',lambda m:'［'+m[1]+'］',variant)
            text=text.replace(variant,literal)
    return text


def citation_markers(answer,citations):
    """Read handles while preserving bracketed text in exact, server-known source titles."""
    return re.findall(r'\[(\d+)\]',literal_titles(answer,citations))


def citation_errors(answer: str,citations: list[dict]) -> list[int]:
    valid=set()
    for c in citations:
        if type(c.get('ordinal')) is not int:continue
        if c.get('source_type')=='unavailable' or c.get('unavailable'):continue
        if (c.get('source_type') in {'configured_news'} or c.get('origin')=='configured_news') and not _has_valid_http_url(c.get('url') or c.get('source_url')):
            continue
        valid.add(int(c['ordinal']))
    return [int(n) for n in citation_markers(answer,citations) if int(n) not in valid]


_CITATION_FIELD_SKIP={'excerpt','answer','summary','content','text','body','quote','raw_content','content_text',
    'source_snapshot','payload','_citations','citation','evidence_quotes','figures'}


def _citation_fields(row: dict) -> dict:
    """Scalar row fields a claim may bind to, kept beside the prose quote.

    Structured sources (price, XBRL, forecasts, saved analyses) expose values the
    answer may cite without a natural-language passage.  The citation has to carry
    those values too, otherwise a correct field claim would fail as a mismatch.
    """
    fields={}
    for key,value in row.items():
        if key in _CITATION_FIELD_SKIP or str(key).startswith('_') or value is None:
            continue
        if isinstance(value,bool) or isinstance(value,(int,float)):
            fields[str(key)]=value
        elif isinstance(value,str) and len(value)<=300:
            fields[str(key)]=value
    return fields


# What a citation shows (and the response catalogue lists) of its source.  It is a presentation cap: the
# number and claim checkers read ``check_text`` as well, which is never cut.
QUOTE_DISPLAY_CHARS = 5000


def citation_check_text(citation: dict) -> str:
    """Everything the checkers may read of one cited source: the shown quote, its figures, the full text and
    the evidence quotes a saved analysis carries (they are source text to the claim gate as well)."""
    quotes = [quote for quote in citation.get('evidence_quotes') or [] if isinstance(quote, str) and quote]
    return ' '.join([str(citation.get(key) or '') for key in ('quote', 'figures', 'check_text')] + quotes)


# The full checking text a stored citation keeps.  A later answer that reads the source back checks its figures
# against this text, so a figure the excerpt does not show is not "insufficient" for that reason alone.  Text over
# the cap is not kept, and the citation says so (``evidence_incomplete``).
STORED_CHECK_TEXT_CHARS = 120_000


def _kept_text(value) -> bool:
    return isinstance(value, str) and len(value) <= STORED_CHECK_TEXT_CHARS


def persistable_citation(citation: dict) -> dict:
    """The citation as it is stored with the turn: its full checking text is kept up to STORED_CHECK_TEXT_CHARS.

    Text over the cap is dropped and the citation is marked ``evidence_incomplete``, so a later reader treats a
    miss as insufficient.  Complete text is not marked."""
    if not isinstance(citation, dict) or 'check_text' not in citation or _kept_text(citation['check_text']):
        return citation
    kept = {key: value for key, value in citation.items() if key != 'check_text'}
    kept['evidence_incomplete'] = True
    return kept


def without_check_text(citation: dict) -> dict:
    """The citation without its checking text, marked partial: for a store with its own size cap that is not the
    turn record (the legacy web hydration in semantic.py)."""
    if not isinstance(citation, dict) or 'check_text' not in citation:
        return citation
    kept = {key: value for key, value in citation.items() if key != 'check_text'}
    kept['evidence_incomplete'] = True
    return kept


def without_evidence_text(outcome):
    """A tool outcome as a model may be shown it again: rows lose the checker-only full text."""
    data = outcome.get('data') if isinstance(outcome, dict) else None
    if not isinstance(data, list) or not any(isinstance(r, dict) and ('_evidence_text' in r or 'evidence_incomplete' in r) for r in data):
        return outcome
    return {**outcome, 'data': [{k: v for k, v in r.items() if k not in {'_evidence_text', 'evidence_incomplete'}} if isinstance(r, dict) else r for r in data]}


def persistable_result_sets(sets):
    """Saved result sets with each page's full text kept up to STORED_CHECK_TEXT_CHARS; a row whose text is longer
    loses it and is marked partial, so a later reuse treats a miss as insufficient."""
    out = []
    for saved in sets or []:
        if not isinstance(saved, dict) or not any(isinstance(r, dict) and '_evidence_text' in r and not _kept_text(r['_evidence_text'])
                                                  for r in saved.get('rows') or []):
            out.append(saved)
            continue
        rows = [{**{k: v for k, v in r.items() if k != '_evidence_text'}, 'evidence_incomplete': True}
                if isinstance(r, dict) and '_evidence_text' in r and not _kept_text(r['_evidence_text']) else r for r in saved['rows']]
        out.append({**saved, 'rows': rows})
    return out


def _evidence_quotes(row: dict) -> list[str]:
    quotes=[]
    for quote in row.get('evidence_quotes') or []:
        if isinstance(quote,str) and quote and quote not in quotes:
            quotes.append(quote)
    return quotes


def number_rows(name: str,rows: list[dict],citations: list[dict],scope: dict | None=None) -> list[dict]:
    """Give accepted rows a citation without changing provenance or raw saved snapshots."""
    scope=scope or {}
    if name=='query_stock_prices' and len(rows)>10 and all(isinstance(r,dict) and r.get('source_type')!='saved_price_set' for r in rows):
        from ..agent_tools import build_price_set_row
        receipt,_=build_price_set_row(rows,symbol=scope.get('symbol'))
        rows=[receipt]
    accepted=[]
    for original in rows:
        row=dict(original)
        rich=row.pop('_citations',[])
        page_text=row.pop('_evidence_text',None)
        # A tool that knows its own text is partial says so; the flag never reaches the model's row.
        declared_partial=bool(row.pop('evidence_incomplete',False))
        if rich:
            mapping={}
            for original_citation in rich:
                old=next((c for c in citations if c.get('chunk_id')==original_citation.get('chunk_id') and c.get('source_hash')==original_citation.get('source_hash')),None)
                number=old['ordinal'] if old else len(citations)+1
                mapping[original_citation['ordinal']]=number
                if not old:
                    fallback=str(row.get('excerpt') or row.get('answer') or '')
                    entry={**original_citation,'quote':original_citation.get('quote') or fallback[:QUOTE_DISPLAY_CHARS],
                        'ordinal':number,'fields':_citation_fields(row),'evidence_quotes':_evidence_quotes(row)}
                    check=page_text if isinstance(page_text,str) and page_text.strip() else (fallback if not original_citation.get('quote') and len(fallback)>QUOTE_DISPLAY_CHARS else None)
                    if check:entry['check_text']=check
                    if declared_partial or (entry.get('truncated') and not check):entry['evidence_incomplete']=True
                    citations.append(entry)
                else:
                    old.setdefault('fields',_citation_fields(row))
                    old.setdefault('evidence_quotes',_evidence_quotes(row))
            for field in ('excerpt','answer','summary'):
                if isinstance(row.get(field),str):row[field]=re.sub(r'\[(\d+)\]',lambda m:'['+str(mapping.get(int(m[1]),int(m[1])))+']',row[field])
            row['citation']='['+str(next(iter(mapping.values())))+']'
            row['_citations']=[{**c,'ordinal':mapping[c['ordinal']]} for c in rich]
            accepted.append(row)
            continue
        kind=row.get('source_type') or ('market_quote' if name=='query_market_quote' else 'configured_news' if name=='search_configured_news' else 'web' if name=='web_research' else 'official_filing' if name=='query_sec_filings' else 'saved_price' if name=='query_stock_prices' else 'saved_forecast' if name=='query_latest_forecast' else 'ai_analysis' if 'analysis' in name else 'research_faq' if 'faq' in name else 'saved_material')
        if kind=='configured_news' and not _has_valid_http_url(row.get('url') or row.get('source_url')):
            continue
        if kind=='saved_price_set':
            from ..agent_tools import PRICE_SET_FIELDS, get_cached_price_set
            set_id=str(row.get('set_id') or '')
            meta=get_cached_price_set(set_id) or {}
            sym=str(row.get('symbol') or meta.get('symbol') or scope.get('symbol') or '')
            row_ids=list(row.get('row_ids') or meta.get('row_ids') or [])
            parent_digest=str(row.get('parent_digest') or meta.get('parent_digest') or '')
            n_count=int(row.get('n') or meta.get('n') or len(row_ids))
            start_date=str(row.get('start_date') or meta.get('start_date') or '')
            end_date=str(row.get('end_date') or meta.get('end_date') or '')
            first_close=row.get('first_close') if row.get('first_close') is not None else meta.get('first_close')
            last_close=row.get('last_close') if row.get('last_close') is not None else meta.get('last_close')
            # Yahoo's single precision (92.06999969482422) is shown as the price it is, 92.07; the stored rows are not touched.
            from .calculation import format_price
            first_close,last_close=[None if v is None else float(format_price(v)) for v in (first_close,last_close)]
            fields_avail=list(row.get('fields_available') or meta.get('fields_available') or PRICE_SET_FIELDS)
            source_name=row.get('source') or meta.get('source') or 'market_prices'
            fetched_at=row.get('fetched_at') or meta.get('fetched_at')
            key=hashlib.sha256(json.dumps(['saved_price_set',sym,set_id,parent_digest],sort_keys=True,default=str).encode()).hexdigest()
            old=next((c for c in citations if c.get('evidence_key')==key),None)
            if old:
                ordinal=old['ordinal']
            else:
                ordinal=len(citations)+1
                figures_str=f'{start_date} close {first_close} {end_date} close {last_close}'
                receipt_fields={'symbol':sym,'set_id':set_id,'n':n_count,'start_date':start_date,'end_date':end_date,
                    'first_close':first_close,'last_close':last_close}
                citations.append({
                    'ordinal':ordinal,
                    'evidence_key':key,
                    'source_type':'saved_price_set',
                    'origin':'saved',
                    'symbol':sym,
                    'set_id':set_id,
                    'row_ids':row_ids,
                    'n':n_count,
                    'start_date':start_date,
                    'end_date':end_date,
                    'first_close':first_close,
                    'last_close':last_close,
                    'fields_available':fields_avail,
                    'parent_digest':parent_digest,
                    'source':source_name,
                    'fetched_at':fetched_at,
                    'published_at':end_date,
                    'observed_at':fetched_at,
                    'title':f'{sym} 价格序列 ({start_date}..{end_date})'.strip(),
                    'quote':figures_str,
                    'figures':figures_str,
                    'fields':receipt_fields,
                })
            accepted.append({
                'citation':f'[{ordinal}]',
                'set_id':set_id,
                'symbol':sym,
                'n':n_count,
                'start_date':start_date,
                'end_date':end_date,
                'first_close':first_close,
                'last_close':last_close,
                'fields_available':fields_avail,
            })
            continue
        body=str(row.get('excerpt') or row.get('answer') or row.get('summary') or json.dumps(row,ensure_ascii=False,default=str))
        key=hashlib.sha256(json.dumps([kind,row.get('id'),row.get('source_id'),row.get('url'),body],sort_keys=True,default=str).encode()).hexdigest()
        old=next((c for c in citations if c.get('evidence_key')==key),None)
        if old: ordinal=old['ordinal']
        else:
            ordinal=len(citations)+1
            resolved_url=row.get('source_url') or row.get('content_source_url') or row.get('url')
            origin=row.get('origin') or ('configured_news' if kind=='configured_news' else 'web' if kind in {'web','web_news'} else 'saved')
            citations.append({'ordinal':ordinal,'evidence_key':key,'chunk_id':row.get('chunk_id'),'document_id':row.get('document_id'),
                'source_id':str(row.get('source_id') or row.get('id') or ''),'question':row.get('question'),'source_type':kind,'origin':origin,'tool_arguments':row.get('tool_arguments'),
                'title':str(row.get('title') or row.get('accession_number') or scope.get('company') or name)[:300],
                'source_name':row.get('source_name') or row.get('source'),
                'url':resolved_url,'source_url':resolved_url,
                'published_at':row.get('published_at') or row.get('filed_at') or row.get('trading_date'),
                'observed_at':row.get('fetched_at') or row.get('observed_at'),'quote':body[:QUOTE_DISPLAY_CHARS],
                'trading_date':row.get('trading_date'),'source':row.get('source'),'fetched_at':row.get('fetched_at'),
                'symbol':row.get('symbol') or scope.get('symbol'),'analysis_id':row.get('analysis_id'),'derived':kind=='ai_analysis','truncated':bool(row.get('truncated')),
                'saved_text':row.get('saved_text'),
                'fields':_citation_fields(row),'evidence_quotes':_evidence_quotes(row)})
            # The quote is what is shown; the checker reads the whole text (the page the excerpt was
            # selected from, or a body longer than the display cap).  Only a source whose own stored
            # text is partial makes a figure's absence "insufficient" rather than "unsupported".
            check=page_text if isinstance(page_text,str) and page_text.strip() and page_text!=body else (body if len(body)>QUOTE_DISPLAY_CHARS else None)
            if check:citations[-1]['check_text']=check
            citations[-1]['evidence_incomplete']=bool(declared_partial or (row.get('truncated') and not check))
        if kind=='saved_price':
            from .calculation import format_price
            for k in ('open','high','low','close'):
                if row.get(k) is not None:row[k]=float(format_price(row[k]))
            citations[ordinal-1]['quote']=format_price(row['close'])
            citations[ordinal-1]['fields']=_citation_fields(row)
            # The quote stays the close (the restore check compares it); the row's other prices are
            # kept beside it so an answer that states the open, high, low or volume can be checked.
            citations[ordinal-1]['figures']=' '.join(f'{k} {row[k]}' for k in ('trading_date','open','high','low','close','volume') if row.get(k) is not None)
        elif kind=='market_quote':
            from .calculation import format_price
            for k in ('price','close','prev_close'):
                if row.get(k) is not None:
                    try: row[k]=float(format_price(row[k]))
                    except Exception: pass
            citations[ordinal-1]['fields']=_citation_fields(row)
            citations[ordinal-1]['figures']=' '.join(f'{k} {row[k]}' for k in ('trading_date','price','close','prev_close','change_pct') if row.get(k) is not None)
        row['citation']=f'[{ordinal}]';row['source_type']=kind
        accepted.append(row)
    return accepted


def citation_from_row(name: str, row: dict, citations: list[dict], scope: dict | None = None) -> dict:
    """Build citation for a single row according to number_rows logic."""
    res = number_rows(name, [row], citations, scope)
    return res[0] if res else row


_DASHES=re.compile('[‐‑‒–—−]')
# Never figures: a form or a section reference states no amount whatever the evidence says.
_ALWAYS_IDENTIFIERS=re.compile(r'\b(?:10-K|10-Q|8-K|20-F|6-K|S-1|DEF\s*14A)\b|\b(?:Note|Item|Part|CIK)\s*\d+[A-Z]?\b',re.I)
# Identifiers and names that carry digits: accepted only where the turn's evidence shows them.
_GROUNDED_IDENTIFIERS=re.compile(
    r'\b\d{10}-\d{2}-\d{6}\b|\b\d{18}\b|[\w.-]+\.(?:htm|html|pdf|xml|txt)\b'
    r'|(?:Exhibit|EX-|附件|附录)\s*\d+(?:\.\d+)?'
    r'|\b[A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)?\s\d{1,4}(?![,.]?\d)(?!\s*(?:%|％|万亿|千万|百万|亿|万|千|million|billion|thousand|trillion|bn|mn|美元|元|dollars?|USD|倍))',re.I)
# A link written without its scheme ("sec.gov/Archives/edgar/data/789019/…") names a source, not an amount.
_BARE_LINK=re.compile(r'(?<![\w@/.-])(?:www\.)?(?:[a-z0-9-]+\.)+[a-z]{2,6}/[^\s|()\[\]（）<>，。；、]*',re.I)
_SCALE=((re.compile(r'\(?\s*in\s+millions|百万美元|单位[:：]\s*百万',re.I),1e6),
        (re.compile(r'\(?\s*in\s+thousands|千美元|单位[:：]\s*千',re.I),1e3),
        (re.compile(r'\(?\s*in\s+billions|十亿美元',re.I),1e9))
# Words that count things, not money.  Shared with claim_numeric so the two checkers cannot drift.  The
# lone 个 differs on purpose and is appended by each module: evidence strips every 个, claim_numeric keeps
# "个百分点" (a percentage-point change) as a figure.
COUNT_UNITS=(r'天|日|个月|年|周|条|篇|份|项|页|行|次|点|位|名|步|轮|倍|小时|分|秒|字符|字|家|只|种|档|岁|期|季|'
             r'days?|hours?|items?|times?|points?|characters?|chars?|months?|years?|weeks?|quarters?')
# A month on its own ("12 月", "3月份") is a date part, not an amount.
BARE_MONTH=re.compile(r'(?<![\d.])(\d{1,2})\s*月份?(?!\s*(?:万|亿|千|百万|美元|元|%|％|billion|million))')
# An index's name carries digits ("标普500", "S&P 500"); a figure written after it ("标普500 上涨 1.2%") still counts.
INDEX_NAME=re.compile(r'(标普|标准普尔|纳指|纳斯达克|罗素|道指|沪深|中证|上证|S&P)\s*(?:1000|2000|3000|500|300|100|50|30)'
                      r'(?![\d.,]|\s*(?:%|％|点|万|亿|千|百万|美元|元|billion|million|trillion|bn|mn))',re.I)
_CLAIM_NUMBER=re.compile(r'(\$\s*)?(\d+(?:\.\d+)?)\s*(万亿|千万|百万|亿|万|千|trillion|billion|million|thousand|bn|mn|b|k|m)?(?![A-Za-z])(\s*(?:%|％))?(\s*(?:美元|元|dollars?|USD))?',re.I)


def identifier_tokens(text):
    """Digit-bearing names and identifiers in a passage: forms, sections, accessions, file names, product names."""
    text=_DASHES.sub('-',text)
    return [m.group(0) for m in _ALWAYS_IDENTIFIERS.finditer(text)]+[m.group(0) for m in _GROUNDED_IDENTIFIERS.finditer(text)]


def _without_identifiers(passage,grounds):
    passage=_DASHES.sub('-',passage)
    passage=_ALWAYS_IDENTIFIERS.sub(' ',passage)
    def keep(match):
        token=' '.join(match.group(0).split()).casefold()
        return ' ' if token in grounds else match.group(0)
    return _GROUNDED_IDENTIFIERS.sub(keep,passage)


def _significant(number):
    digits=number.replace('.','').lstrip('0')
    if '.' not in number:digits=digits.rstrip('0')
    return max(len(digits),1)


def _round_to(value,digits):
    import math
    if not value:return 0.0
    return round(value,-int(math.floor(math.log10(abs(value))))+digits-1)


@functools.lru_cache(maxsize=512)
def _figures_of(text):
    """The amounts one source text states (cached: a checked answer reads the same long page many times)."""
    from .semantic import figure_values
    return frozenset(figure_values(text))


# --- who may ground a figure besides the cited source -------------------------------------------------

_ZH_DIGIT={'零':0,'〇':0,'一':1,'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9}
_ZH_TEN={'十':10,'百':100,'千':1000}
_ZH_AMOUNT_RUN=re.compile(r'[零〇一二两三四五六七八九十][零〇一二两三四五六七八九十百千万亿]*')


def _zh_section(text):
    total=0;number=0;pending=False
    for char in text:
        if char in _ZH_DIGIT:number=_ZH_DIGIT[char];pending=True
        elif char in _ZH_TEN:total+=(number if pending else 1)*_ZH_TEN[char];number=0;pending=False
    return total+number


def _zh_amount(text):
    total=0
    if '亿' in text:
        head,text=text.split('亿',1);total+=_zh_amount(head or '一')*10**8
    if '万' in text:
        head,text=text.split('万',1);total+=_zh_section(head or '一')*10**4
    return total+_zh_section(text)


def user_figure_values(user_text):
    """The amounts the user wrote (Chinese numerals included: 五万 is 50000, 两百万 is 2000000).

    Only what a person typed this conversation goes in here (``Turn.user_stated_text``), never
    the model's rewrite of the question and never an assistant message."""
    if not user_text:return set()
    text=unicodedata.normalize('NFKC',str(user_text))
    values=set(_figures_of(text))
    from .semantic import figure_values
    values|=figure_values(text,zh=True)
    for run in _ZH_AMOUNT_RUN.findall(text):
        if any(char in run for char in '十百千万亿'):values.add(float(_zh_amount(run)))
    return {round(v,4) for v in values if v}


# --- one record per written figure --------------------------------------------------------------------

_CURRENCY_BEFORE=re.compile(r'[$¥￥€£＄]\s*$')
_CURRENCY_AFTER=re.compile(r'\s*(?:人民币|港元|港币|欧元|日元|英镑|美金|RMB|CNY|EUR|GBP|JPY|HKD)',re.I)
_CLOCK=re.compile(r'(?<![\d.:])\d{1,2}:\d{2}(?::\d{2})?(?![\d:])')


def _figure_records(text):
    """Each stated amount with its precision and what kind of figure it is; the same exclusions as ``figure_values``."""
    from .semantic import ACCESSION,SOURCE_ID,TASK_ID,PERIOD_TEXT,_MAGNITUDE
    text=unicodedata.normalize('NFKC',text).replace('萬','万').replace('億','亿')
    text=re.sub(r'(?<=\d)T(?=\d{2}:)',' ',text)
    text=PERIOD_TEXT.sub(' ',ACCESSION.sub(' ',SOURCE_ID.sub(' ',TASK_ID.sub(' ',text))))
    text=re.sub(r'(?<=\d),(?=\d{3}(?!\d))','',text)
    found=[]
    for match in _CLAIM_NUMBER.finditer(text):
        dollar,number,unit,percent,currency=match.groups()
        unit=unit or ''
        value=round(float(number)*_MAGNITUDE.get(unit.lower(),1.0),4)
        money=bool(dollar or currency or _CURRENCY_BEFORE.search(text[:match.start()]) or _CURRENCY_AFTER.match(text,match.end()))
        found.append({'value':value,'digits':_significant(number),'scaled':bool(unit or percent),
                      'unitless':not(dollar or unit or percent or currency),'money':money,'magnitude':bool(unit),
                      'pct':bool(percent),'integer':'.' not in number,'decimals':len(number.partition('.')[2])})
    return found


def _claim_figures(text):
    """Each stated amount with its precision; the same exclusions as ``figure_values``."""
    return [(r['value'],r['digits'],r['scaled'],r['unitless']) for r in _figure_records(text)]


# --- scope: [n] is the declaration ---------------------------------------------------------------------
# A sentence with a marker is checked for every figure it writes.  One without is checked only for the
# figures a reader would take as a claim about the world: money, magnitude amounts, percentages, table
# rows, decimals and integers of 1000 or more.  A bare integer below 1000 in unmarked prose (21:25 is
# no longer one, 13 家, 12 月, 标普500) is not.

def _backstop_figure(record,table_row):
    if table_row or record['money'] or record['magnitude'] or record['pct']:return True
    if not record['unitless']:return True
    return not record['integer'] or record['value']>=1000


# A sentence that says it is an inference states no fact, so its figures need their premises, not a source.
_LABEL_START=r'^\s*(?:>\s*)*(?:#{1,6}\s+)?(?:(?:[-*+•]|\d+[.)、])\s+)?(?:\*\*|__|\*|_)*\s*'
_LABEL_WORD=r'(?:推断|估算|推算|假设|由此推断|据此估算|预计|预估|测算|建议)'
_INFERENCE_LABEL=re.compile(
    _LABEL_START+r'(?:(?:[（(]\s*'+_LABEL_WORD+r'\s*[）)])|(?:(?:若|如果|如)\s*)?'+_LABEL_WORD+r')'
    r'|^\s*(?:>\s*)*(?:#{1,6}\s+)?(?:(?:[-*+•]|\d+[.)、])\s+)?(?:\*\*|__|\*|_)*\s*(?:inference|estimate[d]?|assuming|assumption|hypothetically)\b'
    r'|[（(]\s*'+_LABEL_WORD+r'\s*[）)]\s*(?:\[\d+\]\s*)*[。.!！]*\s*$',re.I)
# The approximation words: 约 and 近 count only straight in front of a figure (最近, 附近, 合约, 约束 do not).
_APPROXIMATION=re.compile(
    r'大约|接近|将近|左右|上下|约合|\b(?:about|roughly|approximately|around|nearly|almost)\b'
    r'|(?<![合制契大预公条最附贴亲邻靠临])[约近]\s*(?=[\d$¥￥€£＄])|[~≈～]\s*(?=[\d$¥￥€£＄])',re.I)
APPROXIMATION_TOLERANCE=0.05


def is_inference_label(passage):
    """Whether a sentence opens with (or ends in) the label the prompt asks for.  Anchored, so
    「这不是推断，营收 $500 billion [1]」 is not labelled."""
    return bool(_INFERENCE_LABEL.search(passage or ''))


def _match(record,support,percent_pool,percent,approximate):
    """How a written figure is held by ``support``: 'exact', 'rounded' (at the precision written) or 'approx'."""
    value,digits,scaled=record['value'],record['digits'],record['scaled']
    if value in support or (percent and value/100 in percent_pool):return 'exact'
    if (digits>=3 or (digits>=2 and scaled)) and any(_round_to(a,digits)==_round_to(value,digits) for a in support if a):return 'rounded'
    if approximate and any(a and abs(a-value)<=APPROXIMATION_TOLERANCE*abs(a) for a in support):return 'approx'
    return None


# --- closure: a sum, difference, ratio or change of cited figures ------------------------------------------
# With a large pool nearly any number is a sum of something, which would defeat the checker.  So the
# number of candidates a pool offers is held against the number of values the answer's precision can
# tell apart; a pool offering more than this share of them is not searched at all.
CLOSURE_FALSE_ACCEPT_BOUND=0.05


def _operand_pool(values):
    return sorted(v for v in values if v>0 and not (v==int(v) and (v<=10 or 1900<=v<=2100)))


def _amount_closure(value,digits,pool):
    """``(kind, operands, candidates, bins)`` when a sum or difference of 2-3 pool figures is the written amount."""
    n=len(pool)
    if n<2:return None
    bins=18*10**(digits-1)
    two=n*(n-1)//2+n*(n-1)
    three=two+n*(n-1)*(n-2)//6+n*(n-1)//2*(n-2)+n*((n-1)*(n-2)//2)
    if two>CLOSURE_FALSE_ACCEPT_BOUND*bins:return None
    target=_round_to(value,digits)
    hit=lambda x:x>0 and _round_to(x,digits)==target
    for a,b in itertools.combinations(pool,2):
        if hit(a+b):return 'sum',[a,b],two,bins
        if hit(abs(a-b)):return 'difference',[max(a,b),min(a,b)],two,bins
    if three>CLOSURE_FALSE_ACCEPT_BOUND*bins:return None
    for a,b,c in itertools.combinations(pool,3):
        if hit(a+b+c):return 'sum',[a,b,c],three,bins
    for a,b in itertools.combinations(pool,2):
        for c in pool:
            if c!=a and c!=b and hit(a+b-c):return 'difference',[a,b,c],three,bins
    for a in pool:
        for b,c in itertools.combinations(pool,2):
            if a!=b and a!=c and hit(a-b-c):return 'difference',[a,b,c],three,bins
    return None


def _percent_closure(value,decimals,pool):
    n=len(pool)
    if n<2:return None
    bins=200*10**decimals;count=2*n*(n-1)
    if count>CLOSURE_FALSE_ACCEPT_BOUND*bins:return None
    target=round(value,decimals)
    for a,b in itertools.permutations(pool,2):
        if round(a/b*100,decimals)==target:return 'ratio',[a,b],count,bins
        if round(abs(a-b)/b*100,decimals)==target:return 'change',[a,b],count,bins
    return None


def _closure(record,source_pool,verified):
    """The closure of one figure over the cited sources' figures, or None.  Two pools in order: the figures
    this answer has already verified that the cited sources also hold (small), then all the sources' figures."""
    pool=_operand_pool(source_pool)
    pools=(('verified',[v for v in pool if v in verified]),('sources',pool))
    seen=None
    for name,operands in pools:
        if operands==seen:continue
        seen=operands
        found=(_percent_closure(record['value'],record['decimals'],operands) if record['pct']
               else _amount_closure(record['value'],record['digits'],operands))
        if found:
            kind,used,count,bins=found
            return {'value':record['value'],'kind':kind,'operands':used,'pool':name,'candidates':count,'bins':bins}
    return None


# --- one sentence --------------------------------------------------------------------------------------

_DATE_PATTERN=re.compile(
    # Chinese dates are often typeset with spaces ("2025 年 12 月 31 日"), and a CJK neighbour is a word
    # character, so the date is bounded by digits rather than by \b.
    r'(?<!\d)(?:\d{4}\s*[-/年]\s*)?\d{1,2}\s*[-/月]\s*\d{1,2}(?:\s*日)?(?!\d)|(?<!\d)\d{4}\s*年\s*\d{1,2}\s*月|'
    r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}\b|'
    r'\b\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b',
    re.I)
_NUMBER_TEXT=r'\d+(?:,\d{3})*(?:\.\d+)?'
_MAGNITUDE_TEXT=r'(?:万亿|千万|百万|亿|万|千|trillion|billion|million|thousand|bn|mn|b|k|m)?'


class _Context:
    """What one check reads besides the sentence: the turn's sources, the user's own figures, the verified set."""

    def __init__(self,citations,question='',user_text='',verified=None,state_check=False):
        self.indexed={str(c['ordinal']):c for c in citations}
        evidence=' '.join(str(c.get(k) or '') for c in citations for k in ('quote','check_text','title','source_url'))+' '+str(question or '')
        self.grounds=' '.join(_DASHES.sub('-',evidence).split()).casefold()
        self.user=user_figure_values(user_text)
        self.verified=set(verified or ())
        # Against the system's own state log a clock time is a checkable fact, not prose colour.
        self.state_check=state_check


def _calculation_result(citation):
    calculation=citation.get('calculation')
    if not isinstance(calculation,dict):
        try:calculation=json.loads(str(citation.get('quote') or ''))
        except ValueError:return None
    try:return float(calculation.get('value')) if isinstance(calculation,dict) else None
    except (TypeError,ValueError):return None


def _review_passage(passage,citations,ctx,*,closure=False):
    """The numeric verdict of one sentence.

    ``rejected``/``insufficient`` are the figures no source holds; ``direct`` the written figures its
    cited sources state; ``closure`` those only a sum/difference/ratio of cited figures reaches (kept
    apart, because the answer-wide verified set is built from both); ``figures`` every checked figure
    with how it was settled, for the scope audit."""
    from datetime import datetime, timedelta
    refs=citation_markers(passage,citations)
    cited=[ctx.indexed[r] for r in refs if r in ctx.indexed]
    marked=bool(refs)
    labelled=is_inference_label(passage)
    out={'marked':marked,'labelled':labelled,'rejected':[],'insufficient':[],'direct':set(),'closure':set(),'closures':[],'figures':[]}
    body=' '.join(citation_check_text(c)+' '+str(c.get('published_at',''))+' '+str(c.get('source_url',''))+' '+str(c.get('title','')) for c in cited)
    allowed=set(_figures_of(body))
    source_pool=set();percent_pool=set()
    # A miss is "insufficient" only when every source cited for the passage is partial:
    # if any cited source is complete, the figure had complete evidence and failed it.
    partial=bool(cited) and all(c.get('evidence_incomplete') for c in cited)
    for citation in cited:
        quote=str(citation.get('quote',''))
        # The text the checker holds is the whole source when there is one: a unit line ("In millions")
        # beyond the shown quote still applies to the table it heads.
        scanned=str(citation.get('check_text') or quote)
        own=set(_figures_of(citation_check_text(citation)))
        percent_pool|=own;source_pool|=own
        for marker,scale in _SCALE:
            if marker.search(scanned):
                scaled_values={round(v*scale,4) for v in _figures_of(scanned) if v>=1}
                allowed|=scaled_values;source_pool|=scaled_values
        if citation.get('source_type')=='calculation':
            # A result computed on values bound per million is itself in millions.
            allowed|={round(v*1e6,4) for v in _figures_of(quote) if abs(v)>=1}
            # The whole-number part of a result is how people write "219.78 shares".
            result=_calculation_result(citation)
            if result is not None and result>=1:allowed.add(float(math.floor(result)))
        pub = citation.get('published_at') or citation.get('filed_at') or citation.get('trading_date')
        if pub and isinstance(pub, str):
            try:
                dt = datetime.fromisoformat(pub.replace('Z', '+00:00'))
                allowed.add(float(dt.day))
                allowed.add(float((dt + timedelta(hours=8)).day))
                allowed.add(float((dt - timedelta(hours=8)).day))
                allowed.add(float(dt.month))
                allowed.add(float((dt + timedelta(hours=8)).month))
            except (ValueError, TypeError):
                pass
    # A full reported value may be written bare in a table headed in millions, 亿 or billions; a
    # number that carries its own unit ("54.2 美元") is held to that unit.
    headed={round(v/scale,4) for v in allowed if abs(v)>=1e6 for scale in (1e6,1e8,1e9)}
    checked=re.sub(r'\[\d+\](?:\([^)]*\))?','',passage)
    checked=re.sub(r'https?://\S+','',checked)
    # Its digits are not figures when the turn's evidence shows that link; an unknown link keeps them.
    checked=_BARE_LINK.sub(lambda m:' ' if m.group(0).casefold().rstrip('/.,;:') in ctx.grounds else m.group(0),checked)
    checked=_without_identifiers(checked,ctx.grounds)
    # A clock time and an index's name are no amounts, marked sentence or not.  The state check is
    # the exception: it holds narration to the machine's own log, where a time is a fact.
    if not ctx.state_check:checked=_CLOCK.sub(' ',checked)
    checked=INDEX_NAME.sub(r'\1 ',checked)
    # Bare financial amounts are also claims. Strip only citation identities,
    # list labels and grounded date/period syntax, never arbitrary numbers.
    bare=re.sub(r'^\s*\d+[.、)]\s*','',checked)
    bare=_DATE_PATTERN.sub('',bare)
    bare=BARE_MONTH.sub(lambda m:' ' if 1<=int(m[1])<=12 else m[0],bare)
    bare=re.sub(r'\d+(?:\.\d+)?\s*(?:'+COUNT_UNITS+'|个)', ' ', bare)
    # Amounts with a currency or percent are read before list labels are stripped: "0.5万亿美元"
    # must not become "5万亿美元".
    amounts=re.findall(_NUMBER_TEXT+r'\s*'+_MAGNITUDE_TEXT+r'\s*(?:美元|元|dollars?|USD|%|％)',checked,re.I)
    amounts+=re.findall(r'\$\s*'+_NUMBER_TEXT+r'\s*'+_MAGNITUDE_TEXT,checked,re.I)
    percent=bool(re.search(r'%|％|百分',passage))
    approximate=bool(_APPROXIMATION.search(passage))
    table_row=passage.lstrip().startswith('|')
    held=allowed|ctx.user|ctx.verified
    pending=[];settled=[];seen=set()
    for record in _figure_records(' '.join(amounts))+_figure_records(bare):
        value,unitless=record['value'],record['unitless']
        # An amount read with its unit and again bare is one figure.
        identity=(value,unitless,record['scaled'],record['money'],record['pct'],record['magnitude'])
        if identity in seen:continue
        seen.add(identity)
        # Exclude list numbering and calendar years to avoid false positive claim rejections
        if (1.0<=value<=10.0 and value==int(value)) or (1990<=value<=2035 and value==int(value)):continue
        figure={'value':value,'marked':marked}
        if not marked:
            if labelled:figure['how']='exempt:labelled_inference';out['figures'].append(figure);continue
            if not _backstop_figure(record,table_row):figure['how']='exempt:below_backstop';out['figures'].append(figure);continue
            figure['backstop']=True
        support=allowed|headed if unitless else allowed
        how=_match(record,support,allowed,percent,approximate)
        if how:
            if how!='approx' and not labelled:out['direct'].add(value)
            figure['how']='source:'+how;settled.append(figure);out['figures'].append(figure);continue
        support=held|headed if unitless else held
        how=_match(record,support,held,percent,approximate)
        if how:
            figure['how']='set:'+how;settled.append(figure);out['figures'].append(figure);continue
        if (closure or labelled) and cited:
            found=_closure(record,source_pool if not record['pct'] else percent_pool,ctx.verified|out['direct'])
            if found:
                if not labelled:out['closure'].add(value)
                out['closures'].append(found)
                figure['how']='closure:'+found['kind'];settled.append(figure);out['figures'].append(figure);continue
        figure['how']='rejected';out['figures'].append(figure)
        pending.append(value)
    # A labelled inference stands on its premises: one verified figure is enough, none means they failed.
    if labelled and marked and settled:pending=[]
    for value in pending:(out['insufficient'] if partial else out['rejected']).append(value)
    return out


def _passages(answer):
    from .language import simplified
    return cited_passages(simplified(answer))


def _verified_set(passages,citations,ctx,closure_log=None):
    """The figures this answer's own cited sources hold, then those only a closure reaches.  Computed once
    over the whole answer and in two steps, so that it does not depend on the order of the sentences."""
    plain=copy.copy(ctx);plain.verified=set()
    direct=set()
    for passage in passages:direct|=_review_passage(passage,citations,plain)['direct']
    base=copy.copy(ctx);base.verified=set(direct)
    reached=set()
    for passage in passages:
        review=_review_passage(passage,citations,base,closure=True)
        reached|=review['closure']
        if closure_log is not None:closure_log.extend(review['closures'])
    return direct|reached


def verified_figures(answer,citations,*,question='',user_text='',closure_log=None):
    """The answer-wide verified set of one text (see ``answer_verified_figures`` for a whole answer)."""
    ctx=_Context(citations,question,user_text)
    return _verified_set(_passages(answer),citations,ctx,closure_log)


def answer_verified_figures(answer,citations,*,question='',user_text='',closure_log=None):
    """The answer-wide verified set, from the text each line is checked as (a table row inherits its table's markers).

    A figure in it passes wherever the answer restates it, so every line-level caller is handed the same set.
    Figures of a labelled inference are not in it: an estimate does not become evidence by being repeated."""
    checked='\n'.join(text for _,_,text in _reviewable_lines(answer,citations) if text is not None)
    return verified_figures(checked,citations,question=question,user_text=user_text,closure_log=closure_log)


def unsupported_numbers(answer,citations,*,user_text=''):
    """Check cited quantitative claims without inferring facts or entity aliases.

    Unit-normalized amounts may be translated (10 billion / 100亿) and probabilities
    may be shown as percentages. This is a guard, not a semantic answer scorer.
    """
    return bool(unsupported_number_values(answer,citations,user_text=user_text))


def insufficient_numbers(answer,citations,*,user_text=''):
    """Whether a figure is missing from a source whose own stored text is partial (证据不完整)."""
    return bool(insufficient_number_values(answer,citations,user_text=user_text))


def unsupported_number_values(answer,citations,*,question='',user_text='',verified=None,state_check=False):
    """The candidate numbers no cited source supports, so a repair can name them.

    Same rules as ``unsupported_numbers``; the list only tells the rewriting model what to
    drop or re-source, it never decides the answer.  A figure is supported when its cited source
    states it: exactly, in the unit the source's table is in ("(In millions)" 32,000 is 320 亿),
    or rounded to the precision the answer itself writes.  Digits inside identifiers and names
    are not figures when the turn's evidence or the question shows that identifier.

    A figure absent from a *partial* source (``evidence_incomplete``) is not listed here: it may sit
    in the part that was never stored, so it is ``insufficient_number_values``, a different outcome.
    """
    return number_check(answer,citations,question=question,user_text=user_text,verified=verified,state_check=state_check)[0]


def insufficient_number_values(answer,citations,*,question='',user_text='',verified=None):
    """The figures not found in the cited sources, all of which are partial (证据不完整), not refuted."""
    return number_check(answer,citations,question=question,user_text=user_text,verified=verified)[1]


def number_review(answer,citations,*,question='',user_text='',verified=None,closure_log=None,state_check=False):
    """Every sentence's verdict (see ``_review_passage``), the verified set made once for the whole text if none is given."""
    passages=_passages(answer)
    ctx=_Context(citations,question,user_text,state_check=state_check)
    ctx.verified=set(verified) if verified is not None else _verified_set(passages,citations,ctx,closure_log)
    return [_review_passage(passage,citations,ctx) for passage in passages]


def number_check(answer,citations,*,question='',user_text='',verified=None,closure_log=None,state_check=False):
    """``(unsupported, insufficient)``: figures no complete cited source states, and figures missing
    only from cited sources whose stored text is partial.  Unsupported wins when a figure is both.

    A sentence with a ``[n]`` is checked for every figure; one without only for the backstop classes
    (money, magnitude amounts, percentages, table rows, decimals, integers of 1000 or more).  A figure
    the user wrote, one the answer has verified elsewhere, or one that is the sum, difference, ratio
    or change of the cited sources' figures (within the false-accept bound) is held too."""
    rejected=[];insufficient=[]
    for review in number_review(answer,citations,question=question,user_text=user_text,verified=verified,closure_log=closure_log,state_check=state_check):
        rejected+=review['rejected'];insufficient+=review['insufficient']
    return sorted(set(rejected)),sorted(set(insufficient)-set(rejected))


def answer_scope(answer,citations,*,question='',user_text='',verified=None,limit=20):
    """What the check looked at, for the turn's audit: figures in marked sentences, the unmarked ones the
    backstop checked, the unmarked ones it did not (with their line), and those no source of the turn holds."""
    from .language import simplified
    ctx=_Context(citations,question,user_text)
    lines=[(stripped,checked) for _,stripped,checked in _reviewable_lines(answer,citations) if checked is not None]
    ctx.verified=set(verified) if verified is not None else verified_figures('\n'.join(checked for _,checked in lines),citations,question=question,user_text=user_text)
    held=set()
    for citation in citations:held|=_figures_of(citation_check_text(citation))
    marked=0;backstopped=[];exempted=[];no_holder=[]
    for stripped,checked in lines:
        for passage in cited_passages(simplified(checked)):
            review=_review_passage(passage,citations,ctx)
            text=passage.strip()[:200]
            for figure in review['figures']:
                if figure['marked']:marked+=1;continue
                item={'value':figure['value'],'line':text}
                if figure['how'].startswith('exempt:'):exempted.append({**item,'why':figure['how'][7:]})
                else:backstopped.append({**item,'flagged':figure['how']=='rejected'})
                if figure['value'] not in held and figure['value'] not in ctx.user:no_holder.append(item)
    counts={'marked_figures':marked,'unmarked_backstopped':len(backstopped),'unmarked_exempted':len(exempted),'unmarked_no_holder':len(no_holder)}
    return {'marked_figures':marked,'unmarked_backstopped':backstopped[:limit],'unmarked_exempted':exempted[:limit],
            'unmarked_no_holder':no_holder[:limit],'counts':counts}

# Claim validation only. These concepts never route a request or choose a tool.
RESIGNATION_TERMS=('resign','resigned','resignation','stepped down','stepping down','辞职','辞任','离职','退任')
DEPARTURE_TERMS=('departure','departed','departing','left','leave','retired','retires','离任','卸任','退任','离职','走人')
APPOINTMENT_TERMS=('appoint','appointed','appoints','named','hire','hired','promote','promoted','elect','elected','resign','resigned','step down','stepped down','retire','retired','replace','replaced','任命','聘任','出任','升任','辞职','卸任','离任','退休','接替')
ROLE_START_TERMS=('takes charge','took charge','taking charge','takes office','took office','上任','接任','接棒')
CLAIM_FEATURES=(
 RESIGNATION_TERMS,
 APPOINTMENT_TERMS,
 ('bankruptcy','bankrupt','chapter 11','insolvent','insolvency','liquidation','破产','清算'),
 ('acquisition','acquire','acquired','acquiring','merger','merge','merged','takeover','buyout','divest','divested','spin-off','spinoff','收购','并购','合并','剥离','分拆'),
 DEPARTURE_TERMS,
 ROLE_START_TERMS,
)

def supporting_event_terms(terms):
    # Resignation entails departure; a bare departure does not prove resignation.
    if terms==DEPARTURE_TERMS:return terms+RESIGNATION_TERMS
    return terms

def _event_matches(text,terms):
    """``(simplified text, [(term, start, end, negative)])``: every event word found and whether a negation sits before it.

    The negation rule is frozen (polarity is a hint only, see ``polarity_conflicts``): no new words, no patches."""
    from .language import simplified
    text=simplified(text);found=[]
    for term in terms:
        pattern=re.escape(term)
        if term.isascii():pattern=r'(?<![A-Za-z])'+pattern+r'(?![A-Za-z])'
        for match in re.finditer(pattern,text,re.I):
            prefix=re.split(r'[。！？;；.!?\n,，]',text[:match.start()])[-1][-80:]
            negative=bool(re.search(r"(?:\b(?:not|never|no)|n.t)\s+(?:[A-Za-z]+\s+){0,2}$|(?:没有|并非|从未|未曾|并未|未有|不曾|不再|并不|未见|未|不)(?![来断论仅管])[^，。；;.!?\n]{0,10}$",prefix,re.I))
            found.append((term,match.start(),match.end(),negative))
    return text,found

def event_polarities(text,terms):
    """Local explicit negation guard; intentionally not a full natural-language parser."""
    return {negative for *_,negative in _event_matches(text,terms)[1]}

_NUMERIC_ONLY_SOURCE_TYPES = frozenset({
    'saved_price', 'saved_price_set', 'market_quote',
    'reported_figure', 'calculation', 'formula_calculation',
})

# Notes that travel with a kept sentence (``unverified_lines`` items) but are not a verdict: they never
# enter the repair, never lower the turn's status and never add the 「证据不足」 footnote.
# ``number_read_from_source``: every figure of the line was read from a source by the number review
# (``number_review.py``); its evidence travels with the item.
HINT_REASONS=frozenset({'polarity_conflict','event_not_in_source','number_read_from_source'})
_NO_EVIDENCE_PASSAGE=re.compile(r'没有(?:可核验)?(?:资料|证据)|无法(?:核实|确认)|no (?:verified )?evidence',re.I)

def _passage_sources(passage,citations,indexed):
    """The sources a sentence cites; none for a sentence that itself says no evidence was found."""
    if _NO_EVIDENCE_PASSAGE.search(passage):return []
    return [indexed[r] for r in citation_markers(passage,citations) if r in indexed]

def _numeric_only_event(passage,sources):
    """The first event word of a sentence whose every cited source is a bare number (a price, a figure); else ''."""
    if not all(c.get('source_type') in _NUMERIC_ONLY_SOURCE_TYPES for c in sources):return ''
    for terms in CLAIM_FEATURES:
        found=_event_matches(passage,terms)[1]
        if found:return found[0][0]
    return ''

def unsupported_claims(answer,citations):
    """Source-kind rule only: an event asserted on a source that is only a number.  Not a proof of entailment.

    Polarity (the sentence says the opposite of its source) is ``polarity_conflicts``: a hint, not this verdict."""
    from .language import simplified
    answer=simplified(answer)
    indexed={str(c['ordinal']):c for c in citations}
    for passage in cited_passages(answer):
        sources=_passage_sources(passage,citations,indexed)
        if sources and _numeric_only_event(passage,sources):return True
    return False

_SENTENCE_END=re.compile(r'[。！？；;\n]|(?<=[A-Za-z0-9)”"])[.!?](?=\s|$)')

def _source_sentence(text,start,end,limit=200):
    """The sentence of ``text`` holding the span ``start:end``, cut to ``limit`` characters around the span."""
    left=0;right=len(text)
    for match in _SENTENCE_END.finditer(text):
        if match.end()<=start:left=match.end()
        elif match.start()>=end:right=match.start();break
    segment=text[left:right]
    if len(segment)>limit:
        low=max(0,min(start-left-limit//2,len(segment)-limit))
        segment=('…' if low else '')+segment[low:low+limit]+('…' if low+limit<len(segment) else '')
    return ' '.join(segment.split())

def polarity_conflicts(answer,citations):
    """Sentences whose event word is negated on one side only, with the source sentence that says so.

    A hint, never a verdict: the word list is frozen and misreads ("不久前辞职", a different subject), so a hit
    only shows the owner what the cited source says.  Each item: ``sentence``, ``ordinal`` (the source),
    ``terms`` (the sentence's word), ``source_term`` and ``snippet`` (the source's own sentence)."""
    from .language import simplified
    answer=simplified(answer)
    indexed={str(c['ordinal']):c for c in citations}
    out=[]
    for passage in cited_passages(answer):
        sources=_passage_sources(passage,citations,indexed)
        if not sources:continue
        evidence=simplified(' '.join(citation_check_text(c) for c in sources))
        for terms in CLAIM_FEATURES:
            claim_polarity=event_polarities(passage,terms)
            evidence_polarity=event_polarities(evidence,supporting_event_terms(terms))
            if not (claim_polarity and evidence_polarity and not claim_polarity<=evidence_polarity):continue
            # The sentence's word that the source does not share, and the first place a source uses its own.
            claim_word=next(term for term,_,_,negative in _event_matches(passage,terms)[1] if negative not in evidence_polarity)
            for source in sources:
                text,found=_event_matches(citation_check_text(source),supporting_event_terms(terms))
                if found:
                    term,start,end,_=found[0]
                    out.append({'sentence':passage.strip(),'ordinal':int(source['ordinal']),'terms':[claim_word],
                                'source_term':term,'snippet':_source_sentence(text,start,end)})
                    break
            break
    return out

def figures_confirmed(passage,citations,*,user_text='',verified=None,state_check=False):
    """Whether the sentence writes a figure its own cited sources state, and none they refute or lack."""
    reviews=number_review(passage,citations,user_text=user_text,verified=verified,state_check=state_check)
    return any(r['direct'] for r in reviews) and not any(r['rejected'] or r['insufficient'] for r in reviews)

def claim_hints(answer,citations,*,user_text='',verified=None,state_check=False):
    """Line-level hints for ``unverified_lines`` (see ``HINT_REASONS``), one per sentence that earns one.

    ``polarity_conflict``: the sentence and its source disagree on an event word.  ``event_not_in_source``: the
    sentence states an event on a source that is only a number, but the figure it writes is that source's own
    (the event word is background, so it is shown, not repaired).  Items carry ``line`` (the answer's line),
    ``reason``, ``sentence``, ``ordinal``, ``terms`` and ``snippet``."""
    if verified is None:verified=answer_verified_figures(answer,citations,user_text=user_text)
    indexed={str(c['ordinal']):c for c in citations}
    out=[]
    for _,stripped,checked in _reviewable_lines(answer,citations):
        if checked is None:continue
        bullet=_BULLET.match(stripped)
        for passage in cited_passages(checked[bullet.end():] if bullet else checked):
            passage=passage.strip()
            if not passage or is_inference_label(passage):continue
            sources=_passage_sources(passage,citations,indexed)
            if not sources:continue
            found=polarity_conflicts(passage,citations)
            if found:
                out.append({'line':stripped,'reason':'polarity_conflict',**found[0]});continue
            event=_numeric_only_event(passage,sources)
            if event and figures_confirmed(passage,citations,user_text=user_text,verified=verified,state_check=state_check):
                out.append({'line':stripped,'reason':'event_not_in_source','sentence':passage,'ordinal':int(sources[0]['ordinal']),
                            'terms':[event],'snippet':''})
    return out

_NON_TICKER_WORDS = frozenset({
    'SEC', 'FY', 'EPS', 'URL', 'HTTPS', 'HTTP', 'USD', 'CEO', 'CFO', 'CTO', 'COO',
    'AI', 'PE', 'PB', 'PS', 'ROE', 'ROA', 'GAAP', 'NON', 'TTM',
    'Q1', 'Q2', 'Q3', 'Q4', 'H1', 'H2', 'EST', 'EDT', 'CST', 'CDT', 'PST', 'PDT', 'UTC', 'GMT',
    'AND', 'OR', 'NOT', 'FOR', 'THE', 'IN', 'ON', 'AT', 'TO', 'BY', 'OF', 'WITH',
    'A', 'I', 'IT', 'IS', 'AS', 'BE', 'DO', 'AN', 'NO', 'SO', 'UP',
})

def shadow_entity_attribution_check(answer: str, citations: list[dict]) -> list[tuple[str, str, list[str | None]]]:
    """Shadow-mode check for sentences attributing a claim to the wrong ticker.

    Detects when a sentence cites sources whose symbol is all Y, but the sentence body
    only mentions a different ticker X.
    Only logged to audit/results for observation; never blocks or modifies answer.
    """
    if not answer or not citations:
        return []
    indexed = {int(c['ordinal']): c for c in citations if isinstance(c, dict) and isinstance(c.get('ordinal'), int)}
    mismatches = []

    for line in answer.splitlines():
        line_str = line.strip()
        if not line_str:
            continue
        markers = citation_markers(line_str, citations)
        if not markers:
            continue
        cited = [indexed[int(m)] for m in markers if int(m) in indexed]
        if not cited:
            continue
        cited_symbols = [c.get('symbol') for c in cited]
        if not cited_symbols or not all(s and isinstance(s, str) and s.strip() for s in cited_symbols):
            continue
        unique_cited = {s.strip().upper() for s in cited_symbols}
        if len(unique_cited) != 1:
            continue
        y_sym = next(iter(unique_cited))

        plain = re.sub(r'\[\d+\]', '', line_str)
        found_tokens = re.findall(r'(?<![A-Za-z0-9])[A-Z]{1,5}(?:\.[A-Z]{1,2})?(?![A-Za-z0-9])', plain)
        valid_tickers = {t.upper() for t in found_tokens if t.upper() not in _NON_TICKER_WORDS}

        if len(valid_tickers) == 1:
            x_sym = next(iter(valid_tickers))
            if x_sym != y_sym:
                mismatches.append((line_str, x_sym, [c.get('symbol') for c in cited]))

    return mismatches

def check_answer(answer: str, citations: list[dict], **kwargs) -> dict:
    """Shadow entity attribution and answer-level check helper."""
    mismatches = shadow_entity_attribution_check(answer, citations)
    return {
        "shadow_entity_mismatches": mismatches,
        "audit": {"shadow_entity_mismatches": mismatches},
    }

_PARTIAL_8K_TEXTS = frozenset({'exhibit_99_1_only', 'primary_document_only'})

def _partial_8k_claim_missing(passage, citations):
    """Whether a cited passage asserts an event absent from a partially stored 8-K filing."""
    from .language import simplified
    passage = simplified(passage)
    if re.search(r'没有(?:可核验)?(?:资料|证据)|无法(?:核实|确认)|no (?:verified )?evidence', passage, re.I):
        return False
    indexed = {str(c['ordinal']): c for c in citations}
    refs = citation_markers(passage, citations)
    sources = [indexed[r] for r in refs if r in indexed]
    if not sources or not all(c.get('saved_text') in _PARTIAL_8K_TEXTS for c in sources):
        return False
    evidence = simplified(' '.join(citation_check_text(c) for c in sources))
    for terms in CLAIM_FEATURES:
        if event_polarities(passage, terms) and not any(contains(t, evidence) for t in supporting_event_terms(terms)):
            return True
    return False


# A claim is only factual when it states an amount, a rate or a named event. A bare digit, a year,
# a count of results and a form label ("10-K") are none of them, so they must not each demand a
# citation: that rule used to reject most ordinary sentences and turn good turns into partial ones.
_CLAIM_AMOUNT = re.compile(
    r'\d[\d,.]*\s*(?:万亿|千万|百万|亿|万|千|trillion|billion|million|thousand|bn|mn|b\b|k\b)'
    r'|\d[\d,.]*\s*(?:%|％|美元|元|dollars?|USD)', re.I)


# A passage that reports what was NOT found states no fact, so it must not be asked for a
# citation: "本次检索没有取得可核验资料" and "两次均未返回可引用的营收来源" are honest reports of an
# absence.  The old two-form pattern recognised almost none of them, so those sentences were deleted
# and an otherwise good turn ended as partial.
_ABSENCE = re.compile(
    r'没有[^。！？；\n]{0,12}?(?:可核验|可靠|可用)?[^。！？；\n]{0,8}?(?:资料|证据|来源|数据|记录|结果|内容)'
    r'|(?:未|没能|均未|都未|全部未)(?:能)?(?:取得|找到|检索到|返回|核实|确认|读取)'
    r'|无法(?:核实|确认|取得|读取|验证)'
    r'|查无|暂无'
    r'|no (?:verified |matching )?(?:evidence|data|sources?|records?|results?)', re.I)


def reports_absence(text):
    """Whether this passage reports that nothing was found, rather than asserting a fact."""
    return bool(_ABSENCE.search(text))


def factual_claim(text):
    """Whether this passage states a fact that needs a source.

    A stated amount or rate needs one; so does a named event (an acquisition, an appointment).
    Merely naming a metric does not: "本次没有取得可核验的营收资料" mentions revenue while stating
    that nothing was found, and demanding a citation for it used to delete the honest sentence and
    end an otherwise good turn as partial.
    """
    if _CLAIM_AMOUNT.search(text):return True
    if any(any(contains(k, text) for k in group) for group in CLAIM_FEATURES):return True
    return False


def _restated_amounts_held(text,held):
    """Whether every amount a marker-less sentence states is one the answer has already verified (or the user
    wrote), and it names no event: a recap line repeating a cited figure needs no marker of its own."""
    from .semantic import figure_values
    found=list(_CLAIM_AMOUNT.finditer(text))
    if not found or any(any(contains(k,text) for k in group) for group in CLAIM_FEATURES):return False
    any_held=False
    for match in found:
        # The numeric check does not read list numbers, small integers and years as amounts; neither does this.
        values={v for v in figure_values(match.group(0)) if not ((1<=v<=10 or 1990<=v<=2035) and v==int(v))}
        if not values:continue
        if not values<=held:return False
        any_held=True
    return any_held


def reviewed_passages(answer,citations,*,require_citations=False,check_claims=True,user_text='',verified=None,state_check=False):
    """Diagnostics apply to affected passages, never erase other verified content.

    ``verified`` is the answer-wide verified set (``answer_verified_figures``); a caller that reviews one
    line at a time passes the whole answer's, so every verdict agrees.  Without it the set is made from
    ``answer`` itself."""
    accepted=[];issues=[]
    if verified is None and (check_claims or require_citations):verified=verified_figures(answer,citations,user_text=user_text)
    held=set(verified or ())|user_figure_values(user_text)
    for passage in cited_passages(answer):
        stripped = passage.strip()
        if not stripped:continue
        uncertainty=reports_absence(stripped)
        labelled=is_inference_label(stripped)
        is_leadin = bool(re.match(r'^(?:以下|根据|综上|总结|如上|经查询|查询结果|核验结果|提示|注意|说明|确认后|请核对|已为您|请注意)[^。！？\n]{0,35}[：:\n]?', stripped)) or (len(stripped) < 35 and stripped.endswith(('：', ':')))
        # A heading names what follows ("## 二、营收对比", "**单季营收（FY2026 Q3）**"); one that states no
        # amount asserts nothing to cite.
        is_heading = bool(re.match(r'^#{1,6}\s',stripped) or re.fullmatch(r'\*\*[^*]+\*\*\s*[：:]?',stripped))
        has_factual_content = factual_claim(stripped)
        code=('invalid_citation' if citation_errors(stripped,citations) else
              'missing_citation' if require_citations and has_factual_content and not labelled and not citation_markers(stripped,citations) and not uncertainty and not ((is_leadin or is_heading) and not _CLAIM_AMOUNT.search(stripped)) and not (stripped.endswith(('：',':')) and not _CLAIM_AMOUNT.search(stripped)) and not _restated_amounts_held(stripped,held) else None)
        if not code and check_claims:
            # Two outcomes: a figure the complete sources do not state is refuted; one missing only from a
            # partial source is "证据不完整" (it may sit in the part that was never stored).
            unsupported,insufficient=number_check(stripped,citations,user_text=user_text,verified=verified,state_check=state_check)
            marked=bool(citation_markers(stripped,citations))
            # An unmarked sentence is held to the backstop only: what we know is that it names no source,
            # not that a source disagrees.  An absence report states no fact.
            if unsupported and not marked and uncertainty:unsupported=[]
            claim_issue=None
            if not labelled:
                source_kind=unsupported_claims(stripped,citations)
                # An event word beside a figure that the cited source itself states is background: it is
                # shown as a hint (``claim_hints``), not sent to repair.
                if source_kind and not figures_confirmed(stripped,citations,user_text=user_text,verified=verified,state_check=state_check):
                    claim_issue='unsupported_claim'
                elif not source_kind and _partial_8k_claim_missing(stripped,citations):
                    claim_issue='source_part_not_stored'
            code=(('unsupported_numeric_claim' if marked else 'missing_citation') if unsupported else
                  'insufficient_numeric_evidence' if insufficient else
                  claim_issue)
        if code:issues.append(code)
        else:accepted.append(stripped)
    return accepted,issues


_ATOMIC_LINE = re.compile(r'^[|>#]|^[-*+]\s|^\d+[.)]\s')
_TABLE_RULE = re.compile(r'^\|?[\s:|-]+\|?$')
_BULLET = re.compile(r'^(?:[-*+]|\d+[.)])\s+')


def _table_citations(lines,citations):
    """For each table row that carries no [n] of its own, the markers its table states elsewhere.

    A table is cited as a unit: the caption above it, a note below it, a source column or another
    row carries the [n].  The row's figures are still checked against exactly those sources.
    """
    inherited={};index=0
    while index<len(lines):
        if not lines[index].strip().startswith('|'):index+=1;continue
        start=index
        while index<len(lines) and lines[index].strip().startswith('|'):index+=1
        before=next((lines[i] for i in range(start-1,-1,-1) if lines[i].strip()),'')
        after=next((lines[i] for i in range(index,len(lines)) if lines[i].strip()),'')
        markers=list(dict.fromkeys('['+n+']' for n in citation_markers(' '.join([before,*lines[start:index],after]),citations)))
        for row in range(start,index):
            if markers and not citation_markers(lines[row],citations):inherited[row]=' '+''.join(markers)
    return inherited


def _reviewable_lines(answer,citations):
    """Each line to check, with the text it is checked as; table headers and rules are not claims."""
    lines=answer.splitlines();inherited=_table_citations(lines,citations);out=[]
    index=0
    while index<len(lines):
        if not lines[index].lstrip().startswith('>'):index+=1;continue
        start=index
        while index<len(lines) and lines[index].lstrip().startswith('>') and lines[index].lstrip(' >').strip():index+=1
        if index==start:index+=1;continue
        # A citation at the end of one quoted paragraph covers that paragraph. An internal
        # marker, another paragraph, or a source outside the quote has no such scope.
        trailing=re.search(r'((?:\[\d+\]\s*)+)[。.!！?？]*\s*$',literal_titles(lines[index-1],citations))
        if trailing:
            for row in range(start,index):
                if not citation_markers(lines[row],citations):inherited[row]=' '+trailing[1]
    for index,line in enumerate(lines):
        stripped=line.strip()
        if not stripped or _TABLE_RULE.match(stripped):out.append((line,stripped,None));continue
        following=lines[index+1].strip() if index+1<len(lines) else ''
        if stripped.startswith('|') and '-' in following and _TABLE_RULE.match(following):
            # A header names columns ("| 期间 | 全年营业收入 |"); it states nothing to cite.
            out.append((line,stripped,None));continue
        out.append((line,stripped,stripped+inherited.get(index,'')))
    return out


def reviewed_answer(answer,citations,*,require_citations=False,check_claims=True,user_text='',verified=None):
    """Drop only what cannot be supported, line by line, so the answer keeps its formatting.

    ``reviewed_passages`` reads sentences; the answer is written in lines.  A rejected passage used
    to be handled by splitting the whole answer and rejoining the survivors with '。', which turned a
    Markdown table's separator row into '| --- | --- |。' and broke the table.  Here the line is the
    unit: a table row, list item, heading or quote is dropped whole (its syntax cannot survive half a
    sentence), and a prose line keeps the sentences that passed.
    """
    kept=[];issues=[]
    if verified is None and (check_claims or require_citations):verified=answer_verified_figures(answer,citations,user_text=user_text)
    for line,stripped,checked in _reviewable_lines(answer,citations):
        if checked is None:
            kept.append(line);continue
        # A list marker is not a sentence ("1." would otherwise split off as one).
        bullet=_BULLET.match(stripped)
        accepted,line_issues=reviewed_passages(checked[bullet.end():] if bullet else checked,citations,require_citations=require_citations,check_claims=check_claims,user_text=user_text,verified=verified)
        if not line_issues:
            kept.append(line);continue
        issues.extend(line_issues)
        if bullet and accepted:
            # A list item survives losing a sentence: keep its marker and the sentences that passed.
            kept.append(bullet.group(0)+'。'.join(accepted));continue
        if _ATOMIC_LINE.match(stripped):continue
        if accepted:kept.append('。'.join(accepted))
    text='\n'.join(kept).strip()
    return text,issues


def rejected_lines(answer,citations,*,require_citations=False,check_claims=True,user_text='',verified=None,state_check=False):
    """The lines ``reviewed_answer`` drops or trims, each with its first reason, for the repair."""
    out=[]
    if verified is None and (check_claims or require_citations):verified=answer_verified_figures(answer,citations,user_text=user_text)
    for _,stripped,checked in _reviewable_lines(answer,citations):
        if checked is None:continue
        bullet=_BULLET.match(stripped)
        _,issues=reviewed_passages(checked[bullet.end():] if bullet else checked,citations,require_citations=require_citations,check_claims=check_claims,user_text=user_text,verified=verified,state_check=state_check)
        if issues:out.append((stripped,issues[0]))
    return out


def labelled_inference_lines(answer,citations,*,user_text=''):
    """The sentences that carry an inference label (推断/估算/推算/假设) and passed: their premises hold, or they
    cite nothing.  For a later surface to show them as inference; nothing displays them yet."""
    verified=answer_verified_figures(answer,citations,user_text=user_text)
    out=[]
    for _,_,checked in _reviewable_lines(answer,citations):
        if checked is None:continue
        for passage in cited_passages(checked):
            stripped=passage.strip()
            if stripped and is_inference_label(stripped) and not reviewed_passages(stripped,citations,check_claims=True,user_text=user_text,verified=verified)[1]:
                out.append(stripped)
    return out


class ClaimGateResult:
    """Accepted claims plus drop issues. Iterates as ``(accepted, issues)``."""

    def __init__(self, accepted, issues, audit):
        self.accepted = accepted
        self.issues = issues
        self.audit = audit

    def __iter__(self):
        yield self.accepted
        yield self.issues


def reviewed_claims(claims, citations, source_bodies=None, *, min_chars=24):
    """Drop claims whose quote or field evidence does not bind to the cited source.

    Numbers are checked on the resolved source span (and header walk-up), never on
    the model-copied quote. Quote miss and unverified binds are drops, not pending.
    ``reviewed_answer`` is intentionally not called from here.
    """
    from dataclasses import replace

    from .claim_numeric import field_evidence_matches, header_context, numbers_supported
    from .claim_units import ClaimParseError, ClaimUnit, FieldEvidence, QuoteEvidence, parse_claims
    from .quote_bind import bind_quote

    units = _claim_units(claims, parse_claims, ClaimUnit, ClaimParseError)
    indexed = {}
    for citation in citations or []:
        if isinstance(citation, dict) and citation.get("ordinal") is not None:
            try:
                indexed[int(citation["ordinal"])] = citation
            except (TypeError, ValueError):
                continue
    bodies = source_bodies or {}
    accepted = []
    issues = []
    audit = {
        "claim_count": len(units),
        "accepted_count": 0,
        "quote_match_kinds": [],
        "resolved_span_hashes": [],
        "drop_reasons": [],
        "source_body_fallback": [],
    }
    for claim in units:
        citation = indexed.get(claim.citation_ordinal)
        if citation is None:
            _drop(issues, audit, claim, "bad_ordinal")
            continue
        if isinstance(claim.evidence, FieldEvidence):
            if not field_evidence_matches(claim.evidence, citation):
                _drop(issues, audit, claim, "field_mismatch")
                continue
            material = _citation_material(citation)
            unsupported = numbers_supported(claim.statement, material)
            if unsupported:
                _drop(issues, audit, claim, "unsupported_numeric", values=unsupported)
                continue
            accepted.append(claim)
            continue
        if not isinstance(claim.evidence, QuoteEvidence):
            _drop(issues, audit, claim, "field_mismatch")
            continue
        source, fallback = _source_body(bodies, claim.citation_ordinal, citation)
        if fallback:
            audit["source_body_fallback"].append(claim.citation_ordinal)
        bound = bind_quote(claim.evidence.evidence_quote, source, min_chars=min_chars)
        if not bound.ok:
            _drop(issues, audit, claim, bound.reason or "quote_not_found")
            continue
        context = header_context(source, bound.start_char)
        unsupported = numbers_supported(claim.statement, bound.resolved_quote, header_context=context)
        if unsupported:
            _drop(issues, audit, claim, "unsupported_numeric", values=unsupported)
            continue
        audit["quote_match_kinds"].append(bound.match_kind)
        audit["resolved_span_hashes"].append(hashlib.sha256(bound.resolved_quote.encode()).hexdigest())
        accepted.append(replace(claim, evidence=replace(claim.evidence, evidence_quote=bound.resolved_quote)))
    audit["accepted_count"] = len(accepted)
    audit["drop_reasons"] = [item["reason"] for item in issues]
    return ClaimGateResult(accepted, issues, audit)


def _claim_units(claims, parse_claims, claim_type, error_type):
    if not claims:
        return []
    if isinstance(claims, dict):
        return parse_claims(claims)
    first = claims[0]
    if isinstance(first, claim_type):
        return list(claims)
    try:
        return parse_claims(claims)
    except error_type:
        raise


def _drop(issues, audit, claim, reason, **extra):
    issues.append({
        "id": claim.id,
        "reason": reason,
        "citation_ordinal": claim.citation_ordinal,
        "statement": claim.statement,
        **extra,
    })
    audit["drop_reasons"].append(reason)


def _source_body(bodies, ordinal, citation):
    text = bodies.get(ordinal) if isinstance(bodies, dict) else None
    if isinstance(text, str) and text.strip():
        return text, False
    parts = [str(citation.get("check_text") or citation.get("quote") or "")]
    parts.extend(str(quote) for quote in citation.get("evidence_quotes") or [] if isinstance(quote, str) and quote)
    return "\n".join(part for part in parts if part), True


def _citation_material(citation):
    parts = [str(citation.get(key) or "") for key in ("quote", "figures", "check_text", "title",
             "published_at", "observed_at", "filed_at", "analysis_id", "accession_number", "form")]
    fields = citation.get("fields")
    if isinstance(fields, dict):
        parts.append(json.dumps(fields, ensure_ascii=False, default=str))
    parts.extend(str(quote) for quote in citation.get("evidence_quotes") or [] if isinstance(quote, str) and quote)
    calculation = citation.get("calculation")
    if isinstance(calculation, dict):
        parts.append(json.dumps(calculation, ensure_ascii=False, default=str))
    return " ".join(parts)
