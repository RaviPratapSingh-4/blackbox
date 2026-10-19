"""Shape of what the LLM must return. Anything that doesn't validate against this is rejected."""
from typing import Literal

from pydantic import BaseModel, Field

Level = Literal["high", "medium", "low"]
# Risk of each action type is decided in code (actions.py), never by the LLM.
ActionType = Literal[
    "reconcile_with_provider", "gather_more_data", "fix_idempotency_key_on_retry", "adjust_timeout_config",
    "rollback_deployment", "refund_affected_customers", "edit_order_status",
]


class CitedNumber(BaseModel):
    fact: str   # name of a computed fact
    key: str    # top-level key inside that fact's "value"
    value: float


class Hypothesis(BaseModel):
    title: str = Field(max_length=200)
    explanation: str
    supporting_evidence: list[str] = Field(min_length=1)
    contradicting_evidence: list[str] = []
    unexplained: str   # what this hypothesis fails to explain
    numbers_cited: list[CitedNumber] = []
    likelihood: Level


class ProposedAction(BaseModel):
    action_type: ActionType
    description: str


class LLMOutput(BaseModel):
    incident_summary: str
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=4)  # ranked, most likely first
    stated_confidence: Level  # capped by confidence.py; never trusted as is
    missing_information: list[str]
    recommended_actions: list[ProposedAction]