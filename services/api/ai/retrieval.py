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
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

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


SLANG_MAP = {
    "walas": "wali kelas",
    "wali kls": "wali kelas",
    "kepsek": "kepala sekolah",
    "wakasek": "wakil kepala sekolah",
    "eskul": "ekstrakurikuler",
    "ekskul": "ekstrakurikuler",
    "sarpras": "sarana prasarana",
    "telp": "telepon",
    "tlp": "telepon",
    "hp": "telepon",
    "handphone": "telepon",
    "kontak": "telepon",
    "nohp": "nomor telepon",
    "no": "nomor",
    "mapel": "mata pelajaran",
    "mtk": "matematika",
    "penjas": "pjok",
    "penjaskes": "pjok",
    "olahraga": "pjok",
    "solat": "shalat",
    "sholat": "shalat",
    "dzuhur": "dhuhur",
    "zuhur": "dhuhur",
    "ashar": "ashar",
    "asar": "ashar",
    "sklh": "sekolah",
    "skolah": "sekolah",
    "sekola": "sekolah",
    "latian": "latihan",
    "dihukum": "sanksi",
    "hukuman": "sanksi",
    "brp": "berapa",
    "berpa": "berapa",
    "piro": "berapa",
    "sp": "siapa",
    "syp": "siapa",
    "sapaeh": "siapa",
    "kpn": "kapan",
    "dmn": "dimana",
    "dimn": "dimana",
    "gmn": "bagaimana",
    "gimana": "bagaimana",
    "knp": "mengapa",
    "napa": "mengapa",
    "kenape": "mengapa",
    "klo": "kalau",
    "kl": "kalau",
    "kalo": "kalau",
    "krn": "karena",
    "karna": "karena",
    "bwt": "untuk",
    "utk": "untuk",
    "dgn": "dengan",
    "dr": "dari",
    "tp": "tetapi",
    "tpi": "tetapi",
    "yg": "yang",
    "udh": "sudah",
    "udah": "sudah",
    "sdh": "sudah",
    "blm": "belum",
    "lom": "belum",
    "ga": "tidak",
    "gak": "tidak",
    "nggak": "tidak",
    "ngga": "tidak",
    "engga": "tidak",
    "kagak": "tidak",
    "bgt": "sangat",
    "banget": "sangat",
    "tau": "tahu",
    "tw": "tahu",
    "info": "informasi",
    "inpo": "informasi",
    "sy": "saya",
    "gw": "saya",
    "gue": "saya",
    "gua": "saya",
    "lu": "kamu",
    "lo": "kamu",
    "loe": "kamu",
    "skrg": "sekarang",
    "tu": "",
    "tuh": "",
}

CHAT_FILLERS = {
    "si", "sih", "aja", "ajah", "doang", "lah", "kah", "pun", "deh", "dong", "dunk",
    "nih", "kan", "ya", "yah", "woy", "rek", "min", "admin", "bang", "kak", "pak", "bu",
    "om", "tante", "gan", "coy", "bray", "ges", "guys", "beneran", "dah", "bro", "sis",
    "disini", "situ", "sini", "kok", "loh", "lho", "toh", "cik", "teh", "mah", "atuh", "euy", "punten", "wae", "geura", "pisan"
}

ID_STOPWORDS = {
    "apa", "apakah", "siapa", "siapakah", "bagaimana", "bagaimanakah", "mengapa", "kenapa", "kapan",
    "dimana", "dimanakah", "mana", "yang", "dan", "di", "ke", "dari", "pada", "untuk", "dengan",
    "ini", "itu", "atau", "adalah", "yaitu", "sebagai", "bisa", "dapat", "ada",
    "saya", "kamu", "anda", "kami", "kita", "mereka", "dia", "nya", "tolong",
    "coba", "jelaskan", "sebutkan", "tentang", "kasih", "tahu", "beri", "detail", "detailnya",
    "berapa", "berapakah", "nomor", "no", "jumlah", "total", "sekolah",
    # Chat fillers, slang particles, conversational noise
    "si", "sih", "aja", "ajah", "doang", "lah", "kah", "pun", "deh", "dong", "dunk", "nih",
    "tuh", "tu", "kan", "ya", "yah", "toh", "kok", "loh", "lho", "woy", "rek", "min", "admin",
    "bang", "kak", "pak", "bu", "om", "tante", "gan", "coy", "bray", "ges", "guys", "beneran",
    "dah", "bro", "sis", "disini", "situ", "sini", "klo", "kl", "kalo", "krn", "karna", "bwt",
    "utk", "dgn", "dr", "tp", "tpi", "yg", "udh", "udah", "sdh", "blm", "lom", "ga", "gak",
    "nggak", "ngga", "engga", "kagak", "bgt", "banget", "tau", "tw", "sp", "syp", "brp",
    "kpn", "dmn", "gmn", "knp", "sy", "aku", "gw", "gue", "gua", "lu", "lo", "loe", "skrg",
    "cik", "teh", "mah", "atuh", "euy", "punten", "wae", "geura", "pisan"
}

SEED_SLANG_MAP = SLANG_MAP

KEY_ENTITIES = [
    "luas tanah", "luas bangunan", "kepala sekolah", "wali kelas",
    "tata tertib", "kalender pendidikan", "ekstrakurikuler", "jadwal",
    "npsn", "nss", "nisn", "nip", "kkm", "visi", "misi",
    "telepon", "telp", "pramuka", "osis", "paskibra", "pmr", "akreditasi",
    "semester", "libur", "anbk", "pts", "pas", "pat", "kisi-kisi",
    "eskul", "ekskul", "walas", "kepsek", "guru ipa", "guru mtk", "guru pjok",
    "bahasa sunda", "jadwal ekstrakurikuler", "toilet", "lab komputer"
]

ROMAN_MAP = {"7": "VII", "8": "VIII", "9": "IX"}
REV_ROMAN_MAP = {"vii": "7", "viii": "8", "ix": "9"}


class LearnedSynonymsRegistry:
    """Registry memori mandiri thread-safe untuk menyimpan kosakata dan sinonim yang dipelajari AI."""
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        self._learned_cache: dict[str, str] = {}
        self._items_metadata: list[dict] = []
        self._last_synced: float = 0.0
        self._sync_interval: float = 30.0  # sync tiap 30 detik

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def sync_from_db(self, supabase: Optional[Client] = None, force: bool = False) -> None:
        if not supabase:
            return
        now = time.time()
        if not force and (now - self._last_synced < self._sync_interval):
            return

        with self._lock:
            try:
                # 1. Coba baca dari tabel ai_learned_synonyms jika ada
                try:
                    res = supabase.table("ai_learned_synonyms").select("*").order("occurrences", desc=True).execute()
                    rows = res.data or []
                except Exception:
                    # 2. Fallback: baca dari tabel ai_provider_config baris 'learned_synonyms'
                    res = supabase.table(config.AI_CONFIG_TABLE).select("system_prompt_extra").eq("id", "learned_synonyms").limit(1).execute()
                    rows = []
                    if res.data and res.data[0].get("system_prompt_extra"):
                        rows = json.loads(res.data[0]["system_prompt_extra"])

                new_cache = {}
                for r in rows:
                    slang = str(r.get("slang_word") or "").strip().lower()
                    canonical = str(r.get("canonical_word") or "").strip().lower()
                    if slang and canonical:
                        new_cache[slang] = canonical

                self._learned_cache = new_cache
                self._items_metadata = rows
                self._last_synced = now
            except Exception as exc:
                logger.debug("Synonym sync skipped: %s", exc)

    def get_all_synonyms(self, supabase: Optional[Client] = None) -> dict[str, str]:
        if supabase:
            self.sync_from_db(supabase)
        with self._lock:
            merged = dict(SEED_SLANG_MAP)
            merged.update(self._learned_cache)
            return merged

    def get_learned_list(self, supabase: Optional[Client] = None) -> list[dict]:
        if supabase:
            self.sync_from_db(supabase)
        with self._lock:
            return list(self._items_metadata)

    def record_learned_term(
        self,
        supabase: Client,
        slang_word: str,
        canonical_word: str,
        source: str = "auto_chat"
    ) -> bool:
        slang = slang_word.strip().lower()
        canonical = canonical_word.strip().lower()
        if not slang or not canonical or len(slang) < 2 or slang == canonical:
            return False
        if slang in ID_STOPWORDS or slang in CHAT_FILLERS:
            return False

        with self._lock:
            self._learned_cache[slang] = canonical

            # Simpan ke Supabase
            try:
                try:
                    supabase.table("ai_learned_synonyms").upsert({
                        "slang_word": slang,
                        "canonical_word": canonical,
                        "source": source,
                        "updated_at": datetime.now(timezone.utc).isoformat()
                    }, on_conflict="slang_word").execute()
                except Exception:
                    existing = list(self._items_metadata)
                    found = False
                    for item in existing:
                        if item.get("slang_word") == slang:
                            item["canonical_word"] = canonical
                            item["occurrences"] = item.get("occurrences", 1) + 1
                            item["updated_at"] = datetime.now(timezone.utc).isoformat()
                            found = True
                            break
                    if not found:
                        existing.append({
                            "slang_word": slang,
                            "canonical_word": canonical,
                            "occurrences": 1,
                            "source": source,
                            "learned_at": datetime.now(timezone.utc).isoformat(),
                            "updated_at": datetime.now(timezone.utc).isoformat()
                        })
                    self._items_metadata = existing
                    supabase.table(config.AI_CONFIG_TABLE).upsert({
                        "id": "learned_synonyms",
                        "enabled": True,
                        "model": "auto-smart-v1",
                        "system_prompt_extra": json.dumps(existing),
                        "priority": 99
                    }).execute()
                return True
            except Exception as exc:
                logger.warning("Failed to persist learned synonym: %s", exc)
                return False

    def delete_learned_term(self, supabase: Client, slang_word: str) -> bool:
        slang = slang_word.strip().lower()
        with self._lock:
            self._learned_cache.pop(slang, None)
            try:
                try:
                    supabase.table("ai_learned_synonyms").delete().eq("slang_word", slang).execute()
                except Exception:
                    existing = [it for it in self._items_metadata if it.get("slang_word") != slang]
                    self._items_metadata = existing
                    supabase.table(config.AI_CONFIG_TABLE).upsert({
                        "id": "learned_synonyms",
                        "enabled": True,
                        "model": "auto-smart-v1",
                        "system_prompt_extra": json.dumps(existing),
                        "priority": 99
                    }).execute()
                return True
            except Exception as exc:
                logger.warning("Failed to delete learned synonym: %s", exc)
                return False


def get_synonyms_registry() -> LearnedSynonymsRegistry:
    return LearnedSynonymsRegistry.get_instance()


def reformulate_with_llm(question: str) -> dict:
    """
    Gunakan LLM ultra-cepat (Gemini 3.5 Flash-Lite) untuk mendekonstruksi pertanyaan dengan bahasa gaul
    atau bahasa daerah baru menjadi format baku dan mendeteksi kosakata baru.
    """
    if not question:
        return {"canonical_query": "", "search_keywords": [], "new_slang_detected": []}

    try:
        from ai.generation import get_provider_manager, _call_gemini
        manager = get_provider_manager()
        gemini_provider = manager.get_provider("gemini")
        if not gemini_provider:
            return {"canonical_query": question, "search_keywords": [], "new_slang_detected": []}

        messages = [
            {
                "role": "system",
                "content": (
                    "Anda adalah modul analisis bahasa untuk sistem pencarian dokumen AI sekolah SMP Negeri 2 Cibungbulang.\n"
                    "Tugas:\n"
                    "1. Ubah maksud pertanyaan pengguna ke dalam bahasa Indonesia baku formal yang cocok untuk pencarian dokumen sekolah.\n"
                    "2. Berikan daftar 2-4 kata kunci pencarian penting.\n"
                    "3. Jika ada kata gaul/singkatan/bahasa daerah baru yang bukan bahasa baku, identifikasi setiap kata per kata tunggal (jangan menggabungkan kata filler/partikel).\n\n"
                    "Keluarkan HANYA format JSON valid berikut:\n"
                    "{\n"
                    "  \"canonical_query\": \"...\",\n"
                    "  \"search_keywords\": [\"...\"],\n"
                    "  \"new_slang_detected\": [{\"slang\": \"...\", \"canonical\": \"...\"}]\n"
                    "}"
                ),
            },
            {"role": "user", "content": f"Pertanyaan pengguna: \"{question}\""}
        ]

        raw_text, _ = _call_gemini(gemini_provider, messages)
        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text)
            raw_text = re.sub(r"\n?```$", "", raw_text).strip()

        data = json.loads(raw_text)
        return {
            "canonical_query": str(data.get("canonical_query") or question).strip(),
            "search_keywords": [str(k).strip() for k in data.get("search_keywords", []) if str(k).strip()],
            "new_slang_detected": data.get("new_slang_detected") or []
        }
    except Exception as exc:
        logger.debug("LLM reformulation skipped: %s", exc)
        return {"canonical_query": question, "search_keywords": [], "new_slang_detected": []}


def auto_extract_and_learn_synonyms(
    supabase: Client,
    question: str,
    docs: list[dict],
    answer: str,
    evidence: dict,
    new_terms: list[dict] = None
) -> None:
    """Secara otomatis mencatat kosakata gaul/daerah baru yang terbukti berhasil menghasilkan jawaban akurat."""
    if not supabase or not question or not docs:
        return
    if not evidence.get("supported"):
        return

    registry = LearnedSynonymsRegistry.get_instance()
    if new_terms:
        for t in new_terms:
            slang = str(t.get("slang") or t.get("slang_word") or "").strip().lower()
            canonical = str(t.get("canonical") or t.get("canonical_word") or "").strip().lower()
            if slang and canonical:
                registry.record_learned_term(supabase, slang, canonical, source="auto_chat")
                # Jika slang berbentuk gabungan frasa (mis. 'cik saha'), ekstrak kata inti non-filler ('saha')
                if " " in slang:
                    for p in slang.split():
                        if p not in CHAT_FILLERS and p not in ID_STOPWORDS:
                            registry.record_learned_term(supabase, p, canonical, source="auto_chat")






def extract_class_tokens(text: str) -> list[str]:
    """Ekstrak variasi kelas (7.1, 7-1, VII-1, VII.1) baik Romawi maupun Arab."""
    results = []
    t_lower = text.lower()
    # Format numerik: 7.1, 7-1, 7 1, 8.4, 9.5, dst.
    m_num = re.search(r"\b([789])[\.\-\s_](\d{1,2})\b", t_lower)
    if m_num:
        grade, num = m_num.group(1), m_num.group(2)
        rom = ROMAN_MAP.get(grade, grade)
        results.extend([
            f"{rom}-{num}",
            f"{rom}.{num}",
            f"{grade}.{num}",
            f"{grade}-{num}",
            f"kelas {rom}-{num}",
            f"kelas {grade}.{num}",
        ])
    # Format romawi: VII-1, IX-5, dst.
    m_rom = re.search(r"\b(vii|viii|ix)[\.\-\s_](\d{1,2})\b", t_lower)
    if m_rom:
        rom_str, num = m_rom.group(1), m_rom.group(2)
        grade = REV_ROMAN_MAP.get(rom_str, rom_str)
        rom_upper = rom_str.upper()
        results.extend([
            f"{rom_upper}-{num}",
            f"{rom_upper}.{num}",
            f"{grade}.{num}",
            f"{grade}-{num}",
            f"kelas {rom_upper}-{num}",
            f"kelas {grade}.{num}",
        ])
    return list(dict.fromkeys(results))


def normalize_informal_query(query: str, supabase: Optional[Client] = None) -> str:
    """Normalisasi pertanyaan gaul / informal menjadi teks pencarian semantik bersih."""
    if not query:
        return ""
    active_synonyms = LearnedSynonymsRegistry.get_instance().get_all_synonyms(supabase)
    cleaned = re.sub(r"[\?\!\.,;:]+", " ", query.lower()).strip()

    # 1. Ganti frasa multi-kata terlebih dahulu (diurutkan dari yang paling panjang)
    multi_word_keys = sorted([k for k in active_synonyms if " " in k], key=len, reverse=True)
    for phrase in multi_word_keys:
        val = active_synonyms[phrase]
        cleaned = re.sub(rf"\b{re.escape(phrase)}\b", f" {val} ", cleaned)

    words_list = cleaned.split()
    mapped = []
    for w in words_list:
        w_clean = active_synonyms.get(w, w)
        if w_clean and w_clean not in CHAT_FILLERS:
            mapped.append(w_clean)
    res = " ".join(mapped).strip()
    return res or query


def _strip_id_affixes(word: str) -> str:
    """Hapus akhiran/imbuhan umum bahasa Indonesia (-nya, -lah, -kah, -pun)."""
    w = word.lower()
    for suffix in ("nya", "lah", "kah", "pun"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            return w[:-len(suffix)]
    return w


def _extract_search_candidates(query: str, supabase: Optional[Client] = None) -> list[str]:
    """Ekstrak beberapa kombinasi kata kunci bertingkat dari pertanyaan dengan prioritas entitas dan kelas."""
    ql = query.lower()
    candidates: list[str] = []
    active_synonyms = LearnedSynonymsRegistry.get_instance().get_all_synonyms(supabase)

    # 1. Deteksi nomor kelas (Arab & Romawi: 9.5 <-> IX-5)
    class_tokens = extract_class_tokens(query)
    for ct in class_tokens:
        candidates.append(ct)
        if "walas" in ql or "wali" in ql:
            candidates.append(f"wali kelas {ct}")

    # 2. Deteksi entitas kunci sekolah
    for ent in KEY_ENTITIES:
        if ent in ql:
            canonical_ent = active_synonyms.get(ent, ent)
            candidates.append(canonical_ent)
            if ent in ("telepon", "telp"):
                candidates.extend(["telp", "telepon"])
            elif ent in ("eskul", "ekskul", "ekstrakurikuler"):
                candidates.extend(["ekstrakurikuler", "ekskul"])

    # 3. Query normalisasi (slang diganti, filler dibersihkan)
    normalized = normalize_informal_query(query, supabase)
    if normalized and normalized != ql:
        candidates.append(normalized)

    # 4. Tokenisasi kata & pemetaan kata bermakna
    tokens = re.findall(r"[a-zA-Z0-9]+", ql)
    mapped_tokens = [active_synonyms.get(t, t) for t in tokens if t]
    meaningful = [t for t in mapped_tokens if t and t not in ID_STOPWORDS]
    stemmed = [_strip_id_affixes(t) for t in meaningful]

    if meaningful:
        candidates.append(" ".join(meaningful))
        if len(meaningful) > 1:
            candidates.extend(meaningful)
    if stemmed and stemmed != meaningful:
        candidates.append(" ".join(stemmed))

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

    # Fallback pencarian langsung (ILIKE) untuk entitas kunci & kelas jika RPC mengembalikan 0 hasil
    for cand in queries[:6]:
        cand_clean = cand.strip()
        if len(cand_clean) >= 2 and cand_clean not in ID_STOPWORDS:
            try:
                qb = supabase.table(config.SUPABASE_TABLE).select("id, pdf_name, category, content")
                if categories:
                    qb = qb.in_("category", list(categories))
                res = qb.ilike("content", f"%{cand_clean}%").limit(top_k).execute()
                if res.data:
                    for r in res.data:
                        r["similarity"] = 0.5
                        r["keyword_score"] = 1.0
                    return res.data
            except Exception as exc:
                logger.debug("ILIKE fallback search skipped: %s", exc)

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
        "keywords": ["kurikulum", "jadwal", "pelajaran", "mapel", "ujian", "pts", "pas", "pat", "rapor", "kelulusan", "kalender", "semester", "kkm", "asesmen", "anbk", "libur", "kisi-kisi", "mtk", "matematika", "penjas", "pjok", "olahraga"],
        "filenames": ["kurikulum", "akademik", "jadwal", "kalender", "pedoman"],
    },
    "profil": {
        "keywords": ["visi", "misi", "sejarah", "kepala sekolah", "profil", "alamat", "kontak", "fasilitas", "sarana", "prasarana", "akreditasi", "npsn", "nss", "ruang", "gedung", "lapangan", "perpustakaan", "lab", "laboratorium", "tanah", "luas tanah", "luas bangunan", "telepon", "telp", "wa", "nohp", "nomor hp", "kepsek", "email", "toilet"],
        "filenames": ["profil", "profile", "visi_misi", "fasilitas", "sarpras"],
    },
    "kesiswaan": {
        "keywords": ["ekstrakurikuler", "ekskul", "eskul", "osis", "pramuka", "paskibra", "pmr", "tata tertib", "aturan", "seragam", "poin", "pelanggaran", "prestasi siswa", "lomba", "beasiswa", "pip", "jadwal eskul", "rohis", "futsal", "basket", "voli", "musik", "tari"],
        "filenames": ["tata_tertib", "ekskul", "kesiswaan", "osis", "tata-tertib", "ekstrakurikuler", "jadwal-ekstrakurikuler"],
    },
    "kepegawaian": {
        "keywords": ["guru", "wali kelas", "walas", "nip", "staf", "tu", "tata usaha", "tenaga pendidik", "kepala tu", "pengajar", "wali", "kelas 7", "kelas 8", "kelas 9"],
        "filenames": ["guru", "kepegawaian", "staf", "wali_kelas", "wali-kelas", "absen"],
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
    """Rerank dokumen berdasarkan kombinasi vector similarity, keyword overlap, intent boosting, dan token kelas spesifik."""
    if final_k is None:
        final_k = config.RAG_FINAL_K
    qwords = words(question)
    detected_intents = set(detect_query_intent(question))
    class_tokens = [ct.lower() for ct in extract_class_tokens(question)]
    ql = question.lower()

    scored = []
    for i, doc in enumerate(docs):
        content = str(doc.get("content") or doc.get("text") or "").lower()
        vector = float(doc.get("similarity") or doc.get("score") or doc.get("similarity_score") or 0)
        overlap = len(qwords & words(content)) / max(1, len(qwords))

        category = str(doc.get("category") or "").lower()
        pdf_name = str(doc.get("pdf_name") or "").lower()

        boost = 0.0
        # 1. Boost jika dokumen sesuai kategori tematik pertanyaan
        if detected_intents:
            for cat in detected_intents:
                cat_filenames = THEMATIC_CATEGORIES.get(cat, {}).get("filenames", [])
                if any(fn in pdf_name for fn in cat_filenames):
                    boost += 0.20
                    break

        # 2. Boost kuat jika dokumen memuat kelas spesifik yang ditanyakan (misal 9.5 / IX-5)
        if class_tokens and any(ct in content for ct in class_tokens):
            boost += 0.35

        # 3. Boost jika dokumen memuat ekstrakurikuler saat ditanya eskul
        if any(ek in ql for ek in ("eskul", "ekskul", "ekstrakurikuler")):
            if "ekstrakurikuler" in pdf_name or "jadwal-ekstrakurikuler" in pdf_name:
                boost += 0.30

        # 4. Boost jika ditanya wali kelas / walas dan dokumen adalah wali-kelas
        if ("walas" in ql or "wali kelas" in ql) and "wali-kelas" in pdf_name:
            boost += 0.30

        score = (vector * 0.55) + (overlap * 0.20) + boost
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
