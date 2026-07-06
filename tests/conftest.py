"""Shared test helpers."""

import math
from zlib import crc32

DIMS = 64


def fake_embedder(texts: list[str]) -> list[list[float]]:
    """Deterministic bag-of-words embedder (crc32, not the randomized hash())."""
    vectors = []
    for text in texts:
        vec = [0.0] * DIMS
        for token in text.lower().split():
            vec[crc32(token.encode()) % DIMS] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        vectors.append([v / norm for v in vec])
    return vectors
