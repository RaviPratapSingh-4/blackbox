
# Limitations

Each item: what could fail, why it matters, how I would fix it, why I did not.

- **Verifier checks existence, not context.** A real number can be used in the wrong hypothesis; the model can also list a "missing" item that exists. Fix: per-hypothesis checks tied to fact scope, or a stricter schema. Skipped: needs a larger fact model.
- **Numbers in prose are unchecked.** Only `numbers_cited` is verified. Fix: extract and match numbers from text. Skipped: brittle.
- **Regex defences are bypassable.** The injection filter and destructive-word scan miss paraphrases. Mitigation in place: tagging, verifier, and no execution path. Fix: a classifier plus an allow-list of action phrases.
- **Root cause versus contributor depends on the model.** The prompt asks for it, but the model can merge them (seen in testing). Fix: a deterministic rule that ranks by "present in every affected case". Skipped for time.
- **Fact functions are tailored to payment incidents.** A new incident type needs new functions in FACT_FUNCS; the fallback only recognises the missing-key pattern.
- **Suspect deployment is chosen by correlation** in a 24h window; it ignores several overlapping deploys and weak traffic.
- **No concurrency control.** Two simultaneous runs or resumes of one investigation can both execute a step. Fix: row lock or advisory lock.
- **Synchronous requests and large stored steps.** Collect and normalize outputs are stored whole in JSONB. Fix: background worker, store row IDs only.
- **LLM nondeterminism and free-tier limits.** Runs vary; rate limits trigger one wait then fallback. Not automatically tested against the live model (two saved example reports only).
- **Row cap of 20,000 per source** is reported as a finding but can hide late evidence.
- **No auth, rate limiting or audit log** on the API.
