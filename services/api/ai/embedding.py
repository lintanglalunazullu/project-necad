# services/api/ai/embedding.py
# Embedding via Gemini Embedding API
# Mendukung auto-detection model, dynamic fallback, dan output_dimensionality.
import logging
import time
from numbers import Number
from typing import Any

import google.generativeai as genai

import config

logger = logging.getLogger("aksaraku.embedding")

_ACTIVE_MODEL: str | None = None


def _ensure_configured() -> None:
    """Pastikan Google GenAI SDK dikonfigurasi dengan API key aktif."""
    key = getattr(config, "GEMINI_API_KEY", "")
    if not key or key.startswith("AIzaSy_xxx"):
        try:
            from ai.generation import get_provider_manager
            mgr = get_provider_manager()
            keys = mgr.get_provider_keys("gemini")
            if keys:
                key = keys[0]
                config.GEMINI_API_KEY = key
        except Exception:
            pass

    if key and not key.startswith("AIzaSy_xxx"):
        genai.configure(api_key=key.strip())


# Inisialisasi awal
_ensure_configured()


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


# ======================= CORE EMBEDDING CALL =======================

def _call_gemini_embed(text: str, task_type: str) -> list[float]:
    """
    Generate embedding menggunakan official google.genai SDK (v1) dengan instance Client.
    Fallback otomatis antar model (gemini-embedding-001, gemini-embedding-2),
    output_dimensionality=384, dan fallback ke google.generativeai jika diperlukan.
    """
    global _ACTIVE_MODEL

    # 1. Coba via modern official google.genai (thread-safe, instance Client)
    try:
        from google import genai as modern_genai
        from google.genai import types as genai_types

        keys = []
        try:
            from ai.generation import get_provider_manager
            mgr = get_provider_manager()
            keys = mgr.get_provider_keys("gemini")
        except Exception:
            pass
        if not keys and getattr(config, "GEMINI_API_KEY", None):
            keys = [config.GEMINI_API_KEY]
        keys = [k.strip() for k in keys if k and not k.startswith("AIzaSy_xxx")]
        if not keys:
            keys = [""]

        models_to_try = ["gemini-embedding-001", "gemini-embedding-2"]

        for model_name in models_to_try:
            for idx, key in enumerate(keys):
                try:
                    client = modern_genai.Client(api_key=key) if key else modern_genai.Client()
                    embed_cfg = genai_types.EmbedContentConfig(
                        output_dimensionality=config.EXPECTED_EMBEDDING_DIMENSION
                    ) if config.EXPECTED_EMBEDDING_DIMENSION else None

                    resp = client.models.embed_content(
                        model=model_name,
                        contents=text,
                        config=embed_cfg,
                    )
                    if resp.embeddings and resp.embeddings[0].values:
                        vector = [float(v) for v in resp.embeddings[0].values]
                        if config.EXPECTED_EMBEDDING_DIMENSION and len(vector) > config.EXPECTED_EMBEDDING_DIMENSION:
                            vector = vector[: config.EXPECTED_EMBEDDING_DIMENSION]
                        _ACTIVE_MODEL = model_name
                        return vector
                except Exception as g_err:
                    err_str = str(g_err).lower()
                    if "429" in err_str or "quota" in err_str or "resourceexhausted" in err_str:
                        logger.warning("google.genai embedding key #%d hit rate limit, mencoba kunci cadangan...", idx + 1)
                        continue
                    elif "not found" in err_str or "404" in err_str or "is not supported" in err_str:
                        break
                    else:
                        logger.debug("google.genai embed attempt note: %s", g_err)
                        continue
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("Modern google.genai attempt failed, falling back to legacy: %s", exc)

    # 2. Fallback legacy via google.generativeai
    _ensure_configured()

    models_to_try = []
    if _ACTIVE_MODEL:
        models_to_try.append(_ACTIVE_MODEL)
    if config.GEMINI_EMBEDDING_MODEL and config.GEMINI_EMBEDDING_MODEL not in models_to_try:
        models_to_try.append(config.GEMINI_EMBEDDING_MODEL)

    fallbacks = [
        "models/gemini-embedding-001",
        "models/gemini-embedding-2",
        "models/text-embedding-004",
        "models/embedding-001",
    ]
    for fb in fallbacks:
        if fb not in models_to_try:
            models_to_try.append(fb)

    keys = []
    try:
        from ai.generation import get_provider_manager
        mgr = get_provider_manager()
        keys = mgr.get_provider_keys("gemini")
    except Exception:
        pass
    if not keys and config.GEMINI_API_KEY:
        keys = [config.GEMINI_API_KEY]
    if not keys:
        keys = [""]

    last_error: Exception | None = None

    for model_name in models_to_try:
        for idx, key in enumerate(keys):
            if key and not key.startswith("AIzaSy_xxx"):
                genai.configure(api_key=key.strip())

            model_not_found = False
            for attempt in range(config.EMBEDDING_RETRIES):
                try:
                    kwargs: dict[str, Any] = {
                        "model": model_name,
                        "content": text,
                        "task_type": task_type,
                    }
                    if config.EXPECTED_EMBEDDING_DIMENSION:
                        kwargs["output_dimensionality"] = config.EXPECTED_EMBEDDING_DIMENSION

                    try:
                        result = genai.embed_content(**kwargs)
                    except Exception as call_err:
                        err_msg = str(call_err).lower()
                        # Kalau model tidak mendukung output_dimensionality, coba lagi tanpa parameter tersebut
                        if "output_dimensionality" in err_msg:
                            kwargs.pop("output_dimensionality", None)
                            result = genai.embed_content(**kwargs)
                        else:
                            raise call_err

                    vector = normalize_embedding_result(result["embedding"])

                    # Jika dimensi tidak sesuai dan model tidak memotongnya otomatis
                    if config.EXPECTED_EMBEDDING_DIMENSION and len(vector) != config.EXPECTED_EMBEDDING_DIMENSION:
                        if len(vector) > config.EXPECTED_EMBEDDING_DIMENSION:
                            vector = vector[: config.EXPECTED_EMBEDDING_DIMENSION]
                        else:
                            raise ValueError(
                                f"Invalid embedding dimension from {model_name}: {len(vector)} != {config.EXPECTED_EMBEDDING_DIMENSION}"
                            )

                    _ACTIVE_MODEL = model_name
                    return vector

                except Exception as exc:
                    last_error = exc
                    err_str = str(exc).lower()
                    # Jika model 404 / not found, jangan retry model ini lagi — langsung coba model berikutnya
                    if "not found" in err_str or "404" in err_str or "is not supported" in err_str:
                        logger.warning("Model embedding %s tidak tersedia (%s), mencoba model alternatif...", model_name, exc)
                        model_not_found = True
                        break

                    # Jika terkena 429 / kuota habis, coba kunci cadangan berikutnya jika tersedia
                    if "429" in err_str or "quota" in err_str or "resourceexhausted" in err_str:
                        if idx < len(keys) - 1:
                            logger.warning("Embedding key #%d terkena limit (429). Beralih ke kunci cadangan #%d...", idx + 1, idx + 2)
                            break

                    if attempt < config.EMBEDDING_RETRIES - 1:
                        wait = 2 ** attempt
                        logger.warning(
                            "Embedding (%s) attempt %s/%s gagal, retry in %ss: %s",
                            model_name, attempt + 1, config.EMBEDDING_RETRIES, wait, exc,
                        )
                        time.sleep(wait)
                    else:
                        logger.warning("Semua retry gagal untuk model %s (key #%d): %s", model_name, idx + 1, exc)

            if model_not_found:
                break

    raise RuntimeError(f"Gagal generate embedding setelah mencoba model {models_to_try}: {last_error}")


# ======================= EMBEDDING CACHE =======================

from collections import OrderedDict
import re
import threading


class EmbeddingCache:
    """Thread-safe LRU cache with TTL untuk embedding query."""

    def __init__(self, max_size: int = 1000, ttl_seconds: float = 21600.0):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, tuple[list[float], float]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def normalize_key(text: str) -> str:
        clean = re.sub(r"[^\w\s]", " ", text.lower()).strip()
        return re.sub(r"\s+", " ", clean)

    def get(self, text: str) -> list[float] | None:
        key = self.normalize_key(text)
        if not key:
            return None
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            vector, timestamp = self._cache[key]
            if time.time() - timestamp > self.ttl_seconds:
                del self._cache[key]
                self._misses += 1
                return None
            self._cache.move_to_end(key)
            self._hits += 1
            return list(vector)

    def set(self, text: str, vector: list[float]) -> None:
        key = self.normalize_key(text)
        if not key or not vector:
            return
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (list(vector), time.time())
            if len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 3) if total > 0 else 0.0,
            }


embedding_cache = EmbeddingCache(max_size=1000, ttl_seconds=21600.0)


# ======================= PUBLIC API =======================

def embed_text(text: str) -> list[float]:
    """
    Buat embedding dokumen dari teks.
    """
    if not text or not text.strip():
        raise ValueError("Text cannot be empty")
    return _call_gemini_embed(text.strip(), "retrieval_document")


def embed_query(text: str) -> list[float]:
    """
    Embedding khusus untuk query pertanyaan chat (pakai task_type retrieval_query).
    Memanfaatkan in-memory LRU embedding cache untuk performa sub-millisecond pada query berulang.
    """
    if not text or not text.strip():
        raise ValueError("Query text cannot be empty")
    cleaned = text.strip()
    cached = embedding_cache.get(cleaned)
    if cached is not None:
        logger.info("Embedding cache hit untuk query: '%s'", cleaned[:40])
        return cached

    vector = _call_gemini_embed(cleaned, "retrieval_query")
    if vector:
        embedding_cache.set(cleaned, vector)
    return vector

