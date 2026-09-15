# services/api/ai/embedding.py
# Embedding via Gemini text-embedding-004 API
# Tidak ada model lokal, tidak ada download, startup instant.
import logging
import time
from numbers import Number
from typing import Any

import google.generativeai as genai

import config

logger = logging.getLogger("aksaraku.embedding")

# Inisialisasi client Gemini sekali saja
genai.configure(api_key=config.GEMINI_API_KEY)


# ======================= VALIDATION HELPERS =======================

def _is_numeric(value: Any) -> bool:
    return isinstance(value, Number) and not isinstance(value, bool)


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
    raise ValueError(f"Unable to normalize embedding result; type={type(result).__name__}")


# ======================= EMBEDDING =======================

def embed_text(text: str) -> list[float]:
    """
    Buat embedding dari teks menggunakan Gemini text-embedding-004.
    Output dimensi dikontrol via EXPECTED_EMBEDDING_DIMENSION (default 384).
    Retry otomatis 3x dengan exponential backoff.
    """
    if not text or not text.strip():
        raise ValueError("Text cannot be empty")

    text = text.strip()
    last_error: Exception | None = None

    for attempt in range(config.EMBEDDING_RETRIES):
        try:
            result = genai.embed_content(
                model=config.GEMINI_EMBEDDING_MODEL,
                content=text,
                task_type="retrieval_document",
                output_dimensionality=config.EXPECTED_EMBEDDING_DIMENSION,
            )
            vector = normalize_embedding_result(result["embedding"])

            if len(vector) != config.EXPECTED_EMBEDDING_DIMENSION:
                raise ValueError(
                    f"Invalid embedding dimension: {len(vector)} != {config.EXPECTED_EMBEDDING_DIMENSION}"
                )

            return vector

        except Exception as exc:
            last_error = exc
            if attempt < config.EMBEDDING_RETRIES - 1:
                wait = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(
                    "Embedding attempt %s/%s gagal, retry in %ss: %s",
                    attempt + 1, config.EMBEDDING_RETRIES, wait, exc,
                )
                time.sleep(wait)
            else:
                logger.error("Semua embedding retry gagal: %s", exc)

    raise RuntimeError(f"Gagal generate embedding setelah {config.EMBEDDING_RETRIES} percobaan: {last_error}")


def embed_query(text: str) -> list[float]:
    """
    Embedding khusus untuk query (pakai task_type retrieval_query).
    Dipisah dari embed_text agar Gemini bisa optimasi representasi vektor.
    """
    if not text or not text.strip():
        raise ValueError("Query text cannot be empty")

    text = text.strip()
    last_error: Exception | None = None

    for attempt in range(config.EMBEDDING_RETRIES):
        try:
            result = genai.embed_content(
                model=config.GEMINI_EMBEDDING_MODEL,
                content=text,
                task_type="retrieval_query",
                output_dimensionality=config.EXPECTED_EMBEDDING_DIMENSION,
            )
            return normalize_embedding_result(result["embedding"])

        except Exception as exc:
            last_error = exc
            if attempt < config.EMBEDDING_RETRIES - 1:
                wait = 2 ** attempt
                logger.warning(
                    "Query embedding attempt %s/%s gagal, retry in %ss: %s",
                    attempt + 1, config.EMBEDDING_RETRIES, wait, exc,
                )
                time.sleep(wait)

    raise RuntimeError(f"Gagal generate query embedding: {last_error}")
