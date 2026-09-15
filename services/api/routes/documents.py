# services/api/routes/documents.py — CRUD dokumen knowledge base
# Semua endpoint memerlukan autentikasi role teacher/admin
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from supabase import Client

from auth import authenticated_user
from models import DocumentRenameRequest, EmbedUpsertRequest
from ai.embedding import embed_text, validate_embedding
from ai.retrieval import fetch_document_rows, document_summary
from utils.helpers import extract_response_parts
import config

logger = logging.getLogger("aksaraku.routes.documents")

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
    """
    supabase = _get_supabase()
    _, role = authenticated_user(supabase, authorization)

    rows = fetch_document_rows(supabase)
    docs = document_summary(rows)

    if role not in {"admin", "teacher"}:
        docs = [d for d in docs if str(d.get("category") or "public").lower() == "public"]

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

    rows = fetch_document_rows(supabase)
    names = {str(r.get("pdf_name") or "").strip() for r in rows}
    if document_id not in names:
        raise HTTPException(404, "document not found")
    if new_name != document_id and new_name in names:
        raise HTTPException(409, "document name already exists")

    payload: dict = {"pdf_name": new_name}
    if body.category is not None:
        payload["category"] = body.category

    response = (
        supabase.table(config.SUPABASE_TABLE)
        .update(payload)
        .eq("pdf_name", document_id)
        .execute()
    )
    parts = extract_response_parts(response)
    if parts["error"]:
        raise HTTPException(500, str(parts["error"]))

    return {"data": {"id": new_name, "name": new_name, "pdf_name": new_name}}


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

    rows = fetch_document_rows(supabase)
    names = {str(r.get("pdf_name") or "").strip() for r in rows}
    if document_id not in names:
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
        row: dict = {
            "content": content,
            "pdf_name": chunk.pdf_name or None,
            "category": chunk.category,
        }
        if chunk.metadata is not None and config.SUPABASE_USE_METADATA:
            row[config.SUPABASE_METADATA_COLUMN] = chunk.metadata
        row["embedding"] = chunk.embedding if chunk.embedding is not None else embed_text(content)
        if not validate_embedding(row["embedding"]):
            raise HTTPException(400, f"Invalid embedding vector; expected {config.EXPECTED_EMBEDDING_DIMENSION} dimensions")
        rows.append(row)

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

    response = supabase.table(config.SUPABASE_TABLE).insert(rows).select("id, pdf_name, category, content").execute()
    parts = extract_response_parts(response)
    if parts["error"]:
        raise HTTPException(500, str(parts["error"]))

    return {"data": parts["data"] or []}
