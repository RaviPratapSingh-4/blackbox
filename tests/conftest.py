import pytest

from app.models.schemas import LLMOutput
import copy
import json

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models.orm import AppLog, Incident, Investigation, InvestigationStep
from app.services.collect import collect
from app.services.facts import compute_facts
from app.services.normalize import normalize
from app.services.pipeline import run_investigation


@pytest.fixture
def context():
    facts = [
        {"name": "duplicate_charges", "statement": "44 of 1580 orders", "value": {"orders": 44}, "evidence_ids": ["pay:1"]},
        {"name": "deployment_impact", "statement": "s", "value": {"rate_before": 0.0124}, "evidence_ids": ["dep:3"]},
        {"name": "duplicates_predate_deployment", "statement": "s", "value": {"duplicates_before_deploy": 13},
         "evidence_ids": ["pay:2"]},
    ]
    quality = [{"code": "METRICS_GAP", "severity": "warn", "summary": "gap", "examples": ["log:5"], "details": {}}]
    return {"facts": facts, "data_quality": quality,
            "past_incidents": [{"evidence_id": "inc:1"}], "docs": [{"evidence_id": "doc:2"}]}


@pytest.fixture
def make_output():
    """Builds a valid LLMOutput; override hypothesis fields with hyp={...}, top-level fields with keywords."""
    def make(hyp=None, **top):
        h = {"title": "t", "explanation": "e", "supporting_evidence": ["duplicate_charges", "pay:1"],
             "contradicting_evidence": [], "unexplained": "u", "likelihood": "high",
             "numbers_cited": [{"fact": "duplicate_charges", "key": "orders", "value": 44}]}
        h.update(hyp or {})
        data = {"incident_summary": "s", "hypotheses": [h], "stated_confidence": "high",
                "missing_information": ["gap"],
                "recommended_actions": [{"action_type": "gather_more_data", "description": "d"}]}
        data.update(top)
        return LLMOutput.model_validate(data)
    return make


INCIDENT_TEXT = "customers charged twice, orders still pending, payment timeouts"


@pytest.fixture
def db():
    try:
        session = SessionLocal()
        rows = session.scalar(select(func.count()).select_from(AppLog))
    except Exception:
        pytest.skip("database not available (docker compose up -d db)")
    if not rows:
        pytest.skip("database is empty (python -m data.generate)")
    yield session
    session.close()


@pytest.fixture
def run(db):
    def _run(llm_factory):
        incident = Incident(title="Double charges", description=INCIDENT_TEXT)
        db.add(incident)
        db.commit()
        inv = Investigation(incident_id=incident.id)
        db.add(inv)
        db.commit()
        return run_investigation(db, inv.id, llm_factory=llm_factory)
    return _run


@pytest.fixture
def step(db):
    def _step(inv, name):
        return db.scalar(select(InvestigationStep.output).where(
            InvestigationStep.investigation_id == inv.id, InvestigationStep.step_name == name))
    return _step


@pytest.fixture(scope="module")
def good_data():
    """A valid model answer, built from the real computed facts (no live LLM involved)."""
    try:
        with SessionLocal() as s:
            facts = {f["name"]: f for f in compute_facts(normalize(collect(s, INCIDENT_TEXT)))["facts"]}
    except Exception:
        pytest.skip("database not available")
    return {
        "incident_summary": "Customers were charged twice.",
        "hypotheses": [
            {"title": "Retries sent without an idempotency key", "explanation": "e",
             "supporting_evidence": ["retry_without_key", "duplicate_charges"], "contradicting_evidence": [],
             "unexplained": "Why only some timeouts end in a double charge.", "likelihood": "high",
             "numbers_cited": [{"fact": "duplicate_charges", "key": "orders",
                                "value": facts["duplicate_charges"]["value"]["orders"]}]},
            {"title": "Timeout cut in v2.14.0 made it more frequent", "explanation": "e",
             "supporting_evidence": ["deployment_impact", "timeout_config"],
             "contradicting_evidence": ["duplicates_predate_deployment"],
             "unexplained": "Duplicates that happened before the deploy.", "likelihood": "medium",
             "numbers_cited": []}],
        "stated_confidence": "high",
        "missing_information": ["Provider-side records", "Metrics for the 3h gap around the deploy"],
        "recommended_actions": [
            {"action_type": "gather_more_data", "description": "Compare with the provider report."},
            {"action_type": "fix_idempotency_key_on_retry", "description": "Reuse the original key on retries."},
            {"action_type": "refund_affected_customers", "description": "Refund the extra charges."}]}


@pytest.fixture
def good(good_data):
    return json.dumps(good_data)


@pytest.fixture
def bad(good_data):
    data = copy.deepcopy(good_data)
    data["hypotheses"][0]["supporting_evidence"] = ["pay:999999"]  # invented evidence ID
    return json.dumps(data)