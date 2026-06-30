# Capstone — Agentic Power-Market Analyst

A retrieval-augmented LLM analyst for European power markets (zones **DE-LU, DK1, NO2**).
It ingests outage disclosures (REMIT/ACER) and energy news as a searchable corpus,
extracts each disclosure into a structured event, and answers questions with citations
over a hybrid retrieval layer (semantic + structured), grounded by ENTSO-E market data.
A tool-calling agent (later) lets the model query live ENTSO-E figures.

MSSE Capstone (solo). See the project plan and to-do checklist for full scope.

## Tech
FastAPI · Neon Postgres + pgvector · Cohere embeddings · GroqGemini LLM fallback ·
GitHub Actions CI/CD · deployed on Render.

## Setup
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then fill in your keys (see below)
```

## Environment variables
Copy `.env.example` to `.env` and fill in. Locally these load via python-dotenv;
on Render set them as Environment Variables instead. **Never commit `.env`.**

| Variable | Used for |
|----------|----------|
| `COHERE_API_KEY` | Embeddings (Cohere trial key) |
| `GROQ_API_KEY` | Primary LLM |
| `GEMINI_API_KEY` | Fallback LLM |
| `ENTSOE_API_TOKEN` | ENTSO-E market data |
| `DATABASE_URL` | Neon Postgres connection string |
| `GUARDIAN_API_KEY` | News full text (Sprint 2, optional) |

## Run
```bash
uvicorn app:app --reload
# GET /health  -> {"status":"ok"}
# GET /        -> chat UI
# POST /chat   -> {"question": "..."} -> answer + citations
```

## Tests
```bash
pytest -q
```

## Project structure
```
app.py                 FastAPI entrypoint (/, /chat, /health)
config.py              env vars, seeds, zones, model + chunking constants
src/
  ingestion/           entsoe_client.py · outages.py · news.py
  extraction/          events.py (OutageEvent schema + extraction)
  index/               db.py (Neon + retry) · embeddings.py · retrieval.py (hybrid)
  generation/          llm.py (GroqGemini) · answer.py (prompt, guardrails, citations)
  webapp/              optional Streamlit frontend
tests/                 smoke test
.github/workflows/     ci.yml
```

## Status
Under construction: Sprint 2 of 4. 
