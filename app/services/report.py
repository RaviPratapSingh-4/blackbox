"""Turns the (verified or fallback) hypotheses into the final structured report. Pure functions, no DB."""
from app.models.schemas import Hypothesis, LLMOutput, ProposedAction
from app.services.actions import classify
from app.services.confidence import compute_confidence

RISK_NOTES = {
    "refund_affected_customers": "Refunding the wrong orders, or twice, loses money and cannot be undone.",
    "edit_order_status": "Editing order state by hand can hide the real inconsistency and break other services.",
    "rollback_deployment": "A rollback may reintroduce old bugs and does not fix charges that already happened.",
    "adjust_timeout_config": "A longer timeout slows checkout and does not remove a missing-idempotency-key bug.",
    "fix_idempotency_key_on_retry": "A code change in the payment path needs tests; wrong key reuse could block valid retries.",
    "reconcile_with_provider": "Provider data may lag or disagree with ours; treat it as one more source, not the truth.",
    "gather_more_data": "Costs time while customers may still be affected.",
}


def fallback_output(context: dict) -> LLMOutput:
    """Used when the LLM is down or rejected twice. Rule-based, and it says so."""
    facts = {f["name"]: f for f in context["facts"]}
    dup, retry = facts.get("duplicate_charges"), facts.get("retry_without_key")
    n_dup = dup["value"].get("orders", 0) if dup else 0
    keyless = retry["value"].get("duplicate_orders_second_charge_without_key", 0) if retry else 0
    matched = n_dup > 0 and keyless == n_dup
    if matched:
        hypothesis = Hypothesis(
            title="Retries sent without an idempotency key duplicate charges (rule-based)",
            explanation=f"All {n_dup} duplicate-charge orders had their retry sent without an idempotency key.",
            supporting_evidence=["retry_without_key", "duplicate_charges"],
            unexplained="The rule-based fallback does not weigh other causes (for example the deployment); "
                        "review the computed facts.", likelihood="medium")
        actions = [ProposedAction(action_type="gather_more_data", description="Review the computed facts and raw logs."),
                   ProposedAction(action_type="reconcile_with_provider", description="Compare our charges with the provider report."),
                   ProposedAction(action_type="fix_idempotency_key_on_retry", description="Reuse the original idempotency key on retries.")]
    else:
        hypothesis = Hypothesis(
            title="No rule matched; manual review of the computed facts is needed",
            explanation="Automatic analysis could not single out a cause.",
            supporting_evidence=[next(iter(facts), "duplicate_charges")],
            unexplained="Everything.", likelihood="low")
        actions = [ProposedAction(action_type="gather_more_data", description="Review the computed facts and raw logs.")]
    return LLMOutput(
        incident_summary=dup["statement"] if dup else "Facts could not be computed.",
        hypotheses=[hypothesis], stated_confidence="low",
        missing_information=["LLM analysis was unavailable; a human must review the computed facts."],
        recommended_actions=actions)


def build_report(hyp_step: dict, facts_out: dict, normalized: dict) -> dict:
    out = LLMOutput.model_validate(hyp_step["output"])
    facts, quality = facts_out["facts"], normalized["data_quality"]
    lookup = {f["name"]: f["statement"] for f in facts} | {f["code"]: f["summary"] for f in quality}

    def explain(refs: list[str]) -> list[dict]:
        return [{"ref": r, "detail": lookup.get(r, "raw record; look it up by ID")} for r in refs]

    top = out.hypotheses[0]
    actions = classify(out.recommended_actions)
    missing = out.missing_information + [f"Fact computation failed: {n}" for n in facts_out["errors"]]
    return {
        "incident_summary": out.incident_summary,
        "findings": [f["statement"] for f in facts] + [f["summary"] for f in quality],
        "root_cause_hypothesis": {"title": top.title, "explanation": top.explanation, "likelihood": top.likelihood,
                                  "alternatives": [{"title": h.title, "likelihood": h.likelihood} for h in out.hypotheses[1:]]},
        "evidence": explain(top.supporting_evidence),
        "contradicting_evidence": explain(top.contradicting_evidence),
        "unexplained_by_top_hypothesis": top.unexplained,
        "confidence": compute_confidence(out.stated_confidence, out.hypotheses, quality, hyp_step["llm_used"]),
        "missing_information": missing,
        "recommended_actions": actions,
        "risks": [RISK_NOTES[a["action_type"]] for a in actions]
                 + ["If the top hypothesis is wrong, the actions above target the wrong cause."],
        "meta": {"llm_used": hyp_step["llm_used"], "attempts": hyp_step["attempts"],
                 "llm_rejections": hyp_step["rejections"], "llm_error": hyp_step.get("llm_error")},
    }