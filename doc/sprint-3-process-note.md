# Sprint 3 — Process Note

**Author:** Amalie Berg · MSSE Capstone (solo) · Scrum evidence for Sprint 3

---

## 1. Sprint goal

Elevate the Sprint-2 evaluated RAG system into a defensibly **agentic** analyst, and bring the
project to submission-ready state. Three themes: the **agent layer** (tool-calling over live
ENTSO-E data, reasoning across it and the frozen text corpus), **hardening** (latency, guardrails,
cold-start UX), and **finalization** (documentation, repo hygiene, evaluation of the new capability).

As in prior sprints, "scrum" here means a disciplined personal cadence: a unit-based backlog in
Trello (U-numbered cards), one working increment per session, and an explicit decision log rather
than ceremony for its own sake.

---

## 2. Planned backlog (entering the sprint)

| Card | Story | Priority |
|------|-------|----------|
| U7.1 | Agent layer: tool-calling over live ENTSO-E numeric data | Should |
| U8.3 | Ablations: retrieval k / chunk size / prompt variants | Could |
| U7.2 | Event-driven news enrichment | Could |
| U6.3 | Scheduled ingestion (cron) + auto-deploy on merge | Should |
| U6.4 | Cold-start decision (paid tier vs. waking-up UX) | Should |
| U10.1/U10.2 | Landing state, example questions, citation display | Should |
| U10.3 | Visual polish: layout, zone selector, loading feedback | Could |
| U9.2 | Design & testing doc, Sprint 3 addition | Must |
| U9.4 | `ai-tooling.md` | Must |
| U9.5 | Final recorded presentation | Must |
| U9.6 | Sprint-3 process note | Must |

MIN_RELEVANCE calibration was also carried in from Sprint 2 as an open item, flagged "still open"
on the board at sprint start.

---

## 3. What was delivered

Most planned cards were delivered; several were closed on evidence rather than built, and
significant unplanned work emerged from testing the new agent layer (§4).

- **U7.1 — Agent layer.** Built `src/agent.py`: a LangChain-based tool-calling agent
  (`ChatGroq` + `ChatGoogleGenerativeAI`, `bind_tools()`, `.with_fallbacks()`) orchestrated by a
  hand-wired tool-dispatch loop, not `AgentExecutor`/LangGraph — a deliberate choice given the
  single-tool, 1-2 hop scope (rationale documented in `doc/design-and-testing-sprint-3.md`).
  The tool (`get_entsoe_numeric`) reuses the U1.1 `EntsoeClient` directly, live and in-memory,
  bypassing `ingest()`/`CORPUS_FROZEN` entirely — resolving the tension between a frozen,
  reproducible eval corpus and a live-data agent capability.
- **Groq model re-pin.** `llama-3.3-70b-versatile` was confirmed deprecated (shutdown 08/16/26);
  re-pinned to `openai/gpt-oss-120b` before the deployed URL was put at risk.
- **Guardrail redesign for the agent path.** The Sprint-2 relevance bands assumed "in scope" meant
  "text corpus has something relevant" — false for a pure live-numeric question. Extended with a
  tool-aware gate, after two false starts (§4).
- **Latency diagnosis, resolved.** The open hypothesis from Sprint 2 (Render cold start vs.
  `tenacity` retry storms) was resolved: root cause was `tenacity` retrying
  `NoMatchingDataError` (a "no data" case, not a transient failure) up to 3 times with exponential
  backoff, across 4 series calls per zone. Fixed with `retry_if_not_exception_type`. Measured
  53-79s before the fix, ~8.5s after, on the deployed URL, warm.
- **U6.3 — closed on evidence, not built.** Scheduled ingestion was found to conflict directly
  with `CORPUS_FROZEN` (a cron calling `ingest()` would fail every run) and to be unnecessary once
  the live-tool path existed. Auto-deploy on merge was confirmed already working via Render's
  existing push-triggered deploy. No new infrastructure required.
- **U6.4 — cold-start decision.** Measured Render free-tier cold start directly: ~32.7s on
  `/health` alone (warm: ~90-150ms). Decided against the paid Starter tier, since the project's own
  original constraint (C5: "warm the URL before any recorded demo") already covers the one
  interaction that matters most for grading. Implemented a delayed "waking up" message in the chat
  UI instead (fires after 4s, so normal warm latency isn't misrepresented as a cold start).
- **U10.1/U10.2 — landing state and citation display.** Added clickable example-question chips,
  a live/corpus/refused status badge reading `used_tool`/`refused` directly from the `/chat`
  contract, and markdown-aware answer rendering (bold formatting, no raw bracket artifacts).
- **Eval harness extended for the agent path.** Four `live_numeric` gold questions added to the
  existing 30-question set. Since live values aren't reproducible, two new metrics replace
  `fact_match` for this category: `tool_selection_correct` (compared across all 34 questions, not
  just the new 4 — catches both under- and over-firing of the tool) and `plausibility_pass`
  (range + freshness check against the structured tool result, not parsed prose).
- **MIN_RELEVANCE — closed on evidence.** Confirmed the Sprint-2 three-band redesign (which
  superseded the original single `0.30` threshold) still holds against the expanded 34-question
  set with no regression (`refusal_correct: 0.94`). No recalibration needed; Trello card updated
  to reflect what had already actually happened.
- **U8.3, U7.2, U10.3 — deferred, not dropped.** All three are Could-priority and gated on "if
  ahead"; the sprint was recovering from a substantial debugging arc rather than ahead. Each has a
  one-line note on its Trello card describing what it depends on and that it can be picked up
  later using existing infrastructure (the eval harness for U8.3; U2.2 + U7.1 for U7.2; U10.3's
  loading-feedback and layout pieces were substantially covered by U6.4/U10.1 already).
- **Repo hygiene pass.** A full-repo coherence review (structure, README, design doc) surfaced a
  stale README (still describing Sprint 2 of 4, no LangChain, agent framed as future work) and a
  dead duplicate design document (`design-and-testing-sprint-1.md`, superseded by the combined
  `-sprint-1-and-2.md` but never removed). Both corrected.

---

## 4. Adaptations and mid-sprint decisions

Sprint 3's agent layer was the most iteratively-debugged piece of work in the project to date —
worth documenting honestly, including the false starts, since the debugging process is itself
evidence of engineering practice.

1. **Guardrail bypass, first attempt — a real regression, caught by eval.** The first fix for
   "pure live-numeric questions get wrongly refused" bypassed the relevance guardrail entirely
   whenever a zone was recognized in the question text. This over-corrected: a question naming a
   covered zone only incidentally (e.g. "the Polish-German interconnector," where "German" alone
   triggered the bypass) slipped past refusal entirely. Caught via the eval harness — refusal
   correctness on an otherwise-passing category dropped on a single question, isolated by rerunning
   the gold set and diffing which item changed.
2. **Guardrail bypass, second attempt — also a regression, same detection method.** Applying the
   new gate to *every* zone-recognized question (rather than only the weak/ambiguous-match band)
   roughly doubled LLM calls per request, degraded citation and fact-match scores across
   freetext/cross-zonal/news categories, and pushed p95 latency to ~26s. Resolved by restoring the
   original Sprint-2 band structure exactly, substituting the tool-aware gate only in the
   zone-recognized weak-match case.
3. **Determinism was assumed, not verified, and cost real time.** Flaky pass/fail results on
   identical repeated questions (a tool-selection check passing once, failing the next run with no
   code change) were traced to the agent's LangChain model instances having no `temperature`
   argument set, defaulting to provider-level non-zero sampling — while the existing `llm.complete`
   path (used by the original guardrail gate) was already pinned to 0. Fixed by explicitly setting
   `temperature=0` on both agent-path models.
4. **A tabs/spaces mismatch produced a misleading error late in the debugging arc.** An
   `IndentationError` on a line that looked syntactically correct in every paste was eventually
   isolated to invisible mixed tabs/spaces from a prior edit; resolved by normalizing the file
   (`expandtabs`) rather than hand-hunting the exact character.
5. **A stale `uvicorn --reload` process produced a false "code is broken" signal.** Local-import
   changes inside a function body (`from src.agent import run_agent`, called inside the `/chat`
   handler rather than at module top) weren't reliably picked up by `--reload`'s file watcher.
   The system appeared to have a live bug (`used_tool: False` over HTTP, `True` via direct function
   call) that was actually a stale process; resolved by a clean restart, and the practice of
   restarting rather than trusting `--reload` after function-local import edits was adopted going
   forward.
6. **Groq quota exhaustion produced a full-eval collapse that looked like a new bug.** A clean run
   showed every category degrade simultaneously (uniform latency spike, citations and refusals both
   wrong) — traced to the Gemini-fallback path activating under quota exhaustion, not a code
   regression. Distinguishing "the code is wrong" from "the environment is degraded" required
   checking the server log directly for the `429`/fallback line rather than continuing to iterate
   on the scoring logic.
7. **A prompt design choice (bracket-style live-data markers) was replaced once it proved fragile.**
   Asking the model to embed a machine-parseable `【live: ...】` marker in prose worked inconsistently
   across calls and rendered oddly in the UI. Replaced with plain-language phrasing plus a separate,
   already-built structural signal (the `used_tool`/`tool_result` fields) doing the job the bracket
   marker was trying to do — a case of removing a fragile solution once a more robust one already
   existed elsewhere in the system, rather than hardening the fragile one further.

---

## 5. Engineering-practice evidence

- **Diagnostics before changes, consistently.** Every suspected bug this sprint was isolated with
  a targeted probe (a 2-question direct-call script, `Select-String` greps against source, a
  `git log`/`git status` check on the frozen snapshot) before a fix was written, matching the
  established project pattern from Sprints 1-2.
- **Eval-driven regression detection.** Both guardrail-bypass errors (§4.1, §4.2) were caught by
  rerunning the existing 34-question gold set and comparing against the prior run, not by manual
  spot-checking — the harness built in Sprint 2 paid for itself directly in Sprint 3.
- **Distinguishing infrastructure failures from code failures.** Two incidents this sprint (stale
  reload process, quota exhaustion) initially presented as code bugs. Both were correctly
  re-diagnosed by checking the actual runtime environment (server logs, process state) rather than
  continuing to edit code against a misleading symptom.
- **Evidence-based backlog grooming.** MIN_RELEVANCE recalibration and U6.3 scheduled ingestion
  were both closed not by skipping them, but by checking whether the underlying need still existed
  and citing the evidence (a stale Trello card description, a superseded architecture) rather than
  silently dropping or blindly executing a stale plan.
- **Repo-level self-audit.** A full coherence pass against the actual repository content (not
  assumption) caught a stale README and a dead duplicate document before submission, following the
  same "verify, don't assume" discipline applied to code throughout the sprint.

---

## 6. Constraints encountered

- **Groq daily quota exhaustion**, mid-eval-run, produced misleading results across every category
  simultaneously; required waiting for the daily reset before a trustworthy eval run could be
  obtained. Documented rather than worked around with a partial/stale result.
- **Render free-tier cold start** (measured ~32.7s) is a genuine constraint on the deployed
  experience for a grader's first cold visit; addressed via UX (waking-up message) rather than
  cost, consistent with the project's original free-tier constraint framing (C5).
- **ENTSO-E publication lag** means a short live-data lookback window can legitimately return no
  data for some series; this is a data characteristic, not a bug, and the retry-storm fix
  specifically had to distinguish "no data exists" from "the request failed."

---

## 7. Definition of done — status

| Item | Done |
|------|------|
| Agent layer built, deployed, and tested end-to-end (live price / retrieval-only / refusal) | Done |
| Groq model re-pinned ahead of deprecation shutdown | Done |
| Tool-path latency diagnosed and fixed | Done (53-79s to ~8.5s) |
| Guardrails extended to the agent path without regressing existing behavior | Done (after two documented false starts) |
| Eval harness extended to score the agent path | Done (`tool_selection_correct`, `plausibility_pass`) |
| Clean, quota-unaffected eval run confirming the fix | Done |
| Cold-start behavior measured and a decision made | Done (free tier + waking-up UX) |
| Landing state and citation display improved | Done |
| README and design docs reflect actual Sprint-3 state | Done |
| `ai-tooling.md` (U9.4) | Not started — deferred to after this note |
| Final recorded presentation (U9.5) | Not started |

---

## 8. Deferred items (not carried to a future sprint — this is the final sprint)

- **U8.3** — ablations (retrieval k / chunk size / prompt variants). Deferred, not dropped: the
  eval harness (U8.2) already supports rerunning with varied parameters, so no new infrastructure
  is needed if time remains before submission.
- **U7.2** — event-driven news enrichment. Deferred, not dropped: depends only on already-completed
  work (U2.2, U7.1), so remains available if time allows.
- **U10.3 (partial)** — a dedicated zone-selector UI control. Loading feedback and general layout
  polish were substantially addressed via U6.4 and U10.1/U10.2; the selector itself was the one
  piece not built.

These are explicitly prioritized below `ai-tooling.md` and the final presentation, per the
project's own cut-line ordering.