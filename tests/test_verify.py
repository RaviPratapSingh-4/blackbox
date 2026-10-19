from app.services.verify import verify


def test_valid_output_passes(context, make_output):
    assert verify(make_output(), context) == []


def test_invented_evidence_id_rejected(context, make_output):
    out = make_output(hyp={"supporting_evidence": ["pay:999999"]})
    assert any("pay:999999" in p for p in verify(out, context))


def test_wrong_number_rejected(context, make_output):
    out = make_output(hyp={"numbers_cited": [{"fact": "duplicate_charges", "key": "orders", "value": 50}]})
    assert any("44" in p for p in verify(out, context))


def test_number_from_missing_key_rejected(context, make_output):
    out = make_output(hyp={"numbers_cited": [{"fact": "deployment_impact", "key": "nonexistent", "value": 1}]})
    assert any("nonexistent" in p for p in verify(out, context))


def test_ignored_contradiction_rejected_then_accepted(context, make_output):
    blames_deploy = {"supporting_evidence": ["deployment_impact"], "numbers_cited": []}
    problems = verify(make_output(hyp=blames_deploy), context)
    assert any("duplicates_predate_deployment" in p for p in problems)
    fixed = {**blames_deploy, "contradicting_evidence": ["duplicates_predate_deployment"]}
    assert verify(make_output(hyp=fixed), context) == []


def test_same_ref_on_both_sides_rejected(context, make_output):
    out = make_output(hyp={"contradicting_evidence": ["pay:1"]})
    assert any("both supporting and contradicting" in p for p in verify(out, context))


def test_missing_information_required_when_data_quality_warns(context, make_output):
    out = make_output(missing_information=[])
    assert any("missing_information" in p for p in verify(out, context))