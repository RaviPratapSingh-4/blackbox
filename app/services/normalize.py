"""Step 2: dedupe, quarantine/redact untrusted text, and turn data problems into explicit findings.
Findings travel with the evidence so the LLM, verifier and confidence rules can all see them."""
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median

from app.services.redact import looks_like_injection, redact

SKEW_TOLERANCE = timedelta(seconds=60)   # a follower-service log this far BEFORE the first payment log is impossible
SKEW_MIN_ROWS = 5
DELAY_THRESHOLD = timedelta(hours=1)
METRIC_GAP = timedelta(minutes=90)       # metrics are hourly; longer silence = missing data
STUCK_AFTER = timedelta(minutes=30)
QUARANTINED = "[quarantined: suspected prompt injection]"


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _finding(code: str, severity: str, summary: str, examples: list[str], **details) -> dict:
    return {"code": code, "severity": severity, "summary": summary, "examples": examples[:5], "details": details}


def dedupe_logs(logs: list[dict]) -> tuple[list[dict], list[dict]]:
    seen, unique, dupes = set(), [], []
    for row in logs:
        key = (row["ts"], row["service"], row["message"], row["trace_id"])
        (dupes if key in seen else unique).append(row)
        seen.add(key)
    return unique, dupes


def clean_rows(rows: list[dict]) -> list[dict]:
    """Quarantine injection-looking strings, redact PII. The row stays so evidence IDs remain valid."""
    for row in rows:
        for field, value in list(row.items()):  # copy: we add a key to row inside the loop
            if field == "evidence_id" or not isinstance(value, str):
                continue
            if looks_like_injection(value):
                row[field], row["quarantined"] = QUARANTINED, True
            else:
                row[field] = redact(value)
    return rows


def detect_clock_skew(logs: list[dict]) -> list[dict]:
    first_payment: dict[str, datetime] = {}
    for row in logs:  # logs arrive sorted by ts
        if row["service"] == "payment-service" and row["trace_id"]:
            first_payment.setdefault(row["trace_id"], _ts(row["ts"]))
    early = defaultdict(list)
    for row in logs:
        base = first_payment.get(row["trace_id"])
        if row["service"] != "payment-service" and base and _ts(row["ts"]) < base - SKEW_TOLERANCE:
            early[row["service"]].append((row, (base - _ts(row["ts"])).total_seconds()))
    return [
        _finding("CLOCK_SKEW_SUSPECTED", "warn",
                 f"{svc}: {len(items)} logs are timestamped before the payment request that caused them "
                 f"(median {median(s for _, s in items):.0f}s early); its clock is likely wrong, so cross-service "
                 "ordering involving it is unreliable",
                 [r["evidence_id"] for r, _ in items], service=svc, count=len(items),
                 first_seen=min(r["ts"] for r, _ in items))
        for svc, items in early.items() if len(items) >= SKEW_MIN_ROWS
    ]


def detect_delayed_logs(logs: list[dict]) -> list[dict]:
    late = [r for r in logs if r["ingested_at"] and _ts(r["ingested_at"]) - _ts(r["ts"]) > DELAY_THRESHOLD]
    if not late:
        return []
    return [_finding("DELAYED_LOGS", "info",
                     f"{len(late)} logs were ingested over an hour after their timestamp; recent windows may be incomplete",
                     [r["evidence_id"] for r in late], count=len(late))]


def detect_metric_gaps(metrics: list[dict]) -> list[dict]:
    series = defaultdict(list)
    for row in metrics:
        series[(row["service"], row["metric"])].append(_ts(row["ts"]))
    findings = []
    for (service, metric), times in series.items():
        times.sort()
        for a, b in zip(times, times[1:]):
            if b - a > METRIC_GAP:
                findings.append(_finding(
                    "METRICS_GAP", "warn",
                    f"{service}/{metric} has no data between {a.isoformat()} and {b.isoformat()}",
                    [], service=service, metric=metric, start=a.isoformat(), end=b.isoformat()))
    return findings


def stuck_pending_orders(orders: list[dict], payments: list[dict]) -> dict[str, str]:
    """order_id -> evidence_id of its last event, for orders still PENDING despite an old successful payment."""
    reference = max((_ts(r["ts"]) for r in orders), default=None)
    last = {}
    for row in orders:  # rows arrive sorted by ts
        last[row["order_id"]] = row
    paid_at = defaultdict(list)
    for p in payments:
        if p["status"] == "SUCCESS":
            paid_at[p["order_id"]].append(_ts(p["ts"]))
    return {oid: row["evidence_id"] for oid, row in last.items()
            if row["status"] == "PENDING" and any(t < reference - STUCK_AFTER for t in paid_at.get(oid, []))}


def detect_order_conflicts(orders: list[dict], payments: list[dict]) -> list[dict]:
    stuck = stuck_pending_orders(orders, payments)
    statuses, last_event = defaultdict(set), {}
    for row in orders:
        statuses[row["order_id"]].add(row["status"])
        last_event[row["order_id"]] = row["evidence_id"]
    paid_cancelled = [last_event[oid] for oid, s in statuses.items() if {"PAID", "CANCELLED"} <= s]

    findings = []
    if stuck:
        findings.append(_finding("ORDER_PENDING_DESPITE_PAYMENT", "warn",
                                 f"{len(stuck)} orders are still PENDING although a successful payment exists; "
                                 "order status is not a reliable proof of payment state",
                                 list(stuck.values()), count=len(stuck)))
    if paid_cancelled:
        findings.append(_finding("ORDER_PAID_THEN_CANCELLED", "info",
                                 f"{len(paid_cancelled)} orders have both PAID and CANCELLED events; services disagree "
                                 "on final state", paid_cancelled, count=len(paid_cancelled)))
    return findings


def normalize(bundle: dict) -> dict:
    src = {name: list(rows) for name, rows in bundle["sources"].items()}
    findings: list[dict] = []

    src["logs"], dupes = dedupe_logs(src["logs"])
    if dupes:
        findings.append(_finding(
            "DUPLICATE_LOGS", "info",
            f"{len(dupes)} exact duplicate log lines removed (same ts, service, message, trace); "
            f"affected window {min(r['ts'] for r in dupes)} to {max(r['ts'] for r in dupes)}",
            [r["evidence_id"] for r in dupes], count=len(dupes)))

    findings += detect_clock_skew(src["logs"])
    findings += detect_delayed_logs(src["logs"])
    findings += detect_metric_gaps(src["metrics"])
    findings += detect_order_conflicts(src["orders"], src["payments"])

    for name in ("logs", "past_incidents", "docs"):
        src[name] = clean_rows(src[name])
        flagged = [r["evidence_id"] for r in src[name] if r.get("quarantined")]
        if flagged:
            findings.append(_finding("PROMPT_INJECTION_SUSPECTED", "warn",
                                     f"{len(flagged)} {name} rows contained instruction-like text and were quarantined",
                                     flagged, source=name, count=len(flagged)))

    for name, message in bundle["errors"].items():
        findings.append(_finding("SOURCE_UNAVAILABLE", "warn", f"{name} could not be read: {message}", [], source=name))
    for name in bundle["truncated"]:
        findings.append(_finding("SOURCE_TRUNCATED", "warn", f"{name} hit the row limit; analysis is partial", [], source=name))

    return {"sources": src, "data_quality": findings}