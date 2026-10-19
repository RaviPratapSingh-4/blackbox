"""Runs the steps in order and persists each one, so a crashed or interrupted investigation resumes where it stopped."""
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.llm.base import LLMError
from app.llm.factory import get_llm
from app.models.orm import Incident, Investigation, InvestigationStep
from app.services.collect import collect
from app.services.facts import compute_facts
from app.services.hypotheses import InvalidLLMOutput, build_context, propose
from app.services.normalize import normalize
from app.services.report import build_report, fallback_output
from app.services.verify import verify

STEPS = ["collect", "normalize", "facts", "hypotheses", "finalize"]


def _hypotheses_step(text: str, done: dict, llm_factory) -> dict:
    """One LLM try plus one retry with the verifier's complaints. Any failure ends in the deterministic fallback."""
    context = build_context(done["facts"]["facts"], done["normalize"])
    rejections, feedback, llm_error = [], None, None
    try:
        llm = llm_factory()
        for attempt in (1, 2):
            try:
                output = propose(llm, text, context, feedback)
            except InvalidLLMOutput as exc:
                feedback = [f"Invalid JSON or schema: {exc}"]
            else:
                feedback = verify(output, context)
                if not feedback:
                    return {"llm_used": True, "output": output.model_dump(), "attempts": attempt, "rejections": rejections}
            rejections.append(feedback)
    except LLMError as exc:
        llm_error = str(exc)
    return {"llm_used": False, "output": fallback_output(context).model_dump(), "attempts": len(rejections),
            "rejections": rejections, "llm_error": llm_error}


def _run_step(name: str, session: Session, text: str, done: dict, llm_factory) -> dict:
    if name == "collect":
        return collect(session, text)
    if name == "normalize":
        return normalize(done["collect"])
    if name == "facts":
        return compute_facts(done["normalize"])
    if name == "hypotheses":
        return _hypotheses_step(text, done, llm_factory)
    return build_report(done["hypotheses"], done["facts"], done["normalize"])


def _save(session: Session, inv_id: int, name: str, status: str, output=None, error=None) -> None:
    session.execute(delete(InvestigationStep).where(
        InvestigationStep.investigation_id == inv_id, InvestigationStep.step_name == name))
    session.add(InvestigationStep(investigation_id=inv_id, step_name=name, status=status, output=output, error=error))
    session.commit()


def run_investigation(session: Session, investigation_id: int, llm_factory=get_llm) -> Investigation:
    """Safe to call again on the same investigation: finished steps are loaded, not recomputed."""
    inv = session.get(Investigation, investigation_id)
    incident = session.get(Incident, inv.incident_id)
    text = f"{incident.title}\n{incident.description}"
    inv.status = "RUNNING"
    session.commit()
    done = {r.step_name: r.output for r in session.scalars(select(InvestigationStep).where(
        InvestigationStep.investigation_id == inv.id, InvestigationStep.status == "DONE"))}
    current = STEPS[0]
    try:
        for current in STEPS:
            if current not in done:
                done[current] = _run_step(current, session, text, done, llm_factory)
                _save(session, inv.id, current, "DONE", output=done[current])
    except Exception as exc:
        session.rollback()
        _save(session, inv.id, current, "FAILED", error=str(exc)[:500])
        inv.status = "FAILED"
        session.commit()
        return inv
    inv.report, inv.llm_used, inv.status = done["finalize"], done["hypotheses"]["llm_used"], "DONE"
    session.commit()
    return inv