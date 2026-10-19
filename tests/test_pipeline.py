from sqlalchemy import select

from app.llm.base import LLMError
from app.llm.fake import FakeLLM
from app.models.orm import InvestigationStep
from app.services.pipeline import run_investigation


def test_valid_answer_passes_first_try_and_actions_are_gated(run, good):
    inv = run(lambda: FakeLLM([good]))
    assert inv.status == "DONE" and inv.llm_used and inv.report["meta"]["attempts"] == 1
    refund = next(a for a in inv.report["recommended_actions"] if a["action_type"] == "refund_affected_customers")
    assert refund["risk"] == "destructive" and refund["requires_approval"]
    assert not any(a["auto_execute"] for a in inv.report["recommended_actions"])


def test_bad_answer_is_retried_once_with_feedback(run, good, bad):
    fake = FakeLLM([bad, good])
    inv = run(lambda: fake)
    assert inv.llm_used and inv.report["meta"]["attempts"] == 2
    assert len(inv.report["meta"]["llm_rejections"]) == 1
    assert "REJECTED" in fake.calls[1][1] and "pay:999999" in fake.calls[1][1]  # the retry prompt names the problem


def test_two_bad_answers_fall_back_to_deterministic_report(run, bad):
    inv = run(lambda: FakeLLM([bad, bad]))
    assert inv.status == "DONE" and not inv.llm_used
    assert inv.report["confidence"]["level"] == "low"


def test_malformed_json_falls_back(run):
    inv = run(lambda: FakeLLM(["not json", "{still not json"]))
    assert inv.status == "DONE" and not inv.llm_used


def test_llm_outage_falls_back_and_records_the_error(run):
    def down():
        raise LLMError("provider down")
    inv = run(down)
    assert inv.status == "DONE" and not inv.llm_used
    assert inv.report["meta"]["llm_error"] == "provider down"


def test_interrupted_investigation_resumes_without_recomputing(run, db, good):
    def crash():
        raise RuntimeError("worker killed")
    inv = run(crash)
    assert inv.status == "FAILED"

    def collect_step_id():
        return db.scalar(select(InvestigationStep.id).where(
            InvestigationStep.investigation_id == inv.id, InvestigationStep.step_name == "collect"))
    before = collect_step_id()
    run_investigation(db, inv.id, llm_factory=lambda: FakeLLM([good]))
    assert inv.status == "DONE" and inv.llm_used
    assert collect_step_id() == before  # same row, so the step was loaded, not run again


def test_untrusted_text_never_reaches_the_model(run, good):
    fake = FakeLLM([good])
    run(lambda: fake)
    prompt = fake.calls[0][1].lower()
    assert "disregard prior instructions" not in prompt  # planted wiki doc
    assert "drop table" not in prompt                    # planted support-log line
    assert "@example.com" not in prompt                  # PII redacted