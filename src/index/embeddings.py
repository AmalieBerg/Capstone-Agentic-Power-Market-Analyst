"""Cohere embeddings (D11). Trial key, model = config.EMBED_MODEL.

Use input_type = search_document for corpus chunks, search_query for questions.
Batches (Cohere caps at 96 texts/call) and retries on 429 — trial keys cap at
100k tokens/min and the per-minute window resets after 60s.
"""
from __future__ import annotations

import logging
import time

import config

logger = logging.getLogger(__name__)


def embed(texts: list[str], input_type: str, batch_size: int = 96, pause: float = 1.0) -> list[list[float]]:
    """Embed texts via Cohere. Returns one vector per input, in order."""
    out: list[list[float]] = []
    texts = list(texts)
    total = (len(texts) + batch_size - 1) // batch_size
    for n, i in enumerate(range(0, len(texts), batch_size), start=1):
        if total > 1:
            logger.info("embedding batch %d/%d", n, total)
        out.extend(_embed_batch(texts[i:i + batch_size], input_type))
        if i + batch_size < len(texts):
            time.sleep(pause)
    return out


def embed_documents(texts: list[str]) -> list[list[float]]:
    """Embed corpus chunks for storage (U3.1)."""
    return embed(texts, "search_document")


def embed_query(text: str) -> list[float]:
    """Embed a single user question for similarity search (U3.3)."""
    return embed([text], "search_query")[0]


def _embed_batch(texts: list[str], input_type: str) -> list[list[float]]:
    if not texts:
        return []
    import cohere
    from cohere.errors import TooManyRequestsError
    from tenacity import (
        retry, retry_if_exception_type, stop_after_attempt, wait_fixed,
    )

    co = cohere.ClientV2(config.require("COHERE_API_KEY"))

    def _log_wait(state):
        logger.warning("Cohere 429 (trial token limit); waiting 60s, attempt %d", state.attempt_number)

    @retry(
        retry=retry_if_exception_type(TooManyRequestsError),
        wait=wait_fixed(60),
        stop=stop_after_attempt(6),
        before_sleep=_log_wait,
        reraise=True,
    )
    def _call() -> list[list[float]]:
        resp = co.embed(
            texts=texts,
            model=config.EMBED_MODEL,
            input_type=input_type,
            embedding_types=["float"],
        )
        embs = resp.embeddings
        # ClientV2 with embedding_types=["float"] -> embeddings.float
        return list(getattr(embs, "float", embs))

    return _call()


def to_pgvector(vec: list[float]) -> str:
    """Format a vector as a pgvector literal: '[0.1,0.2,...]' (cast with ::vector)."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"
