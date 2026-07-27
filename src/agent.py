"""Agent layer (U7.1).

Tool-calling agent that reasons across retrieval (answer.py's guardrailed
pipeline) + live ENTSO-E numbers (entsoe_client.py). Reuses answer.py's
guardrail bands, context formatting, and citation extraction directly --
this is a drop-in replacement for the LLM-completion step in answer.generate,
not a parallel pipeline.

Clean cut-line: this module imports from src.generation.answer and
src.index.retrieval; neither imports from here. If this module fails, /chat
falls back to answer.answer_question() untouched.

Live-data note: get_entsoe_numeric calls EntsoeClient directly (live), NOT
db.get_latest -- see prior discussion on CORPUS_FROZEN.
"""
from __future__ import annotations

import logging
from datetime import timedelta

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

import config
from src.generation import answer as answer_mod
from src.index import retrieval
from src.ingestion.entsoe_client import (
    EntsoeClient,
    SERIES_PRICE,
    SERIES_LOAD_FC,
    SERIES_WIND_SOLAR_FC,
    SERIES_GENERATION,
)

log = logging.getLogger(__name__)

_KNOWN_SERIES = {SERIES_PRICE, SERIES_LOAD_FC, SERIES_WIND_SOLAR_FC, SERIES_GENERATION}
MAX_HOPS = 3


@tool
def get_entsoe_numeric(zones: list[str], series: str, hours_back: int = 6) -> dict:
    """Fetch live ENTSO-E numeric market data for one or more bidding zones.

    Args:
        zones: bidding zone codes, e.g. ["DE-LU"], ["DK1", "NO2"].
        series: one of "day_ahead_price", "load_forecast",
            "wind_solar_forecast", "generation".
        hours_back: how far back to look for the most recent point (default 6h;
            ENTSO-E publication lag means "now" is often empty).

    Returns:
        {zone: {series_name: {"ts": iso timestamp, "value": float}}}
    """
    if series not in _KNOWN_SERIES:
        return {"error": f"unknown series '{series}'. Expected one of {sorted(_KNOWN_SERIES)}"}

    end = pd.Timestamp.now(tz="Europe/Brussels")
    start = end - timedelta(hours=hours_back)

    result: dict = {}
    for zone in zones:
        if zone not in config.ZONES:
            result[zone] = {"error": f"unknown zone '{zone}'"}
            continue
        try:
            rows = EntsoeClient().fetch_market_data(zone, start, end)
        except Exception as exc:
            log.warning("live ENTSO-E fetch failed for %s: %s", zone, exc)
            result[zone] = {"error": str(exc)}
            continue

        latest: dict[str, tuple] = {}
        for _, series_name, ts, value in rows:
            if series_name == series or series_name.startswith(series + "."):
                if series_name not in latest or ts > latest[series_name][0]:
                    latest[series_name] = (ts, value)

        result[zone] = {
            name: {"ts": ts.isoformat(), "value": value}
            for name, (ts, value) in latest.items()
        } or {"error": f"no recent '{series}' data for {zone}"}

    return result


TOOLS = [get_entsoe_numeric]


def _build_llm():
    primary = ChatGroq(model=config.LLM_PRIMARY["model"], temperature=0).bind_tools(TOOLS)
    fallback = ChatGoogleGenerativeAI(model=config.LLM_FALLBACK["model"], temperature=0)
    return primary.with_fallbacks([fallback])


_llm = None
def _get_llm():
    global _llm
    if _llm is None:
        _llm = _build_llm()
    return _llm


def _build_agent_prompt(question: str, context_text: str) -> str:
    return (
        "You are a power-market analyst assistant. Answer using ONLY the "
        "numbered sources below, citing every claim inline like [1] or [2]. "
        "The sources reflect a fixed historical window (mid-June 2026) -- if "
        "you need a CURRENT live figure (price, generation, load, or wind/"
        "solar forecast) not covered by the sources, call get_entsoe_numeric. "
        "When you use a live tool result, label it explicitly as current/live "
        "with its timestamp, separate from the dated source citations, so the "
        "two time frames are never conflated. Answer concisely, at most ~150 "
        "words. If neither sources nor tools answer the question, say so.\n\n"
        f"Sources:\n{context_text}\n\n"
        f"Question: {question}\n\n"
        "Answer (cite sources as [n]; label live tool data explicitly):"
    )

def passes_agent_relevance_gate(question: str, items: list[dict], complete) -> bool:
    """Agent-aware scope gate: in-scope if about power/outages/energy in
    DE-LU/DK1/NO2 -- via text corpus OR the live numeric tool, even with a
    thin/empty text match. Still refuses when the question's real subject is
    outside the covered zones, even if a covered zone is mentioned
    incidentally (e.g. one side of a cross-border interconnector)."""
    ctx = "\n".join(
        f"[{i+1}] {(it.get('content') or it.get('title') or '')[:300]}"
        for i, it in enumerate(items[:5])
    )
    prompt = (
        "You filter questions for a power-market assistant covering ONLY the "
        "DE-LU, DK1, and NO2 bidding zones (Germany/Luxembourg, West Denmark, "
        "South Norway) for mid-2026, with access to historical outage/news "
        "sources AND a live tool for current price/generation/load/wind-solar "
        "figures in those zones. Answer NO if the question's main subject is a "
        "different region not in this list (e.g. Poland, Texas, Japan) -- even "
        "if a covered zone is mentioned incidentally, such as one side of a "
        "cross-border interconnector whose primary focus is outside scope. "
        "Answer NO for a different commodity or time period. Otherwise, if the "
        "question is about power/outages/energy/prices in the covered zones, "
        "answer YES even if no source below covers it -- the live tool may "
        "still answer it.\n\n"
        f"SOURCES:\n{ctx}\n\nQUESTION: {question}\n\nIn scope (YES/NO):"
    )
    try:
        return not (complete(prompt) or "").strip().upper().startswith("NO")
    except Exception:
        return True


def run_agent(question: str, conn, k: int = 6, zone: str | None = None) -> dict:
    items = retrieval.retrieve(conn, question, k=k, zone=zone)

    resolved = zone or next(iter(retrieval.detect_zones(question, list(config.ZONES))), None)
    zone_recognized = resolved in config.ZONES if resolved else False

    if zone_recognized:
        top = answer_mod.top_score(items)
        if top >= answer_mod.RELEVANCE_HIGH:
            pass  # strong match -- answer directly, no gate call (fast path, matches original design)
        elif not passes_agent_relevance_gate(question, items, complete=answer_mod.llm.complete):
            return {"answer": answer_mod.REFUSAL, "sources": [], "citations": [], "refused": True}
        # else: weak/empty match but zone recognized and gate passed -- the
        # live tool may still answer even though text retrieval is thin.
    else:
        top = answer_mod.top_score(items)
        if not items or top < answer_mod.RELEVANCE_LOW:
            return {"answer": answer_mod.REFUSAL, "sources": [], "citations": [], "refused": True}
        if top < answer_mod.RELEVANCE_HIGH and not answer_mod.passes_relevance_gate(question, items, complete=answer_mod.llm.complete):
            return {"answer": answer_mod.REFUSAL, "sources": [], "citations": [], "refused": True}

    context_text, sources = answer_mod.format_context(items)
    prompt = _build_agent_prompt(question, context_text)

    messages = [SystemMessage(content="You are a precise power-market analyst."), HumanMessage(content=prompt)]
    llm = _get_llm()
    used_tool = False
    last_tool_result = None
    answer_text = None

    for _ in range(MAX_HOPS):
        response = llm.invoke(messages)
        messages.append(response)
        if not getattr(response, "tool_calls", None):
            answer_text = response.content
            break
        used_tool = True
        for call in response.tool_calls:
            if call["name"] == "get_entsoe_numeric":
                result = get_entsoe_numeric.invoke(call["args"])
                last_tool_result = result
                messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

    if answer_text is None:
        log.warning("agent hit MAX_HOPS=%d without a final answer: %s", MAX_HOPS, question)
        answer_text = "I gathered live data but couldn't complete the analysis in time. Please try again."

    if len(answer_text) > answer_mod.MAX_ANSWER_CHARS:
        answer_text = answer_text[:answer_mod.MAX_ANSWER_CHARS].rstrip() + "…"

    return {
        "answer": answer_text,
        "sources": sources,
        "citations": answer_mod.extract_citations(answer_text, sources),
        "refused": False,
        "used_tool": used_tool,  # not surfaced by shape_response; eval harness can read it directly
        "tool_result": last_tool_result,
    }