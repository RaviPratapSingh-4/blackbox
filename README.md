
# Black Box: incident investigation system

Repository: https://github.com/RaviPratapSingh-4/blackbox

Investigates "customers charged twice" using synthetic production data and returns an evidence-backed report. Details: [docs/architecture.md](docs/architecture.md), [DECISIONS.md](DECISIONS.md), [LIMITATIONS.md](LIMITATIONS.md).

## Setup (Windows PowerShell; Python 3.11+, Docker Desktop)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env        # then set GROQ_API_KEY; delete the DATABASE_URL line when running outside Docker
docker compose up -d db            # Postgres on host port 5433 (5432 is often taken by a local Postgres)
python -m data.generate            # seeds the dataset and writes data/ground_truth.json
uvicorn app.main:app --reload      # API docs: http://localhost:8000/docs
```

Everything in Docker instead: `docker compose up --build`. In Docker, docker-compose.yml sets DATABASE_URL to the db service (overriding the `.env` value). Then seed with `docker compose exec api python -m data.generate`.

## Environment variables

`DATABASE_URL`, `LLM_PROVIDER` (groq), `GROQ_API_KEY`, `GROQ_MODEL` (default openai/gpt-oss-120b). Without a key the system still works and returns the labelled fallback report.

## Tests

`pytest -q`: 30 tests. 19 need nothing; 11 need the seeded database and skip otherwise. None call the real LLM.

## API

| Method and path                  | Purpose                                                    |
| -------------------------------- | ---------------------------------------------------------- |
| POST /incidents                  | submit an incident (title, description)                    |
| POST /incidents/{id}/investigate | run an investigation synchronously, returns report + steps |
| GET /investigations/{id}         | retrieve a stored investigation                            |
| GET /investigations?incident_id= | list past investigations                                   |
| POST /investigations/{id}/resume | continue an interrupted or failed investigation            |
| GET /health                      | liveness                                                   |

```powershell
$body = '{"title":"Double charges","description":"customers charged twice, orders still pending, payment timeouts"}'
$inc = Invoke-RestMethod -Method Post -Uri http://localhost:8000/incidents -ContentType "application/json" -Body $body
$r = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/incidents/$($inc.id)/investigate"
$r.report | ConvertTo-Json -Depth 10
```

curl: `curl -X POST localhost:8000/incidents -H "Content-Type: application/json" -d '{"title":"Double charges","description":"customers charged twice"}'`

Report fields: incident_summary, findings, root_cause_hypothesis, evidence, contradicting_evidence, unexplained_by_top_hypothesis, confidence (with reasons), missing_information, recommended_actions (with risk and approval flag), risks, meta (llm_used, attempts, rejections).

## Database

Evidence tables: app_logs, payment_events, order_events, deployments, service_metrics, past_incidents, docs (full-text indexes on text). State tables: incidents, investigations (status, report JSONB, llm_used), investigation_steps (one row per step, output JSONB, used for resume). Schema: app/models/orm.py.

## Example results

docs/example_results/double_charge_llm.json (live model) and double_charge_fallback.json (LLM down).

## Assumptions

Synthetic data only; one real root cause (retry without idempotency key) plus a contributor (timeout cut 10s to 3s) and red herrings; investigations run synchronously; no action is ever executed by the system; the answer key in data/ground_truth.json is used only by tests.
