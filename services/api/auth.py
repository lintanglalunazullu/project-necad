# services/api/auth.py — Autentikasi dan otorisasi berbasis role
import logging
from typing import Any, Optional

from fastapi import HTTPException
from supabase import Client

logger = logging.getLogger("aksaraku.auth")


def _extract_profile_role(response: Any) -> Optional[str]:
    from utils.helpers import extract_response_parts

    parts = extract_response_parts(response)
    if parts["error"]:
        return None
    data = parts["data"]
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict):
        return None
    return str(data.get("role")).strip().lower() if data.get("role") is not None else None


def authenticated_user(supabase: Client, authorization: Optional[str]) -> tuple[str, str]:
    """
    Validasi Bearer token dan kembalikan (user_id, role).
    Raise HTTPException 401/403 jika tidak valid.
    """
    if not isinstance(authorization, str) or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Bearer token is required")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(401, "Bearer token is required")

    try:
        auth = supabase.auth.get_user(token)
        user = getattr(auth, "user", None) or (auth.get("user") if isinstance(auth, dict) else None)
        user_id = getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None)
        if not user_id:
            raise ValueError("user missing")
    except Exception as exc:
        logger.warning("Token validation failed: %s", exc)
        raise HTTPException(401, "Invalid or expired token")

    try:
        profile = supabase.table("profiles").select("role").eq("id", user_id).limit(1).execute()
    except Exception as exc:
        logger.warning("Profile lookup failed: %s", exc)
        raise HTTPException(403, "User profile is not available")

    role = _extract_profile_role(profile)
    if role not in {"user", "teacher", "admin"}:
        raise HTTPException(403, "User role is not valid")

    return str(user_id), role


def authenticated_role(supabase: Client, authorization: Optional[str]) -> str:
    """Kembalikan hanya role dari token yang valid."""
    return authenticated_user(supabase, authorization)[1]


def chat_role(supabase: Client, authorization: Optional[str]) -> str:
    """
    Kembalikan role untuk endpoint chat.
    Jika tidak ada token → anonymous (boleh chat, tapi tanpa sesi tersimpan).
    """
    if not isinstance(authorization, str) or not authorization.strip():
        return "anonymous"
    return authenticated_role(supabase, authorization)


def require_admin(supabase: Client, authorization: Optional[str]) -> tuple[str, str]:
    """Validasi token dan pastikan role-nya admin. Raise 403 jika bukan."""
    user_id, role = authenticated_user(supabase, authorization)
    if role != "admin":
        raise HTTPException(403, "Admin role is required")
    return user_id, role


def allowed_categories(role: str) -> list[str]:
    """Kembalikan kategori dokumen yang boleh diakses berdasarkan role."""
    return ["public", "private"] if role in {"teacher", "admin"} else ["public"]


def filter_documents_for_role(
    documents: list[dict], role: str
) -> list[dict]:
    """Filter dokumen berdasarkan kategori yang diizinkan untuk role tersebut."""
    categories = set(allowed_categories(role))
    return [
        doc
        for doc in documents
        if (
            role in {"teacher", "admin"} and not doc.get("category")
        )
        or str(doc.get("category") or "public").strip().lower() in categories
    ]


def filter_rpc_documents_for_role(
    documents: list[dict], role: str
) -> list[dict]:
    """
    Filter hasil RPC untuk role yang tidak dipercaya.
    Row tanpa category tidak bisa dipastikan public, jadi tidak ditampilkan ke user biasa.
    """
    if role in {"teacher", "admin"}:
        return filter_documents_for_role(documents, role)
    return [
        doc
        for doc in documents
        if str(doc.get("category") or "").strip().lower() == "public"
    ]
