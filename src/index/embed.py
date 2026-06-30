"""Cohere embeddings for the chunk index (U3.1).

embed-multilingual-v3.0 (1024-dim) — the corpus mixes English/German/Norwegian/
Danish (DE-LU, NO2, DK1), so multilingual matters. Cohere needs distinct
input_type for indexing vs querying:
  - documents (chunks) -> "search_document"
  - user questions      -> "search_query"   (used by U3.3 retrieval)
Batches internally (Cohere caps at 96 texts/call) so callers pass any length.
"""
from __future__ import annotations

import config

EMBED_MODEL = getattr(config, "EMBED_MODEL", "embed-multilingual-v3.0")
EMBED_DIM = getattr(config, "EMBED_DIM", 1024)


def embed_documents(texts: list[str], batch_size: int = 96) -> list[list[float]]:
    """Embed chunk texts for storage. Returns one vector per input, in order."""
    out: list[list[float]] = []
    texts = list(texts)
    for i in range(0, len(texts), batch_size):
        out.extend(_embed(texts[i:i + batch_size], "search_document"))
    return out


def embed_query(text: str) -> list[float]:
    """Embed a single user question for similarity search (U3.3)."""
    return _embed([text], "search_query")[0]


def _embed(texts: list[str], input_type: str) -> list[list[float]]:
    if not texts:
        return []
    import cohere

    co = cohere.Client(config.require("COHERE_API_KEY"))
    resp = co.embed(
        texts=texts,
        model=EMBED_MODEL,
        input_type=input_type,
        embedding_types=["float"],
    )
    embs = resp.embeddings
    # Cohere v5 returns embeddings.float; older SDKs return the list directly.
    return list(getattr(embs, "float", embs))


def to_pgvector(vec: list[float]) -> str:
    """Format a vector as a pgvector literal: '[0.1,0.2,...]' (cast with ::vector)."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"