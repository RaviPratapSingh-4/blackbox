"""Step 1: pull raw rows from every source. Read-only; each row gets an evidence_id the LLM must cite later."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session
import re

from app.models.orm import AppLog, Deployment, Doc, OrderEvent, PastIncident, PaymentEvent, ServiceMetric

MAX_ROWS = 20_000  # per source; hitting it is reported as truncation, not hidden

# name -> (model, evidence_id prefix, columns to keep). To add a new source, add one line here.
TIME_SOURCES = {
    "logs": (AppLog, "log", ["ts", "ingested_at", "service", "level", "message", "order_id", "trace_id"]),
    "payments": (PaymentEvent, "pay", ["ts", "order_id", "provider_txn_id", "idempotency_key", "status", "amount", "attempt"]),
    "orders": (OrderEvent, "ord", ["ts", "order_id", "status", "source_service"]),
    "deployments": (Deployment, "dep", ["ts", "service", "version", "change_summary"]),
    "metrics": (ServiceMetric, "met", ["ts", "service", "metric", "value"]),
}
TEXT_SOURCES = {
    "past_incidents": (PastIncident, "inc", ["title", "root_cause", "resolution", "body"]),
    "docs": (Doc, "doc", ["title", "body"]),
}


def _to_row(obj, prefix: str, fields: list[str]) -> dict:
    row = {"evidence_id": f"{prefix}:{obj.id}"}
    for name in fields:
        value = getattr(obj, name)
        if isinstance(value, datetime):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = float(value)
        row[name] = value
    return row


def _time_rows(session: Session, model, prefix: str, fields: list[str], since, until) -> tuple[list[dict], bool]:
    stmt = select(model).order_by(model.ts).limit(MAX_ROWS + 1)
    if since:
        stmt = stmt.where(model.ts >= since)
    if until:
        stmt = stmt.where(model.ts < until)
    objs = session.scalars(stmt).all()
    return [_to_row(o, prefix, fields) for o in objs[:MAX_ROWS]], len(objs) > MAX_ROWS


def _search_terms(text: str) -> str:
    words = [w for w in dict.fromkeys(re.findall(r"[a-z]{4,}", text.lower()))][:12]
    return " or ".join(words)


def _text_rows(session: Session, model, prefix: str, fields: list[str], terms: str, limit: int = 5) -> list[dict]:
    if not terms:
        return []
    query = func.websearch_to_tsquery("english", terms)
    stmt = select(model).where(model.tsv.op("@@")(query)).order_by(func.ts_rank_cd(model.tsv, query).desc()).limit(limit)
    return [_to_row(o, prefix, fields) for o in session.scalars(stmt)]


def collect(session: Session, incident_text: str, since: datetime | None = None, until: datetime | None = None) -> dict:
    """Returns {"sources": {name: [rows]}, "errors": {name: msg}, "truncated": [names]}.
    One failing source must not kill the investigation; it becomes 'missing information' instead."""
    sources: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}
    truncated: list[str] = []
    terms = _search_terms(incident_text)

    for name, (model, prefix, fields) in TIME_SOURCES.items():
        try:
            sources[name], was_cut = _time_rows(session, model, prefix, fields, since, until)
            if was_cut:
                truncated.append(name)
        except Exception as exc:
            session.rollback()
            sources[name], errors[name] = [], str(exc)[:200]

    for name, (model, prefix, fields) in TEXT_SOURCES.items():
        try:
            sources[name] = _text_rows(session, model, prefix, fields, terms)
        except Exception as exc:
            session.rollback()
            sources[name], errors[name] = [], str(exc)[:200]

    return {"sources": sources, "errors": errors, "truncated": truncated}