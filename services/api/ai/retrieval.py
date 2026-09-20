# services/api/ai/retrieval.py
# Hybrid search pipeline: vector (Gemini embedding) + keyword + exact match
# RRF (Reciprocal Rank Fusion) untuk merge hasil, reranking berdasarkan similarity + keyword overlap.
#
# CATATAN PERFORMA (migrasi lihat docs/migration_performance_and_security.sql):
# Sebelumnya modul ini SELALU fetch seluruh tabel pdf_documents (termasuk kolom
# embedding) untuk SETIAP pesan chat, lalu hitung cosine similarity di Python.
# Sekarang RPC match_pdf_documents/search_pdf_documents_keyword/search_pdf_documents_exact
# menerima parameter category_filter, jadi filtering role terjadi di Postgres
# (pakai index HNSW + FTS yang sudah ada) untuk SEMUA role, termasuk "user" biasa.
# Fetch-seluruh-tabel + cosine similarity di Python hanya dipakai sebagai FALLBACK
# kalau RPC gagal (mis. koneksi database bermasalah).
import logging
import re
from typing import Any

from supabase import Client

import config
from auth import allowed_categories, filter_documents_for_role, filter_rpc_documents_for_role
from utils.helpers import extract_response_parts, words

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


# ======================= DOCUMENT FETCH (fallback / admin listing only) =======================

def fetch_document_rows(supabase: Client) -> list[dict[str, Any]]:
    """
    Ambil semua baris dokumen dari Supabase.
    MAHAL — hanya dipakai untuk fallback saat RPC gagal, atau saat memang perlu
    baris mentah (mis. shortcut "daftar dokumen apa saja" di chat.py). Untuk
    ringkasan dokumen di admin/listing, pakai fetch_document_summary() di bawah,
    yang GROUP BY di database, bukan di Python.
    """
    from fastapi import HTTPException

    response = (
        supabase.table(config.SUPABASE_TABLE)
        .select("id, pdf_name, content, category, embedding, created_at")
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


def fetch_document_summary(supabase: Client) -> list[dict[str, Any]]:
    """
    Ringkasan dokumen (1 baris per pdf_name) langsung dari database via RPC
    get_document_summary (GROUP BY di Postgres). Jauh lebih murah daripada
    fetch_document_rows() + document_summary() saat jumlah chunk besar.
    Fallback otomatis ke cara lama kalau RPC belum ter-deploy.
    """
    try:
        response = supabase.rpc("get_document_summary", {}).execute()
        parts = extract_response_parts(response)
        if not parts["error"] and parts["data"] is not None:
            return [
                {
                    "id": row.get("pdf_name"),
                    "name": row.get("pdf_name"),
                    "pdf_name": row.get("pdf_name"),
                    "chunk_count": row.get("chunk_count", 0),
                    "created_at": row.get("created_at"),
                    "status": "completed",
                    "category": row.get("category") or "public",
                }
                for row in (parts["data"] or [])
            ]
    except Exception as exc:
        logger.warning("get_document_summary RPC failed, fallback to full fetch: %s", exc)
    return document_summary(fetch_document_rows(supabase))


# ======================= SEARCH STRATEGIES (fallback path) =======================

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
    """Cari dokumen berdasarkan overlap kata kunci (fallback dari RPC FTS)."""
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


# ======================= RPC CALLS (primary path — DB-side filtering) =======================

def _rpc_vector_search(
    supabase: Client, query_embedding: list[float], categories: set[str], top_k: int
) -> tuple[list[dict], bool]:
    """Vector search via RPC dengan category_filter. Return (results, ok)."""
    try:
        response = supabase.rpc(
            config.VECTOR_FUNCTION,
            {
                "query_embedding": query_embedding,
                "match_threshold": config.RAG_MIN_SIMILARITY,
                "match_count": max(top_k * 3, 15),
                "category_filter": sorted(categories),
            },
        ).execute()
        parts = extract_response_parts(response)
        if parts["error"]:
            raise RuntimeError(str(parts["error"]))
        return parts["data"] or [], True
    except Exception as exc:
        logger.warning("Vector RPC failed: %s", exc)
        return [], False


ID_STOPWORDS = {
    "apa", "apakah", "siapa", "siapakah", "bagaimana", "mengapa", "kenapa", "kapan",
    "dimana", "mana", "yang", "dan", "di", "ke", "dari", "pada", "untuk", "dengan",
    "ini", "itu", "atau", "adalah", "yaitu", "sebagai", "bisa", "dapat", "ada",
    "saya", "kamu", "anda", "kami", "kita", "mereka", "dia", "nya", "tolong",
    "coba", "jelaskan", "sebutkan", "tentang", "kasih", "tahu", "beri", "detail", "detailnya"
}

SYNONYMS = {
    "eskul": "ekstrakurikuler",
    "ekskul": "ekstrakurikuler",
    "walas": "wali kelas",
    "kepsek": "kepala sekolah",
    "wakasek": "wakil kepala sekolah",
    "tu": "tata usaha",
    "sarpras": "sarana prasarana",
}


def _strip_id_affixes(word: str) -> str:
    """Hapus akhiran/imbuhan umum bahasa Indonesia (-nya, -lah, -kah, -pun)."""
    w = word.lower()
    for suffix in ("nya", "lah", "kah", "pun"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[:-len(suffix)]
    return w


def _extract_search_candidates(query: str) -> list[str]:
    """Ekstrak beberapa kombinasi kata kunci bertingkat dari pertanyaan."""
    tokens = re.findall(r"[a-zA-Z0-9]+", query.lower())
    mapped_tokens = [SYNONYMS.get(t, t) for t in tokens]
    meaningful = [t for t in mapped_tokens if t not in ID_STOPWORDS]
    stemmed = [_strip_id_affixes(t) for t in meaningful]

    candidates: list[str] = []
    if meaningful:
        candidates.append(" ".join(meaningful))
    if stemmed and stemmed != meaningful:
        candidates.append(" ".join(stemmed))
    # Ambil 2-gram pertama untuk pertanyaan panjang (mis. 'wali kelas' dari 'sebutkan wali kelas dan detailnya')
    if len(stemmed) >= 2:
        sub = " ".join(stemmed[:2])
        if sub not in candidates:
            candidates.append(sub)
    if query not in candidates:
        candidates.append(query)

    # Hilangkan duplikasi dengan mempertahankan urutan
    return list(dict.fromkeys(candidates))


def _rpc_keyword_search(
    supabase: Client, question: str, categories: set[str], top_k: int
) -> list[dict]:
    if not question:
        return []
    queries = _extract_search_candidates(question)

    for q_text in queries:
        try:
            response = supabase.rpc(
                config.KEYWORD_FUNCTION,
                {
                    "search_query": q_text,
                    "result_limit": max(top_k * 2, 10),
                    "category_filter": sorted(categories),
                },
            ).execute()
            parts = extract_response_parts(response)
            if not parts["error"] and parts["data"]:
                return parts["data"]
        except Exception as exc:
            logger.warning("Keyword RPC failed for query '%s': %s", q_text, exc)

    return []


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
    Jalur cepat (default): 2 panggilan RPC ber-index (vector + keyword), keduanya
    sudah difilter kategori di database — TIDAK fetch seluruh tabel.
    Jalur fallback (hanya kalau RPC gagal): fetch tabel penuh + hitung similarity
    di Python, seperti sebelumnya.
    """
    if top_k is None:
        top_k = config.RAG_TOP_K

    categories = set(allowed_categories(role))

    rpc_vector_documents, vector_ok = _rpc_vector_search(supabase, query_embedding, categories, top_k)
    rpc_keyword_documents = _rpc_keyword_search(supabase, question, categories, top_k) if question else []

    # Defense-in-depth: walau RPC sudah filter kategori, filter lagi di Python
    # (murah — hasil RPC sudah kecil, bukan seluruh tabel).
    rpc_vector_documents = filter_rpc_documents_for_role(rpc_vector_documents, role)
    rpc_keyword_documents = filter_rpc_documents_for_role(rpc_keyword_documents, role)

    if vector_ok:
        return _merge_similar_documents(rpc_vector_documents, rpc_keyword_documents, top_k)

    # ---- Fallback: RPC vector search gagal (mis. DB down) ----
    logger.warning("Falling back to full-table similarity search (role=%s)", role)
    cached_rows = None
    try:
        cached_rows = fetch_document_rows(supabase)
    except Exception as exc:
        logger.warning("Fallback pre-fetch document rows failed: %s", exc)

    keyword_documents = (
        _keyword_similar_documents(supabase, question, categories, top_k, cached_rows)
        if question
        else []
    )
    vector_documents = _table_similar_documents(supabase, query_embedding, categories, top_k, cached_rows)
    return _merge_similar_documents(
        rpc_keyword_documents + vector_documents, keyword_documents, top_k
    )


async def hybrid_search(supabase: Client, question: str, top_k: int = None) -> list[dict]:
    """Hybrid search menggunakan RRF: vector + keyword + exact match (tanpa filter role -
    dipakai hanya untuk pemanggil yang sudah menjamin scope kategori-nya sendiri)."""
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


THEMATIC_CATEGORIES = {
    "ppdb": {
        "keywords": ["ppdb", "pendaftaran", "daftar", "syarat masuk", "jalur", "zonasi", "afirmasi", "prestasi", "kuota", "biaya masuk", "formulir", "calon siswa"],
        "filenames": ["ppdb", "pendaftaran", "siswa_baru"],
    },
    "akademik": {
        "keywords": ["kurikulum", "jadwal", "pelajaran", "mapel", "ujian", "pts", "pas", "pat", "rapor", "kelulusan", "kalender", "semester", "kkm", "asesmen", "anbk"],
        "filenames": ["kurikulum", "akademik", "jadwal", "kalender"],
    },
    "profil": {
        "keywords": ["visi", "misi", "sejarah", "kepala sekolah", "profil", "alamat", "kontak", "fasilitas", "sarana", "prasarana", "akreditasi", "npsn", "ruang", "gedung", "lapangan", "perpustakaan", "lab", "laboratorium"],
        "filenames": ["profil", "visi_misi", "fasilitas", "sarpras"],
    },
    "kesiswaan": {
        "keywords": ["ekstrakurikuler", "ekskul", "osis", "pramuka", "paskibra", "pmr", "tata tertib", "aturan", "seragam", "poin", "pelanggaran", "prestasi siswa", "lomba", "beasiswa", "pip"],
        "filenames": ["tata_tertib", "ekskul", "kesiswaan", "osis", "tata-tertib"],
    },
    "kepegawaian": {
        "keywords": ["guru", "wali kelas", "nip", "staf", "tu", "tata usaha", "tenaga pendidik", "kepala tu", "pengajar"],
        "filenames": ["guru", "kepegawaian", "staf", "wali_kelas"],
    },
}


def detect_query_intent(question: str) -> list[str]:
    """Deteksi kategori tematik dokumen berdasarkan kata kunci pertanyaan."""
    q_lower = question.lower()
    matched = []
    for cat, data in THEMATIC_CATEGORIES.items():
        if any(kw in q_lower for kw in data["keywords"]):
            matched.append(cat)
    return matched


def infer_document_category(filename: str) -> str:
    """Inferensi kategori dokumen dari nama file PDF secara otomatis."""
    fname_lower = filename.lower()
    for cat, data in THEMATIC_CATEGORIES.items():
        if any(fn in fname_lower for fn in data["filenames"]):
            return cat
    return "public"


def rerank_documents(
    question: str, docs: list[dict], final_k: int = None
) -> list[dict]:
    """Rerank dokumen berdasarkan kombinasi vector similarity, keyword overlap, dan category boosting."""
    if final_k is None:
        final_k = config.RAG_FINAL_K
    qwords = words(question)
    detected_intents = set(detect_query_intent(question))
    scored = []
    for i, doc in enumerate(docs):
        content = str(doc.get("content") or doc.get("text") or "")
        vector = float(doc.get("similarity") or doc.get("score") or doc.get("similarity_score") or 0)
        overlap = len(qwords & words(content)) / max(1, len(qwords))

        # Category and filename match boost
        category = str(doc.get("category") or "").lower()
        pdf_name = str(doc.get("pdf_name") or "").lower()

        boost = 0.0
        if detected_intents:
            if category in detected_intents:
                boost += 0.15
            elif any(intent in pdf_name for intent in detected_intents):
                boost += 0.10

        score = (vector * 0.65) + (overlap * 0.25) + boost
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
