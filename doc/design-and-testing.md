# Agentic Power-Market Analyst — Design & Testing Document

**Author:** Amalie Berg · MSSE Capstone (solo) · Living document — *Sprint 1 draft, to be finalised in Sprint 3.*

---

## 1. System overview

The Agentic Power-Market Analyst is a Retrieval-Augmented Generation (RAG) system that answers
natural-language questions about electricity-market generation and transmission outages for three
bidding zones — **DE-LU**, **DK1**, and **NO2**. It ingests structured outage data (ENTSO-E
Transparency) and outage disclosure messages (REMIT/ACER Urgent Market Messages), extracts
structured events, indexes both the text and the structured records, and answers questions with
**grounded, cited** responses through a deployed web app and JSON API.


---

## 2. Architecture

### 2.1 Data flow

```
ENTSO-E API ─┐
             ├─► (U1.1) entsoe_client ─► market_data (time series)
             └────────────────────────► entsoe_outages (structured, JSONB)

REMIT/UMM feeds ─► (U1.2) outages + remit ─► messages (text corpus)
ENTSO-E outages ─► rendered as messages ───► messages

messages ─► (U3.1) chunking + embeddings ─► chunks (text + vector, HNSW index)
messages ─► (U2.1) extraction:
              • ENTSO-E structured  ─► mapped directly (no LLM) ─┐
              • free-text (UMM/news) ─► LLM extraction ──────────┴─► events (structured)

question ─► (U3.3) retrieval: vector search over chunks + events by message_id, per-asset dedup
        ─► (U4.1/U4.2) generation: grounded prompt + guardrails ─► cited answer
        ─► (U5.1) FastAPI app: / (chat UI), /chat (JSON), /health
```

### 2.2 Storage — Neon Postgres + pgvector (single store)

A single Neon Postgres database with the `pgvector` extension holds everything, collapsing the vector
store and relational store into one system. Tables:

- `market_data` — tidy ENTSO-E time series (day-ahead price, load/wind/solar forecast, generation).
- `entsoe_outages` — structured generation-unit outages as JSONB, deduped on a natural key.
- `messages` — the outage-message retrieval corpus (text loaded at runtime, never committed).
- `chunks` — embedded text chunks + an HNSW cosine index.
- `events` — structured `OutageEvent` rows, joined to `messages` via `source_id`.

### 2.3 External services

- **Embeddings:** Cohere `embed-multilingual-v3.0` (1024-dim; the corpus mixes EN/DE/NO/DK).
- **LLM:** Groq (`llama-3.3-70b-versatile`) primary, Google Gemini (`gemini-2.5-flash`, `google-genai`
  SDK) fallback on rate-limit, with an in-process response cache.
- **Deployment:** Render (web service) running `uvicorn app:app`; GitHub Actions for CI.

---

## 3. Component design

### 3.1 Ingestion (E1)

**U1.1 — ENTSO-E client.** Fetches market series and generation-unit outages per zone, throttled below
the 400 req/min limit with exponential-backoff retries, and upserts idempotently into `market_data`
and `entsoe_outages`. The same client is reused by the future agent tool (U7.1).

**U1.2 — Outage message ingestion.** Builds the `messages` corpus as a **union** of two sources:
(a) ENTSO-E structured outages rendered as text messages (the only source for DE-LU, which has no
public UMM RSS), and (b) configured UMM feeds — Nord Pool per-area RSS (fixed-zone, NO2/DK1) and the
German IIP Atom feed (content-zone, REMIT XML). Feeds are fetched with explicit timeouts and retries;
a failed feed is skipped, not fatal. `remit.py` parses the REMIT UMM Electricity Schema V3, extracting
asset, capacity, fuel, window, bidding zone, and the narrative *reason* text, and skips dismissed/
withdrawn messages.

### 3.2 Extraction (E2)

**U2.1 — Structured event extraction.** Two paths, by source type:

- **Structured ENTSO-E outages  mapped directly to `OutageEvent`, no LLM.** The data is already
  structured (asset, `nominal_power`, `plant_type`, start/end), so an LLM call would only add cost and
  hallucination risk. Direct mapping is more accurate and free.
- **Free-text messages (UMM/news)  LLM extraction.** The LLM fills only the genuinely
  natural-language fields; zone, source URL, and `source_id` are filled deterministically from the row.
  Output is validated with Pydantic; failures are logged, never fatal to the batch.

### 3.3 Indexing (E3)

**U3.1 — Chunking + embeddings.** Deterministic char-based chunking with overlap; Cohere embeddings
batched (≤96/call) with 60-second backoff on rate-limit. Stored in `chunks` with an HNSW
`vector_cosine_ops` index.

**U3.2 — Structured event store.** `events` table, with `source_id` joining each event back to its
`messages` row — the linkage that makes citations and retrieval-dedup precise.

**U3.3 — Hybrid retrieval (vector-first).** Detects any zone named in the question and filters to it;
runs cosine vector search over `chunks` (HNSW); attaches each hit's structured event by `message_id`;
dedups by asset, keeping the highest-scoring window per unit. Ranked/aggregate questions
("biggest outage") are deliberately *not* handled here — they belong to the structured agent tool
(U7.1), which can `ORDER BY capacity`.

### 3.4 Generation (E4)

**U4.1 — Cited answers.** Retrieved items are formatted into a numbered context; the LLM is instructed
to answer **only** from those sources and cite inline with `[n]`; citations are mapped back to source
URLs / descriptors. Structured outages cite as "(ENTSO-E structured outage, <zone>)"; UMM messages
cite their live source URL.

**U4.2 — Guardrails.** Out-of-corpus questions are refused **before** an LLM call (empty retrieval, or
top relevance below a tunable threshold); output length is capped; every answer is instructed to cite.
A `refused` flag is returned for the API.

### 3.5 App & deployment (E5/E6)

**U5.1 — FastAPI app.** `GET /` serves a minimal HTML chat page (shareable URL); `POST /chat` returns
JSON `{answer, citations, snippets, refused}` (the contract for a future React frontend); `GET /health`
returns liveness JSON without touching the DB.

**U6.1 — Render deployment.** `uvicorn app:app`; secrets via environment variables. Because Neon is a
persistent store, the data and vector index survive restarts — the original "rebuild index on boot"
constraint (written for an ephemeral local store) does not apply.

**U6.2 — CI.** GitHub Actions installs dependencies and runs the test suite on push/PR, gating merges.

---

## 4. Key design decisions (decision log)

| # | Decision | Rationale |
|---|----------|-----------|
| D2 | Zones DE-LU, DK1, NO2 | DE-LU for outage/news richness; DK1 for high wind share + Nordic coupling; NO2 for domain fluency. |
| D4 | Raw third-party text loaded at runtime; only derived data/embeddings stored in the repo | Respects data licensing; the repo holds no redistributable raw text. |
| — | Neon Postgres + pgvector as a single store | Avoids dual vector+relational complexity; per-query auto-wake suits the free tier; retired the "rebuild index on boot" constraint. |
| — | Outage dedup on a stable natural key (`zone\|unit\|start\|end`), not a content hash | Content hashing over volatile `mrid`/`revision` fields caused every revision to create a new row; the natural key collapses revisions to one outage. Cancelled/withdrawn disclosures are dropped; latest revision wins. |
| — | Structured vs free-text event split | ENTSO-E outages are already structured  map directly (accurate, zero LLM cost); reserve the LLM for genuinely unstructured UMM/news text. |
| — | Incremental indexing | `run_index` processes only messages not already chunked/embedded, preventing repeated full-corpus reprocessing from exhausting Cohere/Groq free-tier quotas. |
| — | Vector-first retrieval + per-asset dedup | Semantic relevance leads; events attach to their chunks; repeated windows of one unit collapse. Ranked/aggregate queries routed to the U7.1 structured tool. |
| — | Guardrail refuses below a relevance threshold before the LLM call | Prevents hallucinated answers to out-of-corpus questions and saves tokens. |
| — | Directional price prediction ruled out | No defensible edge with public-only data; the day-ahead price already embeds available fundamentals. |
| — | Lexical/keyword retrieval deferred | Dense retrieval is weak on bare proper nouns / unit codes; exact-name lookups are served more precisely by the U7.1 structured tool (`events.asset ILIKE`). |
| — | IIP REMIT feed treated as incremental, not load-bearing | Its unique value is narrative *reason* text; DE-LU structured coverage already comes from ENTSO-E. Parser built; a zone-filtered URL is the remaining operational step. |

---

## 5. Scope (Sprint 1) and cut-lines

Sprint 1 scope was deliberately narrow — a thin, live, end-to-end slice. Protected above all:
**deployed + tested**. Delivered ahead of scope: all three zones (not DE-LU only) and a REMIT-XML
parser. Deferred by design: news ingestion, evaluation gold set, the agent tool, lexical retrieval.

---

## 6. Testing strategy

**Principle.** Pure, deterministic logic is unit-tested offline (no network, no DB); integration is
verified by running each user story against live Neon + APIs and confirming results via SQL before the
story is closed. CI gates merges on the offline suite.

**Offline unit tests (run in CI):**

- `test_outages` / `test_outages_dedup` — normalisation helpers; natural-key dedup; cancelled-message filtering.
- `test_extraction` — prompt building, JSON parsing/fence-stripping, field merge, failure logging; structured-mapping field builder.
- `test_index` — chunking (overlap, edges), pgvector formatting, deterministic ids, event-row mapping.
- `test_retrieval` — zone detection (incl. substring false-match guard), per-asset dedup, event attach.
- `test_generation` — context formatting, citation extraction, guardrail refusal (empty + low-relevance), length cap, LLM cache.
- `test_app` — `/health`, HTML served at `/`, `/chat` response shaping.
- `test_remit` — REMIT UMM XML parsing against a real sample message; dismissed-message skip.

**Live verification (per story, manual):** scripts run from the repo root against Neon; results
confirmed in the Neon SQL editor (row counts, zone breakdowns) and via the smoke runners
(`run_index`, `run_retrieval`, `run_answer`) and the deployed `/chat` endpoint.

**CI:** GitHub Actions installs dependencies and runs `pytest`; a red suite blocks merge. Branch
protection requiring the check is the remaining toggle to complete the gate.

---

## 7. Known limitations & roadmap

**Limitations (Sprint 1):**

- Dense retrieval is weak on bare proper-noun queries (e.g. "Boxberg"); mitigated later by the U7.1 structured tool.
- ENTSO-E names both Boxberg blocks "KW Boxberg", so asset-name dedup collapses distinct units; `production_resource_id` distinguishes them if unit-level granularity is wanted.
- The IIP feed does not currently serve DE-LU messages in its rolling window; a zone-filtered URL is the operational fix.
- `MIN_RELEVANCE` (refusal threshold) is an initial value pending calibration against the eval gold set (U8).
- One event per message (multi-unit messages deferred).
- Free-tier cold starts (Render spins down; Neon scales to zero) — the first request after idle is slow.

**Roadmap (Sprint 2/3):** news ingestion (U1.3); evaluation gold set + retrieval/answer metrics (U8);
the tool-calling agent for live ENTSO-E figures and structured lookups (U7.1); optional lexical
retrieval; Render Starter for an always-on employer-facing URL; CD on merge; finalised design document
and recorded presentation.