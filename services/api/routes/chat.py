# services/api/routes/chat.py — Endpoint chat RAG dan query dokumen
#
# CATATAN KONKURENSI:
# supabase-py, google-generativeai, dan client OpenAI-compatible yang dipakai di
# sini semuanya SYNCHRONOUS (blocking network call). Sebelumnya endpoint ini
# adalah `async def` yang langsung memanggil fungsi-fungsi blocking tersebut —
# artinya SETIAP request chat menahan event loop FastAPI selama seluruh durasi
# embedding + pencarian + generation (bisa beberapa detik, lebih lama lagi kalau
# ada retry). Akibatnya request chat dari user lain ikut mengantre walau server
# "async". Fix: logika berat dipindah ke fungsi sync biasa (`_chat_sync` /
# `_query_docs_sync`) yang dijalankan lewat `asyncio.to_thread`, supaya event
# loop tetap bebas melayani request lain selagi satu chat sedang diproses.
import asyncio
import logging
import json
import threading
import time
from collections import OrderedDict
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from supabase import Client

import config
from auth import authenticated_role, chat_role, filter_documents_for_role
from models import QueryRequest
from ai.embedding import embed_query
from ai.generation import (
    SYSTEM_PROMPT,
    RateLimitError,
    answer_claims_no_information,
    calculate_evidence_confidence,
    clean_answer,
    compress_context,
    generate_with_fallback,
    generate_stream_with_fallback,
    public_sources,
    render_documents_raw,
)
from ai.guardrails import check_guardrails, GUARDRAIL_DEFLECTION_ANSWER
from ai.retrieval import get_similar_documents, is_structured_question, rerank_documents
from ai.session import build_search_query, ensure_session, get_session_history, save_message
from utils.helpers import estimate_tokens

logger = logging.getLogger("aksaraku.routes.chat")


def log_unanswered_query(supabase: Client, question: str, role: str, reason: str, score: float = 0.0) -> None:
    """Catat query yang gagal menemukan dokumen atau tidak ada jawaban ke tabel unanswered_queries."""
    if not supabase or not question:
        return
    import re
    norm_q = re.sub(r"[^\w\s]", " ", question.lower()).strip()
    norm_q = re.sub(r"\s+", " ", norm_q)
    try:
        supabase.table("unanswered_queries").insert({
            "question": question.strip()[:500],
            "normalized_question": norm_q[:500],
            "role": role,
            "reason": reason,
            "similarity_score": round(float(score), 4),
        }).execute()
    except Exception as exc:
        logger.debug("Catat unanswered query dilewati (tabel belum dimigrasi): %s", exc)

router = APIRouter(tags=["chat"])
limiter = Limiter(key_func=get_remote_address)

DOCUMENT_INVENTORY_MARKERS = (
    "dokumen apa",
    "dokumen yang kamu ketahui",
    "dokumen yang tersedia",
    "daftar dokumen",
    "dokumen apa saja",
    "file apa",
)


def _get_supabase() -> Client:
    from app import supabase
    return supabase


GREETINGS = {
    "hai", "halo", "hello", "hi", "hey", "p", "tes", "test", "ping",
    "selamat pagi", "selamat siang", "selamat sore", "selamat malam",
    "assalamualaikum", "assalamu'alaikum", "assalamu alaikum"
}


def _is_greeting(text: str) -> bool:
    import re
    clean = re.sub(r"[^\w\s]", "", text.lower()).strip()
    return clean in GREETINGS


def _is_document_inventory_question(question: str) -> bool:
    import re
    normalized = re.sub(r"\s+", " ", question.lower()).strip()
    return any(marker in normalized for marker in DOCUMENT_INVENTORY_MARKERS)


def _query_docs_sync(supabase: Client, body: QueryRequest, authorization: Optional[str]) -> dict:
    role = authenticated_role(supabase, authorization)
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "question is required")

    try:
        question_embedding = embed_query(question)
    except Exception as embed_err:
        raise HTTPException(400, f"Gagal generate embedding: {embed_err}")
    retrieved = get_similar_documents(supabase, question_embedding, role, config.RAG_TOP_K, question)
    docs = rerank_documents(question, filter_documents_for_role(retrieved, role), config.RAG_FINAL_K)
    return {"data": public_sources(docs)}


@router.post("/query-docs")
@limiter.limit("60/minute")
async def query_docs(request: Request, body: QueryRequest, authorization: Optional[str] = Header(default=None)):
    """Cari dokumen relevan berdasarkan pertanyaan (tanpa generate jawaban LLM)."""
    supabase = _get_supabase()
    return await asyncio.to_thread(_query_docs_sync, supabase, body, authorization)


class ResponseCache:
    """In-memory LRU TTL Cache untuk respons FAQ dan pertanyaan umum sekolah."""
    def __init__(self, max_size: int = 500, ttl_seconds: int = 3600):
        self._cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[dict]:
        with self._lock:
            if key not in self._cache:
                return None
            ts, val = self._cache[key]
            if time.time() - ts > self._ttl:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return dict(val)

    def set(self, key: str, val: dict) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (time.time(), dict(val))
            if len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

response_cache = ResponseCache(max_size=500, ttl_seconds=3600)


def _chat_sync(supabase: Client, body: QueryRequest, authorization: Optional[str]) -> dict:
    """Seluruh pipeline chat RAG. Dijalankan di thread pool — lihat catatan di atas file."""
    role = chat_role(supabase, authorization)

    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    # ========= GUARDRAILS & ANTI-JAILBREAK =========
    is_safe, violation, clean_q = check_guardrails(question)
    if not is_safe:
        logger.warning("Guardrail blocked question: '%s' (reason: %s)", question[:60], violation)
        persist_session = role != "anonymous"
        if persist_session:
            ensure_session(supabase, body.session_id)
            save_message(supabase, body.session_id, "user", question)
            save_message(supabase, body.session_id, "assistant", GUARDRAIL_DEFLECTION_ANSWER)
        return {
            "answer": GUARDRAIL_DEFLECTION_ANSWER,
            "session_id": body.session_id if persist_session else None,
            "provider": "system/guardrail",
            "sources": [],
            "evidence": {"confidence": 1.0, "supported": True},
            "retrieval": {"retrieved_count": 0, "final_count": 0, "min_similarity": config.RAG_MIN_SIMILARITY},
            "token_optimization": {
                "enabled": False,
                "estimated_input_tokens": 0,
                "context_original_tokens": 0,
                "context_compressed_tokens": 0,
                "compression_ratio": 1.0,
                "sentences_kept": 0,
                "max_context_tokens": config.MAX_CONTEXT_TOKENS,
                "max_input_tokens": config.MAX_INPUT_TOKENS,
                "max_output_tokens": config.MAX_OUTPUT_TOKENS,
                "provider_usage": None,
            },
        }
    question = clean_q

    # ========= SESSION =========
    persist_session = role != "anonymous"
    if persist_session:
        ensure_session(supabase, body.session_id)

    history = get_session_history(supabase, body.session_id) if persist_session else []

    # ========= FAQ RESPONSE CACHE =========
    cache_key = None
    if not history:
        import re
        norm_q = re.sub(r"[^\w\s]", "", question.lower()).strip()
        norm_q = re.sub(r"\s+", " ", norm_q)
        if len(norm_q) >= 4:
            cache_key = f"{role}:{norm_q}"
            cached_res = response_cache.get(cache_key)
            if cached_res:
                logger.info("Cache hit FAQ untuk: '%s'", question)
                cached_res["session_id"] = body.session_id if persist_session else None
                cached_res["cached"] = True
                if persist_session:
                    save_message(supabase, body.session_id, "assistant", cached_res["answer"])
                return cached_res

    # ========= QUERY =========
    search_query = build_search_query(question, history)
    if persist_session:
        save_message(supabase, body.session_id, "user", question)

    # ========= GREETING SHORTCUT =========
    if _is_greeting(question):
        greeting_ans = (
            "Halo! Saya Aksaraku AI, asisten virtual SMP Negeri 2 Cibungbulang. "
            "Ada yang bisa saya bantu terkait informasi sekolah, profil, visi misi, fasilitas, atau data guru?"
        )
        if persist_session:
            save_message(supabase, body.session_id, "assistant", greeting_ans)
        return {
            "answer": greeting_ans,
            "session_id": body.session_id if persist_session else None,
            "provider": "assistant",
            "sources": [],
            "evidence": {"confidence": 1.0, "supported": True},
            "retrieval": {"retrieved_count": 0, "final_count": 0, "min_similarity": config.RAG_MIN_SIMILARITY},
            "token_optimization": {
                "enabled": False,
                "estimated_input_tokens": 0,
                "context_original_tokens": 0,
                "context_compressed_tokens": 0,
                "compression_ratio": 1.0,
                "sentences_kept": 0,
                "max_context_tokens": config.MAX_CONTEXT_TOKENS,
                "max_input_tokens": config.MAX_INPUT_TOKENS,
                "max_output_tokens": config.MAX_OUTPUT_TOKENS,
                "provider_usage": None,
            },
        }

    # ========= DOCUMENT INVENTORY SHORTCUT =========
    if _is_document_inventory_question(question):
        from ai.retrieval import fetch_document_summary
        inventory = filter_documents_for_role(fetch_document_summary(supabase), role)
        docs = [
            {**doc, "content": f"Dokumen: {doc['pdf_name']}; jumlah chunk: {doc['chunk_count']}", "similarity": 1.0}
            for doc in inventory
        ]
        retrieved = docs
        context = "\n".join(doc["content"] for doc in docs)
        compression = {
            "original_tokens": estimate_tokens(context),
            "compressed_tokens": estimate_tokens(context),
            "compression_ratio": 1.0,
            "sentences_kept": len(docs),
            "compressed": False,
        }

    # ========= NORMAL RAG SEARCH =========
    else:
        try:
            search_embedding = embed_query(search_query)
        except Exception as embed_err:
            err_str = str(embed_err)
            logger.error("Embedding generation failed: %s", err_str)
            if "API key not valid" in err_str or "API_KEY_INVALID" in err_str or "wajib diisi" in err_str:
                msg = (
                    "⚠️ **GEMINI_API_KEY** belum diisi atau tidak valid di file `services/api/.env`.\n\n"
                    "Untuk mengaktifkan fitur tanya-jawab AI, silakan dapatkan API Key gratis di "
                    "[Google AI Studio](https://aistudio.google.com/apikey) lalu masukkan ke `services/api/.env`."
                )
                if persist_session:
                    save_message(supabase, body.session_id, "assistant", msg)
                return {
                    "answer": msg,
                    "session_id": body.session_id if persist_session else None,
                    "provider": None,
                    "sources": [],
                    "evidence": {"confidence": 0.0, "supported": False},
                }
            raise HTTPException(500, f"Gagal memproses embedding dokumen: {err_str}")

        retrieved = get_similar_documents(supabase, search_embedding, role, config.RAG_TOP_K, search_query)
        accessible_documents = filter_documents_for_role(retrieved, role)
        docs = rerank_documents(search_query, accessible_documents, config.RAG_FINAL_K)

        # No evidence guard
        if not docs:
            logger.warning("No relevant documents found. role=%s question=%s", role, question)
            fallback_answer = "Maaf, informasi tersebut tidak ditemukan dalam dokumen yang tersedia."
            log_unanswered_query(supabase, question, role, "no_documents", 0.0)
            if persist_session:
                save_message(supabase, body.session_id, "assistant", fallback_answer)
            return {
                "answer": fallback_answer,
                "session_id": body.session_id if persist_session else None,
                "provider": None,
                "sources": [],
                "evidence": {"confidence": 0.0, "supported": False},
                "retrieval": {"retrieved_count": len(retrieved), "final_count": 0, "min_similarity": config.RAG_MIN_SIMILARITY},
                "token_optimization": {
                    "enabled": False,
                    "estimated_input_tokens": 0,
                    "context_original_tokens": 0,
                    "context_compressed_tokens": 0,
                    "compression_ratio": 1.0,
                    "sentences_kept": 0,
                    "max_context_tokens": config.MAX_CONTEXT_TOKENS,
                    "max_input_tokens": config.MAX_INPUT_TOKENS,
                    "max_output_tokens": config.MAX_OUTPUT_TOKENS,
                    "provider_usage": None,
                },
            }

        structured = is_structured_question(question)
        if structured:
            context = render_documents_raw(docs)
            compression = {
                "original_tokens": estimate_tokens(context),
                "compressed_tokens": estimate_tokens(context),
                "compression_ratio": 1.0,
                "sentences_kept": 0,
                "compressed": False,
            }
            logger.info("Structured question detected. Context compression disabled.")
        else:
            context_budget = min(
                config.MAX_CONTEXT_TOKENS,
                max(500, config.MAX_INPUT_TOKENS - estimate_tokens(SYSTEM_PROMPT + search_query) - 300),
            )
            if config.COMPRESS_CONTEXT:
                context, compression = compress_context(search_query, docs, context_budget)
            else:
                context = render_documents_raw(docs)
                compression = {
                    "original_tokens": estimate_tokens(context),
                    "compressed_tokens": estimate_tokens(context),
                    "compression_ratio": 1.0,
                    "sentences_kept": 0,
                    "compressed": False,
                }

    logger.info(
        "Chat retrieval role=%s question=%s retrieved=%s final=%s context_tokens=%s",
        role, question, len(retrieved), len(docs), compression["compressed_tokens"],
    )

    # ========= LLM GENERATION =========
    try:
        answer, provider, usage = generate_with_fallback(question, context, history, force_direct=True)
        answer = clean_answer(answer)

        # Retry jika jawaban kosong
        if not answer:
            logger.warning("LLM returned empty answer. Retrying.")
            retry_answer, retry_provider, retry_usage = generate_with_fallback(question, context, history, force_direct=True)
            retry_answer = clean_answer(retry_answer)
            if retry_answer:
                answer, provider, usage = retry_answer, retry_provider, retry_usage

        # Retry jika LLM klaim tidak ada info padahal ada dokumen
        elif docs and answer_claims_no_information(answer):
            logger.warning("LLM claimed no information despite available source. Retrying.")
            retry_answer, retry_provider, retry_usage = generate_with_fallback(question, context, history, force_direct=True)
            retry_answer = clean_answer(retry_answer)
            if retry_answer and not answer_claims_no_information(retry_answer):
                answer, provider, usage = retry_answer, retry_provider, retry_usage

    except RateLimitError as rl_err:
        logger.warning("All providers hit rate limit: %s", rl_err)
        rate_limit_ans = (
            "⚠️ **Batas Kuota AI Sedang Cooldown (Rate Limit)**\n\n"
            "Saat ini kuota gratis Google Gemini sedang dalam jeda singkat (~25 detik) karena aktivitas tanya-jawab yang padat. "
            "Silakan tunggu sekitar 20–30 detik lalu kirimkan kembali pertanyaan Anda.\n\n"
            "💡 *Tips Admin: Anda dapat menambahkan API Key cadangan di menu Pengaturan AI Admin agar sistem dapat langsung beralih kunci tanpa jeda.*"
        )
        if persist_session:
            save_message(supabase, body.session_id, "assistant", rate_limit_ans)
        return {
            "answer": rate_limit_ans,
            "session_id": body.session_id if persist_session else None,
            "provider": "system/cooldown",
            "sources": public_sources(docs) if 'docs' in locals() else [],
            "evidence": {"confidence": 0.0, "supported": False},
            "retrieval": {
                "retrieved_count": len(retrieved) if 'retrieved' in locals() else 0,
                "final_count": len(docs) if 'docs' in locals() else 0,
                "min_similarity": config.RAG_MIN_SIMILARITY,
                "structured_question": is_structured_question(question),
            },
            "token_optimization": {
                "enabled": False,
                "estimated_input_tokens": 0,
                "context_original_tokens": 0,
                "context_compressed_tokens": 0,
                "compression_ratio": 1.0,
                "sentences_kept": 0,
                "max_context_tokens": config.MAX_CONTEXT_TOKENS,
                "max_input_tokens": config.MAX_INPUT_TOKENS,
                "max_output_tokens": config.MAX_OUTPUT_TOKENS,
                "provider_usage": None,
            },
        }
    except Exception as exc:
        logger.exception("All LLM providers failed")
        raise HTTPException(status_code=502, detail=f"All LLM providers failed: {exc}")

    # ========= SAVE & RESPOND =========
    if persist_session:
        save_message(supabase, body.session_id, "assistant", answer)

    prompt_estimate = estimate_tokens(SYSTEM_PROMPT + "\n" + context + "\n" + question)
    evidence = calculate_evidence_confidence(question, docs, answer)
    claims_no_info = answer_claims_no_information(answer)

    # Sumber dokumen HANYA disertakan jika jawaban didukung bukti kuat dan BUKAN klaim informasi tidak ditemukan
    if claims_no_info or not evidence.get("supported", False):
        final_sources = []
        if claims_no_info:
            evidence = {"score": 0.0, "level": "low", "supported": False}
    else:
        final_sources = public_sources(docs)

    result_payload = {
        "answer": answer,
        "session_id": body.session_id if persist_session else None,
        "provider": provider,
        "sources": final_sources,
        "evidence": evidence,
        "retrieval": {
            "retrieved_count": len(retrieved),
            "final_count": len(docs),
            "min_similarity": config.RAG_MIN_SIMILARITY,
            "structured_question": is_structured_question(question),
        },
        "token_optimization": {
            "enabled": config.COMPRESS_CONTEXT and not is_structured_question(question),
            "estimated_input_tokens": prompt_estimate,
            "context_original_tokens": compression["original_tokens"],
            "context_compressed_tokens": compression["compressed_tokens"],
            "compression_ratio": compression["compression_ratio"],
            "sentences_kept": compression["sentences_kept"],
            "max_context_tokens": config.MAX_CONTEXT_TOKENS,
            "max_input_tokens": config.MAX_INPUT_TOKENS,
            "max_output_tokens": config.MAX_OUTPUT_TOKENS,
            "provider_usage": usage,
        },
    }

    if cache_key and answer and not answer_claims_no_information(answer):
        response_cache.set(cache_key, result_payload)

    if docs and answer_claims_no_information(answer):
        log_unanswered_query(supabase, question, role, "claims_no_info", evidence.get("score", 0.0))

    return result_payload


@router.post("/chat")
@limiter.limit("30/minute")
async def chat(request: Request, body: QueryRequest, authorization: Optional[str] = Header(default=None)):
    """Endpoint chat utama dengan RAG pipeline lengkap."""
    supabase = _get_supabase()
    return await asyncio.to_thread(_chat_sync, supabase, body, authorization)


@router.post("/chat/stream")
@limiter.limit("30/minute")
async def chat_stream(request: Request, body: QueryRequest, authorization: Optional[str] = Header(default=None)):
    """Endpoint chat streaming dengan Server-Sent Events (SSE) untuk efek mengetik real-time."""
    supabase = _get_supabase()
    role = chat_role(supabase, authorization)
    question = body.question.strip()

    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    async def sse_event_stream():
        # 1. Guardrail check
        is_safe, violation, clean_q = check_guardrails(question)
        if not is_safe:
            yield f"event: token\ndata: {json.dumps({'text': GUARDRAIL_DEFLECTION_ANSWER})}\n\n"
            yield f"event: metadata\ndata: {json.dumps({'provider': 'system/guardrail', 'sources': [], 'evidence': {'confidence': 1.0, 'supported': True}})}\n\n"
            yield f"event: done\ndata: {json.dumps({'session_id': body.session_id})}\n\n"
            return

        sanitized_q = clean_q
        persist_session = role != "anonymous"
        if persist_session:
            await asyncio.to_thread(ensure_session, supabase, body.session_id)

        history = await asyncio.to_thread(get_session_history, supabase, body.session_id) if persist_session else []

        # 2. Greeting shortcut
        if _is_greeting(sanitized_q):
            greeting_ans = (
                "Halo! Saya Aksaraku AI, asisten virtual SMP Negeri 2 Cibungbulang. "
                "Ada yang bisa saya bantu terkait informasi sekolah, profil, visi misi, fasilitas, atau data guru?"
            )
            if persist_session:
                await asyncio.to_thread(save_message, supabase, body.session_id, "user", sanitized_q)
                await asyncio.to_thread(save_message, supabase, body.session_id, "assistant", greeting_ans)
            yield f"event: token\ndata: {json.dumps({'text': greeting_ans})}\n\n"
            yield f"event: metadata\ndata: {json.dumps({'provider': 'assistant', 'sources': [], 'evidence': {'confidence': 1.0, 'supported': True}})}\n\n"
            yield f"event: done\ndata: {json.dumps({'session_id': body.session_id})}\n\n"
            return

        search_query = build_search_query(sanitized_q, history)
        if persist_session:
            await asyncio.to_thread(save_message, supabase, body.session_id, "user", sanitized_q)

        # 3. Context retrieval
        def _fetch_rag():
            try:
                q_emb = embed_query(search_query)
            except Exception as exc:
                return None, [], str(exc)
            retrieved = get_similar_documents(supabase, q_emb, role, config.RAG_TOP_K, search_query)
            accessible = filter_documents_for_role(retrieved, role)
            docs = rerank_documents(search_query, accessible, config.RAG_FINAL_K)
            if not docs:
                return "", [], None
            if is_structured_question(sanitized_q):
                ctx = render_documents_raw(docs)
            else:
                context_budget = min(config.MAX_CONTEXT_TOKENS, max(500, config.MAX_INPUT_TOKENS - estimate_tokens(SYSTEM_PROMPT + search_query) - 300))
                ctx, _ = compress_context(search_query, docs, context_budget) if config.COMPRESS_CONTEXT else (render_documents_raw(docs), None)
            return ctx, docs, None

        context, docs, err = await asyncio.to_thread(_fetch_rag)
        if err:
            err_msg = f"⚠️ Gagal memproses embedding dokumen: {err}"
            yield f"event: token\ndata: {json.dumps({'text': err_msg})}\n\n"
            yield f"event: done\ndata: {json.dumps({'session_id': body.session_id})}\n\n"
            return

        if not docs:
            fallback_ans = "Maaf, informasi tersebut tidak ditemukan dalam dokumen yang tersedia."
            await asyncio.to_thread(log_unanswered_query, supabase, sanitized_q, role, "no_documents", 0.0)
            if persist_session:
                await asyncio.to_thread(save_message, supabase, body.session_id, "assistant", fallback_ans)
            yield f"event: token\ndata: {json.dumps({'text': fallback_ans})}\n\n"
            yield f"event: metadata\ndata: {json.dumps({'provider': None, 'sources': [], 'evidence': {'confidence': 0.0, 'supported': False}})}\n\n"
            yield f"event: done\ndata: {json.dumps({'session_id': body.session_id})}\n\n"
            return

        # 4. Stream tokens
        full_text = ""
        provider_used = "gemini"
        try:
            queue = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def _stream_producer():
                try:
                    for item in generate_stream_with_fallback(sanitized_q, context, history, force_direct=True):
                        loop.call_soon_threadsafe(queue.put_nowait, item)
                except Exception as exc:
                    loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "error": str(exc)})
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)

            threading.Thread(target=_stream_producer, daemon=True).start()

            while True:
                item = await queue.get()
                if item is None:
                    break
                if item.get("type") == "token":
                    chunk_text = item.get("text", "")
                    full_text += chunk_text
                    yield f"event: token\ndata: {json.dumps({'text': chunk_text})}\n\n"
                elif item.get("type") == "metadata":
                    provider_used = item.get("provider", "gemini")
                elif item.get("type") == "error":
                    err_text = item.get("error", "Stream error")
                    yield f"event: token\ndata: {json.dumps({'text': f'\n\n⚠️ Error: {err_text}'})}\n\n"
                    break

        except Exception as exc:
            yield f"event: token\ndata: {json.dumps({'text': f'\n\n⚠️ Gagal: {exc}'})}\n\n"

        # 5. Clean & Save
        cleaned_ans = clean_answer(full_text)
        if docs and answer_claims_no_information(cleaned_ans):
            await asyncio.to_thread(log_unanswered_query, supabase, sanitized_q, role, "claims_no_info", 0.0)

        if persist_session and cleaned_ans:
            await asyncio.to_thread(save_message, supabase, body.session_id, "assistant", cleaned_ans)

        evidence = calculate_evidence_confidence(sanitized_q, docs, cleaned_ans)
        claims_no_info = answer_claims_no_information(cleaned_ans)
        if claims_no_info or not evidence.get("supported", False):
            final_sources = []
            if claims_no_info:
                evidence = {"score": 0.0, "level": "low", "supported": False}
        else:
            final_sources = public_sources(docs)

        yield f"event: metadata\ndata: {json.dumps({'provider': provider_used, 'sources': final_sources, 'evidence': evidence})}\n\n"
        yield f"event: done\ndata: {json.dumps({'session_id': body.session_id})}\n\n"

    return StreamingResponse(sse_event_stream(), media_type="text/event-stream")
