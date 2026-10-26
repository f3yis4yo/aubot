"""Local intent classifiers.

Why not Dialogflow by default: it needs a GCP project and service account, CX
has no meaningful free tier, and its scores shift when Google updates the
model, which makes the TC01 benchmark irreproducible. The local models are
free, deterministic and train in under a second from data/intents.yaml.

Model selection used 5-fold cross-validation on the training phrases only (the
TC01 set stayed held out):

    TF-IDF word+char n-grams + logistic regression   ~70% CV accuracy
    bge-small embeddings + logistic regression C=300 ~92% CV accuracy  <- default

The TF-IDF engine is kept as a fallback for hosts that cannot download the
embedding model.
"""
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from .base import IntentResult, IntentSpec


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _training_data(specs: dict[str, IntentSpec]) -> tuple[list[str], list[str]]:
    texts, labels = [], []
    for spec in specs.values():
        for phrase in spec.phrases:
            texts.append(_normalise(phrase))
            labels.append(spec.name)
    return texts, labels


class EmbeddingIntentEngine:
    name = "local"

    def __init__(self, clf: LogisticRegression):
        self.clf = clf
        self.classes = list(clf.classes_)

    @classmethod
    def from_specs(cls, specs: dict[str, IntentSpec]) -> "EmbeddingIntentEngine":
        from .embeddings import embed

        texts, labels = _training_data(specs)
        clf = LogisticRegression(C=300, max_iter=8000, class_weight="balanced").fit(embed(texts), labels)
        return cls(clf)

    def classify(self, text: str) -> IntentResult:
        from .embeddings import embed

        probs = self.clf.predict_proba(embed([_normalise(text)]))[0]
        best = int(np.argmax(probs))
        return IntentResult(intent=self.classes[best], confidence=float(probs[best]), engine=self.name)


class TfidfIntentEngine:
    name = "tfidf"

    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline
        self.classes = list(pipeline.classes_)

    @classmethod
    def from_specs(cls, specs: dict[str, IntentSpec]) -> "TfidfIntentEngine":
        features = FeatureUnion(
            [
                ("words", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)),
                ("chars", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True)),
            ]
        )
        pipeline = Pipeline([("features", features), ("clf", LogisticRegression(C=20, max_iter=5000, class_weight="balanced"))])
        return cls(pipeline.fit(*_training_data(specs)))

    def classify(self, text: str) -> IntentResult:
        probs = self.pipeline.predict_proba([_normalise(text)])[0]
        best = int(np.argmax(probs))
        return IntentResult(intent=self.classes[best], confidence=float(probs[best]), engine=self.name)
