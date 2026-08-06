# Capstone — Agentic Power-Market Analyst

A deployed, retrieval-augmented (RAG) and tool-calling LLM analyst for European power markets (bidding zones **DE-LU, DK1, NO2, SE3**). It ingests outage disclosures (REMIT/UMM) and power-market news as a searchable corpus, extracts each disclosure into a structured event, and answers natural-language questions with citations over a hybrid retrieval layer (semantic + structured). A tool-calling agent layer additionally reasons over live ENTSO-E market data (day-ahead price, generation, load and wind/solar forecasts), separate from the frozen text corpus used for grounded historical answers.

**Live URL:** https://capstone-msse-quantic.onrender.com (Free-tier hosting — the first request after idle can take up to ~30s while the service wakes; the chat UI shows a "waking up" message if this happens.)

MSSE Capstone (solo), Quantic School of Business and Technology.

## Tech stack

- **Web app:** FastAPI, deployed on Render
- **Database:** Neon Postgres + pgvector (single store — text chunks with embeddings, structured events, outage/news metadata)
- **Embeddings:** Cohere `embed-multilingual-v3.0`
- **LLM:** Groq (`openai/gpt-oss-120b`, primary) with Google Gemini (`gemini-2.5-flash`, fallback)
- **Agent orchestration:** LangChain (`bind_tools()`, `.with_fallbacks()`) with a hand-wired tool-call loop — no `AgentExecutor`/LangGraph; see the design doc for rationale
- **CI/CD:** GitHub Actions (install, import check, pytest) + Render auto-deploy on push
- **Data sources:** ENTSO-E Transparency Platform (structured outages + live market data), Nord Pool UMM RSS, Germany's IIP REMIT Atom feed, Google News RSS, the Guardian API, Clean Energy Wire

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then fill in your keys (see below)
```

## Environment variables

Copy `.env.example` to `.env` and fill in. Locally these load via `python-dotenv`; on Render set them as Environment Variables instead. Never commit `.env`.

| Variable | Used for |
|---|---|
| `COHERE_API_KEY` | Embeddings |
| `GROQ_API_KEY` | Primary LLM (tool-calling agent path) |
| `GEMINI_API_KEY` | Fallback LLM (retrieval-only degradation on Groq failure) |
| `ENTSOE_API_TOKEN` | ENTSO-E market data — both scheduled ingestion and the live agent tool |
| `DATABASE_URL` | Neon Postgres connection string |
| `GUARDIAN_API_KEY` | News full text (optional) |

## Run

```bash
uvicorn app:app --reload
# GET  /health  -> {"status":"ok"}
# GET  /        -> chat UI (example questions, zone selector, live/corpus/refused badge)
# POST /chat    -> {"question": "...", "zone": "DE-LU"} -> answer + citations + used_tool
# `zone` is optional and accepts any of DE-LU, DK1, NO2, SE3; omit it to let the
# system infer zone from the question text.
```

## Tests

```bash
pytest -q
```

## Evaluation

```bash
python run_eval.py --mode explicit
```

Runs a 37-question gold set (`data/eval/gold.jsonl`) against the live `/chat` endpoint, scoring refusal correctness, citation recall, fact match, tool-selection correctness, and (for live-data questions) plausibility of the returned figures. A retrieval-`k` ablation (`--k 4/6/8/10`) empirically confirmed the default `k=6` as the optimum in the tested range — see the design doc, §8.8. Full methodology and results in `doc/design-and-testing.md`.

## Project management

Agile task board (Trello): https://trello.com/invite/b/6a2f9ff741ca55837e1c5eed/ATTI99702564e211d26339d1080619c40b2a9E87AA51/my-capstone-trello-board

## Project structure

```
app.py                    FastAPI entrypoint (/, /chat, /health)
config.py                 env vars, seeds, zones, model + chunking constants
src/
  agent.py                 U7.1 tool-calling agent: retrieval + live ENTSO-E tool
  llm.py                   Groq/Gemini completion client, fallback + cache
  ingestion/                entsoe_client.py (structured + live data), outages.py, news.py, remit.py
  extraction/               events.py (OutageEvent schema), news_tags.py, event_news.py (U7.2 enrichment)
  index/                    db.py (Neon), embeddings.py, chunking.py, retrieval.py (hybrid)
  generation/               answer.py (prompt, guardrails, citations)
tests/                     pytest suite: extraction, retrieval, guardrails, agent smoke, /health
data/
  eval/                     gold.jsonl (37-question gold set), results.json, results_k*.json (U8.3 ablation)
  snapshot/                 frozen corpus (U1.4): messages, chunks, events, outages, news_zone_tags
doc/                       design-and-testing.md + per-sprint process notes
.github/workflows/ci.yml   install + import check + pytest, on push/PR
```

## Architecture notes

- **Two freshness regimes, deliberately separate.** The text corpus is frozen to a fixed snapshot window (`CORPUS_FROZEN`, `data/snapshot/`) so evaluation is reproducible. The agent's live numeric tool bypasses this freeze entirely, querying ENTSO-E directly per request — genuinely current data for price/generation/forecast questions, kept explicitly separate in answer text from dated corpus citations.
- **Zone is a query-time filter, not an ingestion boundary** — a deliberate Sprint-2 pivot enabling pan-European expansion without re-architecting ingestion. **Validated post-submission:** a fourth zone (SE3) was added using only configuration and data changes — no edits to retrieval, indexing, or the agent's tool logic. The exercise did surface (and fix) two latent bugs: a hardcoded three-zone refusal message and a guardrail prompt that silently assumed exactly three zones — both invisible until a fourth zone exercised that code path.
- **Clean cut-line:** the agent layer wraps the RAG core; if it fails, `/chat` falls back to retrieval-only automatically, and the RAG core has no dependency on the agent layer.

Full architectural rationale, decision log, and iteration history (including guardrail redesigns and documented false starts) are in `doc/design-and-testing.md`.

## Status

Sprint 3 complete. Post-submission stretch phase also complete: event→news enrichment (U7.2), a zone selector UI (U10.3), a validated retrieval-`k` ablation (U8.3), and a fourth bidding zone — SE3 — added with zero changes to core retrieval or guardrail logic (U11.1). Final presentation recorded.