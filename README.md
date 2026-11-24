# Modular AI Agent Platform

A FastAPI backend that lets you spin up per-client AI agents for real businesses — dental clinics, real estate, agencies, and more. Each client gets isolated modules: a **customer reply agent**, **lead qualifier**, **data cleanup**, **weekly auto-reports**, a per-client **RAG knowledge base**, and **guardrails** — all routed through a single webhook and managed from an admin dashboard.

> Four demo-ready modules are implemented. Stages 1–2 are production-ready; the rest are built and tested incrementally.

## What's inside

| Module | What it does | Endpoint |
|--------|--------------|----------|
| Reply Agent | Answers customer questions from the client's own config; escalates when it doesn't know — never guesses | `POST /webhook` |
| Lead Qualifier | Asks configured qualifying questions, scores answers, stores the verdict | `POST /webhook` (auto), `GET /clients/{id}/leads` |
| Data Cleanup | Upload messy CSV/Excel/PDF → cleaned, deterministic CSV out | `POST /cleanup` |
| Auto-Report | Weekly per-client summary, emailed or saved to `reports/` | `POST /clients/{id}/report` |
| Knowledge base (RAG) | Per-client document upload, TF-IDF retrieval, strict client isolation | `POST /clients/{id}/knowledge` |
| Guardrails | `never_say` rules checked in code before any reply is sent | Built into reply agent |
| Admin dashboard | Clients, escalated queue, leads, conversations, cleanup upload, report trigger | `http://127.0.0.1:8000/admin` |

## Quick start

### 1. Install

```powershell
python -m pip install -r requirements.txt
```

### 2. Configure

```powershell
copy .env.example .env
```

Edit `.env` and set at least one LLM key (`GEMINI_API_KEY`, `GROQ_API_KEY`, `XAI_API_KEY`, or `ANTHROPIC_API_KEY`) and the `LLM_PROVIDER`. Keys can also be pasted into the widget's settings panel at runtime — they are sent per-request and never stored server-side.

### 3. Seed demo data

```powershell
python -m scripts.seed_demo
```

Seeds two clients:

| Client | Modules | Demo |
|--------|---------|------|
| Sharma Dental Clinic | reply_agent, auto_report | FAQ answers + escalation, weekly report |
| Verma Realty | lead_qualifier, reply_agent | Budget/timeline/location → qualified lead |

### 4. Run

```powershell
python -m uvicorn app.main:app --reload
```

Open:

- Chat widget demo: http://127.0.0.1:8000/widget/ (add `?client=2` for the real-estate lead demo)
- Admin dashboard: http://127.0.0.1:8000/admin
- API docs (Swagger): http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/health

## API reference

### `POST /webhook`
Receive a customer message and get an agent reply (or escalation).

```json
{
  "client_id": 1,
  "channel": "widget",
  "sender_id": "demo-1",
  "text": "How much is a checkup?"
}
```

### `POST /clients`
Register a new client.

```json
{
  "business_name": "Acme Corp",
  "industry": "consulting",
  "tone_of_voice": "professional",
  "escalation_contact": "ops@acme.com",
  "active_modules": ["reply_agent"]
}
```

Then copy `configs/template.json` to `configs/client_<id>.json` and fill in their FAQs, services, pricing, hours, and `never_say` rules.

### `GET /clients/{id}/leads`
Qualified leads, newest first.

### `POST /cleanup`
Upload a messy file (multipart), get a cleaned CSV back (10 MB limit). Works with or without an LLM key.

### `POST /clients/{id}/knowledge`
Upload reference documents (`.txt`, `.md`, `.csv`, `.pdf`, 15 MB limit) for RAG grounding.

### `POST /clients/{id}/report`
Manually trigger a weekly report for a client.

## Project structure

```
app/              FastAPI app: routes, modules, database, config loader
  modules/        reply_agent, lead_qualifier, data_cleanup, report_agent,
                  knowledge_base, guardrails
  routes/         webhook, clients, cleanup, knowledge, admin
configs/          Per-client JSON configs (client_<id>.json + template.json)
samples/          Messy sample files for the cleanup demo
scripts/          seed_demo, stage2_harness
static/           Chat widget + admin dashboard HTML
tests/            Pytest suite (no API key required)
reports/          Generated weekly reports (gitignored)
.env              Runtime secrets (gitignored)
agency.db         SQLite database (gitignored)
```

## Testing

```powershell
python -m pytest tests/ -q
```

All stage tests run without an API key. There is also a routing harness:

```powershell
python -m scripts.stage2_harness --provider gemini --key YOUR_KEY
```

It sends answerable and out-of-scope messages and verifies the reply/escalate split.

## Adding a new client

1. `POST /clients` with business details and `active_modules`.
2. Copy `configs/template.json` → `configs/client_<id>.json`; fill in FAQs, services, pricing, hours, `never_say` rules.
3. (Optional) Upload reference documents via `POST /clients/{id}/knowledge`.
4. Restart the server if you enabled `auto_report` (scheduler registers jobs at startup).

## Design principles

- **Escalate, never guess:** the agent answers only from the client's config. Unknown answers, refunds, complaints, and discount requests are escalated to a human. LLM/API failures also escalate — fail safe.
- **Client isolation:** every client has its own config file, knowledge-base store, and conversation history. Nothing is shared across clients.
- **Deterministic cleaning:** the LLM only classifies columns in data cleanup; dates, phones, and dedup are handled by deterministic Python so a hallucination can't corrupt data.
- **Swap the DB:** set `DATABASE_URL` to a Postgres URL when you outgrow SQLite; SQLAlchemy handles the rest.
- **No hardcoded secrets:** keys live in `.env` (gitignored) or per-request widget input.

## License

MIT