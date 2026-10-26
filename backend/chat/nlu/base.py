"""Intent-engine interface. Any backend (local classifier, Dialogflow, a future
hosted model) returns the same IntentResult, so UC01/UC03 routing never changes
when the vendor does (Assessment 1, "modular adapters")."""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import yaml
from django.conf import settings

OUT_OF_SCOPE = "out_of_scope"


@dataclass(frozen=True)
class IntentResult:
    intent: str
    confidence: float
    engine: str


class IntentEngine(Protocol):
    name: str

    def classify(self, text: str) -> IntentResult: ...


@dataclass(frozen=True)
class IntentSpec:
    name: str
    phrases: tuple[str, ...]
    responses: tuple[str, ...]
    actions: tuple[str, ...]
    escalate: bool


@lru_cache(maxsize=1)
def load_intents(path: Path | None = None) -> dict[str, IntentSpec]:
    path = path or settings.AUBOT["DATA_DIR"] / "intents.yaml"
    raw = yaml.safe_load(Path(path).read_text())["intents"]
    return {
        name: IntentSpec(
            name=name,
            phrases=tuple(spec.get("phrases", [])),
            responses=tuple(spec.get("responses", [])),
            actions=tuple(spec.get("actions", [])),
            escalate=bool(spec.get("escalate", False)),
        )
        for name, spec in raw.items()
    }


@lru_cache(maxsize=1)
def get_intent_engine() -> IntentEngine:
    """One engine per process; the local model trains in well under a second at startup."""
    backend = settings.AUBOT["INTENT_BACKEND"]
    if backend == "dialogflow":
        from .dialogflow import DialogflowEngine

        return DialogflowEngine(
            project_id=settings.AUBOT["DIALOGFLOW_PROJECT_ID"], language=settings.AUBOT["DIALOGFLOW_LANGUAGE"]
        )
    if backend == "tfidf":
        from .local import TfidfIntentEngine

        return TfidfIntentEngine.from_specs(load_intents())
    from .local import EmbeddingIntentEngine

    return EmbeddingIntentEngine.from_specs(load_intents())
