# services/api/rag/generation.py — LLM generation dengan fallback multi-provider
import logging
import re
from typing import Any, Optional

from openai import OpenAI

import config
from utils.helpers import words, sentences, estimate_tokens

logger = logging.getLogger("aksaraku.generation")

# ======================= SYSTEM PROMPT =======================
SYSTEM_PROMPT = """
Kamu adalah asisten informasi Aksaraku.

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
   untuk memperpendek jawaban.
"""


# ======================= LLM CLIENT SETUP =======================

def _build_llm_clients() -> list[tuple[str, OpenAI, str]]:
    """Bangun daftar LLM client dengan rotasi multi-key dan multi-provider."""
    clients = []
    for index, api_key in enumerate(config.GROQ_API_KEYS, start=1):
        clients.append((
            f"groq_{index}",
            OpenAI(
                api_key=api_key,
                base_url="https://api.groq.com/openai/v1",
                max_retries=0,
            ),
            config.GROQ_CHAT_MODEL,
        ))
    for index, api_key in enumerate(config.OPENROUTER_API_KEYS, start=1):
        clients.append((
            f"openrouter_{index}",
            OpenAI(
                api_key=api_key,
                base_url="https://openrouter.ai/api/v1",
                max_retries=0,
                default_headers={
                    "HTTP-Referer": config.OPENROUTER_SITE_URL,
                    "X-Title": config.OPENROUTER_SITE_NAME,
                },
            ),
            config.OPENROUTER_CHAT_MODEL,
        ))
    return clients


LLM_CLIENTS = _build_llm_clients()


# ======================= HELPERS =======================

def _extract_openai_chat_text(response: Any) -> str:
    try:
        content = response.choices[0].message.content
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return "".join(
                item.get("text", "") for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ).strip()
    except Exception:
        pass
    return ""


def _usage(response: Any) -> dict:
    u = getattr(response, "usage", None)
    finish_reason = None
    try:
        finish_reason = response.choices[0].finish_reason
    except Exception:
        pass
    if u is None:
        return {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None, "finish_reason": finish_reason}
    def g(n):
        try:
            v = getattr(u, n, None)
            return int(v) if v is not None else None
        except Exception:
            return None
    return {"prompt_tokens": g("prompt_tokens"), "completion_tokens": g("completion_tokens"), "total_tokens": g("total_tokens"), "finish_reason": finish_reason}


def _strip_chain_of_thought(answer: str) -> str:
    if not answer:
        return answer
    result = answer
    for tag in ("reasoning", "chain_of_thought", "cot", "thinking", "scratchpad", "thought"):
        result = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", " ", result, flags=re.S | re.I)
    lowered = result.lower()
    for marker in ("jawaban akhir:", "jawaban:", "final answer:", "kesimpulan:", "output final:", "hasil jadinya:", "hasil:"):
        offset = lowered.rfind(marker)
        if offset >= 0:
            return result[offset + len(marker):].strip()
    return result


def clean_answer(answer: str) -> str:
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
    normalized = re.sub(r"\s+", " ", answer.lower()).strip(" .!\n")
    markers = (
        "informasi tidak ditemukan pada dokumen yang tersedia",
        "tidak ditemukan pada dokumen yang tersedia",
        "tidak ada informasi yang ditemukan pada dokumen",
    )
    return any(m in normalized for m in markers)


# ======================= CONTEXT =======================

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
    """Kompres context dengan memilih kalimat yang paling relevan dengan pertanyaan."""
    if not docs:
        return "", {"original_tokens": 0, "compressed_tokens": 0, "compression_ratio": 0.0, "sentences_kept": 0, "compressed": False}

    qwords = words(question)
    candidates = []
    original = []
    for di, doc in enumerate(docs):
        pdf = str(doc.get("pdf_name") or "Sumber tidak diketahui")
        content = str(doc.get("content") or doc.get("text") or "").strip()
        score = float(doc.get("similarity") or doc.get("score") or doc.get("similarity_score") or 0)
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
        return original_text, {"original_tokens": original_tokens, "compressed_tokens": original_tokens, "compression_ratio": 1.0, "sentences_kept": len(candidates), "compressed": False}

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
        "original_tokens": original_tokens, "compressed_tokens": ct,
        "compression_ratio": round(ct / max(1, original_tokens), 4),
        "sentences_kept": len(selected), "compressed": True,
    }


def calculate_evidence_confidence(question: str, docs: list[dict], answer: str) -> dict:
    """Hitung skor keyakinan jawaban berdasarkan overlap dengan dokumen sumber."""
    if not docs:
        return {"score": 0.0, "level": "low", "supported": False}
    awords = words(answer)
    scores = []
    for doc in docs:
        content = str(doc.get("content") or doc.get("text") or "")
        lexical = len(awords & words(content)) / max(1, len(awords))
        vector = float(doc.get("similarity") or doc.get("score") or doc.get("similarity_score") or 0)
        scores.append(vector * 0.65 + lexical * 0.35)
    score = max(0, min(max(scores), 1))
    level = "high" if score >= 0.78 else "medium" if score >= 0.55 else "low"
    return {"score": round(score, 3), "level": level, "supported": score >= 0.55}


def public_sources(documents: list[dict]) -> list[dict]:
    """Hapus field internal (embedding, similarity score) dari response publik."""
    hidden = {"embedding", "embbbed", "embeddings", "similarity", "score", "similarity_score", "confidence", "confidence_score", "akurasi", "accuracy"}
    return [{k: v for k, v in d.items() if k not in hidden} for d in documents]


# ======================= LLM GENERATION =======================

def generate_with_fallback(
    question: str,
    context: str,
    history: list[dict],
    force_direct: bool = False,
) -> tuple[str, str, dict]:
    """
    Generate jawaban menggunakan LLM dengan rotasi provider otomatis.
    Return: (answer, provider_name, usage_stats)
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT.strip()}]
    messages.extend(history[-config.SESSION_HISTORY_LIMIT:])
    user_content = (
        f"SOURCE DOKUMEN:\n\n{context or '[Tidak ada SOURCE yang relevan]'}\n\n"
        f"PERTANYAAN:\n{question}\n\nJAWAB:"
    )
    if force_direct:
        user_content += (
            "\n\nPENTING: SOURCE tidak kosong. Periksa ulang semua SOURCE dan jawab "
            "berdasarkan fakta yang paling relevan. Jawab langsung dan sangat ringkas "
            "tanpa kalimat pengantar, tanpa proses berpikir, tanpa analisis."
        )
    messages.append({"role": "user", "content": user_content})

    if not LLM_CLIENTS:
        raise RuntimeError("Tidak ada LLM provider yang terkonfigurasi")

    errors = []
    for attempt in range(config.LLM_PROVIDER_MAX_ATTEMPTS):
        name, client, model = LLM_CLIENTS[attempt % len(LLM_CLIENTS)]
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.2,
                max_tokens=config.MAX_OUTPUT_TOKENS,
            )
            answer = _extract_openai_chat_text(response)
            if not answer:
                raise RuntimeError(f"{model} returned empty response")
            return answer, name, _usage(response)
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            logger.warning(
                "LLM provider %s gagal (attempt %s/%s): %s",
                name, attempt + 1, config.LLM_PROVIDER_MAX_ATTEMPTS, exc,
            )

    raise RuntimeError(
        f"Semua LLM provider gagal setelah {config.LLM_PROVIDER_MAX_ATTEMPTS} attempt. "
        + " | ".join(errors)
    )
