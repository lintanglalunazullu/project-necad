# services/api/ai/retrieval.py
# Hybrid search pipeline: vector (Gemini embedding) + keyword + exact match
# RRF (Reciprocal Rank Fusion) untuk merge hasil, reranking berdasarkan similarity + keyword overlap.
import logging
import re
from typing import Any

from supabase import Client

import config
from auth import allowed_categories, filter_documents_for_role, filter_rpc_documents_for_role
from utils.helpers import words

logger = logging.getLogger("aksaraku.retrieval")


# ======================= HELPERS =======================

def _parse_embedding(raw: Any) -> list[float] | None:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        import json
        try:
            value = json.loads(raw)
            return value if isinstance(value, list) else None
        except Exception:
            return None
    return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    return -1.0 if norm_a == 0 or norm_b == 0 else dot / (norm_a * norm_b)


def reciprocal_rank_fusion(result_sets: list[list[dict]], k: int = 60) -> list[dict]:
    """Gabungkan beberapa result set menggunakan Reciprocal Rank Fusion (RRF)."""
    fused: dict[str, dict] = {}
    for results in result_sets:
        for rank, doc in enumerate(results, start=1):
            doc_id = str(doc["id"])
            if doc_id not in fused:
                fused[doc_id] = {**doc, "rrf_score": 0.0}
            fused[doc_id]["rrf_score"] += 1.0 / (k + rank)
    return sorted(fused.values(), key=lambda x: x["rrf_score"], reverse=True)


# ======================= DOCUMENT FETCH =======================

def fetch_document_rows(supabase: Client) -> list[dict[str, Any]]:
    """
    Ambil semua baris dokumen dari Supabase.
    Pilih kolom spesifik — bukan select("*") — untuk hemat bandwidth.
    """
    from fastapi import HTTPException
    from utils.helpers import extract_response_parts

    response = (
        supabase.table(config.SUPABASE_TABLE)
        .select("id, pdf_name, content, category, embedding, created_at, status")
        .limit(10000)
        .execute()
    )
    parts = extract_response_parts(response)
    if parts["error"]:
        raise HTTPException(500, str(parts["error"]))
    return parts["data"] or []


def document_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Buat ringkasan dokumen berdasarkan pdf_name (satu entry per file, bukan per chunk)."""
    docs: dict[str, dict] = {}
    for row in rows:
        name = str(row.get("pdf_name") or "").strip()
        if not name:
            continue
        d = docs.setdefault(
            name,
            {
                "id": name,
                "name": name,
                "pdf_name": name,
                "chunk_count": 0,
                "created_at": row.get("created_at"),
                "status": row.get("status") or "completed",
                "category": row.get("category") or "public",
            },
        )
        d["chunk_count"] += 1
        if row.get("created_at") and (
            not d.get("created_at") or str(row["created_at"]) < str(d["created_at"])
        ):
            d["created_at"] = row["created_at"]
        if row.get("status"):
            d["status"] = row["status"]
        if row.get("category"):
            d["category"] = row["category"]
    return list(docs.values())


# ======================= SEARCH STRATEGIES =======================

def _table_similar_documents(
    supabase: Client,
    query_embedding: list[float],
    categories: set[str],
    top_k: int,
    cached_rows: list[dict] | None = None,
) -> list[dict]:
    """Cari dokumen mirip menggunakan cosine similarity di memori (fallback dari RPC)."""
    try:
        rows = cached_rows if cached_rows is not None else fetch_document_rows(supabase)
    except Exception as exc:
        logger.warning("Table vector fallback failed: %s", exc)
        return []

    matches = []
    for row in rows:
        category = str(row.get("category") or "public").strip().lower()
        if category not in categories:
            continue
        embedding = _parse_embedding(row.get("embedding"))
        similarity = _cosine_similarity(query_embedding, embedding or [])
        if similarity >= config.RAG_MIN_SIMILARITY:
            doc = dict(row)
            doc["similarity"] = similarity
            matches.append(doc)

    matches.sort(key=lambda d: float(d.get("similarity") or 0), reverse=True)
    return matches[:top_k]


def _keyword_similar_documents(
    supabase: Client,
    question: str,
    categories: set[str],
    top_k: int,
    cached_rows: list[dict] | None = None,
) -> list[dict]:
    """Cari dokumen berdasarkan overlap kata kunci."""
    try:
        rows = cached_rows if cached_rows is not None else fetch_document_rows(supabase)
    except Exception as exc:
        logger.warning("Keyword document fallback failed: %s", exc)
        return []

    query_words = words(question)
    if not query_words:
        return []

    matches = []
    for row in rows:
        category = str(row.get("category") or "public").strip().lower()
        if category not in categories:
            continue
        content = str(row.get("content") or row.get("text") or "")
        overlap = len(query_words & words(content)) / max(1, len(query_words))
        if overlap <= 0:
            continue
        doc = dict(row)
        doc["keyword_score"] = overlap
        doc["similarity"] = max(float(doc.get("similarity") or 0), overlap)
        matches.append(doc)

    matches.sort(key=lambda d: float(d.get("keyword_score") or 0), reverse=True)
    return matches[:top_k]


def _merge_similar_documents(
    rpc_documents: list[dict],
    fallback_documents: list[dict],
    top_k: int,
) -> list[dict]:
    merged: dict = {}
    for doc in rpc_documents + fallback_documents:
        key = doc.get("id") or (doc.get("pdf_name"), doc.get("content"))
        current = merged.get(key)
        if current is None or float(doc.get("similarity") or 0) > float(current.get("similarity") or 0):
            merged[key] = doc
    return sorted(merged.values(), key=lambda d: float(d.get("similarity") or 0), reverse=True)[:top_k]


# ======================= MAIN RETRIEVAL =======================

def get_similar_documents(
    supabase: Client,
    query_embedding: list[float],
    role: str,
    top_k: int = None,
    question: str = "",
) -> list[dict]:
    """
    Pipeline retrieval utama.
    - Fetch rows sekali, reuse untuk keyword & vector search (kurangi DB calls redundan)
    - Gunakan RPC untuk teacher/admin, table fallback untuk user biasa
    """
    if top_k is None:
        top_k = config.RAG_TOP_K

    categories = set(allowed_categories(role))

    # Cache rows sekali untuk reuse di keyword + vector search
    cached_rows = None
    try:
        cached_rows = fetch_document_rows(supabase)
    except Exception as exc:
        logger.warning("Pre-fetch document rows failed: %s", exc)

    keyword_documents = (
        _keyword_similar_documents(supabase, question, categories, top_k, cached_rows)
        if question
        else []
    )

    if role not in {"teacher", "admin"}:
        vector_documents = _table_similar_documents(
            supabase, query_embedding, categories, top_k, cached_rows
        )
        return _merge_similar_documents(vector_documents, keyword_documents, top_k)

    # Teacher/Admin: coba RPC dulu, gabung dengan table fallback
    rpc_documents = []
    try:
        response = supabase.rpc(
            config.VECTOR_FUNCTION,
            {
                "query_embedding": query_embedding,
                "match_threshold": config.RAG_MIN_SIMILARITY,
                "match_count": max(top_k * 3, 15),
            },
        ).execute()
        from utils.helpers import extract_response_parts
        parts = extract_response_parts(response)
        if not parts["error"]:
            rpc_documents = filter_rpc_documents_for_role(parts["data"] or [], role)
    except Exception as exc:
        logger.warning("Vector RPC failed: %s", exc)

    vector_documents = _table_similar_documents(
        supabase, query_embedding, categories, top_k, cached_rows
    )
    return _merge_similar_documents(rpc_documents + vector_documents, keyword_documents, top_k)


async def hybrid_search(supabase: Client, question: str, top_k: int = None) -> list[dict]:
    """Hybrid search menggunakan RRF: vector + keyword + exact match."""
    from ai.embedding import embed_query

    if top_k is None:
        top_k = config.RAG_TOP_K

    embedding = embed_query(question)

    vector_results: list[dict] = []
    try:
        response = supabase.rpc(
            config.VECTOR_FUNCTION,
            {"query_embedding": embedding, "match_threshold": config.RAG_MIN_SIMILARITY, "match_count": top_k},
        ).execute()
        vector_results = response.data or []
    except Exception as exc:
        logger.exception("Vector search failed: %s", exc)

    keyword_results: list[dict] = []
    try:
        response = supabase.rpc(
            config.KEYWORD_FUNCTION, {"search_query": question, "result_limit": top_k}
        ).execute()
        keyword_results = response.data or []
    except Exception as exc:
        logger.exception("Keyword search failed: %s", exc)

    exact_results: list[dict] = []
    numbers = re.findall(r"\b\d{3,20}\b", question)
    for number in numbers[:5]:
        try:
            response = supabase.rpc(
                config.EXACT_FUNCTION, {"search_term": number, "result_limit": 10}
            ).execute()
            exact_results.extend(response.data or [])
        except Exception as exc:
            logger.exception("Exact search failed: %s", exc)

    fused = reciprocal_rank_fusion([exact_results, keyword_results, vector_results])
    return fused[:top_k]


def rerank_documents(
    question: str, docs: list[dict], final_k: int = None
) -> list[dict]:
    """Rerank dokumen berdasarkan kombinasi vector similarity dan keyword overlap."""
    if final_k is None:
        final_k = config.RAG_FINAL_K
    qwords = words(question)
    scored = []
    for i, doc in enumerate(docs):
        content = str(doc.get("content") or doc.get("text") or "")
        vector = float(doc.get("similarity") or doc.get("score") or doc.get("similarity_score") or 0)
        overlap = len(qwords & words(content)) / max(1, len(qwords))
        score = vector * 0.75 + overlap * 0.25
        scored.append((score, i, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[2] for x in scored[:final_k]]


def is_structured_question(question: str) -> bool:
    """Deteksi apakah pertanyaan mengandung data terstruktur (nomor, NIP, NISN, dll)."""
    q = question.lower()
    keywords = [
        "nomor", "no.", "nip", "nisn", "nis", "npsn", "guru", "siswa", "murid",
        "nama", "kelas", "wali kelas", "mata pelajaran", "mapel", "daftar",
        "berapa jumlah", "sebutkan", "siapa",
    ]
    if any(kw in q for kw in keywords):
        return True
    return bool(re.search(r"\b\d{3,20}\b", q))
