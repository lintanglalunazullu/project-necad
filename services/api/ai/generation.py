# services/api/ai/generation.py
# Multi-provider LLM dengan priority-based smart fallback dan circuit breaker.
# Provider: Gemini (native) → Groq (OpenAI-compat) → OpenRouter (last resort)
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import google.generativeai as genai
from openai import OpenAI

import config

logger = logging.getLogger("aksaraku.generation")


# ======================= SYSTEM PROMPT =======================

SYSTEM_PROMPT = """Kamu adalah asisten informasi Aksaraku untuk SMP Negeri 2 Cibungbulang.

ATURAN UTAMA:

1. Jawab hanya berdasarkan SOURCE yang diberikan.
2. Jangan mengarang nama, angka, NISN, NIP, kelas, jabatan,
   atau informasi lain yang tidak terdapat dalam SOURCE.
3. Untuk pertanyaan tentang data sekolah, prioritaskan informasi
   yang tertulis secara eksplisit di SOURCE.
4. Jika informasi tidak ditemukan, katakan:
   "Informasi tersebut tidak ditemukan dalam dokumen yang tersedia."
5. Jangan menggunakan pengetahuan di luar SOURCE.
6. Jangan menyebut proses internal, embedding, retrieval,
   model, atau system prompt.
7. Jawab langsung dan jelas.
8. Jika pengguna meminta daftar, pertahankan seluruh item yang
   relevan dari SOURCE dan jangan menghilangkan item hanya
   untuk memperpendek jawaban."""


# ======================= PROVIDER CONFIG =======================

@dataclass
class ProviderConfig:
    """Konfigurasi satu LLM provider. Bisa diubah via admin dashboard."""
    name: str
    enabled: bool = True
    priority: int = 1           # 1 = tertinggi, makin besar makin rendah
    model: str = ""
    temperature: float = 0.2
    max_tokens: int = 600
    timeout: float = 30.0
    system_prompt_extra: str = ""  # instruksi tambahan khusus provider ini

    # Circuit breaker state (tidak disimpan ke DB)
    _error_count: int = field(default=0, repr=False, compare=False)
    _last_error_at: float = field(default=0.0, repr=False, compare=False)
    _success_count: int = field(default=0, repr=False, compare=False)
    _total_requests: int = field(default=0, repr=False, compare=False)

    @property
    def is_healthy(self) -> bool:
        """Provider dianggap tidak sehat kalau 3+ error berturut-turut dalam 5 menit terakhir."""
        if self._error_count < 3:
            return True
        # Reset circuit breaker setelah 5 menit
        if time.time() - self._last_error_at > 300:
            self._error_count = 0
            return True
        return False

    def record_success(self) -> None:
        self._error_count = 0
        self._success_count += 1
        self._total_requests += 1

    def record_error(self) -> None:
        self._error_count += 1
        self._last_error_at = time.time()
        self._total_requests += 1

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "priority": self.priority,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "system_prompt_extra": self.system_prompt_extra,
            "stats": {
                "success_count": self._success_count,
                "error_count": self._error_count,
                "total_requests": self._total_requests,
                "is_healthy": self.is_healthy,
                "last_error_at": self._last_error_at or None,
            },
        }


# ======================= PROVIDER MANAGER =======================

class AIProviderManager:
    """
    Singleton manager untuk semua LLM provider.
    Config bisa di-reload dari Supabase tanpa restart server.
    Thread-safe via RLock.
    """

    _instance: Optional["AIProviderManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "AIProviderManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._rw_lock = threading.RLock()
        self._providers: dict[str, ProviderConfig] = {}
        self._openai_clients: dict[str, list[tuple[str, OpenAI]]] = {}
        self._initialized = True
        self._load_defaults()

    def _load_defaults(self) -> None:
        """Load konfigurasi default dari environment variable."""
        with self._rw_lock:
            self._providers.clear()
            self._openai_clients.clear()

            # --- Gemini ---
            if config.GEMINI_API_KEY:
                self._providers["gemini"] = ProviderConfig(
                    name="gemini",
                    enabled=True,
                    priority=1,
                    model=config.GEMINI_CHAT_MODEL,
                    temperature=0.2,
                    max_tokens=config.MAX_OUTPUT_TOKENS,
                    timeout=30.0,
                )

            # --- Groq (multi-key round-robin) ---
            if config.GROQ_API_KEYS:
                self._providers["groq"] = ProviderConfig(
                    name="groq",
                    enabled=True,
                    priority=2,
                    model=config.GROQ_CHAT_MODEL,
                    temperature=0.2,
                    max_tokens=config.MAX_OUTPUT_TOKENS,
                    timeout=25.0,
                )
                self._openai_clients["groq"] = [
                    (f"groq_{i}", OpenAI(
                        api_key=key,
                        base_url="https://api.groq.com/openai/v1",
                        max_retries=0,
                        timeout=25.0,
                    ))
                    for i, key in enumerate(config.GROQ_API_KEYS, 1)
                ]

            # --- OpenRouter (multi-key round-robin) ---
            if config.OPENROUTER_API_KEYS:
                self._providers["openrouter"] = ProviderConfig(
                    name="openrouter",
                    enabled=True,
                    priority=3,
                    model=config.OPENROUTER_CHAT_MODEL,
                    temperature=0.2,
                    max_tokens=config.MAX_OUTPUT_TOKENS,
                    timeout=40.0,
                )
                self._openai_clients["openrouter"] = [
                    (f"openrouter_{i}", OpenAI(
                        api_key=key,
                        base_url="https://openrouter.ai/api/v1",
                        max_retries=0,
                        timeout=40.0,
                        default_headers={
                            "HTTP-Referer": config.OPENROUTER_SITE_URL,
                            "X-Title": config.OPENROUTER_SITE_NAME,
                        },
                    ))
                    for i, key in enumerate(config.OPENROUTER_API_KEYS, 1)
                ]

            logger.info(
                "AIProviderManager loaded: %s",
                ", ".join(f"{n}(priority={p.priority})" for n, p in self._providers.items()),
            )

    def reload_from_db(self, supabase: Any) -> int:
        """
        Reload config provider dari Supabase table ai_provider_config.
        Return jumlah provider yang diupdate. Graceful — kalau tabel tidak ada, skip.
        """
        try:
            response = supabase.table(config.AI_CONFIG_TABLE).select("*").execute()
            rows = getattr(response, "data", None) or []
        except Exception as exc:
            logger.info("ai_provider_config table tidak ada atau tidak bisa diakses: %s", exc)
            return 0

        updated = 0
        with self._rw_lock:
            for row in rows:
                name = str(row.get("id") or "").strip().lower()
                if name not in self._providers:
                    continue
                p = self._providers[name]
                if row.get("enabled") is not None:
                    p.enabled = bool(row["enabled"])
                if row.get("model"):
                    p.model = str(row["model"]).strip()
                if row.get("temperature") is not None:
                    p.temperature = float(row["temperature"])
                if row.get("max_tokens") is not None:
                    p.max_tokens = int(row["max_tokens"])
                if row.get("priority") is not None:
                    p.priority = int(row["priority"])
                if row.get("system_prompt_extra") is not None:
                    p.system_prompt_extra = str(row["system_prompt_extra"])
                updated += 1

        logger.info("Reload dari DB: %s provider diupdate", updated)
        return updated

    def update_provider(self, name: str, updates: dict) -> ProviderConfig:
        """Update config satu provider. Dipanggil dari admin endpoint."""
        with self._rw_lock:
            if name not in self._providers:
                raise ValueError(f"Provider '{name}' tidak ditemukan")
            p = self._providers[name]
            allowed = {"enabled", "model", "temperature", "max_tokens", "priority", "timeout", "system_prompt_extra"}
            for key, val in updates.items():
                if key in allowed and val is not None:
                    setattr(p, key, val)
            return p

    def get_sorted_providers(self) -> list[ProviderConfig]:
        """Kembalikan provider aktif dan sehat, diurutkan berdasarkan priority."""
        with self._rw_lock:
            return sorted(
                [p for p in self._providers.values() if p.enabled and p.is_healthy],
                key=lambda p: p.priority,
            )

    def get_all_providers(self) -> list[ProviderConfig]:
        """Kembalikan semua provider (termasuk disabled) untuk admin dashboard."""
        with self._rw_lock:
            return sorted(self._providers.values(), key=lambda p: p.priority)

    def get_provider(self, name: str) -> ProviderConfig | None:
        with self._rw_lock:
            return self._providers.get(name)

    def get_openai_clients(self, provider_name: str) -> list[tuple[str, OpenAI]]:
        with self._rw_lock:
            return list(self._openai_clients.get(provider_name, []))


def get_provider_manager() -> AIProviderManager:
    """Ambil singleton AIProviderManager."""
    return AIProviderManager()


# ======================= LLM CALL PER PROVIDER =======================

def _call_gemini(provider: ProviderConfig, messages: list[dict]) -> tuple[str, dict]:
    """Call Gemini native SDK."""
    genai.configure(api_key=config.GEMINI_API_KEY)

    system_parts = [SYSTEM_PROMPT]
    if provider.system_prompt_extra:
        system_parts.append(provider.system_prompt_extra)

    # Konversi format messages OpenAI → Gemini
    gemini_history = []
    user_content = ""
    for msg in messages:
        role = msg.get("role", "")
        content = str(msg.get("content") or "")
        if role == "system":
            system_parts.append(content)
        elif role == "user":
            user_content = content
        elif role == "assistant":
            gemini_history.append({"role": "model", "parts": [content]})

    model = genai.GenerativeModel(
        model_name=provider.model,
        system_instruction="\n\n".join(system_parts),
        generation_config=genai.GenerationConfig(
            temperature=provider.temperature,
            max_output_tokens=provider.max_tokens,
        ),
    )

    chat = model.start_chat(history=gemini_history)
    response = chat.send_message(user_content, request_options={"timeout": int(provider.timeout)})

    text = response.text.strip() if response.text else ""
    usage = {}
    try:
        u = response.usage_metadata
        usage = {
            "prompt_tokens": getattr(u, "prompt_token_count", None),
            "completion_tokens": getattr(u, "candidates_token_count", None),
            "total_tokens": getattr(u, "total_token_count", None),
        }
    except Exception:
        pass

    return text, usage


def _call_openai_compat(
    provider: ProviderConfig,
    clients: list[tuple[str, OpenAI]],
    messages: list[dict],
    attempt_offset: int,
) -> tuple[str, str, dict]:
    """Call provider yang pakai OpenAI-compatible API (Groq, OpenRouter)."""
    if not clients:
        raise RuntimeError(f"Tidak ada client untuk provider {provider.name}")

    # Inject system prompt extra jika ada
    if provider.system_prompt_extra:
        # Append ke pesan system pertama yang ada
        patched = []
        injected = False
        for msg in messages:
            if msg.get("role") == "system" and not injected:
                patched.append({**msg, "content": msg["content"] + "\n\n" + provider.system_prompt_extra})
                injected = True
            else:
                patched.append(msg)
        messages = patched

    client_id, client = clients[attempt_offset % len(clients)]
    response = client.chat.completions.create(
        model=provider.model,
        messages=messages,
        temperature=provider.temperature,
        max_tokens=provider.max_tokens,
    )

    text = ""
    try:
        content = response.choices[0].message.content
        if isinstance(content, str):
            text = content.strip()
        elif isinstance(content, list):
            text = "".join(
                item.get("text", "") for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ).strip()
    except Exception:
        pass

    usage: dict = {}
    try:
        u = response.usage
        usage = {
            "prompt_tokens": getattr(u, "prompt_tokens", None),
            "completion_tokens": getattr(u, "completion_tokens", None),
            "total_tokens": getattr(u, "total_tokens", None),
            "finish_reason": response.choices[0].finish_reason if response.choices else None,
        }
    except Exception:
        pass

    return text, client_id, usage


# ======================= SMART FALLBACK GENERATION =======================

def generate_with_fallback(
    question: str,
    context: str,
    history: list[dict],
    force_direct: bool = False,
) -> tuple[str, str, dict]:
    """
    Generate jawaban dengan smart fallback antar provider.
    Priority: Gemini → Groq → OpenRouter (sesuai config, bisa diubah via admin).
    Return: (answer, provider_name, usage_stats)
    """
    manager = get_provider_manager()
    providers = manager.get_sorted_providers()

    if not providers:
        raise RuntimeError("Tidak ada LLM provider yang aktif dan sehat. Cek konfigurasi di admin dashboard.")

    # Susun messages OpenAI format (Gemini juga dikonversi dari sini)
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT.strip()}]
    messages.extend(history[-config.SESSION_HISTORY_LIMIT:])

    user_content = (
        f"SOURCE DOKUMEN:\n\n{context or '[Tidak ada SOURCE yang relevan]'}\n\n"
        f"PERTANYAAN:\n{question}\n\nJAWAB:"
    )
    if force_direct:
        user_content += (
            "\n\nPENTING: SOURCE tidak kosong. Periksa ulang semua SOURCE dan jawab "
            "berdasarkan fakta yang paling relevan. Jawab langsung dan sangat ringkas "
            "tanpa kalimat pengantar, tanpa proses berpikir."
        )
    messages.append({"role": "user", "content": user_content})

    errors: list[str] = []
    for attempt, provider in enumerate(providers):
        try:
            if provider.name == "gemini":
                answer, usage = _call_gemini(provider, messages)
                if not answer:
                    raise RuntimeError("Gemini returned empty response")
                provider.record_success()
                logger.info("LLM success via %s", provider.name)
                return answer, provider.name, usage

            else:
                clients = manager.get_openai_clients(provider.name)
                answer, client_id, usage = _call_openai_compat(provider, clients, messages, attempt)
                if not answer:
                    raise RuntimeError(f"{provider.model} returned empty response")
                provider.record_success()
                logger.info("LLM success via %s (%s)", provider.name, client_id)
                return answer, f"{provider.name}/{client_id}", usage

        except Exception as exc:
            provider.record_error()
            errors.append(f"{provider.name}: {exc}")
            logger.warning(
                "LLM provider %s gagal (attempt %s/%s): %s",
                provider.name, attempt + 1, len(providers), exc,
            )

    raise RuntimeError(
        f"Semua LLM provider gagal ({len(providers)} provider dicoba). "
        + " | ".join(errors)
    )


# ======================= CONTEXT HELPERS =======================

def render_documents_raw(documents: list[dict]) -> str:
    """Render dokumen sebagai blok teks terstruktur untuk LLM."""
    parts = []
    for index, doc in enumerate(documents, start=1):
        parts.append(
            f"\n--- SOURCE {index} ---\n"
            f"ID: {doc.get('id')}\n"
            f"PDF: {doc.get('pdf_name')}\n"
            f"CATEGORY: {doc.get('category', 'public')}\n\n"
            f"{doc.get('content', '')}\n"
            f"--- END SOURCE {index} ---\n"
        )
    return "\n".join(parts)


def compress_context(
    question: str, docs: list[dict], max_tokens: int
) -> tuple[str, dict]:
    """Kompres context dengan memilih kalimat yang paling relevan."""
    from utils.helpers import words, sentences, estimate_tokens

    if not docs:
        return "", {"original_tokens": 0, "compressed_tokens": 0, "compression_ratio": 0.0, "sentences_kept": 0, "compressed": False}

    qwords = words(question)
    candidates = []
    original = []

    for di, doc in enumerate(docs):
        pdf = str(doc.get("pdf_name") or "Sumber tidak diketahui")
        content = str(doc.get("content") or doc.get("text") or "").strip()
        score = float(doc.get("similarity") or doc.get("score") or 0)
        original.append(f"[SOURCE {di + 1}]\nFile: {pdf}\n{content}")
        for si, sentence in enumerate(sentences(content)):
            overlap = len(words(sentence) & qwords) / max(1, len(qwords))
            candidates.append({
                "di": di, "si": si, "pdf": pdf, "s": sentence,
                "score": overlap * 0.7 + max(0, min(score, 1)) * 0.3 + (0.03 if si == 0 else 0),
            })

    original_text = "\n\n---\n\n".join(original)
    original_tokens = estimate_tokens(original_text)

    if not config.COMPRESS_CONTEXT or original_tokens <= max_tokens:
        return original_text, {
            "original_tokens": original_tokens,
            "compressed_tokens": original_tokens,
            "compression_ratio": 1.0,
            "sentences_kept": len(candidates),
            "compressed": False,
        }

    grouped: dict[int, list] = {}
    for c in candidates:
        grouped.setdefault(c["di"], []).append(c)

    selected = []
    selected_keys: set = set()
    for di in range(len(docs)):
        arr = sorted(grouped.get(di, []), key=lambda x: x["score"], reverse=True)
        if arr:
            selected.append(arr[0])
            selected_keys.add((arr[0]["di"], arr[0]["si"]))

    def render(items: list) -> str:
        groups: dict = {}
        for c in items:
            groups.setdefault(c["di"], []).append(c)
        blocks = []
        for di in sorted(groups):
            arr = sorted(groups[di], key=lambda x: x["si"])
            blocks.append(
                f"[SOURCE {di + 1}]\nFile: {arr[0]['pdf']}\n"
                + " ".join(x["s"] for x in arr)
            )
        return "\n\n---\n\n".join(blocks)

    for c in sorted(candidates, key=lambda x: x["score"], reverse=True):
        key = (c["di"], c["si"])
        if key in selected_keys:
            continue
        trial = selected + [c]
        if estimate_tokens(render(trial)) <= max_tokens:
            selected.append(c)
            selected_keys.add(key)

    compressed = render(selected)
    if estimate_tokens(compressed) > max_tokens:
        compressed = compressed[: max_tokens * 4].rsplit(" ", 1)[0] + "…"

    ct = estimate_tokens(compressed)
    return compressed, {
        "original_tokens": original_tokens,
        "compressed_tokens": ct,
        "compression_ratio": round(ct / max(1, original_tokens), 4),
        "sentences_kept": len(selected),
        "compressed": True,
    }


def calculate_evidence_confidence(question: str, docs: list[dict], answer: str) -> dict:
    """Hitung skor keyakinan jawaban berdasarkan overlap dengan dokumen sumber."""
    from utils.helpers import words

    if not docs:
        return {"score": 0.0, "level": "low", "supported": False}

    awords = words(answer)
    scores = []
    for doc in docs:
        content = str(doc.get("content") or doc.get("text") or "")
        lexical = len(awords & words(content)) / max(1, len(awords))
        vector = float(doc.get("similarity") or doc.get("score") or 0)
        scores.append(vector * 0.65 + lexical * 0.35)

    score = max(0, min(max(scores), 1))
    level = "high" if score >= 0.78 else "medium" if score >= 0.55 else "low"
    return {"score": round(score, 3), "level": level, "supported": score >= 0.55}


def public_sources(documents: list[dict]) -> list[dict]:
    """Hapus field internal (embedding, similarity score) dari response publik."""
    hidden = {"embedding", "embeddings", "similarity", "score", "similarity_score",
              "confidence", "confidence_score", "akurasi", "accuracy", "rrf_score", "keyword_score"}
    return [{k: v for k, v in d.items() if k not in hidden} for d in documents]


# ======================= ANSWER CLEANUP =======================

def _strip_chain_of_thought(answer: str) -> str:
    """Hapus tag chain-of-thought dari jawaban LLM (khusus model reasoning)."""
    if not answer:
        return answer
    result = answer
    for tag in ("reasoning", "chain_of_thought", "cot", "thinking", "scratchpad", "thought"):
        result = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", " ", result, flags=re.S | re.I)
    lowered = result.lower()
    for marker in ("jawaban akhir:", "jawaban:", "final answer:", "kesimpulan:", "output final:", "hasil:"):
        offset = lowered.rfind(marker)
        if offset >= 0:
            return result[offset + len(marker):].strip()
    return result


def clean_answer(answer: str) -> str:
    """Bersihkan jawaban dari artefak chain-of-thought dan whitespace berlebih."""
    answer = _strip_chain_of_thought(answer)
    patterns = [
        r"\s*\*{0,2}Tidak ada nilai akurasi yang tersedia dalam dokumen\.?\*{0,2}\s*",
        r"\s*nilai akurasi tidak tersedia\.?\s*",
    ]
    for p in patterns:
        answer = re.sub(p, " ", answer, flags=re.I)
    answer = re.sub(r"[ \t]{2,}", " ", answer)
    answer = re.sub(r"\n{3,}", "\n\n", answer)
    return answer.strip()


def answer_claims_no_information(answer: str) -> bool:
    """Deteksi kalau LLM bilang tidak ada info padahal ada dokumen."""
    normalized = re.sub(r"\s+", " ", answer.lower()).strip(" .!\n")
    markers = (
        "informasi tidak ditemukan pada dokumen yang tersedia",
        "tidak ditemukan pada dokumen yang tersedia",
        "tidak ada informasi yang ditemukan pada dokumen",
    )
    return any(m in normalized for m in markers)
