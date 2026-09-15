# services/api/app.py — Entry point FastAPI (ringan, cuma setup + register routes)
import logging

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

# ======================= FASTAPI APP =======================
app = FastAPI(
    title="Aksaraku API",
    description="Backend RAG untuk AI Mentor Aksaraku — SMP Negeri 2 Cibungbulang",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Pasang rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ======================= CORS (Security Fix) =======================
# Whitelist origin berdasarkan ENV, bukan allow_origins=["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ======================= STARTUP EVENT =======================
@app.on_event("startup")
async def startup_event():
    """Pre-load embedding model saat startup biar request pertama tidak lambat."""
    logger.info("🚀 Aksaraku API starting up...")
    logger.info("CORS allowed origins: %s", config.ALLOWED_ORIGINS)
    # Trigger lazy load model embedding
    from rag.embedding import get_model
    get_model()
    logger.info("✅ Aksaraku API siap menerima request.")

# ======================= ROUTES =======================
app.include_router(admin_router)
app.include_router(documents_router)
app.include_router(chat_router)

@app.get("/health", tags=["system"])
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "Aksaraku",
        "embedding_model": config.HUGGINGFACE_EMBEDDING_MODEL,
        "embedding_dimension": config.EXPECTED_EMBEDDING_DIMENSION,
        "rag_top_k": config.RAG_TOP_K,
        "rag_final_k": config.RAG_FINAL_K,
        "context_tokens": config.MAX_CONTEXT_TOKENS,
        "cors_origins": config.ALLOWED_ORIGINS,
    }