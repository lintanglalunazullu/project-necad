# services/api/routes/admin.py — Admin dashboard, manajemen user, dan AI provider config
import logging
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from supabase import Client

from auth import require_admin
from ai.retrieval import fetch_document_rows, document_summary
from ai.generation import get_provider_manager
from utils.helpers import extract_response_parts

logger = logging.getLogger("aksaraku.routes.admin")

router = APIRouter(prefix="/admin", tags=["admin"])


# ======================= HELPERS =======================

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


# ======================= DASHBOARD =======================

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


# ======================= USER MANAGEMENT =======================

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


# ======================= AI PROVIDER CONFIG =======================

class ProviderUpdateRequest(BaseModel):
    enabled: Optional[bool] = Field(default=None, description="Aktifkan atau nonaktifkan provider")
    model: Optional[str] = Field(default=None, description="Model string, misal: gemini-2.0-flash")
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0, description="0.0-2.0")
    max_tokens: Optional[int] = Field(default=None, gt=0, le=8192, description="Batas output token")
    priority: Optional[int] = Field(default=None, ge=1, le=10, description="Urutan fallback (1=tertinggi)")
    timeout: Optional[float] = Field(default=None, gt=0, le=120, description="Timeout detik")
    system_prompt_extra: Optional[str] = Field(default=None, description="Instruksi tambahan khusus provider ini")


class ProviderTestRequest(BaseModel):
    provider: str = Field(description="Nama provider: gemini, groq, openrouter")
    prompt: Optional[str] = Field(default="Halo, siapa kamu?", description="Prompt test")


@router.get("/ai/providers")
async def list_ai_providers(authorization: Optional[str] = Header(default=None)):
    """
    List semua AI provider beserta status, konfigurasi, dan statistik penggunaan.
    Hanya untuk admin.
    """
    require_admin(_get_supabase(), authorization)
    manager = get_provider_manager()
    return {
        "providers": [p.to_dict() for p in manager.get_all_providers()],
        "active_count": len(manager.get_sorted_providers()),
    }


@router.put("/ai/providers/{provider_name}")
async def update_ai_provider(
    provider_name: str,
    body: ProviderUpdateRequest,
    authorization: Optional[str] = Header(default=None),
):
    """
    Update konfigurasi satu AI provider secara runtime (tanpa restart server).
    Perubahan langsung berlaku untuk request berikutnya.
    Optionally, simpan ke Supabase agar survive restart.
    Hanya untuk admin.
    """
    supabase = _get_supabase()
    require_admin(supabase, authorization)

    manager = get_provider_manager()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}

    try:
        provider = manager.update_provider(provider_name, updates)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    # Simpan ke Supabase kalau tabelnya ada (graceful — tidak error kalau tabel belum dibuat)
    try:
        import config
        db_payload: dict[str, Any] = {"id": provider_name, **updates, "updated_at": "now()"}
        supabase.table(config.AI_CONFIG_TABLE).upsert(db_payload, on_conflict="id").execute()
        logger.info("AI provider config '%s' disimpan ke DB", provider_name)
    except Exception as exc:
        logger.info("Tidak bisa simpan ke DB (tabel mungkin belum ada): %s", exc)

    return {"success": True, "provider": provider.to_dict()}


@router.post("/ai/providers/test")
async def test_ai_provider(
    body: ProviderTestRequest,
    authorization: Optional[str] = Header(default=None),
):
    """
    Test satu provider dengan prompt dummy. Berguna untuk verifikasi API key dan model.
    Hanya untuk admin.
    """
    require_admin(_get_supabase(), authorization)

    manager = get_provider_manager()
    provider = manager.get_provider(body.provider)
    if not provider:
        raise HTTPException(404, f"Provider '{body.provider}' tidak ditemukan")

    if not provider.enabled:
        raise HTTPException(400, f"Provider '{body.provider}' sedang dinonaktifkan")

    import time
    start = time.perf_counter()
    error_msg = None
    answer = None

    try:
        from ai.generation import _call_gemini, _call_openai_compat
        messages = [
            {"role": "system", "content": "Kamu adalah asisten AI singkat dan informatif."},
            {"role": "user", "content": body.prompt},
        ]

        if body.provider == "gemini":
            answer, usage = _call_gemini(provider, messages)
        else:
            clients = manager.get_openai_clients(body.provider)
            if not clients:
                raise RuntimeError(f"Tidak ada API key terkonfigurasi untuk {body.provider}")
            answer, _, usage = _call_openai_compat(provider, clients, messages, 0)

    except Exception as exc:
        error_msg = str(exc)

    elapsed = round((time.perf_counter() - start) * 1000)

    return {
        "provider": body.provider,
        "model": provider.model,
        "success": error_msg is None,
        "answer": answer,
        "error": error_msg,
        "latency_ms": elapsed,
    }


@router.get("/ai/stats")
async def ai_provider_stats(authorization: Optional[str] = Header(default=None)):
    """
    Statistik penggunaan tiap AI provider (request count, error count, health status).
    Hanya untuk admin.
    """
    require_admin(_get_supabase(), authorization)
    manager = get_provider_manager()
    return {
        "providers": [
            {
                "name": p.name,
                "enabled": p.enabled,
                "priority": p.priority,
                "model": p.model,
                "is_healthy": p.is_healthy,
                "stats": {
                    "success_count": p._success_count,
                    "error_count": p._error_count,
                    "total_requests": p._total_requests,
                    "error_rate": round(
                        p._error_count / max(1, p._total_requests) * 100, 1
                    ),
                },
            }
            for p in manager.get_all_providers()
        ]
    }


@router.post("/ai/reload")
async def reload_ai_config(authorization: Optional[str] = Header(default=None)):
    """
    Reload konfigurasi AI provider dari Supabase ke memory.
    Gunakan setelah manual edit tabel ai_provider_config di Supabase.
    Hanya untuk admin.
    """
    supabase = _get_supabase()
    require_admin(supabase, authorization)

    manager = get_provider_manager()
    updated = manager.reload_from_db(supabase)

    return {
        "success": True,
        "updated_providers": updated,
        "providers": [p.to_dict() for p in manager.get_all_providers()],
    }
