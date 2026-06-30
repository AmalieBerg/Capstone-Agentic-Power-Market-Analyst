# Sprint 1 — Process Note

**Project:** Agentic Power-Market Analyst · **Sprint goal:** a thin but live end-to-end RAG slice
(ingest  extract  index  retrieve  cited answer), deployed and tested.

## Outcome

Sprint goal met and exceeded. The full pipeline runs end to end and is deployed to a live URL with a
chat UI, JSON API, and CI-gated test suite. Completed stories: U1.1, U1.2, U2.1, U3.1, U3.2, U3.3,
U4.1, U4.2, U5.1, U6.1, U6.2, with the process stories (U9.1/U9.2/U9.3/U9.6) addressed.

## Done ahead of scope

- **All three zones** (DE-LU, DK1, NO2) rather than the planned DE-LU-only slice — zone breadth
  intended for Sprint 2 was banked early.
- A **REMIT UMM Electricity Schema V3 parser** for the German IIP feed, built and verified against a
  live message.
- A **structured-vs-free-text extraction split** that maps already-structured ENTSO-E outages to events
  directly (no LLM), and **incremental indexing** — both beyond the minimal Sprint 1 ask.

## What changed mid-sprint

- **Outage deduplication bug.** The original content-hash id let every disclosure *revision* create a
  new row and kept cancelled outages live, inflating DE-LU from a few hundred real outages to 819 rows
  (440 cancelled). Fixed with a stable natural key + cancelled filtering + latest-revision-wins. This
  was the single largest time cost and the most valuable correctness lesson.
- **Free-tier quota limits.** Repeated full-corpus reprocessing exhausted Groq's daily token limit and
  tripped Cohere's per-minute cap. Resolved by the structured/free-text split (no LLM for structured
  outages) and incremental indexing.
- **Feed issues.** The Nord Pool host was intermittently slow (fixed with timeout + retry); the IIP
  feed returned unfiltered multi-country REMIT XML (parser built; zone-filtered URL deferred as an
  operational step). DE-LU coverage comes from ENTSO-E regardless.
- **Repo/local drift.** Several whole-file edits dropped or lagged code (a deleted `db.py` function; a
  stale `app.py` and `llm.py` reaching deploy/CI). CI caught the drift and is now the guard against it;
  future `db.py` changes are applied as targeted additions, not whole-file swaps.

## Carried into Sprint 2/3

News ingestion (U1.3); evaluation gold set + metrics (U8); the tool-calling agent (U7.1); optional
lexical retrieval; Render Starter for an always-on URL; CD on merge; finalised design document and
recorded presentation.

## Reflection

The intellectually load-bearing half of the system — the RAG pipeline and its data-quality
foundations — is complete and robust. Most of the friction came not from the AI components but from
**data quality** (outage dedup) and **free-tier operational limits** (quotas, cold starts) — a
realistic reflection of production data engineering, and worth foregrounding in the final write-up.