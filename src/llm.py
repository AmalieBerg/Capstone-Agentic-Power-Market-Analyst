"""Shared LLM client (U2.1 + U4.1). Groq primary, Gemini fallback on 429, with
an in-process response cache (D10).

Gemini uses the current google-genai SDK (from google import genai); the legacy
google.generativeai package is retired. The cache keys on model+params+prompt,
so identical questions (same retrieved context) don't re-hit the API. It is
in-process (resets per run/worker); a persistent Neon-backed cache is a possible
later upgrade.
"""
from __future__ import annotations

import hashlib
import logging

import config

logger = logging.getLogger(__name__)

GROQ_MODEL = getattr(config, "GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_MODEL = getattr(config, "GEMINI_MODEL", "gemini-2.5-flash")

_CACHE: dict[str, str] = {}


class _RateLimited(Exception):
    """Internal signal: Groq returned 429 (per-minute or daily)."""


def _cache_key(prompt: str, temperature: float, max_tokens: int) -> str:
    return hashlib.sha1(
        f"{GROQ_MODEL}|{temperature}|{max_tokens}|{prompt}".encode("utf-8")
    ).hexdigest()


def clear_cache() -> None:
    _CACHE.clear()


def complete(prompt: str, *, temperature: float = 0.0, max_tokens: int = 1024,
             use_cache: bool = True) -> str:
    """Text completion for one prompt. Cache -> Groq -> Gemini (on 429)."""
    key = _cache_key(prompt, temperature, max_tokens)
    if use_cache and key in _CACHE:
        logger.debug("llm cache hit")
        return _CACHE[key]
    try:
        out = _groq(prompt, temperature=temperature, max_tokens=max_tokens)
    except _RateLimited:
        logger.warning("Groq rate-limited (429); falling back to Gemini")
        out = _gemini(prompt, temperature=temperature, max_tokens=max_tokens)
    if use_cache:
        _CACHE[key] = out
    return out


def _groq(prompt: str, *, temperature: float, max_tokens: int) -> str:
    from groq import Groq, RateLimitError

    client = Groq(api_key=config.require("GROQ_API_KEY"))
    try:
        resp = client.chat.completions.create(
            model=GROQ_MODEL, temperature=temperature, max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
    except RateLimitError as exc:
        raise _RateLimited() from exc
    return resp.choices[0].message.content or ""


def _gemini(prompt: str, *, temperature: float, max_tokens: int) -> str:
    from google import genai

    client = genai.Client(api_key=config.require("GEMINI_API_KEY"))
    resp = client.models.generate_content(
        model=GEMINI_MODEL, contents=prompt,
        config={"temperature": temperature, "max_output_tokens": max_tokens},
    )
    return resp.text or ""