"""Task 14：预测改走 role=forecast 配置的推理模型，Jev 作为隐藏对照双跑。全部外部调用用 fake。"""
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import agent_model_catalog as catalog
from app import agent_model_roles as roles
from app.agent_chat_models import AgentModelEntry, AgentModelRole
from app.agent_forecast_processor import AgentForecastProcessor
from app.database import Base, SessionLocal, engine
from app.forecast_contract import create_root_contract, latest_completed_xnys_session
from app.forecast_jobs import claim_next_job, enqueue_job
from app.forecast_model_provider import (
    QUESTION_VERSION,
    ForecastModelError,
    ForecastModelProvider,
    create_forecast_provider,
)
from app.forecast_v2 import ForecastDraft, publish_forecast_version, publish_hidden_control
from app.forecast_v2_api import get_v2_evaluations, get_v2_stock_workspace, list_v2_forecast_roots
from app.forecast_v2_models import ForecastVersionV2
from app.forecast_v2_processor import ForecastInputError, ResearchOnlyForecastProcessor
from app.jev_provider import JevProviderError
from tests.test_agent_bots import KEY_A, OWNER_HASH, owner  # noqa: F401  (fixture)

BRIEF = {"symbol": "X", "input_quality": {"status": "ready"}, "market_summary": {"latest_close": 100.0}}
GOOD = {"bullish": 0.2, "neutral": 0.3, "bearish": 0.5, "reasoning": "x"}


@pytest.fixture(autouse=True)
def v2_tables(disposable_database):
    Base.metadata.create_all(bind=engine)


@pytest.fixture
def forecast_model(owner):
    """A catalog with two models; the owner picked "bravo" for role=forecast."""
    with SessionLocal() as db:
        db.query(AgentModelRole).delete()
        db.commit()
    for name in ("alpha", "bravo"):
        catalog.save_entry(name, display_name=name, provider="deepseek", model=f"m-{name}", api_key=KEY_A,
                           is_default=name == "alpha", create=True)
    roles.set_role(OWNER_HASH, "forecast", "bravo")
    yield
    with SessionLocal() as db:
        db.query(AgentModelRole).delete()
        db.query(AgentModelEntry).delete()
        db.commit()


def _fake_call(payload, seen=None):
    def call(model, system, user):
        if seen is not None:
            seen.append({"model": model, "system": system, "user": user})
        return payload if isinstance(payload, str) else json.dumps(payload)
    return call


# --- provider -----------------------------------------------------------------------------------------

def test_probabilities_normalized():
    model = {"name": "bravo", "provider": "deepseek", "model": "m-bravo", "api_key": "k" * 12, "base_url": None}
    ok = ForecastModelProvider(model=model, call=_fake_call(GOOD)).evaluate(BRIEF)
    assert ok.question_version == QUESTION_VERSION == "llm-direction-v1"
    assert ok.choice == "bearish" and ok.probabilities == {"bullish": 0.2, "neutral": 0.3, "bearish": 0.5}
    for bad in ({"bullish": 0.2, "neutral": 0.3, "bearish": 0.4},      # 0.9
                {"bullish": 0.5, "neutral": 0.4, "bearish": 0.3},      # 1.2
                {"bullish": 0.5, "neutral": 0.5},                       # missing class
                {"bullish": 1.2, "neutral": -0.1, "bearish": -0.1},    # out of range
                {"bullish": "high", "neutral": 0.3, "bearish": 0.2}):
        with pytest.raises(ForecastModelError) as caught:
            ForecastModelProvider(model=model, call=_fake_call(bad)).evaluate(BRIEF)
        assert caught.value.code == "invalid_probabilities"
    with pytest.raises(ForecastModelError) as caught:
        ForecastModelProvider(model=model, call=_fake_call("没有 JSON")).evaluate(BRIEF)
    assert caught.value.code == "invalid_response"


def test_prompt_carries_brief_and_fixed_standard():
    seen: list = []
    model = {"name": "bravo", "provider": "deepseek", "model": "m-bravo", "api_key": "k" * 12, "base_url": None}
    ForecastModelProvider(model=model, call=_fake_call(GOOD, seen)).evaluate(BRIEF)
    assert "20" in seen[0]["system"] and "2%" in seen[0]["system"]
    assert json.loads(seen[0]["user"]) == BRIEF


def test_model_role_setting_used(forecast_model):
    seen: list = []
    provider = create_forecast_provider(call=_fake_call(GOOD, seen))
    result = provider.evaluate(BRIEF)
    assert seen[0]["model"]["name"] == "bravo" and seen[0]["model"]["model"] == "m-bravo"
    assert result.requested_model == "m-bravo" and result.provider == "deepseek"
    roles.set_role(OWNER_HASH, "forecast", None)                    # unset: the catalog default, as for earnings
    create_forecast_provider(call=_fake_call(GOOD, seen)).evaluate(BRIEF)
    assert seen[1]["model"]["name"] == "alpha"


def test_unusable_model_is_an_error_not_a_silent_prediction(owner):
    with SessionLocal() as db:
        db.query(AgentModelRole).delete()
        db.query(AgentModelEntry).delete()
        db.commit()
    with pytest.raises(ForecastModelError) as caught:
        create_forecast_provider(call=_fake_call(GOOD))
    assert caught.value.code == "model_not_configured"


# --- processor / publication --------------------------------------------------------------------------

def _base(symbol, instant):
    anchor = latest_completed_xnys_session(instant - timedelta(minutes=1))
    contract = create_root_contract(
        anchor_date=anchor, anchor_close=100.0, price_source="fixture", price_version="fixture-v1",
        price_hash="a" * 64,
        price_basis_metadata={"basis": "provider_quote_close_v1", "provider_behavior_verified": True,
                              "adjusted_close_present": False, "corporate_actions": ()},
    ).as_dict()
    return ForecastDraft(
        target_contract=contract, decision_at=instant - timedelta(minutes=1),
        market_cutoff_at=instant - timedelta(hours=1),
        price_input_manifest={"rows": {symbol: [{"close": 100.0}]}, "source": "fixture"},
        evidence_version_manifest=[], feature_snapshot={"momentum_5d": 0.01, "remaining_sessions": 20},
        baseline_probabilities=None, joint_probabilities=None, model_status="research_only",
        model_manifest={"time_mode": "observed"},
    )


def _brief(symbol, *, target, decision_at, market_cutoff_at):
    return {
        "schema_version": "research-brief-v1", "symbol": symbol, "decision_at": decision_at.isoformat(),
        "target_contract": target,
        "market_summary": {"symbol": symbol, "as_of": market_cutoff_at.isoformat(), "latest_close": 100.0},
        "material_refs": [{
            "analysis_id": "analysis-1", "evidence_version_id": "evidence-1", "source_type": "uploaded_media",
            "source_id": "source-1", "symbol": symbol, "title": "Results", "source_url": None,
            "published_at": (decision_at - timedelta(days=2)).isoformat(),
            "observed_at": (decision_at - timedelta(hours=1)).isoformat(),
            "content_sha256": "c" * 64, "analysis_text_sha256": "d" * 64, "review_status": "accepted",
            "user_rating_stars": None, "user_rating_label": None, "truncated": False,
            "coverage_incomplete": False, "coverage": "complete", "selection_reason": "new_publication",
            "explicitly_selected": False,
        }],
        "new_facts": [{"statement": "Revenue grew.", "citations": [
            {"analysis_id": "analysis-1", "section": "facts", "item_id": "f1"}]}],
        "supporting": [], "counter": [], "background": [], "conflicts": [], "unknowns": [], "changes": [],
        "omitted": [], "input_quality": {"status": "ready", "reasons": []},
    }


JEV_RESULT = SimpleNamespace(
    probabilities={"bearish": 0.1, "neutral": 0.2, "bullish": 0.7}, requested_model="typesafe/jev-1.13",
    actual_model="typesafe/jev-1.13-20260917", request_id="req-1", usage={}, latency_ms=12,
    question_version="jev-direction-v1", input_sha256="e" * 64, choice="bullish", confidence=0.7,
)


def _run(monkeypatch, symbol, *, jev_factory, llm_call=None, instant=None):
    instant = instant or datetime.now(UTC)
    base = _base(symbol, instant)
    monkeypatch.setattr(ResearchOnlyForecastProcessor, "__call__", lambda _self, _job: base)
    with SessionLocal() as db:
        job = enqueue_job(db=db, symbol=symbol, kind="new", idempotency_key=f"t14-{uuid4()}")
        job = claim_next_job(db=db, worker_id="t14", job_id=job.id)
        job_id, lease = job.id, job.lease_epoch
        db.expunge(job)
    processor = AgentForecastProcessor(
        session_factory=SessionLocal, decision_mode="llm", now_factory=lambda: base.decision_at,
        material_provider_factory=lambda: None, jev_provider_factory=jev_factory,
        llm_provider_factory=lambda: create_forecast_provider(call=llm_call or _fake_call(GOOD)),
        brief_builder=lambda **kw: _brief(symbol, target=kw["target_contract"], decision_at=kw["decision_at"],
                                          market_cutoff_at=base.market_cutoff_at),
    )
    draft = processor(job)
    with SessionLocal() as db:
        version, _ = publish_forecast_version(db=db, job_id=job_id, worker_id="t14", lease_epoch=lease,
                                              draft=draft, now=instant)
        primary_id = version.id
    return draft, primary_id


def test_primary_is_experimental_llm_from_role_model(forecast_model, monkeypatch):
    draft, primary_id = _run(monkeypatch, "NVDA", jev_factory=lambda: SimpleNamespace(evaluate=lambda _b: JEV_RESULT))
    with SessionLocal() as db:
        version = db.get(ForecastVersionV2, primary_id)
        assert version.model_status == "experimental_llm"
        assert version.decision_probabilities == {"bearish": 0.5, "neutral": 0.3, "bullish": 0.2}
        provider = version.model_manifest["decision_provider"]
        assert provider["question_version"] == "llm-direction-v1" and provider["actual_model"] == "m-bravo"
        assert provider["provider"] == "deepseek"
        assert version.model_manifest["decision_mode"] == "llm"
        assert "hidden_control" not in version.model_manifest


def test_llm_forecast_makes_no_jev_call(forecast_model, monkeypatch):
    def forbidden():
        raise AssertionError("Jev must not be asked")
    draft, primary_id = _run(monkeypatch, "AMD", jev_factory=forbidden)
    assert draft.hidden_control is None
    assert "control" not in draft.model_manifest
    with SessionLocal() as db:
        assert db.get(ForecastVersionV2, primary_id).model_status == "experimental_llm"
        assert db.query(ForecastVersionV2).filter(ForecastVersionV2.symbol == "AMD").count() == 1


def test_missing_role_model_blocks_forecast_without_calling_jev(owner, monkeypatch):
    with SessionLocal() as db:
        db.query(AgentModelRole).delete()
        db.query(AgentModelEntry).delete()
        db.commit()
    asked = []
    with pytest.raises(ForecastInputError) as caught:
        _run(monkeypatch, "INTC", jev_factory=lambda: SimpleNamespace(evaluate=lambda _b: asked.append(1) or JEV_RESULT))
    assert caught.value.reason == "forecast_model_not_configured" and caught.value.retryable is False
    assert asked == []


def test_control_hidden_from_list_but_in_cohorts(forecast_model, monkeypatch):
    draft, primary_id = _run(monkeypatch, "TSLA", jev_factory=lambda: SimpleNamespace(evaluate=lambda _b: JEV_RESULT))
    assert draft.hidden_control is None
    # The processor no longer writes controls; the one that exists is a retired row, so seed it directly.
    control_payload = {
        "decision_probabilities": dict(JEV_RESULT.probabilities),
        "model_manifest": {
            "processor_version": "agent-forecast-processor-v1", "model_status": "experimental_jev",
            "decision_mode": "jev_control", "time_mode": "observed",
            "decision_provider": {
                "provider": "openrouter", "requested_model": JEV_RESULT.requested_model,
                "actual_model": JEV_RESULT.actual_model, "question_version": JEV_RESULT.question_version,
                "raw_probabilities": dict(JEV_RESULT.probabilities),
            },
            "local_calibration": {"status": "not_applied", "reason": "hidden_control_is_raw"},
        },
    }
    with SessionLocal() as db:
        primary = db.get(ForecastVersionV2, primary_id)
        control = publish_hidden_control(db=db, primary=primary, control=control_payload)
        assert control is not None
        assert control.model_status == "experimental_jev" and control.root_id != primary.root_id
        assert control.decision_probabilities == JEV_RESULT.probabilities
        assert control.model_manifest["hidden_control"] is True
        assert control.model_manifest["control_of_version_id"] == str(primary_id)
        # republishing the same control is idempotent
        again = publish_hidden_control(db=db, primary=primary, control=control_payload)
        assert again.id == control.id
        assert db.query(ForecastVersionV2).filter(ForecastVersionV2.symbol == "TSLA").count() == 2

        roots = list_v2_forecast_roots("TSLA", db)["roots"]
        assert [root["id"] if "id" in root else root.get("root_id") for root in roots] == [str(primary.root_id)]
        workspace = get_v2_stock_workspace("TSLA", db)
        assert workspace["current_root"]["id"] == str(primary.root_id)

        evaluations = get_v2_evaluations("TSLA", db)
        cohorts = evaluations["model_cohorts"]
        by_status = {(cohort["model_status"], cohort["control"]): cohort for cohort in cohorts}
        assert set(by_status) == {("experimental_llm", False), ("experimental_jev", True)}
        assert by_status[("experimental_llm", False)]["question_version"] == "llm-direction-v1"
        assert by_status[("experimental_jev", True)]["question_version"] == "jev-direction-v1"
        assert by_status[("experimental_llm", False)]["sample"]["root_denominator"] == 1
        assert by_status[("experimental_jev", True)]["sample"]["root_denominator"] == 1
        # the time-mode-only legacy cohort counts only the visible forecast
        assert evaluations["cohorts"]["prospective"]["sample"]["root_denominator"] == 1
