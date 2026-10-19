
# Architecture

```mermaid
flowchart TD
    C[Client] -->|POST /incidents, POST /incidents/id/investigate| API[FastAPI]
    API --> P[Pipeline runner]
    P --> S1[1 collect: SQL + full-text search, no LLM]
    S1 --> S2[2 normalize: dedupe, quarantine injections, redact PII, data-quality findings]
    S2 --> S3[3 facts: counts and correlations computed in code]
    S3 --> S4{4 hypotheses}
    S4 -->|facts + findings only, untrusted text tagged| LLM[Groq LLM, strict JSON]
    LLM --> V[verify in code: IDs, numbers, contradictions]
    V -->|rejected: retry once with problem list| LLM
    V -->|rejected twice or LLM down| FB[deterministic fallback, llm_used=false]
    V -->|passed| S5
    FB --> S5[5 finalize: confidence caps, action risk, report]
    S1 & S2 & S3 & S4 & S5 -.each step saved.-> DB[(PostgreSQL: investigation_steps, investigations)]
    DB -.resume skips DONE steps.-> P
    EV[(evidence tables: logs, payments, orders, deploys, metrics, past incidents, docs)] --> S1
```

Where the LLM is used: only step 4. Where failure is handled: per-source errors in collect, per-fact errors in facts, retry then fallback in step 4, per-step persistence for resume.
