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
    primary = ChatGroq(model=config.LLM_PRIMARY["model"]).bind_tools(TOOLS)
    fallback = ChatGoogleGenerativeAI(model=config.LLM_FALLBACK["model"])
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

def run_agent(question: str, conn, k: int = 6, zone: str | None = None) -> dict:
    items = retrieval.retrieve(conn, question, k=k, zone=zone)

    resolved = zone or next(iter(retrieval.detect_zones(question, list(config.ZONES))), None)
    zone_recognized = resolved in config.ZONES if resolved else False

    if not zone_recognized:
        # No zone signal anywhere -- fall back to the original corpus-relevance
        # guardrail (this is what correctly refuses Texas).
        top = answer_mod.top_score(items)
        if not items or top < answer_mod.RELEVANCE_LOW:
            return {"answer": answer_mod.REFUSAL, "sources": [], "citations": [], "refused": True}
        if top < answer_mod.RELEVANCE_HIGH and not answer_mod.passes_relevance_gate(question, items, complete=answer_mod.llm.complete):
            return {"answer": answer_mod.REFUSAL, "sources": [], "citations": [], "refused": True}
    # else: a recognized zone makes the question in-scope even with a thin/empty
    # text corpus match -- e.g. a pure live-price question. Let the LLM decide
    # whether to answer from retrieved context, call the tool, or both.

    context_text, sources = answer_mod.format_context(items)
    prompt = _build_agent_prompt(question, context_text)

    messages = [SystemMessage(content="You are a precise power-market analyst."), HumanMessage(content=prompt)]
    llm = _get_llm()
    used_tool = False
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
    }