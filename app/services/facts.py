"""Step 3: facts computed in code. The LLM may only cite numbers that appear here; the verifier checks them.
Every fact function takes the normalized sources and returns a list of facts (empty if data is insufficient)."""
import re
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median

from app.services.normalize import stuck_pending_orders

WINDOW = timedelta(hours=24)   # before/after comparison window around a deployment
MIN_ORDERS_PER_SIDE = 20       # fewer orders than this and a rate is noise
MIN_DUPLICATES_AFTER = 3
TIMEOUT_RE = re.compile(r"provider timeout after (\d+)ms")
LATENCY_METRIC = "provider_latency_p95_ms"


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _fact(name: str, statement: str, value: dict, evidence_ids: list[str]) -> dict:
    return {"name": name, "statement": statement, "value": value, "evidence_ids": evidence_ids[:10]}


def _rate(n: int, total: int) -> float | None:
    return round(n / total, 4) if total else None


def _per100(n: int, total: int) -> float | None:
    return round(100 * n / total, 2) if total else None


# --- shared building blocks ---
def _successes_by_order(payments: list[dict]) -> dict[str, list[dict]]:
    out = defaultdict(list)
    for p in payments:
        if p["status"] == "SUCCESS":
            out[p["order_id"]].append(p)
    return out


def _duplicates(payments: list[dict]) -> dict[str, list[dict]]:
    """order_id -> its successful charges, for orders charged successfully 2+ times."""
    return {oid: rows for oid, rows in _successes_by_order(payments).items() if len(rows) > 1}


def _order_start(payments: list[dict]) -> dict[str, datetime]:
    start: dict[str, datetime] = {}
    for p in payments:  # sorted by ts
        start.setdefault(p["order_id"], _ts(p["ts"]))
    return start


def _deploy_stats(src: dict) -> list[dict]:
    """Duplicate-charge rate in the 24h before vs after every deployment (orders bucketed by when they started)."""
    start, dup_ids = _order_start(src["payments"]), set(_duplicates(src["payments"]))
    stats = []
    for dep in src["deployments"]:
        t = _ts(dep["ts"])
        before = [o for o, s in start.items() if t - WINDOW <= s < t]
        after = [o for o, s in start.items() if t <= s < t + WINDOW]
        dup_b, dup_a = sum(o in dup_ids for o in before), sum(o in dup_ids for o in after)
        stats.append({
            "evidence_id": dep["evidence_id"], "ts": dep["ts"], "service": dep["service"],
            "version": dep["version"], "change_summary": dep["change_summary"],
            "orders_before": len(before), "orders_after": len(after),
            "duplicates_before": dup_b, "duplicates_after": dup_a,
            "rate_before": _rate(dup_b, len(before)), "rate_after": _rate(dup_a, len(after)),
        })
    return stats


def _suspect(stats: list[dict]) -> dict | None:
    usable = [s for s in stats
              if min(s["orders_before"], s["orders_after"]) >= MIN_ORDERS_PER_SIDE
              and s["duplicates_after"] >= MIN_DUPLICATES_AFTER and s["rate_after"] > s["rate_before"]]
    return max(usable, key=lambda s: s["rate_after"] - s["rate_before"], default=None)


def _timeout_logs(logs: list[dict]) -> list[tuple[dict, int]]:
    out = []
    for row in logs:
        match = TIMEOUT_RE.search(row["message"]) if row["service"] == "payment-service" else None
        if match:
            out.append((row, int(match.group(1))))
    return out


# --- facts ---
def fact_duplicate_charges(src: dict) -> list[dict]:
    dups = _duplicates(src["payments"])
    total = len({p["order_id"] for p in src["payments"]})
    if not dups:
        return [_fact("duplicate_charges", "No order has more than one successful charge",
                      {"orders": 0, "total_orders": total}, [])]
    second_ts = sorted(rows[1]["ts"] for rows in dups.values())
    distinct = sum(len({r["provider_txn_id"] for r in rows}) == len(rows) for rows in dups.values())
    extra = round(sum(rows[1]["amount"] for rows in dups.values()), 2)
    ids = [r["evidence_id"] for rows in list(dups.values())[:5] for r in rows]
    return [_fact(
        "duplicate_charges",
        f"{len(dups)} of {total} orders have 2+ successful charges ({distinct} with different provider txn ids, "
        f"i.e. separate charges rather than one replayed webhook); first duplicate charge at {second_ts[0]}; "
        f"extra amount charged {extra}",
        {"orders": len(dups), "total_orders": total, "orders_with_distinct_txn_ids": distinct,
         "first_duplicate_ts": second_ts[0], "last_duplicate_ts": second_ts[-1], "extra_amount": extra}, ids)]


def fact_deployment_impact(src: dict) -> list[dict]:
    stats = _deploy_stats(src)
    if not stats:
        return []
    s = _suspect(stats)
    if s:
        statement = (f"Largest 24h duplicate-charge rate increase follows {s['service']} {s['version']} at {s['ts']}: "
                     f"{s['rate_before']:.1%} ({s['duplicates_before']}/{s['orders_before']} orders) -> "
                     f"{s['rate_after']:.1%} ({s['duplicates_after']}/{s['orders_after']}). "
                     f"Change: {s['change_summary']}")
    else:
        statement = "No deployment is followed by a clear increase in duplicate-charge rate within 24h"
    ids = ([s["evidence_id"]] if s else []) + [d["evidence_id"] for d in stats if d is not s]
    return [_fact("deployment_impact", statement,
                  {"deployments": stats, "suspect": s["evidence_id"] if s else None}, ids)]


def fact_duplicates_predate_deployment(src: dict) -> list[dict]:
    s = _suspect(_deploy_stats(src))
    if not s:
        return []
    t, start, dups = _ts(s["ts"]), _order_start(src["payments"]), _duplicates(src["payments"])
    early = sorted((start[o], o) for o in dups if start[o] < t)
    value = {"suspect_deployment": s["evidence_id"], "duplicates_before_deploy": len(early),
             "duplicates_after_deploy": len(dups) - len(early),
             "earliest_duplicate_order_start": early[0][0].isoformat() if early else None}
    ids = [r["evidence_id"] for _, o in early[:3] for r in dups[o]]
    if early:
        statement = (f"{len(early)} of {len(dups)} duplicate-charge orders started before {s['version']} was deployed "
                     f"(earliest {value['earliest_duplicate_order_start']}), so duplicates existed before this deployment")
    else:
        statement = f"No duplicate-charge order started before {s['version']} was deployed"
    return [_fact("duplicates_predate_deployment", statement, value, ids)]


def _retry_row(rows: list[dict]) -> dict:
    """The charge with the highest attempt number; timestamps can't be used because webhooks arrive late."""
    return max(rows, key=lambda r: r["attempt"])


def fact_retry_without_key(src: dict) -> list[dict]:
    payments, dups = src["payments"], _duplicates(src["payments"])
    retries = [p for p in payments if p["attempt"] >= 2]
    if not retries:
        return []
    no_key = [p for p in retries if not p["idempotency_key"]]
    no_key_orders = {p["order_id"] for p in no_key}
    keyless = [_retry_row(rows) for rows in dups.values() if not _retry_row(rows)["idempotency_key"]]
    charged_once = len(no_key_orders - set(dups))
    value = {"retry_charges": len(retries), "retries_without_key": len(no_key),
             "retries_with_key": len(retries) - len(no_key), "duplicate_orders": len(dups),
             "duplicate_orders_second_charge_without_key": len(keyless),
             "orders_retried_without_key": len(no_key_orders), "orders_retried_without_key_charged_once": charged_once}
    statement = (f"{len(keyless)} of {len(dups)} duplicate-charge orders had their retry charge sent without an "
                 f"idempotency key; {len(no_key_orders)} orders retried without a key and {charged_once} of them "
                 f"were charged only once")
    return [_fact("retry_without_key", statement, value, [r["evidence_id"] for r in keyless])]


def fact_timeout_config(src: dict) -> list[dict]:
    s, timeouts = _suspect(_deploy_stats(src)), _timeout_logs(src["logs"])
    if not s or not timeouts:
        return []
    t = _ts(s["ts"])
    before = [(r, ms) for r, ms in timeouts if _ts(r["ts"]) < t]
    after = [(r, ms) for r, ms in timeouts if _ts(r["ts"]) >= t]
    if not before or not after:
        return []
    n_before = sum(t - WINDOW <= _ts(r["ts"]) for r, _ in before)
    n_after = sum(_ts(r["ts"]) < t + WINDOW for r, _ in after)
    value = {"median_timeout_ms_before": median(ms for _, ms in before),
             "median_timeout_ms_after": median(ms for _, ms in after),
             "timeouts_per_100_orders_before": _per100(n_before, s["orders_before"]),
             "timeouts_per_100_orders_after": _per100(n_after, s["orders_after"])}
    statement = (f"Provider timeouts logged after {s['version']} use a {value['median_timeout_ms_after']:.0f}ms limit "
                 f"vs {value['median_timeout_ms_before']:.0f}ms before; timeouts per 100 orders "
                 f"{value['timeouts_per_100_orders_before']} -> {value['timeouts_per_100_orders_after']}")
    return [_fact("timeout_config", statement, value, [r["evidence_id"] for r, _ in before[-3:] + after[:3]])]


def fact_peak_timeout_hours(src: dict) -> list[dict]:
    timeouts = _timeout_logs(src["logs"])
    if not timeouts:
        return []
    by_hour = defaultdict(list)
    for row, _ in timeouts:
        by_hour[row["ts"][:13]].append(row)
    start, dups = _order_start(src["payments"]), set(_duplicates(src["payments"]))
    latency = {m["ts"][:13]: m["value"] for m in src["metrics"] if m["metric"] == LATENCY_METRIC}
    hours = sorted(by_hour, key=lambda h: len(by_hour[h]), reverse=True)[:2]
    if latency and max(latency, key=latency.get) not in hours:
        hours.append(max(latency, key=latency.get))  # the slowest provider hour, even if timeouts are few
    top = []
    for hour in hours:
        started = [o for o, ts in start.items() if ts.isoformat()[:13] == hour]
        top.append({"hour": hour, "timeouts": len(by_hour.get(hour, [])), "orders_started": len(started),
                    "duplicate_orders": sum(o in dups for o in started),
                    "provider_latency_p95_ms": latency.get(hour)})
    statement = "Hours with most timeouts or slowest provider: " + "; ".join(
        f"{h['hour']}:00 {h['timeouts']} timeouts, {h['duplicate_orders']}/{h['orders_started']} orders double "
        f"charged, provider p95 {h['provider_latency_p95_ms']} ms" for h in top)
    ids = [r["evidence_id"] for h in hours for r in by_hour.get(h, [])[:2]]
    return [_fact("peak_timeout_hours", statement, {"top_hours": top}, ids)]


def fact_provider_latency(src: dict) -> list[dict]:
    s = _suspect(_deploy_stats(src))
    if not s:
        return []
    t = _ts(s["ts"])
    points = sorted((_ts(m["ts"]), m["value"], m["evidence_id"]) for m in src["metrics"] if m["metric"] == LATENCY_METRIC)
    before = [p for p in points if t - WINDOW <= p[0] < t]
    after = [p for p in points if t <= p[0] < t + WINDOW]
    if not before or not after:
        return [_fact("provider_latency", "Not enough provider latency data on one side of the deployment",
                      {"points_before": len(before), "points_after": len(after)}, [])]
    last_before, first_after = max(p[0] for p in before), min(p[0] for p in after)
    value = {"median_before_ms": median(p[1] for p in before), "median_after_ms": median(p[1] for p in after),
             "points_before": len(before), "points_after": len(after),
             "last_point_before": last_before.isoformat(), "first_point_after": first_after.isoformat(),
             "gap_hours": round((first_after - last_before).total_seconds() / 3600, 1)}
    statement = (f"Provider p95 latency median {value['median_before_ms']:.0f} ms before vs "
                 f"{value['median_after_ms']:.0f} ms after {s['version']} ({len(before)}/{len(after)} points); "
                 f"no data for {value['gap_hours']}h around the deploy ({value['last_point_before']} to "
                 f"{value['first_point_after']})")
    ids = [p[2] for p in points if p[0] in (last_before, first_after)]
    return [_fact("provider_latency", statement, value, ids)]


def fact_pending_overlap(src: dict) -> list[dict]:
    paid = set(_successes_by_order(src["payments"]))
    dups = set(_duplicates(src["payments"]))
    stuck = stuck_pending_orders(src["orders"], src["payments"])
    others = paid - dups
    dup_stuck, other_stuck = dups & stuck.keys(), others & stuck.keys()
    value = {"duplicate_orders": len(dups), "duplicate_orders_pending": len(dup_stuck),
             "other_paid_orders": len(others), "other_paid_orders_pending": len(other_stuck)}
    statement = (f"{len(dup_stuck)} of {len(dups)} double-charged orders are still PENDING "
                 f"vs {len(other_stuck)} of {len(others)} other paid orders")
    return [_fact("pending_overlap", statement, value, [stuck[o] for o in sorted(dup_stuck)[:5]])]


FACT_FUNCS = [fact_duplicate_charges, fact_deployment_impact, fact_duplicates_predate_deployment,
              fact_retry_without_key, fact_timeout_config, fact_peak_timeout_hours,
              fact_provider_latency, fact_pending_overlap]


def compute_facts(normalized: dict) -> dict:
    """One broken fact function must not kill the investigation; it is reported as an error instead."""
    src, facts, errors = normalized["sources"], [], {}
    for fn in FACT_FUNCS:
        try:
            facts.extend(fn(src))
        except Exception as exc:
            errors[fn.__name__] = str(exc)[:200]
    return {"facts": facts, "errors": errors}