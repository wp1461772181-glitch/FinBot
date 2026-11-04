import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.database import Base, SessionLocal, engine
from app.evidence_context import freeze_evidence_context
from app.agent_forecast_processor import AgentForecastProcessor, _forecast_brief_error, _market_summary, _select_manifest_events
from app.forecast_v2 import ForecastDraft
from app.forecast_v2_processor import ForecastInputError, ResearchOnlyForecastProcessor
from app.forecast_jobs import enqueue_job
from app.material_analysis import PROMPT_VERSION, get_material_analysis, request_material_analysis, run_material_analysis_once
from app.models import UploadedEvidence
from app.research_brief import ResearchBriefError, build_research_brief


def test_explicit_trial_sources_do_not_auto_fill_and_rejected_sources_are_skipped():
    now = datetime(2026, 9, 27, 10, tzinfo=UTC)
    manifest = [
        {"source_type": "official_filing", "source_id": "one", "is_new": True, "published_at": now.isoformat()},
        {"source_type": "official_filing", "source_id": "automatic", "is_new": True, "published_at": now.isoformat()},
        {"source_type": "uploaded_media", "source_id": "rejected", "is_new": True,
         "review_status": "rejected", "published_at": now.isoformat()},
        {"source_type": "uploaded_media", "source_id": "inactive", "is_new": True,
         "is_active": False, "published_at": now.isoformat()},
    ]

    selected, explicit, excluded = _select_manifest_events(
        manifest, [{"source_type": "official_filing", "source_id": "one"}]
    )

    assert [item["source_id"] for item in selected] == ["one"]
    assert explicit == [{"source_type": "official_filing", "source_id": "one"}]
    assert {item["reason"] for item in excluded} == {"source_rejected", "inactive_source"}


def test_market_summary_uses_the_requested_symbol_without_relying_on_row_symbol_fields():
    draft = SimpleNamespace(
        price_input_manifest={"rows": {"MSFT": [{"close": 410.0}], "SPY": [{"close": 500.0}]}},
        feature_snapshot={"momentum_5d": 0.02, "momentum_20d": 0.04, "volatility_20d": 0.3,
                          "volume_ratio_20d": 1.2, "remaining_sessions": 20,
                          "realized_return_from_anchor": 0.0},
        market_cutoff_at=datetime(2026, 9, 26, 20, tzinfo=UTC),
    )

    summary = _market_summary(draft, "MSFT")

    assert summary["symbol"] == "MSFT"
    assert summary["latest_close"] == 410.0
    assert summary["return_5_sessions"] == 0.02


def test_brief_failures_keep_safe_reason_and_retry_only_transient_provider_errors():
    provider_error = _forecast_brief_error(ResearchBriefError("provider unavailable", code="provider_error"))
    invalid_output = _forecast_brief_error(ResearchBriefError("invalid cited response", code="invalid_model_output"))
    invalid_contract = _forecast_brief_error(ResearchBriefError("invalid contract", code="invalid_brief_output"))

    assert provider_error.reason == "research_brief_provider_error"
    assert provider_error.retryable is True
    assert invalid_output.reason == "research_brief_invalid_model_output"
    assert invalid_output.retryable is True
    assert invalid_contract.reason == "research_brief_invalid_brief_output"
    assert invalid_contract.retryable is False


def test_real_l1_cache_reuses_text_analysis_after_review_state_change_without_rebinding():
    Base.metadata.create_all(bind=engine)
    text_value = "Revenue grew."
    raw = text_value.encode()
    source_id = uuid4()
    now = datetime.now(UTC) - timedelta(minutes=3)
    with SessionLocal() as db:
        db.add(UploadedEvidence(
            id=source_id, symbol="MSFT", title="Results", source_url="https://example.org/results",
            published_at=now - timedelta(days=1), observed_at=now - timedelta(hours=1),
            credibility_stars=2, credibility_reason="Awaiting review", impact_severity="medium",
            filename="results.txt", content_sha256=hashlib.sha256(raw).hexdigest(),
            raw_content=raw, content_text=text_value, status="unconfirmed",
        ))
        db.commit()

    class AnalysisProvider:
        def extract(self, **_kwargs):
            return SimpleNamespace(content=json.dumps({
                "schema_version": "material-analysis-v1",
                "prompt_version": PROMPT_VERSION,
                "summary": "Revenue increased.",
                "facts": [{"id": "f1", "statement": "Revenue grew.",
                           "citations": [{"quote": "Revenue grew."}]}],
                "supporting": [], "counter": [], "uncertainties": [], "key_numbers": [],
            }), response_model="fixture-model", usage={})

    first_request_key = f"agent-l1-first-{uuid4()}"
    with SessionLocal() as db:
        queued = request_material_analysis(db=db, source_type="uploaded_media", source_id=source_id,
                                           idempotency_key=first_request_key)
    analyzed = run_material_analysis_once(
        session_factory=SessionLocal, provider=AnalysisProvider(), job_id=__import__("uuid").UUID(queued["job_id"]),
        worker_id="agent-processor-test",
    )
    assert analyzed["status"] == "succeeded"
    original_analysis_id = analyzed["analysis_id"]
    with SessionLocal() as db:
        original_analysis = get_material_analysis(db=db, analysis_id=__import__("uuid").UUID(original_analysis_id))
        original_analysis_evidence_id = original_analysis["evidence_version_id"]
        source = db.get(UploadedEvidence, source_id)
        source.credibility_stars = 5
        source.credibility_reason = "Reviewed and retained"
        db.commit()
        current_context = freeze_evidence_context(
            db=db, symbol="MSFT", decision_at=datetime.now(UTC), mode="observed",
            source_refs=[{"source_type": "uploaded_media", "source_id": source_id}], max_new_documents=1,
        )
    current_event = current_context.events[0].as_manifest_item()
    processor = AgentForecastProcessor(
        session_factory=SessionLocal, decision_mode="research_only",
        analysis_runner=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("cache hit must not run provider")),
    )
    cached = processor._ensure_analysis(job=SimpleNamespace(id=uuid4()), event=current_event)

    assert cached["analysis_id"] == original_analysis_id
    assert cached["evidence_version_id"] == original_analysis_evidence_id
    assert original_analysis_evidence_id != current_event["event_version_id"]
    assert cached["source_manifest"]["content_sha256"] == current_event["content_sha256"]

    refreshed_manifest = dict(cached["source_manifest"])
    refreshed_manifest.update({"review_status": current_event["review_status"],
                               "user_rating_stars": current_event["user_rating_stars"]})
    cached_for_brief = {**cached, "source_manifest": refreshed_manifest}

    class BriefProvider:
        def extract(self, **_kwargs):
            return SimpleNamespace(content=json.dumps({
                "new_facts": [], "supporting": [], "counter": [], "background": [],
                "conflicts": [], "unknowns": [], "changes": [],
            }), response_model="fixture-model", usage={})

    cutoff = datetime.now(UTC) + timedelta(seconds=1)
    brief = build_research_brief(
        market_summary={"symbol": "MSFT", "as_of": cutoff.isoformat(), "latest_close": 410.0,
                        "return_5_sessions": 0.01, "return_20_sessions": 0.03,
                        "volatility_20_sessions": 0.2, "volume_ratio_20_sessions": 1.0},
        analyses=[cached_for_brief], target_contract={"target_end_date": "2026-10-23"},
        decision_at=cutoff, parent_brief=None, provider=BriefProvider(),
    )
    assert brief.material_refs[0].analysis_id == original_analysis_id
    assert brief.material_refs[0].evidence_version_id == original_analysis_evidence_id
    assert brief.material_refs[0].user_rating_stars == 5
    with SessionLocal() as db:
        still_original = get_material_analysis(db=db, analysis_id=__import__("uuid").UUID(original_analysis_id))
    assert still_original["evidence_version_id"] == original_analysis_evidence_id
    assert still_original["source_manifest"].get("user_rating_stars") is None


def test_failed_material_analysis_retries_once_with_stronger_deepseek_model(monkeypatch):
    source_id = uuid4()
    calls = []

    class EmptySession:
        def __enter__(self): return self
        def __exit__(self, *_args): return False

    def requester(**kwargs):
        calls.append(kwargs)
        retry = kwargs.get("model_override") is not None
        if not retry:
            return {"status": "queued", "job_id": str(uuid4())} if len([c for c in calls if c.get("model_override") is None]) == 1 else {"status": "failed", "safe_error_code": "invalid_model_output"}
        return {"status": "queued", "job_id": str(uuid4())} if len([c for c in calls if c.get("model_override")]) == 1 else {"status": "succeeded", "analysis_id": str(uuid4())}

    result_analysis_id = None

    def analysis_getter(*, db, analysis_id):
        nonlocal result_analysis_id
        result_analysis_id = analysis_id
        return {"analysis_id": str(analysis_id), "source_manifest": {"content_sha256": "a" * 64}}

    monkeypatch.setenv("DEEPSEEK_ANALYSIS_RETRY_MODEL", "deepseek-v4-pro")
    processor = AgentForecastProcessor(
        session_factory=EmptySession,
        analysis_requester=requester,
        analysis_runner=lambda **_kwargs: {"status": "failed"},
        analysis_getter=analysis_getter,
        material_provider_factory=lambda: object(),
    )
    result = processor._ensure_analysis(
        job=SimpleNamespace(id=uuid4()),
        event={"source_type": "official_filing", "source_id": str(source_id)},
    )

    assert result is not None
    assert result_analysis_id is not None
    assert len(calls) == 4
    assert calls[0]["idempotency_key"] == calls[1]["idempotency_key"]
    assert calls[2]["idempotency_key"].endswith(":quality-retry-v1")
    assert calls[2]["model_override"] == "deepseek-v4-pro"
    assert calls[2]["force"] is False


def test_invalid_material_analysis_failure_is_cached_until_forced_retry():
    Base.metadata.create_all(bind=engine)
    content = b"Revenue increased by 12 percent."
    source_id = uuid4()
    with SessionLocal() as db:
        db.add(UploadedEvidence(
            id=source_id, symbol="MSFT", title="Results", source_url="https://example.org/results",
            published_at=datetime.now(UTC) - timedelta(days=1), observed_at=datetime.now(UTC),
            credibility_stars=3, credibility_reason="Awaiting review", impact_severity="medium",
            filename="results.txt", content_sha256=hashlib.sha256(content).hexdigest(),
            raw_content=content, content_text=content.decode(), status="unconfirmed",
        ))
        db.commit()
        first = request_material_analysis(
            db=db, source_type="uploaded_media", source_id=source_id,
            idempotency_key=f"invalid-analysis-first-{uuid4()}",
        )

    class InvalidProvider:
        def extract(self, **_kwargs):
            return SimpleNamespace(content="{}", response_model="fixture-model", usage={})

    outcome = run_material_analysis_once(
        session_factory=SessionLocal, provider=InvalidProvider(),
        job_id=__import__("uuid").UUID(first["job_id"]), worker_id="invalid-analysis-cache-test",
    )
    assert outcome["status"] == "failed"

    with SessionLocal() as db:
        cached_failure = request_material_analysis(
            db=db, source_type="uploaded_media", source_id=source_id,
            idempotency_key=f"invalid-analysis-cached-{uuid4()}",
        )
        forced = request_material_analysis(
            db=db, source_type="uploaded_media", source_id=source_id,
            idempotency_key=f"invalid-analysis-forced-{uuid4()}", force=True,
        )

    assert cached_failure["status"] == "failed"
    assert cached_failure["failure_cached"] is True
    assert cached_failure["job_id"] == first["job_id"]
    assert forced["status"] == "queued"
    assert forced["job_id"] != first["job_id"]


def test_insufficient_material_inputs_skip_the_model_even_when_llm_mode_is_enabled():
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from test_forecast_v2_processor import _Provider, _rows

    Base.metadata.create_all(bind=engine)
    now = datetime(2025, 3, 4, 22, tzinfo=UTC)
    anchor = datetime(2025, 1, 31).date()
    rows_by_symbol = {
        "AMZN": _rows(anchor=anchor, symbol="AMZN", observed_at=now),
        "SPY": _rows(anchor=anchor, symbol="SPY", observed_at=now),
    }
    with SessionLocal() as db:
        job = enqueue_job(db=db, symbol="AMZN", kind="new", idempotency_key=f"agent-insufficient-{uuid4()}")
        job_id = job.id

    def fail_model():
        raise AssertionError("insufficient brief must not instantiate the forecast model")

    processor = AgentForecastProcessor(
        session_factory=SessionLocal, decision_mode="llm",
        market_provider_factory=lambda: _Provider(rows_by_symbol),
        now_factory=lambda: now,
        market_ingester=lambda *_args, **_kwargs: None,
        market_loader=lambda ticker, **_kwargs: rows_by_symbol[ticker],
        material_provider_factory=lambda: (_ for _ in ()).throw(AssertionError("there are no materials")),
        brief_provider_factory=lambda: SimpleNamespace(extract=lambda **_kwargs: None),
        llm_provider_factory=fail_model,
    )
    with SessionLocal() as db:
        from app.forecast_v2_models import ForecastJobV2
        job = db.get(ForecastJobV2, job_id)
        draft = processor(job)

    assert draft.model_status == "research_only"
    assert draft.decision_probabilities is None
    assert draft.joint_probabilities is None
    assert draft.research_brief["input_quality"]["status"] == "insufficient"
    assert draft.research_brief["symbol"] == "AMZN"


def test_leftover_jev_mode_fails_visibly():
    """A server still configured with FORECAST_DECISION_MODE=jev must fail, not silently run research-only."""
    with pytest.raises(ForecastInputError) as caught:
        AgentForecastProcessor(session_factory=SessionLocal, decision_mode="jev")
    assert caught.value.reason == "invalid_forecast_decision_mode"


# --- B12: a judgment's "create a forecast" button ------------------------------------------------------------
# The button posts {symbol, kind: "new", source_refs: [{source_type: "official_filing", source_id}]} and nothing
# else.  These two tests pin what that request can and cannot carry into a forecast.

_8K_TEXT = "Revenue grew."


def _seed_8k(*, symbol="AMD"):
    """One fetched 8-K of the library, public and observed a little while ago; returns (id, accession)."""
    from app.models import SecFilingInventory
    Base.metadata.create_all(bind=engine)
    instant = datetime.now(UTC)
    accepted_at = instant - timedelta(hours=2)
    observed_at = instant - timedelta(hours=1)
    accession = f"0000002488-26-{uuid4().int % 1_000_000:06d}"
    with SessionLocal() as db:
        row = SecFilingInventory(
            symbol=symbol, cik="0000002488", accession_number=accession, form="8-K", filed_at=instant.date(),
            accepted_at=accepted_at.isoformat(), primary_document="ex99.htm",
            source_url="https://www.sec.gov/Archives/example/ex99.htm", source="sec-edgar", review_status="accepted",
            observed_at=observed_at, content_status="fetched", content_observed_at=observed_at,
            content_excerpt=_8K_TEXT, content_excerpt_sha256=hashlib.sha256(_8K_TEXT.encode()).hexdigest(),
            content_truncated=False, related_attachment_status="not_found",
        )
        db.add(row)
        db.commit()
        return row.id, accession


def _frozen_brief(*, symbol, source_refs):
    """Freeze the way the worker does for a new forecast, analyse with a fake model, build the brief.

    Returns (manifest, selected events, brief as a dict).  Only the model is faked: the freezer, the manifest
    selection, the material-analysis pipeline and the brief builder are the real ones.
    """
    from uuid import UUID
    refs = [{"source_type": ref["source_type"], "source_id": UUID(str(ref["source_id"]))} for ref in source_refs]
    with SessionLocal() as db:
        context = freeze_evidence_context(
            db=db, symbol=symbol, decision_at=datetime.now(UTC), mode="observed", source_refs=refs,
            include_automatic_new_sources=False,
        )
    manifest = [event.as_manifest_item() for event in context.events]
    selected, explicit, excluded = _select_manifest_events(manifest, list(source_refs))

    class AnalysisProvider:
        def extract(self, **_kwargs):
            return SimpleNamespace(content=json.dumps({
                "schema_version": "material-analysis-v1", "prompt_version": PROMPT_VERSION,
                "summary": "Revenue increased.",
                "facts": [{"id": "f1", "statement": _8K_TEXT, "citations": [{"quote": _8K_TEXT}]}],
                "supporting": [], "counter": [], "uncertainties": [], "key_numbers": [],
            }), response_model="fixture-model", usage={})

    class BriefProvider:
        def extract(self, **_kwargs):
            return SimpleNamespace(content=json.dumps({
                "new_facts": [], "supporting": [], "counter": [], "background": [],
                "conflicts": [], "unknowns": [], "changes": [],
            }), response_model="fixture-model", usage={})

    analyses = []
    for event in selected:
        with SessionLocal() as db:
            queued = request_material_analysis(db=db, source_type=event["source_type"], source_id=UUID(event["source_id"]),
                                               idempotency_key=f"b12-{uuid4()}")
        outcome = run_material_analysis_once(session_factory=SessionLocal, provider=AnalysisProvider(),
                                             job_id=UUID(queued["job_id"]), worker_id="b12-test")
        assert outcome["status"] == "succeeded"
        with SessionLocal() as db:
            analysis = get_material_analysis(db=db, analysis_id=UUID(outcome["analysis_id"]))
        # The same steps as AgentForecastProcessor._process: the analysis must belong to the frozen content.
        source_manifest = dict(analysis.get("source_manifest") or {})
        assert source_manifest.get("content_sha256") == event.get("content_sha256")
        source_manifest.update({"review_status": event.get("review_status", "pending_review"),
                                "user_rating_stars": event.get("user_rating_stars"),
                                "is_active": event.get("is_active", True),
                                "is_corrected_or_withdrawn": event.get("is_corrected_or_withdrawn", False)})
        analysis["source_manifest"] = source_manifest
        analyses.append(analysis)
    cutoff = datetime.now(UTC) + timedelta(seconds=1)
    brief = build_research_brief(
        market_summary={"symbol": symbol, "as_of": cutoff.isoformat(), "latest_close": 100.0,
                        "return_5_sessions": 0.01, "return_20_sessions": 0.03,
                        "volatility_20_sessions": 0.2, "volume_ratio_20_sessions": 1.0},
        analyses=analyses, target_contract={"target_end_date": "2026-12-01"}, decision_at=cutoff, parent_brief=None,
        provider=BriefProvider(), explicit_source_refs=explicit, excluded_source_refs=excluded,
    )
    return manifest, selected, brief.model_dump(mode="json")


def test_explicit_8k_ref_reaches_the_brief():
    """The promotion button names a library 8-K by its SecFilingInventory id.  The request is accepted, the
    freezer puts that 8-K in the manifest, only manifest sources are analysed, and the 8-K is in the brief."""
    from app.forecast_v2_api import V2RequestError, _validate_source_refs
    source_id, _accession = _seed_8k()
    ref = {"source_type": "official_filing", "source_id": str(source_id)}

    # 1. The request check accepts a library declaration for this symbol, and still refuses another symbol's.
    with SessionLocal() as db:
        _validate_source_refs(db, refs=[ref], symbol="AMD", decision_at=datetime.now(UTC))
        with pytest.raises(V2RequestError):
            _validate_source_refs(db, refs=[ref], symbol="MSFT", decision_at=datetime.now(UTC))

    # 2. Selection works on the frozen manifest alone: a reference that is not in it is never analysed.
    manifest, selected, brief = _frozen_brief(symbol="AMD", source_refs=[ref])
    assert [item["source_id"] for item in manifest] == [str(source_id)]
    stray = {"source_type": "official_filing", "source_id": str(uuid4())}
    picked, _explicit, _excluded = _select_manifest_events(manifest, [ref, stray])
    assert [item["source_id"] for item in picked] == [str(source_id)]

    # 3. The 8-K itself is in the brief.
    assert [item["source_id"] for item in selected] == [str(source_id)]
    assert [(r["source_type"], r["source_id"]) for r in brief["material_refs"]] == [("official_filing", str(source_id))]


def test_promoted_forecast_has_no_trace_of_the_judgment():
    """A forecast started from a judgment is an independent forecast: the judgment's direction, reasons and
    counter-argument exist only in earnings_events, and nothing about the request or the freeze can carry them."""
    from app.agent_chat_models import EarningsEvent
    markers = {"direction": "ZQX-DIRECTION-2093", "reason": "ZQX-REASON-7781", "counter": "ZQX-COUNTER-4410"}
    source_id, accession = _seed_8k()
    event_id = uuid4()
    with SessionLocal() as db:
        db.add(EarningsEvent(
            id=event_id, owner_hash="b12-owner", symbol="AMD", accession=accession, cik="0000002488", held=True,
            accepted_at=datetime.now(UTC) - timedelta(hours=2), status="first_sent", followup_status="sent",
            detail={"followup": {"direction": markers["direction"], "confidence": "high",
                                 "reasons": [{"text": markers["reason"], "quote": markers["reason"]}],
                                 "counter_argument": markers["counter"], "validated": True}},
        ))
        db.commit()
    try:
        # Exactly what the button sends, and the job the API stores from it.
        request = {"symbol": "AMD", "kind": "new",
                   "source_refs": [{"source_type": "official_filing", "source_id": str(source_id)}]}
        with SessionLocal() as db:
            job = enqueue_job(db=db, symbol=request["symbol"], kind=request["kind"],
                              idempotency_key=f"b12-{uuid4()}", source_refs=request["source_refs"])
            job_columns = {column.name: getattr(job, column.name) for column in job.__table__.columns}
        assert job_columns["source_refs"] == request["source_refs"]
        manifest, _selected, brief = _frozen_brief(symbol="AMD", source_refs=job_columns["source_refs"])

        everything = json.dumps({"job": job_columns, "manifest": manifest, "brief": brief}, default=str, ensure_ascii=False)
        for name, marker in markers.items():
            assert marker not in everything, f"the judgment's {name} reached the job or the brief"
        assert str(event_id) not in everything
    finally:
        with SessionLocal() as db:
            db.query(EarningsEvent).filter(EarningsEvent.id == event_id).delete(synchronize_session=False)
            db.commit()
