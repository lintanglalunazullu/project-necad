# services/api/routes/admin.py — Admin dashboard, manajemen user, dan AI provider config
import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from supabase import Client

from auth import require_admin
from ai.retrieval import fetch_document_summary, get_synonyms_registry
from ai.generation import get_provider_manager
from utils.helpers import extract_response_parts

logger = logging.getLogger("aksaraku.routes.admin")

router = APIRouter(prefix="/admin", tags=["admin"])


# ======================= HELPERS =======================

def _get_supabase() -> Client:
    from app import supabase
    return supabase


def _fetch_recent_rows(
    supabase: Client, table_name: str, order_col: str = "created_at", limit: int = 10
) -> list[dict]:
    """Ambil N baris TERBARU saja (ORDER BY + LIMIT didorong ke Postgres),
    bukan seluruh tabel yang lalu diurutkan di Python."""
    response = (
        supabase.table(table_name)
        .select("*")
        .order(order_col, desc=True)
        .limit(limit)
        .execute()
    )
    parts = extract_response_parts(response)
    if parts["error"]:
        raise HTTPException(500, str(parts["error"]))
    return parts["data"] or []


def _fetch_table_rows(supabase: Client, table_name: str, limit: int = 1000) -> list[dict]:
    """Fetch tanpa urutan tertentu — dipakai hanya di jalur fallback stats di bawah."""
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


def _dashboard_stats_fallback(supabase: Client) -> dict:
    """
    Jalur lama (fetch tabel penuh) — dipakai HANYA kalau RPC get_admin_dashboard_stats
    belum di-deploy (migrasi belum dijalankan). Lihat docs/migration_performance_and_security.sql.
    """
    logger.warning(
        "get_admin_dashboard_stats RPC tidak tersedia, pakai fallback full-table fetch. "
        "Jalankan docs/migration_performance_and_security.sql untuk performa optimal."
    )
    document_rows = (
        supabase.table("pdf_documents").select("id, category, pdf_name").limit(10000).execute().data or []
    )
    profiles = _fetch_table_rows(supabase, "profiles", 1000)
    sessions = _fetch_table_rows(supabase, "chat_sessions", 1000)
    messages = _fetch_table_rows(supabase, "chat_messages", 1000)

    category_counts = {"public": 0, "private": 0}
    for row in document_rows:
        category = str(row.get("category") or "public").lower()
        category_counts[category if category in category_counts else "public"] += 1

    role_counts: dict[str, int] = {}
    for profile in profiles:
        profile_role = str(profile.get("role") or "user").strip().lower()
        role_counts[profile_role] = role_counts.get(profile_role, 0) + 1

    messages_role_counts = {"user": 0, "assistant": 0}
    for message in messages:
        message_role = str(message.get("role") or "").lower()
        if message_role in messages_role_counts:
            messages_role_counts[message_role] += 1

    return {
        "documents": len({r.get("pdf_name") for r in document_rows if r.get("pdf_name")}) or len(document_rows),
        "chunks": len(document_rows),
        "users": len(profiles),
        "sessions": len(sessions),
        "messages": len(messages),
        "public_documents": category_counts["public"],
        "private_documents": category_counts["private"],
        "users_by_role": role_counts,
        "messages_by_role": messages_role_counts,
    }


def _dashboard_stats(supabase: Client) -> dict:
    """
    Statistik dashboard dalam 1 round-trip via RPC get_admin_dashboard_stats
    (agregat COUNT di Postgres). Fallback otomatis ke fetch tabel penuh kalau
    RPC belum ter-deploy, supaya dashboard tidak error sebelum migrasi dijalankan.
    """
    try:
        response = supabase.rpc("get_admin_dashboard_stats", {}).execute()
        parts = extract_response_parts(response)
        if not parts["error"] and parts["data"] is not None:
            data = parts["data"]
            data.setdefault("users_by_role", {})
            data.setdefault("messages_by_role", {"user": 0, "assistant": 0})
            return data
    except Exception as exc:
        logger.warning("get_admin_dashboard_stats RPC gagal: %s", exc)
    return _dashboard_stats_fallback(supabase)


# ======================= DASHBOARD =======================

@router.get("/dashboard")
async def admin_dashboard(authorization: Optional[str] = Header(default=None)):
    """
    Statistik dashboard — hanya untuk admin.
    Sebelumnya endpoint ini fetch SELURUH isi tabel pdf_documents (limit 10000)
    + profiles/chat_sessions/chat_messages (limit 1000 masing-masing) di setiap
    kali dashboard dibuka. Sekarang: 1 RPC agregat untuk angka statistik, dan
    hanya baris TERBARU (limit kecil, di-order di database) untuk daftar aktivitas.
    """
    supabase = _get_supabase()
    require_admin(supabase, authorization)

    # Jalankan semua query independen secara paralel di thread pool — sebelumnya
    # berurutan (blocking) satu per satu.
    (
        stats,
        documents,
        recent_sessions,
        recent_messages,
        recent_profiles,
    ) = await asyncio.gather(
        asyncio.to_thread(_dashboard_stats, supabase),
        asyncio.to_thread(fetch_document_summary, supabase),
        asyncio.to_thread(_fetch_recent_rows, supabase, "chat_sessions", "created_at", 10),
        asyncio.to_thread(_fetch_recent_rows, supabase, "chat_messages", "created_at", 10),
        asyncio.to_thread(_fetch_recent_rows, supabase, "profiles", "created_at", 8),
    )

    documents.sort(key=lambda d: str(d.get("created_at") or ""), reverse=True)

    recent_users = [
        {
            "id": p.get("id"),
            "email": p.get("email") or "",
            "full_name": p.get("full_name") or p.get("email") or "Pengguna",
            "role": str(p.get("role") or "user").lower(),
            "provider": p.get("provider") or "email",
            "created_at": p.get("created_at"),
        }
        for p in recent_profiles
    ]

    activities = (
        _dashboard_activity(documents[:10], "Dokumen", "pdf_name")
        + _dashboard_activity(recent_sessions, "Sesi chat", "title")
        + _dashboard_activity(recent_messages, "Pesan AI", "content")
        + _dashboard_activity(recent_users, "Pengguna", "full_name")
    )
    activities.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)

    return {
        "stats": stats,
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
    api_key: Optional[str] = Field(default=None, description="API Key tunggal baru")
    api_keys: Optional[list[Any]] = Field(default=None, description="Daftar API Key untuk multi-key fallback")
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0, description="0.0-2.0")
    max_tokens: Optional[int] = Field(default=None, gt=0, le=8192, description="Batas output token")
    priority: Optional[int] = Field(default=None, ge=1, le=10, description="Urutan fallback (1=tertinggi)")
    timeout: Optional[float] = Field(default=None, gt=0, le=120, description="Timeout detik")
    system_prompt_extra: Optional[str] = Field(default=None, description="Instruksi tambahan khusus provider ini")


class ProviderTestRequest(BaseModel):
    provider: str = Field(description="Nama provider: gemini, groq, openrouter")
    prompt: Optional[str] = Field(default="Sebutkan 1 kalimat motivasi belajar untuk siswa SMP!", description="Prompt test")
    model: Optional[str] = Field(default=None, description="Model opsional untuk ditest")
    api_key: Optional[str] = Field(default=None, description="API Key opsional untuk ditest sebelum disimpan")


class ScanModelsRequest(BaseModel):
    api_key: Optional[str] = Field(default=None, description="API Key opsional untuk scanning")


class TestKeysRequest(BaseModel):
    keys: Optional[list[str]] = Field(default=None, description="Daftar key untuk ditest secara bersamaan")


# Katalog model terkurasi dengan klasifikasi Tier (Free vs Pro)
CURATED_MODELS = [
    # Gemini
    {
        "provider": "gemini",
        "id": "gemini-3.5-flash-lite",
        "name": "Gemini 3.5 Flash-Lite (Ultra Cepat & Stabil)",
        "tier": "free",
        "speed": "Ultra Kilat (~0.3s)",
        "context": "1.000.000 tokens",
        "badge": "Rekomendasi Utama (Anti-Overload)",
        "desc": "Model resmi Google paling stabil di Free Tier. Bebas dari kendala kapasitas 503 dan sangat hemat kuota.",
    },
    {
        "provider": "gemini",
        "id": "gemini-3.6-flash",
        "name": "Gemini 3.6 Flash (Utama & Cerdas)",
        "tier": "free",
        "speed": "Cepat (~120 t/s)",
        "context": "1.000.000 tokens",
        "badge": "Cerdas / Analitis",
        "desc": "Model Gemini 3 terbaru: penalaran cerdas, responsif, dan kuota gratis di AI Studio.",
    },
    {
        "provider": "gemini",
        "id": "gemini-3.5-flash",
        "name": "Gemini 3.5 Flash (Stabil & Cepat)",
        "tier": "free",
        "speed": "Sangat Cepat",
        "context": "1.000.000 tokens",
        "badge": "Stabil / Cadangan",
        "desc": "Sangat stabil untuk pencarian konteks dokumen sekolah dan tanya jawab materi.",
    },
    # Groq
    {
        "provider": "groq",
        "id": "llama-3.3-70b-versatile",
        "name": "Llama 3.3 70B Versatile",
        "tier": "free",
        "speed": "Super Kilat (~300 t/s)",
        "context": "128.000 tokens",
        "badge": "Rekomendasi Groq",
        "desc": "Inferensi hardware LPU Groq tercepat di dunia. Sangat akurat untuk bahasa Indonesia.",
    },
    {
        "provider": "groq",
        "id": "deepseek-r1-distill-llama-70b",
        "name": "DeepSeek R1 Distill 70B",
        "tier": "free",
        "speed": "Cepat (~250 t/s)",
        "context": "128.000 tokens",
        "badge": "Penalaran Sains/MTK",
        "desc": "Distilasi model DeepSeek R1 dengan kemampuan *step-by-step reasoning* superior.",
    },
    {
        "provider": "groq",
        "id": "llama-3.1-8b-instant",
        "name": "Llama 3.1 8B Instant",
        "tier": "free",
        "speed": "Ultra Kilat (~700 t/s)",
        "context": "128.000 tokens",
        "badge": "Cadangan Kilat",
        "desc": "Model 8B sangat ringan dan instan, cocok untuk respon kilat tanpa jeda.",
    },
    # OpenRouter
    {
        "provider": "openrouter",
        "id": "meta-llama/llama-3.3-70b-instruct:free",
        "name": "Llama 3.3 70B (Free)",
        "tier": "free",
        "speed": "Cepat",
        "context": "128.000 tokens",
        "badge": "Free Tier Utama",
        "desc": "Model 70B gratis via OpenRouter tanpa biaya token.",
    },
    {
        "provider": "openrouter",
        "id": "deepseek/deepseek-r1:free",
        "name": "DeepSeek R1 (Free)",
        "tier": "free",
        "speed": "Normal",
        "context": "64.000 tokens",
        "badge": "Free Reasoning",
        "desc": "Model penalaran DeepSeek R1 penuh secara gratis via OpenRouter.",
    },
    {
        "provider": "openrouter",
        "id": "qwen/qwen-2.5-72b-instruct:free",
        "name": "Qwen 2.5 72B (Free)",
        "tier": "free",
        "speed": "Cepat",
        "context": "32.000 tokens",
        "badge": "Free Multilingual",
        "desc": "Model open-source cerdas kelas atas dari Alibaba dengan akses gratis.",
    },
    {
        "provider": "openrouter",
        "id": "anthropic/claude-3.5-sonnet",
        "name": "Claude 3.5 Sonnet",
        "tier": "pro",
        "speed": "Kualitas Terbaik",
        "context": "200.000 tokens",
        "badge": "Premium / Pro",
        "desc": "Model kecerdasan bahasa dan instruksi terbaik di dunia (memerlukan kredit berbayar).",
    },
]


@router.get("/ai/models")
async def list_curated_models(authorization: Optional[str] = Header(default=None)):
    """Katalog model AI terkurasi dengan metadata tier (Free vs Pro)."""
    require_admin(_get_supabase(), authorization)
    return {"models": CURATED_MODELS}


@router.get("/ai/providers")
async def list_ai_providers(authorization: Optional[str] = Header(default=None)):
    """List semua AI provider beserta status, konfigurasi, masking key, dan statistik penggunaan."""
    require_admin(_get_supabase(), authorization)
    manager = get_provider_manager()

    providers_data = []
    for p in manager.get_all_providers():
        data = p.to_dict()
        data["has_api_key"] = manager.has_api_key(p.name)
        data["masked_api_key"] = manager.get_masked_key(p.name)
        data["keys"] = manager.get_masked_keys(p.name)
        data["keys_count"] = len(manager.get_provider_keys(p.name))
        providers_data.append(data)

    return {
        "providers": providers_data,
        "active_count": len(manager.get_sorted_providers()),
    }


def _sync_keys_to_env(provider_name: str, keys: list[str]) -> None:
    """Sinkronisasi daftar API keys yang baru disimpan ke file .env dan memory secara aman."""
    import os
    import re
    import config
    api_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(api_dir, ".env")
    if not os.path.exists(env_path):
        return

    prefix_map = {
        "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }
    base_var = prefix_map.get(provider_name)
    if not base_var:
        return

    clean_keys = [
        k.strip() for k in keys
        if k and "••••" not in k and not k.startswith("AIzaSy_xxx") and not k.startswith("gsk_xxx") and not k.startswith("sk-or-xxx")
    ]

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            content = f.read()

        vars_to_sync = [
            (base_var, clean_keys[0] if len(clean_keys) > 0 else ""),
            (f"{base_var}_2", clean_keys[1] if len(clean_keys) > 1 else ""),
            (f"{base_var}_3", clean_keys[2] if len(clean_keys) > 2 else ""),
        ]

        for var_name, var_val in vars_to_sync:
            pattern = rf"^({var_name}[ \t]*=[ \t]*)[^\r\n]*$"
            if re.search(pattern, content, flags=re.MULTILINE):
                content = re.sub(pattern, lambda m, v=var_val: f"{m.group(1)}{v}", content, flags=re.MULTILINE)
            elif var_val:
                content += f"\n{var_name}={var_val}\n"

        with open(env_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Update in-memory config variables
        if provider_name == "gemini":
            if clean_keys:
                config.GEMINI_API_KEY = clean_keys[0]
        elif provider_name == "groq":
            config.GROQ_API_KEYS = clean_keys
        elif provider_name == "openrouter":
            config.OPENROUTER_API_KEYS = clean_keys

        logger.info(".env berhasil disinkronkan dengan API keys untuk %s (%d kunci)", provider_name, len(clean_keys))
    except Exception as exc:
        logger.warning("Gagal sinkronisasi API keys ke .env: %s", exc)


@router.put("/ai/providers/{provider_name}")
async def update_ai_provider(
    provider_name: str,
    body: ProviderUpdateRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Update konfigurasi satu AI provider secara runtime (tanpa restart server)."""
    supabase = _get_supabase()
    require_admin(supabase, authorization)

    manager = get_provider_manager()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}

    # Proteksi: Cegah model preview yang terkena 503 kapasitas di Google Free Tier
    if provider_name == "gemini" and "model" in updates:
        from ai.generation import sanitize_gemini_model
        updates["model"] = sanitize_gemini_model(updates["model"])

    try:
        provider = manager.update_provider(provider_name, updates)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    # Simpan ke Supabase kalau tabelnya ada
    try:
        import config
        import json
        save_updates = dict(updates)
        keys = manager.get_provider_keys(provider_name)
        if keys:
            save_updates["api_key"] = json.dumps(keys) if len(keys) > 1 else keys[0]
            _sync_keys_to_env(provider_name, keys)
        elif "api_key" in save_updates and (not save_updates["api_key"] or "••••" in save_updates["api_key"]):
            save_updates.pop("api_key", None)
        save_updates.pop("api_keys", None)

        db_payload: dict[str, Any] = {"id": provider_name, **save_updates, "updated_at": "now()"}
        supabase.table(config.AI_CONFIG_TABLE).upsert(db_payload, on_conflict="id").execute()
        logger.info("AI provider config '%s' disimpan ke DB", provider_name)
    except Exception as exc:
        logger.info("Tidak bisa simpan ke DB (tabel mungkin belum ada): %s", exc)

    data = provider.to_dict()
    data["has_api_key"] = manager.has_api_key(provider.name)
    data["masked_api_key"] = manager.get_masked_key(provider.name)
    data["keys"] = manager.get_masked_keys(provider.name)
    data["keys_count"] = len(manager.get_provider_keys(provider.name))
    return {"success": True, "provider": data}


@router.post("/ai/providers/{provider_name}/scan-models")
async def scan_provider_models(
    provider_name: str,
    body: ScanModelsRequest = ScanModelsRequest(),
    authorization: Optional[str] = Header(default=None),
):
    """Scan model AI yang tersedia langsung dari API provider secara live."""
    require_admin(_get_supabase(), authorization)
    manager = get_provider_manager()

    keys = manager.get_provider_keys(provider_name)
    scan_key = body.api_key.strip() if body.api_key and "••••" not in body.api_key else (keys[0] if keys else "")
    scan_key = scan_key.strip()

    if not scan_key:
        raise HTTPException(400, f"Belum ada API Key untuk {provider_name.capitalize()}. Masukkan API Key terlebih dahulu.")

    models_result = []

    if provider_name == "gemini":
        try:
            all_m = []
            try:
                from google import genai as modern_genai
                client = modern_genai.Client(api_key=scan_key)
                all_m = list(client.models.list())
            except Exception:
                import google.generativeai as genai
                genai.configure(api_key=scan_key)
                all_m = list(genai.list_models())

            excluded_keywords = [
                "tts", "transcribe", "banana", "computer-use", "deep-research",
                "agent", "antigravity", "omni", "gemma", "lyria", "robotics",
                "embed", "aqa", "image", "clip", "customtools", "vision-preview"
            ]
            deprecated_models = {
                "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro",
                "gemini-2.0-flash", "gemini-2.0-pro", "gemini-1.5-flash", "gemini-1.5-pro",
                "gemini-1.0-pro", "gemini-pro", "gemini-3-flash-preview",
                "gemini-3.8-flash", "gemini-3.7-flash"  # Sering 503 No capacity di Free Tier
            }

            for m in all_m:
                methods = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", []) or []
                if "generateContent" not in methods:
                    continue
                mid = m.name.replace("models/", "")
                mid_l = mid.lower()
                if any(k in mid_l for k in excluded_keywords) or mid in deprecated_models or any(bad in mid_l for bad in ("3.8", "3.7", "2.5", "2.0", "1.5", "1.0", "preview")):
                    continue

                is_pro = "pro" in mid_l
                is_rec = mid == "gemini-3.5-flash-lite"
                tier = "pro" if is_pro else "free"

                disp_name = getattr(m, "display_name", None) or mid
                if mid == "gemini-3.5-flash-lite":
                    disp_name = "Gemini 3.5 Flash-Lite (Rekomendasi Utama — Ultra Cepat & Stabil)"
                elif mid == "gemini-3.6-flash":
                    disp_name = "Gemini 3.6 Flash (Utama & Cerdas)"
                elif mid == "gemini-3.5-flash":
                    disp_name = "Gemini 3.5 Flash (Stabil & Cepat)"
                elif mid == "gemini-3.1-flash-lite":
                    disp_name = "Gemini 3.1 Flash-Lite (Ringan)"

                models_result.append({
                    "id": mid,
                    "name": disp_name,
                    "tier": tier,
                    "tier_label": "Pro / Analitis" if is_pro else "Gratis / Cepat",
                    "is_recommended": is_rec,
                    "description": (getattr(m, "description", "") or "").strip()[:140],
                })
        except Exception as exc:
            logger.warning("Gagal scan Gemini models: %s", exc)

        # Fallback jika scan kosong atau gagal terhubung
        if not models_result:
            models_result = [
                {
                    "id": m["id"],
                    "name": m["name"],
                    "tier": m["tier"],
                    "tier_label": "Gratis / Cepat",
                    "is_recommended": m["id"] == "gemini-3.6-flash",
                    "description": m["desc"],
                }
                for m in CURATED_MODELS
                if m["provider"] == "gemini"
            ]

    elif provider_name == "groq":
        try:
            import httpx
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    "https://api.groq.com/openai/v1/models",
                    headers={"Authorization": f"Bearer {scan_key}"},
                )
                if resp.status_code != 200:
                    raise RuntimeError(f"Groq API HTTP {resp.status_code}: {resp.text}")
                data = resp.json().get("data", [])
                for item in data:
                    mid = item.get("id", "")
                    mid_l = mid.lower()
                    if any(bad in mid_l for bad in ["whisper", "guard", "vision", "preview", "playpen"]):
                        continue
                    is_rec = "llama-3.3-70b-versatile" in mid_l or "llama-3.1-8b-instant" in mid_l
                    is_70b = "70b" in mid_l
                    # Di Groq Developer Console, seluruh model teks adalah Free Tier (14.400 req/hari)
                    models_result.append({
                        "id": mid,
                        "name": mid,
                        "tier": "free",
                        "tier_label": "Gratis / Akurasi Tinggi" if is_70b else "Gratis / Kilat LPU",
                        "is_recommended": is_rec,
                        "description": f"Context window: {item.get('context_window', '8k')} tokens (Inference LPU)",
                    })
        except Exception as exc:
            logger.warning("Gagal scan Groq models: %s", exc)
            raise HTTPException(400, f"Gagal memindai model Groq: {exc}")

    elif provider_name == "openrouter":
        try:
            import httpx
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(
                    "https://openrouter.ai/api/v1/models",
                    headers={"Authorization": f"Bearer {scan_key}"},
                )
                if resp.status_code != 200:
                    raise RuntimeError(f"OpenRouter API HTTP {resp.status_code}: {resp.text}")
                data = resp.json().get("data", [])
                for item in data:
                    mid = item.get("id", "")
                    mid_l = mid.lower()
                    mname = item.get("name", mid)
                    is_free = ":free" in mid_l
                    pricing = item.get("pricing", {})
                    prompt_price = float(pricing.get("prompt", "0") or 0)
                    tier = "free" if (is_free or prompt_price == 0) else "pro"

                    # Saring model terpercaya dan populer
                    if any(brand in mid_l for brand in ["llama", "mistral", "gemini", "deepseek", "qwen", "gemma"]):
                        models_result.append({
                            "id": mid,
                            "name": mname,
                            "tier": tier,
                            "tier_label": "Gratis (Free Tier)" if tier == "free" else "Berbayar / Pro",
                            "is_recommended": is_free and any(rec in mid_l for rec in ["llama-3.3-70b", "deepseek-r1", "qwen-2.5-72b"]),
                            "description": (item.get("description") or "")[:120],
                        })
        except Exception as exc:
            logger.warning("Gagal scan OpenRouter models: %s", exc)
            raise HTTPException(400, f"Gagal memindai model OpenRouter: {exc}")

    # Urutkan: Rekomendasi di paling atas, lalu seluruh Free Tier, baru model berbayar
    models_result.sort(key=lambda m: (not m.get("is_recommended", False), m.get("tier") != "free", m.get("id")))
    return {"provider": provider_name, "count": len(models_result), "models": models_result}


@router.post("/ai/providers/{provider_name}/test-keys")
async def test_provider_keys(
    provider_name: str,
    body: TestKeysRequest = TestKeysRequest(),
    authorization: Optional[str] = Header(default=None),
):
    """Uji koneksi & kesehatan setiap API Key pada provider."""
    require_admin(_get_supabase(), authorization)
    manager = get_provider_manager()
    provider = manager.get_provider(provider_name)
    test_model = provider.model if provider else ""

    if body.keys is not None:
        raw_keys = [k.strip() for k in body.keys if k and "••••" not in k]
    else:
        raw_keys = manager.get_provider_keys(provider_name)

    if not raw_keys:
        return {"provider": provider_name, "results": []}

    import time
    import asyncio
    
    async def _test_single_key(idx, key):
        from ai.generation import AIProviderManager
        masked = AIProviderManager.mask_key(key)
        start = time.perf_counter()
        success = False
        error_msg = None
        status = "unknown"

        try:
            if provider_name == "gemini":
                # Coba model terpilih, jika 404/503/429 fallback ke model ultra-stabil (gemini-3.5-flash-lite)
                from ai.generation import sanitize_gemini_model
                safe_model = sanitize_gemini_model(test_model)
                models_to_test = [safe_model]
                for fb in ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.5-flash"]:
                    if fb not in models_to_test:
                        models_to_test.append(fb)

                loop = asyncio.get_running_loop()
                tested = False
                active_tested_model = None

                # 1. Coba modern google.genai
                try:
                    from google import genai as modern_genai
                    client = modern_genai.Client(api_key=key.strip())
                    for m_name in models_to_test:
                        try:
                            resp = await loop.run_in_executor(None, lambda m=m_name: client.models.generate_content(model=m, contents="Ping"))
                            if resp.text:
                                success = True
                                status = "active"
                                tested = True
                                active_tested_model = m_name
                                break
                        except Exception as call_exc:
                            err_c = str(call_exc)
                            if "403" in err_c and "denied" in err_c.lower():
                                status = "project_denied"
                                error_msg = "Akses project ditolak oleh Google Cloud (403)"
                                tested = True
                                break
                            elif "404" in err_c or "no longer available" in err_c or "not found" in err_c:
                                continue
                            elif "429" in err_c or "quota" in err_c.lower() or "resourceexhausted" in err_c.lower():
                                status = "quota_exceeded"
                                error_msg = "Batas kuota habis (429)"
                                continue
                            elif "503" in err_c or "unavailable" in err_c.lower() or "capacity" in err_c.lower() or "demand" in err_c.lower():
                                logger.warning("Model %s sedang 503 (No capacity/high demand), mencoba model cadangan...", m_name)
                                continue
                            else:
                                raise call_exc
                except Exception as modern_err:
                    err_c = str(modern_err)
                    if "403" in err_c and "denied" in err_c.lower():
                        status = "project_denied"
                        error_msg = "Akses project ditolak oleh Google Cloud (403)"
                        tested = True

                # 2. Fallback legacy jika modern belum berhasil
                if not tested and not success and status == "unknown":
                    import google.generativeai as genai
                    genai.configure(api_key=key.strip())
                    for m_name in models_to_test:
                        try:
                            m = genai.GenerativeModel(model_name=m_name)
                            resp = await loop.run_in_executor(None, lambda: m.generate_content("Ping", request_options={"timeout": 25}))
                            if resp.text:
                                success = True
                                status = "active"
                                active_tested_model = m_name
                                break
                        except Exception as call_exc:
                            err_c = str(call_exc)
                            if "403" in err_c and "denied" in err_c.lower():
                                status = "project_denied"
                                error_msg = "Akses project ditolak oleh Google Cloud (403)"
                                break
                            elif "404" in err_c or "no longer available" in err_c or "not found" in err_c:
                                continue
                            elif "429" in err_c or "quota" in err_c.lower() or "resourceexhausted" in err_c.lower():
                                status = "quota_exceeded"
                                error_msg = "Batas kuota habis (429)"
                                continue
                            elif "503" in err_c or "unavailable" in err_c.lower() or "capacity" in err_c.lower() or "demand" in err_c.lower():
                                continue
                            else:
                                raise call_exc

                if success and active_tested_model and test_model and active_tested_model != test_model:
                    error_msg = f"Kunci aktif (Dialihkan ke {active_tested_model} karena {test_model} sibuk/overload 503)"

            elif provider_name in ("groq", "openrouter"):
                from openai import AsyncOpenAI
                import config
                base_url = "https://api.groq.com/openai/v1" if provider_name == "groq" else "https://openrouter.ai/api/v1"
                headers = {}
                if provider_name == "openrouter":
                    headers = {"HTTP-Referer": config.OPENROUTER_SITE_URL, "X-Title": config.OPENROUTER_SITE_NAME}
                c = AsyncOpenAI(api_key=key.strip(), base_url=base_url, max_retries=0, timeout=5.0, default_headers=headers)
                m_name = test_model or ("llama-3.3-70b-versatile" if provider_name == "groq" else "meta-llama/llama-3.3-70b-instruct:free")
                res = await c.chat.completions.create(
                    model=m_name,
                    messages=[{"role": "user", "content": "Ping"}],
                    max_tokens=5,
                )
                if res.choices:
                    success = True
                    status = "active"
        except Exception as exc:
            err_str = str(exc)
            error_msg = err_str
            if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                status = "quota_exceeded"
            elif "403" in err_str and "denied" in err_str.lower():
                status = "project_denied"
            elif "401" in err_str or "403" in err_str or "invalid" in err_str.lower() or "api_key" in err_str.lower():
                status = "invalid_key"
            else:
                status = "error"

        latency = round((time.perf_counter() - start) * 1000, 1)
        return {
            "index": idx,
            "label": f"Kunci #{idx+1}" if idx > 0 else "Kunci Utama",
            "masked": masked,
            "success": success,
            "latency_ms": latency if success else None,
            "status": status,
            "error": error_msg,
            "status_label": "Aktif & Normal" if success else (
                "Batas Kuota Habis (429)" if status == "quota_exceeded" else (
                    "Akses Ditolak Google (403)" if status == "project_denied" else (
                        "Kunci Tidak Valid" if status == "invalid_key" else "Gagal Terhubung"
                    )
                )
            ),
        }

    results = []
    for idx, key in enumerate(raw_keys):
        results.append(await _test_single_key(idx, key))

    return {"provider": provider_name, "results": results}


@router.post("/ai/providers/test")
async def test_ai_provider(
    body: ProviderTestRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Test satu provider dengan prompt dummy atau key sementara. Mengukur latency dan token usage."""
    require_admin(_get_supabase(), authorization)

    manager = get_provider_manager()
    provider = manager.get_provider(body.provider)
    if not provider:
        from ai.generation import ProviderConfig
        provider = ProviderConfig(
            name=body.provider,
            enabled=True,
            priority=1,
            model=body.model or "gemini-3.5-flash-lite",
        )

    if body.provider == "gemini":
        from ai.generation import sanitize_gemini_model
        test_model = sanitize_gemini_model(body.model or provider.model)
    else:
        test_model = body.model or provider.model
    import time
    start = time.perf_counter()
    error_msg = None
    answer = None
    tokens_used = None

    try:
        messages = [
            {"role": "system", "content": "Kamu adalah asisten penguji AI yang ramah, ringkas, dan jelas."},
            {"role": "user", "content": body.prompt or "Halo! Tes koneksi model AI."},
        ]

        if body.provider == "gemini":
            from ai.generation import _call_gemini, ProviderConfig
            temp_p = ProviderConfig(
                name="gemini",
                enabled=True,
                model=test_model,
                temperature=0.2,
                max_tokens=200,
                timeout=20.0,
            )
            if body.api_key and not body.api_key.startswith("••••"):
                import google.generativeai as genai
                genai.configure(api_key=body.api_key.strip())

            # _call_gemini blocking (google-generativeai sync SDK) -> jalankan di thread
            # pool supaya tidak menahan event loop selama tes berlangsung.
            answer, usage = await asyncio.to_thread(_call_gemini, temp_p, messages)
            tokens_used = usage

        else:
            from ai.generation import _call_openai_compat, ProviderConfig
            from openai import OpenAI
            import config

            temp_p = ProviderConfig(
                name=body.provider,
                enabled=True,
                model=test_model,
                temperature=0.2,
                max_tokens=200,
                timeout=20.0,
            )

            if body.api_key and not body.api_key.startswith("••••"):
                base_url = "https://api.groq.com/openai/v1" if body.provider == "groq" else "https://openrouter.ai/api/v1"
                headers = {}
                if body.provider == "openrouter":
                    headers = {"HTTP-Referer": config.OPENROUTER_SITE_URL, "X-Title": config.OPENROUTER_SITE_NAME}
                test_clients = [(f"{body.provider}_test", OpenAI(api_key=body.api_key.strip(), base_url=base_url, max_retries=0, timeout=20.0, default_headers=headers))]
            else:
                test_clients = manager.get_openai_clients(body.provider)

            if not test_clients:
                raise RuntimeError(f"Tidak ada API Key yang dikonfigurasi untuk provider {body.provider}")

            # _call_openai_compat pakai client OpenAI() sync -> jalankan di thread pool juga.
            answer, _, usage = await asyncio.to_thread(_call_openai_compat, temp_p, test_clients, messages, 0)
            tokens_used = usage

    except Exception as exc:
        error_msg = str(exc)

    elapsed = round((time.perf_counter() - start) * 1000, 1)

    return {
        "provider": body.provider,
        "model": test_model,
        "success": error_msg is None,
        "answer": answer,
        "error": error_msg,
        "latency_ms": elapsed,
        "tokens": tokens_used,
        "message": "Koneksi berhasil dan model aktif!" if error_msg is None else "Koneksi gagal atau API Key tidak valid.",
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


@router.get("/ai/unanswered-queries")
async def get_unanswered_queries(authorization: Optional[str] = Header(default=None)):
    """Daftar pertanyaan yang belum memiliki dokumen jawaban (Knowledge Gap Analytics)."""
    require_admin(_get_supabase(), authorization)
    sb = _get_supabase()
    try:
        res = sb.table("unanswered_queries").select("*").order("created_at", desc=True).limit(50).execute()
        rows = res.data or []

        frequency: dict[str, dict] = {}
        for r in rows:
            nq = r.get("normalized_question") or r.get("question", "")
            if nq not in frequency:
                frequency[nq] = {
                    "question": r.get("question"),
                    "count": 0,
                    "last_seen": r.get("created_at"),
                    "reason": r.get("reason"),
                }
            frequency[nq]["count"] += 1

        top_gaps = sorted(frequency.values(), key=lambda x: x["count"], reverse=True)[:10]
        return {
            "total_records": len(rows),
            "top_gaps": top_gaps,
            "recent": rows[:20],
        }
    except Exception as exc:
        logger.warning("Gagal mengambil unanswered queries: %s", exc)
        return {"total_records": 0, "top_gaps": [], "recent": []}


# ======================= AUTO-SMART LEARNED SYNONYMS =======================

class LearnedTermRequest(BaseModel):
    slang_word: str = Field(..., min_length=2, max_length=100)
    canonical_word: str = Field(..., min_length=2, max_length=100)


@router.get("/ai/learned-synonyms")
async def get_learned_synonyms(authorization: Optional[str] = Header(default=None)):
    """Daftar seluruh kosakata gaul/daerah yang dipelajari mandiri oleh AI atau ditambahkan admin."""
    supabase = _get_supabase()
    require_admin(supabase, authorization)
    registry = get_synonyms_registry()
    items = registry.get_learned_list(supabase)
    return {
        "success": True,
        "total": len(items),
        "synonyms": items,
    }


@router.post("/ai/learned-synonyms")
async def add_learned_synonym(
    body: LearnedTermRequest,
    authorization: Optional[str] = Header(default=None)
):
    """Tambah atau perbarui pasangan kata gaul dan padanan bahasa bakunya ke memori AI."""
    supabase = _get_supabase()
    require_admin(supabase, authorization)
    registry = get_synonyms_registry()
    ok = registry.record_learned_term(
        supabase=supabase,
        slang_word=body.slang_word,
        canonical_word=body.canonical_word,
        source="manual_admin"
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Kata tidak valid atau termasuk kata henti (stopwords).")
    return {
        "success": True,
        "slang_word": body.slang_word.strip().lower(),
        "canonical_word": body.canonical_word.strip().lower(),
    }


@router.delete("/ai/learned-synonyms/{slang_word}")
async def delete_learned_synonym(
    slang_word: str,
    authorization: Optional[str] = Header(default=None)
):
    """Hapus kata dari memori pembelajaran AI."""
    supabase = _get_supabase()
    require_admin(supabase, authorization)
    registry = get_synonyms_registry()
    ok = registry.delete_learned_term(supabase, slang_word)
    return {
        "success": ok,
        "slang_word": slang_word.strip().lower(),
    }


@router.post("/ai/trigger-learning")
async def trigger_learning_sync(authorization: Optional[str] = Header(default=None)):
    """Sinkronkan paksa memori kosakata AI dari database."""
    supabase = _get_supabase()
    require_admin(supabase, authorization)
    registry = get_synonyms_registry()
    registry.sync_from_db(supabase, force=True)
    items = registry.get_learned_list(supabase)
    return {
        "success": True,
        "total": len(items),
        "message": f"Berhasil menyinkronkan {len(items)} kosakata ke memori aktif AI."
    }

