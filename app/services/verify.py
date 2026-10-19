"""Step 5: check the LLM's answer against the data, in code. Returns a list of problems (empty = passed).
Each problem is a plain sentence, because on a retry the list is sent back to the model as feedback."""
import math

from app.models.schemas import LLMOutput
from app.services.hypotheses import allowed_ids

# (fact the hypothesis leans on, fact that cuts against it, when the cutting fact applies)
# To enforce a new "don't ignore this" rule, add one tuple here.
REQUIRED_CONTRADICTIONS = [
    ("deployment_impact", "duplicates_predate_deployment", lambda v: v.get("duplicates_before_deploy", 0) > 0),
]


def allowed_refs(context: dict) -> set[str]:
    """Everything the model may cite: raw evidence IDs, fact names, data quality codes."""
    return (allowed_ids(context) | {f["name"] for f in context["facts"]}
            | {f["code"] for f in context["data_quality"]})


def check_references(output: LLMOutput, refs: set[str]) -> list[str]:
    problems = []
    for i, h in enumerate(output.hypotheses, 1):
        for ref in h.supporting_evidence + h.contradicting_evidence:
            if ref not in refs:
                problems.append(f"Hypothesis {i}: '{ref}' is not an evidence ID, fact name or data quality code "
                                "from the data. Cite only references that appear in the data.")
        both = set(h.supporting_evidence) & set(h.contradicting_evidence)
        if both:
            problems.append(f"Hypothesis {i}: {sorted(both)} is listed as both supporting and contradicting.")
    return problems


def check_numbers(output: LLMOutput, facts: dict[str, dict]) -> list[str]:
    problems = []
    for i, h in enumerate(output.hypotheses, 1):
        for c in h.numbers_cited:
            fact = facts.get(c.fact)
            if fact is None:
                problems.append(f"Hypothesis {i}: there is no fact named '{c.fact}'.")
                continue
            actual = fact["value"].get(c.key)
            if c.key not in fact["value"]:
                problems.append(f"Hypothesis {i}: fact '{c.fact}' has no top-level key '{c.key}'.")
            elif isinstance(actual, bool) or not isinstance(actual, (int, float)):
                problems.append(f"Hypothesis {i}: {c.fact}.{c.key} is not a number.")
            elif not math.isclose(c.value, actual, rel_tol=0.01, abs_tol=1e-4):
                problems.append(f"Hypothesis {i}: {c.fact}.{c.key} is {actual}, not {c.value}.")
    return problems


def check_contradictions(output: LLMOutput, facts: dict[str, dict]) -> list[str]:
    problems = []
    for i, h in enumerate(output.hypotheses, 1):
        for supports, cuts_against, applies in REQUIRED_CONTRADICTIONS:
            if (supports in h.supporting_evidence and cuts_against in facts
                    and applies(facts[cuts_against]["value"]) and cuts_against not in h.contradicting_evidence):
                problems.append(f"Hypothesis {i} relies on '{supports}' but ignores '{cuts_against}'. "
                                f"List '{cuts_against}' as contradicting evidence and explain it.")
    return problems


def check_completeness(output: LLMOutput, context: dict) -> list[str]:
    problems = []
    for i, h in enumerate(output.hypotheses, 1):
        if not h.unexplained.strip():
            problems.append(f"Hypothesis {i}: say what it fails to explain.")
    if not output.recommended_actions:
        problems.append("recommended_actions is empty.")
    warnings = [f["code"] for f in context["data_quality"] if f["severity"] == "warn"]
    if warnings and not output.missing_information:
        problems.append(f"Data quality warnings exist ({sorted(set(warnings))}) but missing_information is empty.")
    return problems


def verify(output: LLMOutput, context: dict) -> list[str]:
    facts = {f["name"]: f for f in context["facts"]}
    return (check_references(output, allowed_refs(context)) + check_numbers(output, facts)
            + check_contradictions(output, facts) + check_completeness(output, context))