"""FAQ retrieval for the grounded generative fallback (UC01).

Only the top few relevant FAQ entries are sent to the LLM, which keeps prompts
(and cost) small no matter how large the SME's FAQ grows. The index is rebuilt
when an FAQ entry changes.
"""
import threading
from dataclasses import dataclass

import numpy as np
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from core.models import FaqEntry

from .nlu.embeddings import embed

MIN_SIMILARITY = 0.55  # below this an entry is unrelated; with no entry above it we skip the LLM and escalate


@dataclass(frozen=True)
class FaqHit:
    id: int
    question: str
    answer: str
    score: float


class FaqIndex:
    def __init__(self):
        self._lock = threading.Lock()
        self._entries: list[FaqEntry] | None = None
        self._matrix: np.ndarray | None = None

    def invalidate(self):
        with self._lock:
            self._entries, self._matrix = None, None

    async def _build(self) -> tuple[list[FaqEntry], np.ndarray]:
        entries = [e async for e in FaqEntry.objects.filter(active=True)]
        matrix = embed([f"{e.question} {e.tags}" for e in entries]) if entries else np.zeros((0, 384), dtype=np.float32)
        with self._lock:
            self._entries, self._matrix = entries, matrix
        return entries, matrix

    async def search(self, query: str, k: int = 3) -> list[FaqHit]:
        with self._lock:
            entries, matrix = self._entries, self._matrix
        if entries is None:
            entries, matrix = await self._build()
        if not entries:
            return []
        scores = matrix @ embed([query])[0]
        order = np.argsort(-scores)[:k]
        return [
            FaqHit(entries[i].id, entries[i].question, entries[i].answer, float(scores[i]))
            for i in order
            if scores[i] >= MIN_SIMILARITY
        ]


faq_index = FaqIndex()


@receiver([post_save, post_delete], sender=FaqEntry)
def _faq_changed(**kwargs):
    faq_index.invalidate()
