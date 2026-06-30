"""Deterministic text chunking (U3.1).

Outage messages are short (usually one unit each), so most produce a single
chunk — but news/longer bodies in Sprint 2 will split. Char-based with overlap,
deterministic (no randomness) so re-runs are idempotent alongside the chunk-id hash.
"""
from __future__ import annotations


def chunk_text(text: str, size: int = 1000, overlap: int = 200) -> list[str]:
    """Split text into overlapping chunks of at most `size` chars.

    Returns [] for empty text, [text] when it already fits in one chunk.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    step = max(1, size - overlap)
    chunks: list[str] = []
    for start in range(0, len(text), step):
        piece = text[start:start + size]
        if piece:
            chunks.append(piece)
        if start + size >= len(text):
            break
    return chunks