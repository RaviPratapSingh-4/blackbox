from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.orm import Incident, Investigation, InvestigationStep
from app.models.schemas import IncidentIn
from app.services.pipeline import run_investigation

router = APIRouter()
RUNNING_GRACE = timedelta(minutes=2)  # a RUNNING investigation older than this is assumed to have crashed


def _summary(inv: Investigation) -> dict:
    top = inv.report["root_cause_hypothesis"]["title"] if inv.report else None
    return {"id": inv.id, "incident_id": inv.incident_id, "status": inv.status, "llm_used": inv.llm_used,
            "root_cause": top, "created_at": inv.created_at, "updated_at": inv.updated_at}


def _detail(inv: Investigation, db: Session) -> dict:
    steps = db.scalars(select(InvestigationStep).where(InvestigationStep.investigation_id == inv.id)
                       .order_by(InvestigationStep.id))
    return _summary(inv) | {
        "report": inv.report,
        "steps": [{"step": s.step_name, "status": s.status, "error": s.error, "finished_at": s.finished_at}
                  for s in steps]}  # step outputs are large, so they are not returned


def _get_or_404(db: Session, model, row_id: int, name: str):
    row = db.get(model, row_id)
    if row is None:
        raise HTTPException(404, f"{name} {row_id} not found")
    return row


@router.post("/incidents", status_code=201)
def create_incident(body: IncidentIn, db: Session = Depends(get_db)) -> dict:
    incident = Incident(title=body.title, description=body.description)
    db.add(incident)
    db.commit()
    return {"id": incident.id, "title": incident.title, "created_at": incident.created_at}


@router.post("/incidents/{incident_id}/investigate", status_code=201)
def investigate(incident_id: int, db: Session = Depends(get_db)) -> dict:
    _get_or_404(db, Incident, incident_id, "incident")
    inv = Investigation(incident_id=incident_id)
    db.add(inv)
    db.commit()
    run_investigation(db, inv.id)  # synchronous: simple, but the request waits for the LLM
    return _detail(inv, db)


@router.post("/investigations/{investigation_id}/resume")
def resume(investigation_id: int, db: Session = Depends(get_db)) -> dict:
    inv = _get_or_404(db, Investigation, investigation_id, "investigation")
    if inv.status == "RUNNING" and datetime.now(timezone.utc) - inv.updated_at < RUNNING_GRACE:
        raise HTTPException(409, "investigation is still running")
    if inv.status != "DONE":
        run_investigation(db, inv.id)  # finished steps are loaded from the database, not recomputed
    return _detail(inv, db)


@router.get("/investigations/{investigation_id}")
def get_investigation(investigation_id: int, db: Session = Depends(get_db)) -> dict:
    return _detail(_get_or_404(db, Investigation, investigation_id, "investigation"), db)


@router.get("/investigations")
def list_investigations(incident_id: int | None = None, limit: int = Query(20, ge=1, le=100),
                        db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(Investigation).order_by(Investigation.id.desc()).limit(limit)
    if incident_id is not None:
        stmt = stmt.where(Investigation.incident_id == incident_id)
    return [_summary(i) for i in db.scalars(stmt)]