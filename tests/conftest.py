import pytest

from app.models.schemas import LLMOutput


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