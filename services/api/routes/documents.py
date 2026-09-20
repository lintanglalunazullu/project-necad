import asyncio
import base64
import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from supabase import Client

from auth import authenticated_user, allowed_categories
from models import DocumentRenameRequest, DocumentSummaryRequest, EmbedUpsertRequest, OCRPageRequest
from ai.embedding import embed_text, validate_embedding
from ai.retrieval import fetch_document_summary
from ai.generation import get_provider_manager, _call_gemini
from utils.helpers import extract_response_parts
import config

logger = logging.getLogger("aksaraku.routes.documents")


def ocr_image_with_gemini(image_bytes: bytes) -> str:
    """Ekstrak teks, judul, dan tabel dari pindaian/gambar halaman PDF menggunakan Gemini Vision."""
    manager = get_provider_manager()
    keys = manager.get_provider_keys("gemini")
    if not keys and config.GEMINI_API_KEY:
        keys = [config.GEMINI_API_KEY]
    if not keys:
        raise RuntimeError("Tidak ada Gemini API Key yang tersedia untuk OCR.")

    prompt = (
        "Anda adalah modul OCR presisi tinggi untuk dokumen sekolah SMP Negeri 2 Cibungbulang.\n"
        "Tugas:\n"
        "1. Ekstrak seluruh teks, judul, paragraf, nomor butir, dan tabel dari gambar halaman dokumen ini.\n"
        "2. Jika ada tabel (misalnya: daftar guru, wali kelas, jadwal, nomor telepon, sanksi, nilai), "
        "format WAJIB menggunakan tabel Markdown rapi: | Kolom 1 | Kolom 2 | ...\n"
        "3. Pertahankan urutan, hierarki judul (#, ##, ###), dan daftar angka/poin.\n"
        "4. Keluarkan HANYA teks markdown hasil ekstraksi. Jangan menambahkan kata pengantar seperti 'Berikut adalah...' atau tanda pembuka/penutup ```markdown."
    )

    last_error = None
    try:
        from google import genai as modern_genai
        from google.genai import types as genai_types

        part = genai_types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        models_to_try = ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.5-flash"]
        for key in keys:
            for model_name in models_to_try:
                try:
                    client = modern_genai.Client(api_key=key.strip())
                    res = client.models.generate_content(
                        model=model_name,
                        contents=[part, prompt]
                    )
                    text = res.text.strip()
                    if text.startswith("```"):
                        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
                        text = re.sub(r"\n?```$", "", text).strip()
                    return text
                except Exception as exc:
                    last_error = exc
                    continue
    except ImportError:
        pass

    try:
        import google.generativeai as legacy_genai
        for key in keys:
            try:
                legacy_genai.configure(api_key=key.strip())
                model = legacy_genai.GenerativeModel("gemini-1.5-flash")
                res = model.generate_content([
                    {"mime_type": "image/jpeg", "data": image_bytes},
                    prompt
                ])
                text = res.text.strip()
                if text.startswith("```"):
                    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
                    text = re.sub(r"\n?```$", "", text).strip()
                return text
            except Exception as exc:
                last_error = exc
                continue
    except Exception as exc:
        last_error = exc

    raise RuntimeError(f"Gagal melakukan OCR pada halaman dokumen: {last_error}")

router = APIRouter(tags=["documents"])


def _get_supabase() -> Client:
    from app import supabase
    return supabase


@router.get("/documents")
async def list_documents(authorization: Optional[str] = Header(default=None)):
    """
    Ambil daftar dokumen.
    - Admin & Teacher: bisa lihat semua (public + private)
    - User biasa: hanya public

    Sebelumnya endpoint ini fetch SEMUA chunk (limit 10000) lalu group-by pdf_name
    di Python. Sekarang pakai RPC get_document_summary yang sudah GROUP BY di
    database — 1 baris per dokumen dikirim lewat network, bukan 1 baris per chunk.
    """
    supabase = _get_supabase()
    _, role = authenticated_user(supabase, authorization)

    docs = fetch_document_summary(supabase)

    if role not in {"admin", "teacher"}:
        allowed = set(allowed_categories(role))
        docs = [d for d in docs if str(d.get("category") or "").strip().lower() in allowed]

    return {"data": docs}


@router.put("/documents/{document_id}")
async def rename_document(
    document_id: str,
    body: DocumentRenameRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Rename / ubah kategori dokumen — hanya admin dan teacher."""
    supabase = _get_supabase()
    _, role = authenticated_user(supabase, authorization)
    if role not in {"admin", "teacher"}:
        raise HTTPException(403, "Teacher atau Admin role diperlukan")

    new_name = (body.name or body.pdf_name or document_id).strip()
    if not new_name:
        raise HTTPException(400, "name is required")

    # Cek keberadaan & bentrokan nama dengan query terarah (bukan fetch semua chunk).
    exists_res = (
        supabase.table(config.SUPABASE_TABLE)
        .select("pdf_name")
        .eq("pdf_name", document_id)
        .limit(1)
        .execute()
    )
    parts = extract_response_parts(exists_res)
    if parts["error"]:
        raise HTTPException(500, str(parts["error"]))
    if not (parts["data"] or []):
        raise HTTPException(404, "document not found")

    if new_name != document_id:
        collision_res = (
            supabase.table(config.SUPABASE_TABLE)
            .select("pdf_name")
            .eq("pdf_name", new_name)
            .limit(1)
            .execute()
        )
        collision_parts = extract_response_parts(collision_res)
        if collision_parts["error"]:
            raise HTTPException(500, str(collision_parts["error"]))
        if collision_parts["data"]:
            raise HTTPException(409, "document name already exists")

    payload: dict = {"pdf_name": new_name}
    if body.category is not None:
        valid_cat = "private" if str(body.category).strip().lower() == "private" else "public"
        payload["category"] = valid_cat

    response = (
        supabase.table(config.SUPABASE_TABLE)
        .update(payload)
        .eq("pdf_name", document_id)
        .execute()
    )
    parts = extract_response_parts(response)
    if parts["error"]:
        raise HTTPException(500, str(parts["error"]))

    return {"data": {"id": new_name, "name": new_name, "pdf_name": new_name, "category": payload.get("category", "public")}}


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    authorization: Optional[str] = Header(default=None),
):
    """Hapus dokumen beserta semua chunk-nya — hanya admin."""
    supabase = _get_supabase()
    _, role = authenticated_user(supabase, authorization)
    if role != "admin":
        raise HTTPException(403, "Admin role diperlukan untuk menghapus dokumen")

    from utils.helpers import extract_response_parts
    res = supabase.table(config.SUPABASE_TABLE).select("pdf_name").eq("pdf_name", document_id).limit(1).execute()
    parts = extract_response_parts(res)
    if parts["error"]:
        raise HTTPException(500, str(parts["error"]))
    if not parts["data"]:
        raise HTTPException(404, "document not found")

    response = (
        supabase.table(config.SUPABASE_TABLE)
        .delete()
        .eq("pdf_name", document_id)
        .execute()
    )
    parts = extract_response_parts(response)
    if parts["error"]:
        raise HTTPException(500, str(parts["error"]))

    return {"data": {"id": document_id, "deleted": True}}


@router.post("/embed-upsert")
async def embed_upsert(
    body: EmbedUpsertRequest,
    authorization: Optional[str] = Header(default=None),
):
    """
    Upload chunk teks dan generate embedding — hanya admin dan teacher.
    Embedding dibuat via Gemini text-embedding-004.
    """
    supabase = _get_supabase()
    _, role = authenticated_user(supabase, authorization)
    if role not in {"admin", "teacher"}:
        raise HTTPException(403, "Teacher atau Admin role diperlukan untuk upload materi")

    if not body.chunks:
        raise HTTPException(400, "invalid chunks")

    rows = []
    for chunk in body.chunks:
        content = chunk.text.strip()
        if not content:
            raise HTTPException(400, "content tidak boleh kosong")
        pdf_name = chunk.pdf_name or None
        cat = "private" if str(chunk.category).strip().lower() == "private" else "public"

        row: dict = {
            "content": content,
            "pdf_name": pdf_name,
            "category": cat,
        }
        if config.SUPABASE_USE_METADATA:
            from ai.retrieval import infer_document_category
            meta = dict(chunk.metadata or {})
            if pdf_name and "topic" not in meta:
                meta["topic"] = infer_document_category(pdf_name)
            row[config.SUPABASE_METADATA_COLUMN] = meta
        row["embedding"] = chunk.embedding if chunk.embedding is not None else embed_text(content)
        if not validate_embedding(row["embedding"]):
            raise HTTPException(400, f"Invalid embedding vector; expected {config.EXPECTED_EMBEDDING_DIMENSION} dimensions")
        rows.append(row)

    # Clean upsert: jika clean_upsert aktif (default True), bersihkan chunk versi lama
    # dengan nama pdf_name yang sama agar tidak terjadi tumpang-tindih data usang
    if body.clean_upsert is not False:
        pdf_names = {r["pdf_name"] for r in rows if r.get("pdf_name")}
        for name in pdf_names:
            try:
                supabase.table(config.SUPABASE_TABLE).delete().eq("pdf_name", name).execute()
                logger.info("Clean-upsert: purged existing chunks for '%s'", name)
            except Exception as clean_err:
                logger.warning("Clean-upsert purge warning for '%s': %s", name, clean_err)

    response = supabase.table(config.SUPABASE_TABLE).insert(rows).select("id, pdf_name, category, content").execute()
    parts = extract_response_parts(response)
    if parts["error"]:
        raise HTTPException(500, str(parts["error"]))

    return {"success": True, "data": parts["data"] or []}


@router.post("/embed-upsert-raw")
async def embed_upsert_raw(
    body: EmbedUpsertRequest,
    authorization: Optional[str] = Header(default=None),
):
    """
    Upload chunk dengan embedding yang sudah dihitung — hanya admin dan teacher.
    """
    supabase = _get_supabase()
    _, role = authenticated_user(supabase, authorization)
    if role not in {"admin", "teacher"}:
        raise HTTPException(403, "Teacher atau Admin role diperlukan untuk upload materi")

    if not body.chunks:
        raise HTTPException(400, "invalid chunks")

    rows = []
    for chunk in body.chunks:
        if chunk.embedding is None:
            raise HTTPException(400, "Missing embedding for chunk")
        if not validate_embedding(chunk.embedding):
            raise HTTPException(400, f"Invalid embedding; expected {config.EXPECTED_EMBEDDING_DIMENSION} dimensions")
        row: dict = {
            "pdf_name": chunk.pdf_name or None,
            "content": chunk.text.strip(),
            "category": chunk.category,
            "embedding": chunk.embedding,
        }
        if config.SUPABASE_USE_METADATA and chunk.metadata is not None:
            row[config.SUPABASE_METADATA_COLUMN] = chunk.metadata
        rows.append(row)

    if body.clean_upsert is not False:
        pdf_names = {r["pdf_name"] for r in rows if r.get("pdf_name")}
        for name in pdf_names:
            try:
                supabase.table(config.SUPABASE_TABLE).delete().eq("pdf_name", name).execute()
                logger.info("Clean-upsert raw: purged existing chunks for '%s'", name)
            except Exception as clean_err:
                logger.warning("Clean-upsert purge warning for '%s': %s", name, clean_err)

    response = supabase.table(config.SUPABASE_TABLE).insert(rows).select("id, pdf_name, category, content").execute()
    parts = extract_response_parts(response)
    if parts["error"]:
        raise HTTPException(500, str(parts["error"]))

    return {"data": parts["data"] or []}


@router.post("/documents/ocr-page")
async def ocr_page(
    body: OCRPageRequest,
    authorization: Optional[str] = Header(default=None),
):
    """
    Ekstrak teks dan tabel dari halaman PDF berupa pindaian/gambar via Gemini Flash Vision.
    Hanya untuk teacher dan admin.
    """
    supabase = _get_supabase()
    _, role = authenticated_user(supabase, authorization)
    if role not in {"admin", "teacher"}:
        raise HTTPException(403, "Teacher atau Admin role diperlukan untuk OCR dokumen")

    raw_b64 = body.image_base64
    if "," in raw_b64:
        raw_b64 = raw_b64.split(",", 1)[1]

    try:
        image_bytes = base64.b64decode(raw_b64)
    except Exception as exc:
        raise HTTPException(400, f"Format gambar base64 tidak valid: {exc}")

    try:
        extracted_markdown = await asyncio.to_thread(ocr_image_with_gemini, image_bytes)
        return {
            "success": True,
            "page_num": body.page_num or 1,
            "markdown_text": extracted_markdown
        }
    except Exception as exc:
        logger.error("OCR Vision failed: %s", exc)
        raise HTTPException(500, f"Gagal mengekstrak teks via Vision OCR: {exc}")


@router.post("/documents/summarize-and-suggest")
async def summarize_and_suggest(
    body: DocumentSummaryRequest,
    authorization: Optional[str] = Header(default=None),
):
    """
    Buat ringkasan dan rekomendasi contoh pertanyaan yang relevan dari dokumen baru.
    Hanya untuk teacher dan admin.
    """
    supabase = _get_supabase()
    _, role = authenticated_user(supabase, authorization)
    if role not in {"admin", "teacher"}:
        raise HTTPException(403, "Teacher atau Admin role diperlukan")

    doc_name = body.document_name.strip()
    sample = body.sample_text.strip()[:6000]
    if not sample:
        raise HTTPException(400, "sample_text tidak boleh kosong")

    manager = get_provider_manager()
    gemini = manager.get_provider("gemini")
    if not gemini:
        return {"summary": "", "suggested_questions": []}

    messages = [
        {
            "role": "system",
            "content": (
                "Anda adalah asisten AI sekolah SMP Negeri 2 Cibungbulang.\n"
                "Tugas: baca sampel isi dokumen sekolah, lalu buat ringkasan dokumen dan 3-5 contoh pertanyaan siswa/wali murid.\n"
                "Keluarkan HANYA format JSON valid berikut tanpa markdown ```:\n"
                "{\n"
                "  \"summary\": \"Ringkasan 2-3 kalimat...\",\n"
                "  \"suggested_questions\": [\"Pertanyaan 1?\", \"Pertanyaan 2?\"]\n"
                "}"
            ),
        },
        {
            "role": "user",
            "content": f"Nama dokumen: \"{doc_name}\"\nIsi sampel dokumen:\n{sample}"
        }
    ]

    try:
        raw_text, _ = await asyncio.to_thread(_call_gemini, gemini, messages)
        raw_text = raw_text.strip()
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text)
            raw_text = re.sub(r"\n?```$", "", raw_text).strip()
        data = json.loads(raw_text)
        return {
            "success": True,
            "document_name": doc_name,
            "summary": str(data.get("summary") or "").strip(),
            "suggested_questions": data.get("suggested_questions") or []
        }
    except Exception as exc:
        logger.warning("Summarize and suggest skipped: %s", exc)
        return {
            "success": False,
            "document_name": doc_name,
            "summary": "",
            "suggested_questions": []
        }
