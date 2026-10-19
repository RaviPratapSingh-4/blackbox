"""Step 7: risk is decided here, never by the LLM. Nothing is ever auto-executed."""
import re

RISK_BY_TYPE = {
    "gather_more_data": "read_only",
    "reconcile_with_provider": "read_only",
    "fix_idempotency_key_on_retry": "reversible",
    "adjust_timeout_config": "reversible",
    "rollback_deployment": "reversible",
    "refund_affected_customers": "destructive",
    "edit_order_status": "destructive",
}
RANK = {"read_only": 0, "reversible": 1, "destructive": 2}
# the model can hide a destructive step inside a harmless-looking action type, so the text is scanned too
DESTRUCTIVE_WORDS = re.compile(
    r"refund|chargeback|\bdelete\b|\bdrop\b|truncate|purge|(update|edit|change|set) (the )?(order|status)|\bbulk\b", re.I)


def classify(actions: list) -> list[dict]:
    out = []
    for a in actions:
        risk, note = RISK_BY_TYPE[a.action_type], None
        if risk != "destructive" and DESTRUCTIVE_WORDS.search(a.description):
            risk, note = "destructive", "escalated: the description mentions a destructive step"
        out.append({"action_type": a.action_type, "description": a.description, "risk": risk,
                    "requires_approval": risk != "read_only", "auto_execute": False, "note": note})
    return sorted(out, key=lambda x: RANK[x["risk"]])  # stable: safest steps first