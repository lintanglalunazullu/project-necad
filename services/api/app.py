# services/api/app.py — Entry point FastAPI
import os
import sys
import logging
from contextlib import asynccontextmanager

# Pastikan folder services/api ada di sys.path agar import internal (config, routes, ai)
# selalu berhasil baik saat dev lokal maupun saat dijalankan dari root oleh Vercel.
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from supabase import create_client, Client

import config
from routes.admin import router as admin_router
from routes.documents import router as documents_router
from routes.chat import router as chat_router

# ======================= RATE LIMITER =======================
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

# ======================= LOGGING =======================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("aksaraku")

# ======================= SUPABASE CLIENT =======================
supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)


# ======================= LIFESPAN (ganti @app.on_event yang deprecated) =======================
@asynccontextmanager
async def lifespan(_app: FastAPI):
    # ---- Startup ----
    logger.info("🚀 Aksaraku API v3.0 starting up...")
    logger.info("CORS allowed origins: %s", config.ALLOWED_ORIGINS)

    from ai.generation import get_provider_manager
    manager = get_provider_manager()
    updated = manager.reload_from_db(supabase)
    if updated:
        logger.info("✅ AI provider config dimuat dari DB: %s provider", updated)

    active = manager.get_sorted_providers()
    logger.info(
        "✅ AI providers aktif: %s",
        ", ".join(f"{p.name}(priority={p.priority}, model={p.model})" for p in active),
    )
    logger.info("✅ Aksaraku API siap menerima request.")

    yield

    # ---- Shutdown ----
    logger.info("👋 Aksaraku API shutting down.")


# ======================= FASTAPI APP =======================
app = FastAPI(
    title="Aksaraku API",
    description="Backend RAG untuk AI Mentor Aksaraku — SMP Negeri 2 Cibungbulang",
    version="3.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Pasang rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ======================= CORS (Security Fix) =======================
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_origin_regex=config.ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ======================= ROUTES =======================
# Mount routes langsung (direct call) dan dengan prefix /api (Vercel rewrite & proxy)
app.include_router(admin_router)
app.include_router(documents_router)
app.include_router(chat_router)

app.include_router(admin_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(chat_router, prefix="/api")


@app.get("/health", tags=["system"])
@app.get("/api/health", tags=["system"])
async def health():
    """Health check endpoint — tampilkan status provider AI yang aktif."""
    from ai.generation import get_provider_manager
    manager = get_provider_manager()
    active = manager.get_sorted_providers()

    return {
        "status": "ok",
        "service": "Aksaraku",
        "version": "3.0.0",
        "embedding": {
            "provider": "gemini",
            "model": config.GEMINI_EMBEDDING_MODEL,
            "dimension": config.EXPECTED_EMBEDDING_DIMENSION,
        },
        "llm_providers": [
            {"name": p.name, "model": p.model, "priority": p.priority, "healthy": p.is_healthy}
            for p in active
        ],
        "rag": {
            "top_k": config.RAG_TOP_K,
            "final_k": config.RAG_FINAL_K,
            "min_similarity": config.RAG_MIN_SIMILARITY,
            "compress_context": config.COMPRESS_CONTEXT,
        },
        "cors_origins": config.ALLOWED_ORIGINS,
    }


# ======================= STATIC WEBSITES (Unified Vercel Hosting) =======================
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

_project_root = os.path.abspath(os.path.join(_current_dir, "..", ".."))
_mentor_web_dir = os.path.join(_project_root, "apps", "mentor-web")
_school_web_dir = os.path.join(_project_root, "apps", "school-web")

@app.get("/mentor", include_in_schema=False)
async def redirect_mentor():
    """Redirect /mentor ke /mentor/ agar StaticFiles melayani index.html."""
    return RedirectResponse(url="/mentor/", status_code=301)

if os.path.isdir(_mentor_web_dir):
    app.mount("/mentor", StaticFiles(directory=_mentor_web_dir, html=True), name="mentor")

if os.path.isdir(_school_web_dir):
    app.mount("/", StaticFiles(directory=_school_web_dir, html=True), name="school")