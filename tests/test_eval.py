"""End-to-end check against the answer key. Facts come from code, so no live LLM is needed."""
import json
from pathlib import Path

import pytest

from app.llm.base import LLMError

TRUTH = json.loads((Path(__file__).parent.parent / "data" / "ground_truth.json").read_text())


@pytest.fixture
def down_run(run):
    def down():
        raise LLMError("offline")
    return run(down)  # fallback path: proves the deterministic pipeline alone finds the cause


def facts_of(step, inv):
    return {f["name"]: f["value"] for f in step(inv, "facts")["facts"]}


def test_computed_facts_match_ground_truth(down_run, step):
    facts = facts_of(step, down_run)
    assert facts["duplicate_charges"]["orders"] == len(TRUTH["duplicate_charge_order_ids"])
    assert facts["duplicates_predate_deployment"]["duplicates_before_deploy"] == TRUTH["pre_deploy_duplicate_count"]
    assert facts["duplicates_predate_deployment"]["duplicates_after_deploy"] == TRUTH["post_deploy_duplicate_count"]
    assert facts["duplicate_charges"]["first_duplicate_ts"][:13] == TRUTH["first_duplicate_charge_ts"][:13]
    assert facts["retry_without_key"]["duplicate_orders_second_charge_without_key"] == len(TRUTH["duplicate_charge_order_ids"])


def test_all_planted_data_problems_are_found(down_run, step):
    codes = {f["code"] for f in step(down_run, "normalize")["data_quality"]}
    assert {"DUPLICATE_LOGS", "CLOCK_SKEW_SUSPECTED", "METRICS_GAP", "ORDER_PENDING_DESPITE_PAYMENT",
            "ORDER_PAID_THEN_CANCELLED", "PROMPT_INJECTION_SUSPECTED"} <= codes


def test_fallback_report_names_the_true_root_cause_not_the_deploy(down_run):
    title = down_run.report["root_cause_hypothesis"]["title"].lower()
    assert "idempotency key" in title and "deploy" not in title


def test_confidence_is_never_high_with_this_data(down_run):
    assert down_run.report["confidence"]["level"] in ("low", "medium")
    assert down_run.report["confidence"]["reasons"]