from app.agent_tools import TOOL_REGISTRY, tool_schemas, normalize_agent_symbol
import asyncio


def test_fixed_read_only_registry_and_provider_schemas():
    assert set(TOOL_REGISTRY) == {
        "query_stock_prices", "query_latest_forecast", "query_materials", "query_sec_filings",
        "query_financials", "query_research_faq", "query_material_analysis", "search_material_analysis",
        "web_research", "query_portfolio", "query_market_quote", "query_alerts", "query_holdings_overview"
    }
    assert set(TOOL_REGISTRY) <= {x["function"]["name"] for x in tool_schemas()}
    assert normalize_agent_symbol(" brk-b ") == "BRK.B"
    assert normalize_agent_symbol("amd") == "AMD"


def test_tool_schemas_are_strict_and_limited():
    price = TOOL_REGISTRY["query_stock_prices"].args_schema
    assert price.model_validate({"symbol": "amd"}).symbol == "AMD"
    try:
        price.model_validate({"symbol": "AMD", "sql": "DROP TABLE"})
    except Exception:
        pass
    else:
        raise AssertionError("unknown fields must be rejected")
    assert price.model_validate({"symbol": "BRK-B"}).symbol == "BRK.B"
    assert price.model_json_schema()["properties"]["limit"]["maximum"] == 366


def test_sec_without_form_omits_nullable_parameter(monkeypatch):
    import app.agent_tools as tools
    seen=[]
    async def query(sql,params): seen.append((sql,params)); return []
    monkeypatch.setattr(tools,"_query",query)
    asyncio.run(tools.query_sec_filings.ainvoke({"symbol":"AAPL","form":None}))
    assert ":form" not in seen[0][0]
    assert "form" not in seen[0][1]

def test_sec_filing_tool_preserves_source_and_selects_item_text(monkeypatch):
    import app.agent_tools as tools
    import hashlib
    body='Cover page\n'+('x'*1500)+'\nItem 2. Management discussion of operating performance.'+(' substantive text.'*100)
    digest=hashlib.sha256(body.encode()).hexdigest()
    async def query(sql,params):
        assert 'accession_number' in sql and 'content_source_url' in sql
        return [{'id':'filing-uuid','accession_number':'0000000000-26-000001','source_url':'https://sec.test/main','content_source_url':'https://sec.test/exhibit','content_excerpt':body,'content_excerpt_sha256':digest,'content_truncated':True,'content_status':'fetched','observed_at':None}]
    monkeypatch.setattr(tools,'_query',query)
    async def index_state(_source_id): return 'not_imported'
    monkeypatch.setattr(tools,'_index_state',index_state)
    result=asyncio.run(tools.query_sec_filings.ainvoke({'symbol':'AMD'}))
    row=result['data'][0]
    assert row['body_hash_valid'] is True
    assert row['excerpt'].startswith('Item 2.')
    assert row['source_url']=='https://sec.test/main' and row['content_source_url']=='https://sec.test/exhibit'
    assert row['excerpt_coverage']=='partial_excerpt'
    assert tools._substantive_excerpt('Cover\n'+'x'*1400+'\nItem 3.02 Unregistered Sales\nDetails of the transaction') .startswith('Item 3.02')


def test_xbrl_preamble_yields_financial_table_with_byte_boundaries():
    import app.agent_tools as tools
    body = ('UNITED STATES SECURITIES AND EXCHANGE COMMISSION\n'
            'FORM 10-Q\nTABLE OF CONTENTS\nItem 1. Financial Statements ........ 3\n'
            + ('<xbrli:context id="c1"><xbrli:period>2026-06-27</xbrli:period></xbrli:context>\n' * 35)
            + 'APPLE INC.\nCONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS\n'
            'Three Months Ended June 27, 2026 and June 28, 2025\n'
            'Net sales\t94,036\t85,777\nCost of sales\t48,822\t46,099\n'
            'Gross margin\t45,214\t39,678\n')
    excerpt = tools._substantive_excerpt(body, 650)
    assert excerpt.startswith('CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS')
    assert 'Net sales\t94,036\t85,777\nCost of sales\t48,822' in excerpt
    assert 'TABLE OF CONTENTS' not in excerpt and '<xbrli:context' not in excerpt
    assert len(excerpt.encode('utf-8')) <= 650
    assert len(tools._substantive_excerpt('财报\n' * 1000, 301).encode('utf-8')) <= 301

def test_latest_saved_analysis_tool_schema_is_registered_and_bounded():
    import app.agent_tools as tools
    assert 'query_material_analysis' in tools.TOOL_REGISTRY
    assert 'search_material_analysis' in tools.TOOL_REGISTRY
    schema=tools.TOOL_REGISTRY['search_material_analysis'].args_schema.model_json_schema()
    assert schema['properties']['symbol']['maxLength']==12 and schema['properties']['limit']['maximum']==10
    schema=tools.query_material_analysis.args_schema.model_json_schema()
    assert {'symbol','accession_number','source_id','form','financial_only'}==set(schema['properties'])
    assert 'source_id' not in schema.get('required',[])


def test_saved_analysis_query_nullable_filters_bind_on_real_postgres(disposable_database):
    from app.database import Base, engine
    from app.models import SecFilingInventory, UploadedEvidence
    from app.forecast_v2_models import EvidenceEventVersionV2
    from app.material_analysis_models import MaterialAnalysisJob, MaterialAnalysisVersion
    Base.metadata.create_all(engine, tables=[SecFilingInventory.__table__, UploadedEvidence.__table__,
        EvidenceEventVersionV2.__table__, MaterialAnalysisJob.__table__, MaterialAnalysisVersion.__table__])
    result=asyncio.run(TOOL_REGISTRY['query_material_analysis'].ainvoke({'symbol':'AMD'}))
    assert result['ok'] is True and result['data']==[]

def test_saved_analysis_source_url_drops_private_credentials():
    from app.agent_tools import _safe_source_url
    assert _safe_source_url('https://user:pass@example.test/doc?access_token=private&section=2#part')=='https://example.test/doc?section=2'


def test_saved_analysis_rejects_tampering_and_accepts_owner_scoped_parsed_upload(monkeypatch):
    import asyncio, hashlib
    from datetime import UTC, datetime
    import app.agent_tools as tools
    from app.knowledge.runtime import research_context
    now=datetime.now(UTC)
    source_id='00000000-0000-4000-8000-000000000001'
    body='PDF raw bytes are intentionally different from parsed text.'
    parsed='The parsed report states World Labs consideration is $8.2 billion.'
    digest=hashlib.sha256(body.encode()).hexdigest()
    frozen={'source_id':source_id,'source_type':'uploaded_media','content_sha256':digest,'analysis_text':parsed}
    manifest={'source_id':source_id,'source_type':'uploaded_media','content_sha256':digest,
        'evidence_version_id':'event-1','analysis_text_sha256':hashlib.sha256(parsed.encode()).hexdigest()}
    def result_row(**changes):
        row={'id':'analysis-1','evidence_version_id':'event-1','source_type':'uploaded_media','source_id':source_id,'version_no':1,
            'created_at':now,'actual_model':'pinned-model','payload':{'summary':'A saved analysis.','facts':[{'citations':[{'quote':'$8.2 billion'}]}]},
            'source_manifest':manifest,'content_sha256':digest,'source_snapshot':frozen,'citations':[],
            'symbol':'AMD','published_at':now,'observed_at':now,'upload_published_at':now,'upload_observed_at':now,'upload_title':'Parsed report',
            'upload_url':'https://example.test/report','upload_text':parsed,'upload_body_hash':digest}
        row.update(changes);return row
    current=[result_row()]
    async def query(sql,params):
        if 'SELECT owner_hash FROM knowledge_upload_owners' in sql:return [{'owner_hash':'a'*64}]
        assert 'v.created_at<=:cutoff' in sql and 'v.created_at<=:now' in sql
        if params['symbol']!='AMD':return []
        if params['cutoff']<now:return []
        return current
    monkeypatch.setattr(tools,'_query',query)
    async def index_state(_source_id): return 'not_imported'
    monkeypatch.setattr(tools,'_index_state',index_state)
    with research_context('a'*64):
        valid=asyncio.run(tools.query_material_analysis.ainvoke({'symbol':'AMD','source_id':source_id}))
    assert valid['ok'] and len(valid['data'])==1 and valid['data'][0]['evidence_quotes']==['$8.2 billion']
    assert len(__import__('json').dumps(valid).encode())<8192
    with research_context('b'*64):
        assert asyncio.run(tools.query_material_analysis.ainvoke({'symbol':'AMD','source_id':source_id}))['data']==[]
    current[:]=[result_row(source_manifest={**manifest,'content_sha256':'0'*64})]
    with research_context('a'*64):
        assert asyncio.run(tools.query_material_analysis.ainvoke({'symbol':'AMD','source_id':source_id}))['data']==[]


def test_an_analysis_done_twice_is_read_with_the_version_before_it(monkeypatch):
    """Regression from 2026-10-26: Intel's 10-Q had two AI analyses, but the tool returned only the
    latest, so asked to look at both the agent said the other version could not be found."""
    import asyncio, hashlib
    from datetime import UTC, datetime, timedelta
    import app.agent_tools as tools
    from app.agent_chat_stream import bounded_tool_result
    from app.knowledge.runtime import research_context
    now=datetime.now(UTC)
    source_id='00000000-0000-4000-8000-000000000001'
    parsed='报'*2000
    digest=hashlib.sha256(parsed.encode()).hexdigest()
    frozen={'source_id':source_id,'source_type':'uploaded_media','content_sha256':digest,'analysis_text':parsed}
    manifest={'source_id':source_id,'source_type':'uploaded_media','content_sha256':digest,
        'evidence_version_id':'event-1','analysis_text_sha256':hashlib.sha256(parsed.encode()).hexdigest()}
    # Long summaries and quotes: the budget, not the sample, has to keep both versions in the result.
    def version(number):
        return {'id':f'analysis-{number}','evidence_version_id':'event-1','source_type':'uploaded_media','source_id':source_id,
            'version_no':number,'created_at':now-timedelta(days=2-number),'actual_model':f'model-{number}',
            'payload':{'summary':f'第{number}版'+'析'*900,'facts':[{'citations':[{'quote':'报'*(400+n)}]} for n in range(3)]},
            'source_manifest':manifest,'content_sha256':digest,'source_snapshot':frozen,'citations':[],
            'symbol':'AMD','published_at':now,'observed_at':now,'upload_published_at':now,'upload_observed_at':now,
            'upload_title':'Parsed report','upload_url':'https://example.test/report','upload_text':parsed,'upload_body_hash':digest}
    async def query(sql,params):
        if 'SELECT owner_hash FROM knowledge_upload_owners' in sql:return [{'owner_hash':'a'*64}]
        return [version(2),version(1)]
    monkeypatch.setattr(tools,'_query',query)
    async def index_state(_source_id): return 'not_imported'
    monkeypatch.setattr(tools,'_index_state',index_state)
    with research_context('a'*64):
        rows=bounded_tool_result(asyncio.run(tools.query_material_analysis.ainvoke({'symbol':'AMD'})))['data']

    assert [(row['version_no'],row.get('role')) for row in rows]==[(2,None),(1,'previous_version')]
    assert rows[0]['summary'].startswith('第2版') and rows[1]['summary'].startswith('第1版')
    assert rows[1]['evidence_quotes']==[]


def test_saved_sec_analysis_rejects_changed_current_body_without_changing_saved_digests(monkeypatch):
    import asyncio, hashlib
    from datetime import UTC, datetime
    import app.agent_tools as tools
    from app.knowledge.runtime import research_context
    now=datetime.now(UTC)
    source_id='00000000-0000-4000-8000-000000000001'
    body='Item 3.02: acquisition consideration was $8.2 billion.'
    analysis='Saved analysis text with the quoted $8.2 billion.'
    digest=hashlib.sha256(body.encode()).hexdigest()
    manifest={'source_id':source_id,'source_type':'official_filing','content_sha256':digest,
        'evidence_version_id':'event-1','analysis_text_sha256':hashlib.sha256(analysis.encode()).hexdigest()}
    frozen={'source_id':source_id,'content_sha256':digest,'analysis_text':analysis}
    row={'id':'analysis-1','evidence_version_id':'event-1','source_type':'official_filing','source_id':source_id,
        'version_no':1,'created_at':now,'actual_model':'pinned-model','payload':{'summary':'Saved summary.',
        'facts':[{'citations':[{'quote':'$8.2 billion'}]}]},'source_manifest':manifest,'content_sha256':digest,
        'source_snapshot':frozen,'citations':[],'symbol':'AMD','published_at':now,'observed_at':now,
        'accession_number':'0000320193-26-000001','filed_at':now.date(),'filing_filed_at':now.date(),
        'filing_url':'https://example.test/sec','content_source_url':'https://example.test/sec',
        'filing_body_hash':digest,'filing_text':body,'filing_content_observed_at':now,'filing_observed_at':now}
    async def query(sql,params): return [row]
    monkeypatch.setattr(tools,'_query',query)
    async def index_state(_source_id): return 'not_imported'
    monkeypatch.setattr(tools,'_index_state',index_state)
    with research_context('a'*64):
        valid=asyncio.run(tools.query_material_analysis.ainvoke({'symbol':'AMD','source_id':source_id}))
    assert len(valid['data'])==1
    # Mutate only the authoritative current body; stored hashes and frozen input stay intact.
    row['filing_text']=body+' Altered current SEC text.'
    with research_context('a'*64):
        altered=asyncio.run(tools.query_material_analysis.ainvoke({'symbol':'AMD','source_id':source_id}))
    assert altered['data']==[]


def test_material_search_delegates_natural_language_to_dense_retrieval(monkeypatch):
    import app.agent_tools as tools
    monkeypatch.setenv('RAG_ENABLED','true')
    seen=[]
    async def retrieve(symbol,query,limit):
        seen.append((symbol,query,limit))
        return {"ok":True,"data":[],"source":"knowledge_documents","as_of":None}
    monkeypatch.setattr(tools,"retrieve_materials",retrieve)
    result=asyncio.run(tools.query_materials.ainvoke({"symbol":"AAPL","keyword":"查FY2025收入"}))
    assert seen==[("AAPL","查FY2025收入",5)]
    assert result=={"ok":True,"data":[],"source":"knowledge_documents","as_of":None}
    schema=tools.query_materials.args_schema.model_json_schema()
    assert set(schema["properties"])=={"symbol","keyword","source_id","limit"}


def test_forecast_jsonb_null_falls_through_to_baseline(monkeypatch):
    import app.agent_tools as tools
    async def query(sql,params):
        assert "forecast_versions_v2" in sql and "forecast_snapshots" not in sql
        return [{"id":"v","version_no":1,"decision_probabilities":"null","joint_probabilities":None,"baseline_probabilities":{"bearish":.2,"neutral":.3,"bullish":.5},"research_brief":None,"created_at":None}]
    monkeypatch.setattr(tools,"_query",query)
    result=asyncio.run(tools.query_latest_forecast.ainvoke({"symbol":"AAPL"}))
    assert result["data"][0]["probabilities"]=={"bearish":.2,"neutral":.3,"bullish":.5}


def test_legacy_materials_recovers_when_owner_table_is_absent(disposable_database):
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4
    from app.database import Base, engine
    from app.database import SessionLocal
    from app.models import SecFilingInventory, UploadedEvidence
    from app.knowledge.models import KnowledgeUploadOwner
    from app.knowledge.runtime import research_context
    import app.agent_tools as tools

    required = [UploadedEvidence.__table__, SecFilingInventory.__table__, KnowledgeUploadOwner.__table__]
    Base.metadata.create_all(engine, tables=required)
    upload_id = uuid4()
    now = datetime.now(UTC)
    body = "legacy uploaded evidence"
    excerpt = "public SEC excerpt"
    with SessionLocal() as session:
        session.add(UploadedEvidence(
            id=upload_id, symbol="AAPL", title="Legacy upload", source_url="https://example.test/upload",
            published_at=now, observed_at=now, credibility_stars=3, credibility_reason="fixture",
            impact_severity="medium", filename="fixture.txt", content_sha256="a" * 64,
            raw_content=body.encode(), content_text=body, status="unconfirmed",
        ))
        session.add(SecFilingInventory(
            id=uuid4(), symbol="AAPL", cik="0000320193", accession_number=f"0000320193-26-{uuid4().int % 1000000:06d}",
            form="10-Q", filed_at=now.date(), primary_document="public excerpt", source_url="https://example.test/sec",
            source="synthetic", review_status="pending_review", reviewed_at=None, observed_at=now-timedelta(minutes=2),
            content_status="fetched", content_observed_at=now-timedelta(minutes=1), content_excerpt=excerpt,
            content_excerpt_sha256=__import__("hashlib").sha256(excerpt.encode()).hexdigest(),
        ))
        missing_observation = "excerpt without content observation"
        session.add(SecFilingInventory(
            id=uuid4(), symbol="AAPL", cik="0000320193", accession_number=f"0000320193-26-{uuid4().int % 1000000:06d}",
            form="10-Q", filed_at=now.date(), primary_document="missing observation", source_url="https://example.test/sec-2",
            source="synthetic", review_status="accepted", reviewed_at=now-timedelta(minutes=3), observed_at=now-timedelta(minutes=4),
            content_status="fetched", content_observed_at=None, content_excerpt=missing_observation,
            content_excerpt_sha256=__import__("hashlib").sha256(missing_observation.encode()).hexdigest(),
        ))
        future_body="future fetched excerpt"
        session.add(SecFilingInventory(
            id=uuid4(), symbol="AAPL", cik="0000320193", accession_number=f"0000320193-26-{uuid4().int % 1000000:06d}",
            form="10-Q", filed_at=now.date()+timedelta(days=1), primary_document="future filing", source_url="https://example.test/sec-future",
            source="synthetic", review_status="pending_review", reviewed_at=None, observed_at=now,
            content_status="fetched", content_observed_at=now, content_excerpt=future_body,
            content_excerpt_sha256=__import__("hashlib").sha256(future_body.encode()).hexdigest(),
        ))
        tampered_body="tampered excerpt"
        session.add(SecFilingInventory(
            id=uuid4(), symbol="AAPL", cik="0000320193", accession_number=f"0000320193-26-{uuid4().int % 1000000:06d}",
            form="10-Q", filed_at=now.date(), primary_document="tampered filing", source_url="https://example.test/sec-tampered",
            source="synthetic", review_status="pending_review", reviewed_at=None, observed_at=now,
            content_status="fetched", content_observed_at=now, content_excerpt=tampered_body,
            content_excerpt_sha256="0"*64,
        ))
        session.commit()

    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE knowledge_upload_owners RENAME TO knowledge_upload_owners_temporarily_absent")
    try:
        with research_context("verified-owner") as context:
            context.legacy_unmapped_owner = True
            owner_result = asyncio.run(tools._legacy_materials("AAPL", "legacy", 5))
        guest_result = asyncio.run(tools._legacy_materials("AAPL", "legacy", 5))
        assert [row["material_type"] for row in owner_result["data"]] == ["uploaded_media"]
        assert guest_result["data"] == []
        public_result = asyncio.run(tools._legacy_materials("AAPL", "excerpt", 5))
        assert [row["material_type"] for row in public_result["data"]] == ["official_filing"]
        assert datetime.fromisoformat(public_result["as_of"]) == now-timedelta(minutes=1)
        with research_context("verified-owner", cutoff=now-timedelta(seconds=90)):
            too_early = asyncio.run(tools._legacy_materials("AAPL", "excerpt", 5))
        assert too_early["data"] == []
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE knowledge_upload_owners_temporarily_absent RENAME TO knowledge_upload_owners")
    with SessionLocal() as session:
        session.add(KnowledgeUploadOwner(upload_id=upload_id, owner_hash="verified-owner"))
        session.commit()
    with research_context("verified-owner"):
        mapped_owner = asyncio.run(tools._legacy_materials("AAPL", "legacy", 5))
    with research_context("different-owner"):
        mapped_guest = asyncio.run(tools._legacy_materials("AAPL", "legacy", 5))
    assert [row["material_type"] for row in mapped_owner["data"]] == ["uploaded_media"]
    assert mapped_guest["data"] == []


def test_sql_latest_financial_ai_summary_ignores_newer_8k_with_index_pending(disposable_database, monkeypatch):
    import asyncio
    import hashlib
    from datetime import UTC, date, datetime, timedelta
    from uuid import uuid4
    import app.agent_tools as tools
    from app.database import Base, SessionLocal, engine
    from app.models import SecFilingInventory, UploadedEvidence
    from app.forecast_v2_models import EvidenceEventVersionV2
    from app.material_analysis_models import MaterialAnalysisJob, MaterialAnalysisVersion
    Base.metadata.create_all(engine, tables=[SecFilingInventory.__table__, UploadedEvidence.__table__,
        EvidenceEventVersionV2.__table__, MaterialAnalysisJob.__table__, MaterialAnalysisVersion.__table__])
    now=datetime.now(UTC)-timedelta(hours=1)
    with SessionLocal() as db:
        for form,day,summary in (("10-Q",date(2026,9,25),"Correct 10-Q AI summary."),
                                 ("8-K",date(2026,10,2),"Newer 8-K AI summary.")):
            source_id=uuid4(); event_id=uuid4(); job_id=uuid4()
            body=f"{form} saved filing body for AMD."
            analysis_text=f"AI analysis of {form} saved source."
            digest=hashlib.sha256(body.encode()).hexdigest()
            accession=f"0000000001-26-{1 if form=='10-Q' else 2:06d}"
            db.add(SecFilingInventory(id=source_id,symbol="AMD",cik="0000000001",accession_number=accession,
                form=form,filed_at=day,primary_document="report.htm",source_url="https://example.test/"+accession,
                source="sec",review_status="accepted",observed_at=now,content_status="fetched",
                content_observed_at=now,content_excerpt=body,content_excerpt_sha256=digest,content_truncated=False))
            db.add(EvidenceEventVersionV2(id=event_id,symbol="AMD",source_type="official_filing",source_id=source_id,
                source_snapshot={"source_id":str(source_id),"content_sha256":digest,"analysis_text":analysis_text},
                content_sha256=digest,published_at=now,observed_at=now,event_key=str(source_id),
                citations=[],review_status="accepted",review_snapshot={},review_fingerprint=str(source_id),
                extraction_schema_version="fixture-v1"))
            db.add(MaterialAnalysisJob(id=job_id,source_type="official_filing",source_id=source_id,status="succeeded",
                current_stage="complete",idempotency_key="fixture-"+str(job_id),request_fingerprint="fixture",
                input_fingerprint="fixture",requested_model="fixture",schema_version="fixture",prompt_version="fixture"))
            db.add(MaterialAnalysisVersion(id=uuid4(),source_type="official_filing",source_id=source_id,
                evidence_version_id=event_id,version_no=1,job_id=job_id,input_fingerprint="fixture",
                schema_version="fixture",prompt_version="fixture",requested_model="fixture",actual_model="fixture",
                payload={"summary":summary},source_manifest={"source_id":str(source_id),
                "source_type":"official_filing","content_sha256":digest,"evidence_version_id":str(event_id),
                "analysis_text_sha256":hashlib.sha256(analysis_text.encode()).hexdigest()},usage={}))
        db.commit()
    async def pending(_): return "index_pending"
    monkeypatch.setattr(tools,"_index_state",pending)
    financial=asyncio.run(tools.query_material_analysis.ainvoke({"symbol":"AMD","financial_only":True}))
    latest=asyncio.run(tools.query_material_analysis.ainvoke({"symbol":"AMD"}))
    exact=asyncio.run(tools.query_material_analysis.ainvoke({"symbol":"AMD","form":"10-Q",
        "accession_number":"0000000001-26-000001"}))
    assert financial["data"][0]["summary"]==exact["data"][0]["summary"]=="Correct 10-Q AI summary."
    assert financial["data"][0]["index_status"]=="index_pending"
    assert latest["data"][0]["summary"]=="Newer 8-K AI summary."


def test_sec_filing_tool_reads_the_full_text_and_reports_its_size(monkeypatch):
    import app.agent_tools as tools
    import hashlib
    text = 'Cover page\n' + ('x' * 20000) + '\nItem 7. MD&A of results of operations\n' + ('y' * 20000)
    digest = hashlib.sha256(text.encode()).hexdigest()

    async def query(sql, params):
        assert 'content_text' in sql and 'content_length' in sql
        return [{'id': 'filing-uuid', 'accession_number': '0000000000-26-000009', 'form': '10-K',
                 'filed_at': None, 'source_url': 'https://sec.test/main', 'content_source_url': None,
                 'content_status': 'fetched', 'content_truncated': True,
                 'content_excerpt': text[:80000], 'content_excerpt_sha256': digest,
                 'content_text': text, 'content_text_sha256': digest, 'content_length': len(text),
                 'observed_at': None}]

    monkeypatch.setattr(tools, '_query', query)

    async def index_state(_source_id):
        return 'not_imported'

    monkeypatch.setattr(tools, '_index_state', index_state)
    row = asyncio.run(tools.query_sec_filings.ainvoke({'symbol': 'AAPL'}))['data'][0]
    assert row['body_hash_valid'] is True
    assert row['saved_text'] == 'full_document'
    assert row['saved_characters'] == len(text)
    assert row['excerpt'].startswith('Item 7.')
    assert len(row['excerpt']) <= tools.FILING_EXCERPT_BYTES
    assert 'content_text' not in row


def test_evidence_class_declarations():
    from app.agent_tool_catalog import definitions
    defs = definitions()
    assert defs["query_portfolio"].evidence_class == "owner_record"
    assert defs["query_alerts"].evidence_class == "owner_record"
    assert defs["query_holdings_overview"].evidence_class == "owner_record"
    assert defs["query_stock_prices"].evidence_class == "subject_row"
    assert defs["query_market_quote"].evidence_class == "subject_row"
    assert defs["query_financials"].evidence_class == "subject_row"
    assert defs["query_sec_filings"].evidence_class == "subject_row"
    assert defs["recall_conversations"].evidence_class == "memory"
    assert defs["calculate"].evidence_class == "derived"
    assert defs["calculate_formula"].evidence_class == "derived"


def test_query_market_quote_read_only_and_fallback(monkeypatch):
    import app.agent_tools as tools
    tools._QUOTE_CACHE.clear()

    async def mock_query(sql, params):
        if params.get("symbol") == "AAPL":
            return [
                {"trading_date": "2026-11-03", "close": 230.5},
                {"trading_date": "2026-11-02", "close": 228.0},
            ]
        return []

    monkeypatch.setattr(tools, "_query", mock_query)

    def mock_fetch_yahoo(sym, timeout=5.0):
        if sym == "MSFT":
            return {
                "price": 420.0,
                "prev_close": 415.0,
                "change_pct": 1.20,
                "trading_date": "2026-11-03",
            }
        raise RuntimeError("remote unavailable")

    monkeypatch.setattr(tools, "_fetch_yahoo_market_quote", mock_fetch_yahoo)

    # 1. Successful local DB lookup
    res_aapl = asyncio.run(tools.query_market_quote.ainvoke({"symbols": ["AAPL"]}))
    assert res_aapl["ok"] is True
    row_aapl = res_aapl["data"][0]
    assert row_aapl["symbol"] == "AAPL"
    assert row_aapl["price"] == 230.5
    assert row_aapl["prev_close"] == 228.0
    assert row_aapl["change_pct"] == 1.1
    assert "230.5" in row_aapl["excerpt"]
    assert "228.0" in row_aapl["excerpt"]

    # 2. Remote Yahoo fallback for uncached/unpersisted symbol
    res_msft = asyncio.run(tools.query_market_quote.ainvoke({"symbols": ["MSFT"]}))
    assert res_msft["ok"] is True
    row_msft = res_msft["data"][0]
    assert row_msft["symbol"] == "MSFT"
    assert row_msft["price"] == 420.0
    assert "420.0" in row_msft["excerpt"]

    # 3. Remote failure gracefully degrades to unavailable
    res_fail = asyncio.run(tools.query_market_quote.ainvoke({"symbols": ["UNKNOWN"]}))
    assert res_fail["ok"] is True
    row_fail = res_fail["data"][0]
    assert row_fail["symbol"] == "UNKNOWN"
    assert row_fail["status"] == "unavailable"

    # 4. Truncation to 5 symbols
    symbols_6 = ["S1", "S2", "S3", "S4", "S5", "S6"]
    res_capped = asyncio.run(tools.query_market_quote.ainvoke({"symbols": symbols_6}))
    assert res_capped["ok"] is True
    assert len(res_capped["data"]) == 5
    assert res_capped["meta"].get("capped_at") == 5


def test_query_alerts_read_only_and_fallback(tmp_path, monkeypatch):
    import app.agent_tools as tools
    import sqlite3

    # 1. Missing db file -> silent graceful return
    monkeypatch.setenv("SENTINEL_DB_PATH", str(tmp_path / "nonexistent.db"))
    res_missing = asyncio.run(tools.query_alerts.ainvoke({}))
    assert res_missing["ok"] is True
    assert res_missing["data"] == []
    assert res_missing["meta"]["note"] == "sentinel_db_not_found"

    # 2. Existing db with test alerts
    db_file = tmp_path / "sentinel.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, kind TEXT, text TEXT, created_at REAL)")
    conn.execute("INSERT INTO alerts (symbol, kind, text, created_at) VALUES ('AAPL', 'daily', 'AAPL 涨超 5%', 1793750000.0)")
    conn.execute("INSERT INTO alerts (symbol, kind, text, created_at) VALUES ('MSFT', 'short', 'MSFT 5分钟异动', 1793751000.0)")
    conn.commit()
    conn.close()

    monkeypatch.setenv("SENTINEL_DB_PATH", str(db_file))
    res_all = asyncio.run(tools.query_alerts.ainvoke({}))
    assert res_all["ok"] is True
    assert len(res_all["data"]) == 2
    assert res_all["data"][0]["source_type"] == "portfolio"
    assert res_all["data"][0]["id"].startswith("alert:")
    assert "MSFT" in res_all["data"][0]["excerpt"]

    # Filter by symbol
    res_aapl = asyncio.run(tools.query_alerts.ainvoke({"symbol": "AAPL"}))
    assert res_aapl["ok"] is True
    assert len(res_aapl["data"]) == 1
    assert res_aapl["data"][0]["symbol"] == "AAPL"


def test_query_holdings_overview_aggregation(monkeypatch):
    import app.agent_tools as tools
    import app.portfolio as portfolio
    import json
    from app.knowledge.runtime import research_context

    mock_summary = {
        "price_date": "2026-11-03",
        "available_funds": "10000.00",
        "positions_value": "5000.00",
        "total_assets": "15000.00",
        "floating_pnl": "500.00",
        "today_pnl": "100.00",
        "today_pnl_reference_only": False,
        "realized_pnl": "0.00",
        "warnings": [],
        "positions": [
            {
                "symbol": "NVDA",
                "shares": "10",
                "avg_cost": "120.00",
                "diluted_cost": "120.00",
                "cost": "1200.00",
                "price": "135.00",
                "price_date": "2026-11-03",
                "market_value": "1350.00",
                "floating_pnl": "150.00",
                "floating_pnl_pct": "12.50",
                "today_pnl": "20.00",
                "today_pnl_reference_only": False,
                "weight_pct": "9.00",
                "realized_pnl": "0.00",
                "plan": {},
            }
        ],
    }

    monkeypatch.setattr(portfolio, "build_summary", lambda owner: mock_summary)

    async def mock_query(sql, params):
        if params.get("symbol") == "NVDA":
            return [{
                "id": "fc-uuid",
                "version_no": 3,
                "decision_at": "2026-11-01",
                "decision_probabilities": json.dumps({"bullish": 0.65, "neutral": 0.25, "bearish": 0.10}),
                "joint_probabilities": None,
                "baseline_probabilities": None,
                "target_contract": {},
            }]
        return []

    monkeypatch.setattr(tools, "_query", mock_query)

    with research_context("test_owner"):
        res = asyncio.run(tools.query_holdings_overview.ainvoke({}))
    assert res["ok"] is True
    # rows: 1 account row + 1 holding row
    assert len(res["data"]) == 2
    holding = res["data"][1]
    assert holding["symbol"] == "NVDA"
    assert "最新 20 交易日预测（第 3 版，决策日 2026-11-01）：看涨 65.0%、持平 25.0%、看跌 10.0%。" in holding["excerpt"]


def test_owner_record_evidence_class_auto_accept(monkeypatch):
    from app.agent_workflow.direct import Turn
    from app.agent_workflow.state import AgentRuntimeContext

    t = Turn("持仓和提醒", AgentRuntimeContext("custom", "test", "dummy"), None, [], {})
    t.route = "A"

    outcome = {
        "ok": True,
        "source": "mock_owner_tool",
        "data": [
            {"id": "alert:1", "source_type": "portfolio", "symbol": "AAPL", "excerpt": "AAPL 盘前异动 5%。"}
        ]
    }

    # Calling accept with query_alerts (which has evidence_class='owner_record')
    t.accept("query_alerts", {}, outcome)
    assert t.last_accepted is not None
    assert len(t.citations) == 1
    assert t.citations[0]["symbol"] == "AAPL"
    assert "[1]" in t.last_accepted["data"][0]["citation"]


def test_shadow_entity_attribution_check():
    from app.agent_workflow.evidence import shadow_entity_attribution_check
    from app.agent_workflow.direct import Turn
    from app.agent_workflow.state import AgentRuntimeContext

    citations = [
        {"ordinal": 1, "quote": "100", "source_type": "saved_price", "symbol": "MSFT"}
    ]

    # 1. Plain mismatch: sentence body names AAPL, but citation 1 belongs to MSFT
    answer_mismatch = "AAPL 收盘价为 100 美元 [1]。"
    mismatches = shadow_entity_attribution_check(answer_mismatch, citations)
    assert len(mismatches) == 1
    assert mismatches[0][0] == answer_mismatch
    assert mismatches[0][1] == "AAPL"
    assert mismatches[0][2] == ["MSFT"]

    # 2. Matching entity: no mismatch
    answer_match = "MSFT 收盘价为 100 美元 [1]。"
    assert shadow_entity_attribution_check(answer_match, citations) == []

    # 3. Turn.finish integration: recorded in audit and result dict, but not in issues, not in unverified_lines
    t = Turn("AAPL 股价", AgentRuntimeContext("custom", "test", "dummy"), None, [], {})
    t.route = "A"
    t.citations = citations
    t.observations = [{"accepted_evidence": True}]

    res = t.finish(answer_mismatch)
    assert len(res["shadow_entity_mismatches"]) == 1
    assert res["shadow_entity_mismatches"][0][1] == "AAPL"
    assert res["audit"]["shadow_entity_mismatches"] == res["shadow_entity_mismatches"]
    # Red line: shadow attribution MUST NOT add to unverified_lines, issues, or status degradation
    assert res["unverified_lines"] == []
    assert res["status"] == "succeeded"
