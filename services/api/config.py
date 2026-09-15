# services/api/config.py — Konfigurasi terpusat dari environment variable
import os
from dotenv import load_dotenv

load_dotenv()

# ======================= SUPABASE =======================
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_TABLE: str = os.getenv("SUPABASE_TABLE", "pdf_documents")
VECTOR_FUNCTION: str = os.getenv("SUPABASE_VECTOR_FUNCTION", "match_pdf_documents")
KEYWORD_FUNCTION: str = os.getenv("SUPABASE_KEYWORD_FUNCTION", "search_pdf_documents_keyword")
EXACT_FUNCTION: str = os.getenv("SUPABASE_EXACT_FUNCTION", "search_pdf_documents_exact")
SUPABASE_METADATA_COLUMN: str = os.getenv("SUPABASE_METADATA_COLUMN", "metadata")
SUPABASE_USE_METADATA: bool = os.getenv("SUPABASE_USE_METADATA", "false").lower() in {"1", "true", "yes"}

# ======================= EMBEDDING =======================
HUGGINGFACE_API_KEY: str | None = os.getenv("HUGGINGFACE_API_KEY")
HUGGINGFACE_EMBEDDING_MODEL: str = os.getenv(
    "HUGGINGFACE_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
EXPECTED_EMBEDDING_DIMENSION: int = int(
    os.getenv(
        "EXPECTED_EMBEDDING_DIMENSION",
        os.getenv("HUGGINGFACE_EXPECTED_EMBEDDING_DIMENSION", "384"),
    )
)
HUGGINGFACE_EMBEDDING_RETRIES: int = max(1, int(os.getenv("HUGGINGFACE_EMBEDDING_RETRIES", "3")))

# ======================= LLM PROVIDERS =======================
GROQ_API_KEYS: list[str] = [
    v
    for v in (
        os.getenv("GROQ_API_KEY"),
        os.getenv("GROQ_API_KEY_2"),
        os.getenv("GROQ_API_KEY_3"),
    )
    if v
]
GROQ_CHAT_MODEL: str = os.getenv("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile")

OPENROUTER_API_KEYS: list[str] = [
    v
    for v in (
        os.getenv("OPENROUTER_API_KEY"),
        os.getenv("OPENROUTER_API_KEY_2"),
        os.getenv("OPENROUTER_API_KEY_3"),
    )
    if v
]
OPENROUTER_CHAT_MODEL: str = os.getenv("OPENROUTER_CHAT_MODEL", "openrouter/free")
OPENROUTER_SITE_URL: str = os.getenv("OPENROUTER_SITE_URL", "http://localhost:3000")
OPENROUTER_SITE_NAME: str = os.getenv("OPENROUTER_SITE_NAME", "Aksaraku")

PRIMARY_LLM_PROVIDER: str = os.getenv("PRIMARY_LLM_PROVIDER", "groq").strip().lower()
LLM_PROVIDER_MAX_ATTEMPTS: int = max(1, int(os.getenv("LLM_PROVIDER_MAX_ATTEMPTS", "12")))

# ======================= TOKEN LIMITS =======================
MAX_INPUT_TOKENS: int = int(os.getenv("MAX_INPUT_TOKENS", "3500"))
MAX_CONTEXT_TOKENS: int = int(os.getenv("MAX_CONTEXT_TOKENS", "2000"))
MAX_OUTPUT_TOKENS: int = int(os.getenv("MAX_OUTPUT_TOKENS", "600"))

# ======================= RAG SETTINGS =======================
RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "20"))
RAG_FINAL_K: int = int(os.getenv("RAG_FINAL_K", "8"))
RAG_MIN_SIMILARITY: float = float(os.getenv("RAG_MIN_SIMILARITY", "0.20"))
COMPRESS_CONTEXT: bool = os.getenv("COMPRESS_CONTEXT", "false").lower() in {"1", "true", "yes"}

# ======================= SESSION =======================
SESSION_TABLE: str = os.getenv("SESSION_TABLE", "chat_sessions")
MESSAGE_TABLE: str = os.getenv("MESSAGE_TABLE", "chat_messages")
SESSION_HISTORY_LIMIT: int = int(os.getenv("SESSION_HISTORY_LIMIT", "4"))

# ======================= CORS =======================
# Daftar origin yang boleh akses API. Isi di .env:
# ALLOWED_ORIGINS=https://domain-kamu.com,http://localhost:8081
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins
    else [
        "http://localhost:8080",
        "http://localhost:8081",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:8081",
    ]
)

# ======================= VALIDASI WAJIB =======================
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("SUPABASE_URL dan SUPABASE_SERVICE_ROLE_KEY wajib diisi di .env")
