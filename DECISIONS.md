
# Decisions and trade-offs

1. **Evidence first, LLM last.** Queries and arithmetic are done in code (facts.py). The LLM sees computed facts and data-quality findings, never raw logs, so it cannot miscount and sees less untrusted text. Trade-off: it can only reason about what the facts functions measure.
2. **Verify in code, not with a second LLM.** Cited references must exist, cited numbers must match a fact's top-level value, and the verifier requires the "duplicates predate the deploy" fact to be addressed. Rejected output is retried once with the problems listed; after that a labelled deterministic fallback is returned. Trade-off: it checks existence, not context (limitations).
3. **Confidence is capped by rules** (metrics gap, clock skew, contradictions, fallback), so the model's own claim can only lower, never raise, the result.
4. **Risk is classified in code**: a table by action type plus a keyword scan of the description. Nothing is auto-executed and there is no execute endpoint, so human approval is enforced by design.
5. **Every step is persisted** (investigation_steps). Resume reloads finished steps. Chosen over a queue or workflow engine to keep it explainable.
6. **Data problems are explicit findings** (duplicate logs, clock skew, delayed logs, metric gaps, state conflicts, quarantined text) that travel with the evidence.
7. **Security:** regex quarantine of injection-like text, `<untrusted>` tagging with escaping, PII redaction, only shown IDs citable, no secrets in repo.
8. **Postgres full-text search, no vector DB; no LangGraph, Redis or agents.** The corpus is small and each extra technology needs a defence.
9. **Synchronous API.** Simple and safe because of persistence; a worker would be the next step.
10. **Provider-agnostic LLM interface with a scripted FakeLLM** so failure paths are tested deterministically. The model is a reasoning model, so the client sets a token budget and low reasoning effort after we saw truncated JSON and rate limits.
