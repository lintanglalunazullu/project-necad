# services/api/config.py — Konfigurasi terpusat dari environment variable
import os
from dotenv import load_dotenv

# Muat .env baik dari direktori services/api maupun dari CWD root
_this_dir = os.path.dirname(os.path.abspath(__file__))
_local_env = os.path.join(_this_dir, ".env")
if os.path.exists(_local_env):
    load_dotenv(dotenv_path=_local_env)
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

# ======================= AI PROVIDER CONFIG TABLE =======================
# Nama tabel Supabase untuk menyimpan konfigurasi AI provider secara persistent.
# Kalau tabelnya belum ada, fallback ke konfigurasi ENV (tidak error).
AI_CONFIG_TABLE: str = os.getenv("AI_CONFIG_TABLE", "ai_provider_config")

# ======================= EMBEDDING (Gemini) =======================
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_EMBEDDING_MODEL: str = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")
# Dimensi output embedding. Kolom vector Supabase pdf_documents adalah vector(384).
EXPECTED_EMBEDDING_DIMENSION: int = int(os.getenv("EXPECTED_EMBEDDING_DIMENSION", "384"))
EMBEDDING_RETRIES: int = max(1, int(os.getenv("EMBEDDING_RETRIES", "3")))

# ======================= LLM PROVIDERS =======================
# --- Gemini ---
GEMINI_CHAT_MODEL: str = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.5-flash-lite")

# --- Groq (support multi-key round-robin) ---
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

# --- OpenRouter (support multi-key round-robin) ---
OPENROUTER_API_KEYS: list[str] = [
    v
    for v in (
        os.getenv("OPENROUTER_API_KEY"),
        os.getenv("OPENROUTER_API_KEY_2"),
        os.getenv("OPENROUTER_API_KEY_3"),
    )
    if v
]
OPENROUTER_CHAT_MODEL: str = os.getenv("OPENROUTER_CHAT_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
OPENROUTER_SITE_URL: str = os.getenv("OPENROUTER_SITE_URL", "http://localhost:3000")
OPENROUTER_SITE_NAME: str = os.getenv("OPENROUTER_SITE_NAME", "Aksaraku")

# ======================= TOKEN LIMITS =======================
MAX_INPUT_TOKENS: int = int(os.getenv("MAX_INPUT_TOKENS", "3500"))
MAX_CONTEXT_TOKENS: int = int(os.getenv("MAX_CONTEXT_TOKENS", "2000"))
MAX_OUTPUT_TOKENS: int = int(os.getenv("MAX_OUTPUT_TOKENS", "600"))

# ======================= RAG SETTINGS =======================
RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "20"))
RAG_FINAL_K: int = int(os.getenv("RAG_FINAL_K", "8"))
RAG_MIN_SIMILARITY: float = float(os.getenv("RAG_MIN_SIMILARITY", "0.05"))
COMPRESS_CONTEXT: bool = os.getenv("COMPRESS_CONTEXT", "false").lower() in {"1", "true", "yes"}

# ======================= SESSION =======================
SESSION_TABLE: str = os.getenv("SESSION_TABLE", "chat_sessions")
MESSAGE_TABLE: str = os.getenv("MESSAGE_TABLE", "chat_messages")
SESSION_HISTORY_LIMIT: int = int(os.getenv("SESSION_HISTORY_LIMIT", "4"))

# ======================= CORS =======================
# Daftar origin yang boleh akses API. Isi di .env:
# ALLOWED_ORIGINS=https://smpn2cibungbulang.sch.id,https://mentor.smpn2cibungbulang.sch.id
_raw_origins = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS: list[str] = (
    [o.strip() for o in _raw_origins.split(",") if o.strip()]
    if _raw_origins
    else [
        "http://localhost:8080",
        "http://localhost:8081",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:8081",
        "https://smpn2cibungbulang.sch.id",
        "https://www.smpn2cibungbulang.sch.id",
        "https://mentor.smpn2cibungbulang.sch.id",
        "https://api.smpn2cibungbulang.sch.id",
    ]
)

# Regex pattern untuk mengizinkan semua subdomain sekolah, vercel.app, & localhost secara fleksibel
ALLOWED_ORIGIN_REGEX: str = os.getenv(
    "ALLOWED_ORIGIN_REGEX",
    r"^(https?://([a-zA-Z0-9-]+\.)*(smpn2cibungbulang\.sch\.id|vercel\.app)(:[0-9]+)?|http://(localhost|127\.0\.0\.1)(:[0-9]+)?)$",
)


# ======================= VALIDASI WAJIB =======================
if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise RuntimeError("SUPABASE_URL dan SUPABASE_SERVICE_ROLE_KEY wajib diisi di .env")

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY wajib diisi di .env. "
        "Dapatkan gratis di: https://aistudio.google.com/apikey"
    )
