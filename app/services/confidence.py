"""Step 6: final confidence = the LLM's own claim, capped by rules. Every rule that applies leaves a reason."""
LEVELS = ["low", "medium", "high"]


def _cap(level: str, ceiling: str) -> str:
    return LEVELS[min(LEVELS.index(level), LEVELS.index(ceiling))]


def compute_confidence(stated: str, hypotheses: list, data_quality: list[dict], llm_used: bool) -> dict:
    level, reasons = stated, []
    codes = [f["code"] for f in data_quality]

    def apply(ceiling: str, reason: str) -> None:
        nonlocal level
        level = _cap(level, ceiling)
        reasons.append(f"{reason} -> at most {ceiling}")

    if not llm_used:
        apply("low", "LLM output unavailable or rejected; this is a deterministic fallback report")
    broken = [c for c in codes if c in ("SOURCE_UNAVAILABLE", "SOURCE_TRUNCATED")]
    if len(broken) >= 2:
        apply("low", "two or more data sources are unavailable or truncated")
    elif broken:
        apply("medium", "a data source is unavailable or truncated")
    if "METRICS_GAP" in codes:
        apply("medium", "metrics are missing for part of the incident window")
    if "CLOCK_SKEW_SUSPECTED" in codes:
        apply("medium", "a service clock is suspect, so cross-service timing is unreliable")
    if hypotheses and hypotheses[0].contradicting_evidence:
        apply("medium", "the top hypothesis has contradicting evidence")
    if len(hypotheses) > 1 and hypotheses[0].likelihood == hypotheses[1].likelihood:
        apply("medium", "the top two hypotheses are rated equally likely")
    return {"level": level, "stated_by_llm": stated, "reasons": reasons}