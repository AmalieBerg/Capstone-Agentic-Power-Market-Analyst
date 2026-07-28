# AI Tooling — Disclosure and Reflection

**Author:** Amalie Berg · MSSE Capstone (solo)

This document addresses Learning Outcome 4 of the Capstone ("demonstrate the use of appropriate
AI tooling to support software development"). It is a specific, verifiable account of how AI was
used across all three sprints, not a general statement — claims here can be checked against the
repository's commit history and the design-and-testing document.

---

## 1. Tools used

**Claude (Anthropic)** was the AI tool used throughout the project, in a standard chat interface,
across every sprint from initial project scoping through final documentation. It was used for:

- Code generation and editing (Python: FastAPI, LangChain, psycopg, pandas, retry logic)
- Debugging: diagnosing tracebacks, designing diagnostic/probe scripts, interpreting eval output
- Architecture discussion: evaluating tradeoffs (e.g. orchestration framework vs. hand-wired agent
  loop; guardrail design) before code was written
- Documentation: drafting and revising the design-and-testing document, README, and process notes
  from source material I provided (real code, real test output, real decisions)

No other AI coding tool (e.g. GitHub Copilot) was used in a way that materially shaped this
codebase. Package selection, external APIs, and non-AI documentation were sourced directly from
official docs (ENTSO-E, entsoe-py, Groq, LangChain, Render), not AI-suggested without verification.

---

## 2. How AI was used — and its limits, in practice

AI-generated code and AI-proposed designs were treated as **drafts requiring verification**, not
finished work. The clearest evidence of this is the number of times AI output was found to be
wrong and had to be corrected — documented here specifically because a capstone reflection should
show engineering judgment, not just tool usage.

**Architectural pushback.** When building the Sprint-3 agent layer, Claude's initial recommendation
was against using an orchestration framework (LangChain), arguing the single-tool, 1-2 hop scope
didn't need one. I asked to revisit this decision explicitly rather than accept the recommendation,
weighing the course's own emphasis on named frameworks against the technical argument. The final
architecture — LangChain for `bind_tools()`/`.with_fallbacks()` specifically, but a hand-wired tool
loop rather than `AgentExecutor`/LangGraph — was a negotiated outcome, not one I simply accepted.

**Code that was wrong and had to be caught by testing, not inspection.** Several AI-authored
changes this sprint were plausible-looking but incorrect, and were only caught because I ran them
rather than trusting the code on read-through:

- A guardrail fix (bypassing the relevance check whenever a zone was named in a question) looked
  reasonable but was a real regression — a question about "the Polish-German interconnector"
  slipped past refusal because "German" alone triggered the bypass. This was caught by rerunning
  the existing eval gold set and noticing a single category score drop, not by reading the code.
- The fix for that regression was itself wrong a second time — applying the new check to every
  zone-recognized question instead of only weak/ambiguous matches, which roughly doubled LLM calls
  per request and degraded scores elsewhere. Caught the same way: rerunning the eval, not trusting
  the fix.
- AI-authored code referenced function signatures and module structures it hadn't actually seen
  (e.g. an assumed `retrieve()` signature, an invented `ChatResponse` pydantic model that didn't
  exist in the real codebase). These were caught by pasting the real source files back for
  comparison rather than letting the assumption stand.
- A literal import typo (`from entsoe-exceptions import ...`, invalid Python syntax) shipped in
  AI-generated code and was only caught by actually running the script and reading the traceback.

**AI overclaiming, caught by verification.** During a full-repository coherence review at the end
of Sprint 3, Claude flagged the frozen evaluation snapshot as critically missing from the repository
— a finding that, if true, would have broken reproducibility. Before acting on it, I checked
`git log` and `git status` directly against the actual files. The files were present and committed;
the "critical" finding was an artifact of the repo-export tool silently truncating large files, not
a real problem. This is included here specifically because it is an example of AI being **wrong in
a specific, checkable way**, and of verification (not trust) being what prevented an unnecessary
fix to something that wasn't broken.

**Corrected misunderstandings ran in both directions.** When I stated a Groq model deprecation
concern didn't apply because the model showed as `on_demand` in the console, Claude checked Groq's
actual deprecations page via live web search and corrected the misunderstanding: `on_demand` is a
billing-tier label, unrelated to deprecation status, and the model did in fact have a confirmed
shutdown date. The model was re-pinned as a direct result.

---

## 3. What stayed entirely my own judgment

AI proposed technical options; scope, priority, and product decisions were mine throughout:

- **Every backlog and sprint-scope decision** — what to build in each sprint, what to defer (U8.3
  ablations, U7.2 enrichment, the zone-selector control), and what to close on evidence rather than
  build (U6.3 scheduled ingestion, MIN_RELEVANCE recalibration) were my calls, made after AI
  presented the tradeoffs and evidence.
- **The architectural pivot** of zone from an ingestion-time boundary to a query-time filter
  (Sprint 2) and the decision to keep it that way through Sprint 3's agent design were product/
  architecture decisions I made and held to, explicitly instructing that they not be revisited
  without good reason.
- **Cost decisions** — e.g. staying on Render's free tier rather than paying for the Starter plan
  for cold-start elimination — were made by me after AI presented the measured tradeoff, not
  defaulted to by the AI.
- **What to disclose and how** in this document, and the decision to write it as a specific,
  checkable account rather than a general statement.

---

## 4. Verification practice

Consistent with the diagnostic-first working style documented throughout this project (small probe
scripts before code changes, `git status` checks before deploys, function-inventory checks after
large edits), AI-proposed changes were verified the same way as my own: run locally first, checked
against real output (test results, eval scores, live API responses), and only committed once
confirmed working. The eval harness (`run_eval.py`) in particular served as an objective check on
AI-proposed guardrail changes — both regressions described in §2 were caught by its output, not by
manual code review, which is direct evidence that automated testing infrastructure — not trust in
the AI tool — was the actual safeguard against incorrect changes reaching the deployed system.