# Sprint 2 — Process Note

**Author:** Amalie Berg · MSSE Capstone (solo) · Scrum evidence for Sprint 2

---

## 1. Sprint goal

Extend the Sprint-1 vertical slice from a three-zone outage assistant toward a **broader, evaluated,
pan-European-ready** system. Three themes: **breadth** (real free-text for all three zones, plus news),
**evaluation** (a reproducible gold set and metrics), and a **pan-European architectural pivot** so the
three-zone scope becomes a starting point rather than a hard boundary.

As a solo project, "scrum" here means a disciplined personal cadence: a unit-based backlog in Trello
(U-numbered cards with user stories and acceptance criteria), a single working increment per session,
and an explicit decision log rather than ceremony for its own sake.

---

## 2. Planned backlog (entering the sprint)

| Card | Story | Priority |
|------|-------|----------|
| U1.3 | News inlet (Google News, Guardian, Clean Energy Wire) | Should |
| U2.2 | Tag news to zones/assets; link to events | Should |
| U1.4 | Frozen evaluation snapshot | Must |
| U8.1 | Gold set (15–30 Q&A + supporting passages) | Must |
| U8.2 | Metrics: groundedness, citation accuracy, latency | Must |
| U9.2 | Expand design document | Must |
| U9.3 | Broaden test suite | Must |
| U9.6 | Sprint-2 process note | Must |

Carried in from Sprint 1 and closed early in Sprint 2: **U6.1** (Render deploy), **U6.2** (CI green),
**U9.2** design-doc baseline.

---

## 3. What was delivered

All planned cards were delivered, plus unplanned work that emerged from testing (§4).

- **Breadth (unplanned, high-value).** A diagnostic on the German disclosure feed revealed the
  inside-information.de IIP feed was returning an empty shell; DE-LU had *zero* free-text (its
  `messages` count exactly equalled its structured-outage count). Root-caused and fixed by adding
  DE-LU to the already-working Nord Pool UMM feed. All three zones now carry genuine free-text.
- **U1.3 — News inlet.** Google News RSS (query-scoped), Guardian API (full text), Clean Energy Wire
  RSS, routed through the shared feed path, with news excluded from outage extraction.
- **U2.2 — News zone-tagging.** Content-based tagging into a `news_zone_tags` junction table.
  Asset-level linking was evaluated and **descoped** on evidence (0 matches — REMIT asset codes do not
  appear in journalistic text); documented as a design decision rather than silently dropped.
- **Data-quality hardening (unplanned).** News ingestion admitted sport/politics/macro articles
  matching incidentally on "power"/"gas"; a three-layer relevance filter was built and tuned against
  observed contamination.
- **Pan-European pivot.** Zone moved from an ingestion-time gate to an **optional query-time filter**;
  a single `GEO_TERMS` registry now serves both tagging and retrieval; retrieval consults the junction
  table so cross-zonal content surfaces for every zone it concerns.
- **U1.4 — Frozen snapshot.** Versioned JSONL export/restore with a `CORPUS_FROZEN` guard.
- **U8.1 / U8.2 — Gold set + metrics.** A 30-question stratified gold set and an evaluation harness
  scoring refusal correctness, citation recall, fact match, LLM-judged groundedness, and latency.
- **Guardrail recalibration (unplanned).** Evaluation exposed that the Sprint-1 refusal threshold was
  mis-set; recalibration showed a single cosine threshold could not separate in- from out-of-corpus
  questions, so the guardrail was rebuilt as a banded gate with an LLM relevance check.
- **U9.2 / U9.3 / U9.6 — Docs & tests.** Design doc expanded; test suite broadened with three new
  offline modules; this process note.

---

## 4. Adaptations and mid-sprint decisions

Sprint 2 was shaped more by findings than by the original plan — which is the point of running an
evaluation. Key adaptations:

1. **DE-LU free-text gap (found, not planned).** Chasing why DE-LU looked structurally different from
   DK1/NO2 surfaced a dead feed. The fix reused proven infrastructure rather than debugging the dead
   feed — a deliberate choice to avoid a rabbit hole.
2. **Pan-European pivot (scope-shaping).** A question about whether cross-zonal information reaches
   both zones exposed that ingestion-time geography filtering hard-coded the three-zone scope against
   the project's stated pan-European goal. The architecture was pivoted to query-time filtering. This
   was the sprint's most significant design change and touched retrieval, tagging, and config.
3. **Asset-linking descoped on evidence.** Rather than build a feature the data could not support, a
   0-match query justified descoping asset-level news->event linking to zone-level association.
4. **Guardrail rebuilt from evaluation data.** The eval's refusal metric drove a genuine redesign: the
   threshold oscillated under naive tuning, a per-question diagnostic revealed overlapping score
   distributions, and the banded gate resolved it. Calibration was made data-driven (a diagnostic
   script) rather than guess-and-check.
5. **Citation scoring corrected.** Initial exact-message-ID recall understated retrieval quality
   because the corpus holds many revised disclosures per asset; the scorer was extended to credit
   same-asset matches, with both figures reported honestly.

---

## 5. Engineering-practice evidence

- **Version control & CI.** Work landed in focused commits with descriptive messages; GitHub Actions
  ran the test suite on every push and caught a stale test after the guardrail change (the assertion
  was updated to match the new, intended behaviour).
- **Diagnostics before changes.** Recurring pattern: write a small diagnostic (feed prober, band
  diagnostic, threshold calibrator, dry-run gate) to get data *before* changing code, rather than
  tuning blind. This prevented several wasted re-ingest/re-eval cycles.
- **Reproducibility.** The corpus was frozen and the evaluation runs against it, so metrics are
  reproducible from the repo without external state.
- **Honest limitations.** Descoped features, imperfect refusal calibration, thin DK1 news, and
  lexical-filter limits are documented rather than hidden.

---

## 6. Constraints encountered

Free-tier limits were an active force on both design and process:

- **LLM daily quotas** (Groq tokens-per-day, Gemini free-tier requests) were exhausted during
  guardrail tuning + a groundedness-judged eval run, blocking further runs until the daily reset.
  This motivated a **graceful-degradation** path (both providers down -> clean message, not a 500) and a
  lighter eval mode. It is a genuine limitation, honestly noted.
- **Cohere trial token cap** shaped incremental (new-only) indexing.
- **Render scale-to-zero / Neon auto-wake** produce slow first requests after idle.

---

## 7. Definition of done — status

| Item | Done |
|------|------|
| All planned Sprint-2 cards delivered | Done |
| New/changed code covered by offline tests | Done (3 new test modules) |
| CI green on the offline suite | Done |
| System evaluated against a reproducible gold set | Done (30 questions, frozen corpus) |
| Design document reflects Sprint-2 architecture | Done (U9.2) |
| Corpus frozen for reproducibility | Done (U1.4) |
| Branch protection enforcing CI before merge | Deferred deferred to Sprint 3 |

---

## 8. Carried into Sprint 3

- **U7.1** — the tool-calling agent for live ENTSO-E figures and structured (`ORDER BY capacity`,
  asset-name) lookups — the work that makes the system defensibly "agentic".
- Optional lexical retrieval for exact proper-noun/asset queries.
- CD on merge and branch protection.
- The recorded presentation and final submission.
