# services/api/routes/admin.py — Admin dashboard dan manajemen user
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from supabase import Client

from auth import require_admin
from rag.retrieval import fetch_document_rows, document_summary
from utils.helpers import extract_response_parts

logger = logging.getLogger("aksaraku.routes.admin")

router = APIRouter(prefix="/admin", tags=["admin"])


def _get_supabase() -> Client:
    from app import supabase
    return supabase


def _fetch_table_rows(supabase: Client, table_name: str, limit: int = 1000) -> list[dict]:
    response = supabase.table(table_name).select("*").limit(limit).execute()
    parts = extract_response_parts(response)
    if parts["error"]:
        raise HTTPException(500, str(parts["error"]))
    return parts["data"] or []


def _dashboard_activity(rows: list[dict], label: str, name_key: str) -> list[dict]:
    activities = []
    for row in rows:
        name = row.get(name_key) or row.get("title") or row.get("content") or "Aktivitas baru"
        timestamp = row.get("updated_at") or row.get("created_at") or row.get("inserted_at")
        activities.append({"label": label, "name": str(name)[:120], "timestamp": timestamp})
    return activities


@router.get("/dashboard")
async def admin_dashboard(authorization: Optional[str] = Header(default=None)):
    """Statistik dashboard — hanya untuk admin."""
    supabase = _get_supabase()
    require_admin(supabase, authorization)

    document_rows = _fetch_table_rows(supabase, "pdf_documents", 10000)
    profiles = _fetch_table_rows(supabase, "profiles", 1000)
    sessions = _fetch_table_rows(supabase, "chat_sessions", 1000)
    messages = _fetch_table_rows(supabase, "chat_messages", 1000)
    documents = document_summary(document_rows)

    category_counts = {"public": 0, "private": 0}
    for document in documents:
        category = str(document.get("category") or "public").lower()
        category_counts[category if category in category_counts else "public"] += 1

    role_counts = {"admin": 0, "teacher": 0, "user": 0, "other": 0}
    for profile in profiles:
        profile_role = str(profile.get("role") or "user").strip().lower()
        role_counts[profile_role if profile_role in role_counts else "other"] += 1

    recent_users = sorted(
        [
            {
                "id": p.get("id"),
                "email": p.get("email") or "",
                "full_name": p.get("full_name") or p.get("email") or "Pengguna",
                "role": str(p.get("role") or "user").lower(),
                "provider": p.get("provider") or "email",
                "created_at": p.get("created_at"),
            }
            for p in profiles
        ],
        key=lambda item: str(item.get("created_at") or ""),
        reverse=True,
    )

    messages_role_counts = {"user": 0, "assistant": 0}
    for message in messages:
        message_role = str(message.get("role") or "").lower()
        if message_role in messages_role_counts:
            messages_role_counts[message_role] += 1

    activities = (
        _dashboard_activity(documents, "Dokumen", "pdf_name")
        + _dashboard_activity(sessions, "Sesi chat", "title")
        + _dashboard_activity(messages, "Pesan AI", "content")
        + _dashboard_activity(recent_users, "Pengguna", "full_name")
    )
    activities.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)

    return {
        "stats": {
            "documents": len(documents),
            "chunks": len(document_rows),
            "users": len(profiles),
            "sessions": len(sessions),
            "messages": len(messages),
            "public_documents": category_counts["public"],
            "private_documents": category_counts["private"],
            "users_by_role": role_counts,
            "messages_by_role": messages_role_counts,
        },
        "documents": documents[:8],
        "activity": activities[:10],
        "recent_users": recent_users[:8],
    }


@router.delete("/users/{user_id}")
async def delete_admin_user(user_id: str, authorization: Optional[str] = Header(default=None)):
    """Hapus user — hanya untuk admin."""
    supabase = _get_supabase()
    admin_id, _ = require_admin(supabase, authorization)

    if user_id == admin_id:
        raise HTTPException(400, "Admin tidak dapat menghapus akun sendiri")

    try:
        result = supabase.auth.admin.delete_user(user_id)
        parts = extract_response_parts(result)
        if parts["error"]:
            raise RuntimeError(str(parts["error"]))
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Auth user deletion failed: %s", exc)
        raise HTTPException(500, "Gagal menghapus akun Auth")

    try:
        supabase.table("profiles").delete().eq("id", user_id).execute()
    except Exception as exc:
        logger.warning("Profile deletion after Auth deletion failed: %s", exc)

    return {"success": True, "user_id": user_id}
