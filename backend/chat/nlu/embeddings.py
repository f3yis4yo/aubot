"""Shared local sentence-embedding model (BAAI/bge-small-en-v1.5, quantised ONNX).

Runs on CPU via onnxruntime: ~130 MB RAM, ~2 ms per query, no PyTorch, no API
cost. Used by the intent classifier and by FAQ retrieval.
"""
import os
from functools import lru_cache

import numpy as np
from django.conf import settings

MODEL_NAME = "BAAI/bge-small-en-v1.5"


@lru_cache(maxsize=1)
def get_embedder():
    from fastembed import TextEmbedding

    cache_dir = os.environ.get("FASTEMBED_CACHE_PATH", str(settings.BASE_DIR / ".models"))
    return TextEmbedding(MODEL_NAME, cache_dir=cache_dir)


def embed(texts: list[str]) -> np.ndarray:
    """Return L2-normalised embeddings, one row per text."""
    vectors = np.array(list(get_embedder().embed(texts)), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.clip(norms, 1e-12, None)
