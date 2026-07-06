"""Shared test helpers."""

import json
import math
from zlib import crc32

from seshat.inference.provider import GenerationError

DIMS = 64


class FakeProvider:
    model_version = "fake/test-1"

    def __init__(self, response: str | None = None, fail: bool = False) -> None:
        self.response = response or json.dumps({
            "what_changed": "Added SMOTE oversampling before the classifier.",
            "observable_outcome": "F1 went from 0.61 to 0.68.",
            "inferred_intent": "addressing class imbalance",
            "intent_confidence": 0.8,
        })
        self.fail = fail
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        if self.fail:
            raise GenerationError("provider down")
        self.prompts.append(prompt)
        return self.response


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
