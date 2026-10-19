from datetime import datetime

from sqlalchemy import Computed, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def ts_col(**kw):
    return mapped_column(DateTime(timezone=True), **kw)


# --- investigation state (what the system produces) ---
class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = ts_col(server_default=func.now())


class Investigation(Base):
    __tablename__ = "investigations"
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING/RUNNING/DONE/FAILED
    report: Mapped[dict | None] = mapped_column(JSONB)
    llm_used: Mapped[bool] = mapped_column(default=False)  # False => deterministic fallback
    created_at: Mapped[datetime] = ts_col(server_default=func.now())
    updated_at: Mapped[datetime] = ts_col(server_default=func.now(), onupdate=func.now())


class InvestigationStep(Base):
    """One row per pipeline step; resume skips steps already DONE."""
    __tablename__ = "investigation_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int] = mapped_column(ForeignKey("investigations.id"), index=True)
    step_name: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))  # DONE / FAILED
    output: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime] = ts_col(server_default=func.now())


# --- evidence sources (synthetic production data) ---
class AppLog(Base):
    __tablename__ = "app_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = ts_col(index=True)
    ingested_at: Mapped[datetime | None] = ts_col()  # far after ts => delayed log
    service: Mapped[str] = mapped_column(String(40), index=True)
    level: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(Text)
    order_id: Mapped[str | None] = mapped_column(String(40), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(60))
    tsv = mapped_column(TSVECTOR, Computed("to_tsvector('english', message)", persisted=True))
    __table_args__ = (Index("ix_app_logs_tsv", "tsv", postgresql_using="gin"),)


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = ts_col(index=True)
    order_id: Mapped[str] = mapped_column(String(40), index=True)
    provider_txn_id: Mapped[str | None] = mapped_column(String(60))
    idempotency_key: Mapped[str | None] = mapped_column(String(80))  # NULL = missing key
    status: Mapped[str] = mapped_column(String(20))  # SUCCESS / FAILED / TIMEOUT
    amount: Mapped[float] = mapped_column(Numeric(10, 2))
    attempt: Mapped[int] = mapped_column(Integer, default=1)


class OrderEvent(Base):
    __tablename__ = "order_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = ts_col(index=True)
    order_id: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20))
    source_service: Mapped[str] = mapped_column(String(40))


class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = ts_col(index=True)
    service: Mapped[str] = mapped_column(String(40))
    version: Mapped[str] = mapped_column(String(40))
    change_summary: Mapped[str] = mapped_column(Text)


class ServiceMetric(Base):
    __tablename__ = "service_metrics"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = ts_col(index=True)
    service: Mapped[str] = mapped_column(String(40), index=True)
    metric: Mapped[str] = mapped_column(String(60))
    value: Mapped[float]


class PastIncident(Base):
    __tablename__ = "past_incidents"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    root_cause: Mapped[str] = mapped_column(Text)
    resolution: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    tsv = mapped_column(TSVECTOR, Computed("to_tsvector('english', title || ' ' || body)", persisted=True))
    __table_args__ = (Index("ix_past_incidents_tsv", "tsv", postgresql_using="gin"),)


class Doc(Base):
    __tablename__ = "docs"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    tsv = mapped_column(TSVECTOR, Computed("to_tsvector('english', title || ' ' || body)", persisted=True))
    __table_args__ = (Index("ix_docs_tsv", "tsv", postgresql_using="gin"),)
   