"""Sentiment scoring for Buddy.

Per Assessments 1 and 2 the score is logged and used only to soften the
assistant's tone. It never decides, blocks or delays an escalation.

Backends:
  vader (default) - rule-based, ~1 MB, microseconds per call.
  hf              - Hugging Face transformer (cardiffnlp twitter-roberta sentiment).
                    Needs `pip install -r requirements-hf.txt` and ~2 GB RAM, so it is
                    opt-in rather than the default on free-tier hosts.
"""
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings

# VADER's recommended cut-offs on the compound score.
POSITIVE_CUTOFF, NEGATIVE_CUTOFF = 0.05, -0.05


@dataclass(frozen=True)
class Sentiment:
    label: str  # positive | neutral | negative
    score: float  # -1..1
    backend: str


@lru_cache(maxsize=1)
def _vader():
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    return SentimentIntensityAnalyzer()


@lru_cache(maxsize=1)
def _hf():  # pragma: no cover - optional heavy dependency
    from transformers import pipeline

    return pipeline("sentiment-analysis", model="cardiffnlp/twitter-roberta-base-sentiment-latest")


def analyse(text: str, backend: str | None = None) -> Sentiment:
    backend = backend or settings.AUBOT["SENTIMENT_BACKEND"]
    if backend == "hf":  # pragma: no cover
        result = _hf()(text[:512])[0]
        label = result["label"].lower()
        signed = result["score"] if label == "positive" else -result["score"] if label == "negative" else 0.0
        return Sentiment(label, round(signed, 4), "hf")
    compound = _vader().polarity_scores(text)["compound"]
    label = "positive" if compound >= POSITIVE_CUTOFF else "negative" if compound <= NEGATIVE_CUTOFF else "neutral"
    return Sentiment(label, round(compound, 4), "vader")
