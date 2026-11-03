"""
embeddings.py
-------------
Single owner of the sentence-transformer model.

Both gap_analysis and semantic_scorer used to instantiate
SentenceTransformer("all-MiniLM-L6-v2") at module scope. That built two copies
of the same model and did it at *import* time, so merely importing the scoring
package loaded ~180 MB and could reach out to HuggingFace on a cold machine.

Here the model is built once, on first use, and shared. Importing this module
costs nothing.
"""

from __future__ import annotations

from functools import lru_cache

MODEL_NAME = "all-MiniLM-L6-v2"


@lru_cache(maxsize=1)
def get_model(name: str = MODEL_NAME):
    """Return the shared model, loading it on first call."""
    # Imported lazily: sentence_transformers pulls torch, which is slow.
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(name)


def encode(texts: list[str]):
    """
    Batch-encode a list of texts into a tensor of embeddings.

    Always pass every text you need in one call — encoding items one at a time
    in a loop is dramatically slower than a single batched forward pass.

    Returns None for empty input so callers can guard cheaply.
    """
    if not texts:
        return None
    return get_model().encode(texts, convert_to_tensor=True)


def cos_sim(a, b):
    """Cosine similarity matrix between two embedding tensors."""
    from sentence_transformers import util

    return util.cos_sim(a, b)
