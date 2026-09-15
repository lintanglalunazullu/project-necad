# services/api/rag/embedding.py — Embedding model loading dan inference
import logging
from numbers import Number
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

import config

logger = logging.getLogger("aksaraku.embedding")

# Load model sekali saat startup
if config.HUGGINGFACE_API_KEY:
    import os
    os.environ.setdefault("HF_TOKEN", config.HUGGINGFACE_API_KEY)

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    """Lazy load model embedding (singleton)."""
    global _model
    if _model is None:
        logger.info("Loading embedding model: %s", config.HUGGINGFACE_EMBEDDING_MODEL)
        _model = SentenceTransformer(config.HUGGINGFACE_EMBEDDING_MODEL)
        logger.info("Embedding model loaded, dimension=%d", config.EXPECTED_EMBEDDING_DIMENSION)
    return _model


def _is_numeric(value: Any) -> bool:
    return isinstance(value, Number)


def _infer_shape(value: Any) -> str:
    if isinstance(value, np.ndarray):
        return str(value.shape)
    if isinstance(value, list):
        shape, cur = [], value
        while isinstance(cur, list):
            shape.append(len(cur))
            if not cur:
                break
            cur = cur[0]
        return str(tuple(shape))
    return type(value).__name__


def validate_embedding(embedding: Any) -> bool:
    """Validasi bahwa embedding adalah list float dengan dimensi yang benar."""
    return (
        isinstance(embedding, list)
        and bool(embedding)
        and all(_is_numeric(v) for v in embedding)
        and (
            config.EXPECTED_EMBEDDING_DIMENSION is None
            or len(embedding) == config.EXPECTED_EMBEDDING_DIMENSION
        )
    )


def normalize_embedding_result(result: Any) -> list[float]:
    """Normalisasi berbagai format hasil embedding ke list[float]."""
    if hasattr(result, "tolist"):
        result = result.tolist()
    if isinstance(result, dict):
        result = result.get("embedding", result.get("embeddings", result))
    if isinstance(result, list) and result and all(_is_numeric(v) for v in result):
        return [float(v) for v in result]
    if isinstance(result, list) and result and all(isinstance(v, list) for v in result):
        lengths = {len(v) for v in result}
        if len(lengths) == 1:
            return np.asarray(result, dtype=float).mean(axis=0).tolist()
    raise ValueError(f"Unable to normalize embedding result; shape={_infer_shape(result)}")


def embed_text(text: str) -> list[float]:
    """
    Buat embedding dari teks menggunakan model lokal (SentenceTransformer).
    Raise ValueError jika teks kosong atau dimensi tidak sesuai.
    """
    if not text or not text.strip():
        raise ValueError("Text cannot be empty")

    model = get_model()
    vector = model.encode(text, normalize_embeddings=True, convert_to_numpy=True)
    result = vector.astype(float).tolist()

    if len(result) != config.EXPECTED_EMBEDDING_DIMENSION:
        raise ValueError(
            f"Invalid embedding dimension: {len(result)} != {config.EXPECTED_EMBEDDING_DIMENSION}"
        )

    return result
