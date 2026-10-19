"""Step 4: ask the LLM for ranked hypotheses. It sees computed facts and findings, never raw logs."""
import json
import re

from pydantic import ValidationError

from app.llm.base import LLMClient
from app.llm.prompts import SYSTEM_PROMPT, render_user_prompt
from app.models.schemas import LLMOutput

ID_RE = re.compile(r"\b(?:log|pay|ord|dep|met|inc|doc):\d+\b")
FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


class InvalidLLMOutput(Exception):
    """Output was not valid JSON for LLMOutput. The message is fed back to the model on retry."""


def build_context(facts: list[dict], normalized: dict) -> dict:
    src = normalized["sources"]
    return {"facts": facts, "data_quality": normalized["data_quality"],
            "past_incidents": src["past_incidents"], "docs": src["docs"]}


def allowed_ids(context: dict) -> set[str]:
    """An ID is citable only if the model was shown it. Taken from structured fields, not from document text,
    so a poisoned doc cannot widen the set."""
    blob = json.dumps({"facts": context["facts"], "data_quality": context["data_quality"]})
    return set(ID_RE.findall(blob)) | {r["evidence_id"] for r in context["past_incidents"] + context["docs"]}


def propose(llm: LLMClient, incident_text: str, context: dict, feedback: list[str] | None = None) -> LLMOutput:
    raw = llm.complete_json(SYSTEM_PROMPT, render_user_prompt(incident_text, context, feedback))
    try:
        return LLMOutput.model_validate_json(FENCE_RE.sub("", raw.strip()))
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:5])
        raise InvalidLLMOutput(problems) from exc