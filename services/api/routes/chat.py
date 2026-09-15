# services/api/routes/chat.py — Endpoint chat RAG dan query dokumen
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from supabase import Client

import config
from auth import authenticated_role, chat_role, filter_documents_for_role
from models import QueryRequest
from rag.embedding import embed_text
from rag.generation import (
    SYSTEM_PROMPT,
    answer_claims_no_information,
    calculate_evidence_confidence,
    clean_answer,
    compress_context,
    generate_with_fallback,
    public_sources,
    render_documents_raw,
)
from rag.retrieval import get_similar_documents, is_structured_question, rerank_documents
from rag.session import build_search_query, ensure_session, get_session_history, save_message
from utils.helpers import estimate_tokens

logger = logging.getLogger("aksaraku.routes.chat")

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


def _is_document_inventory_question(question: str) -> bool:
    import re
    normalized = re.sub(r"\s+", " ", question.lower()).strip()
    return any(marker in normalized for marker in DOCUMENT_INVENTORY_MARKERS)


@router.post("/query-docs")
@limiter.limit("60/minute")
async def query_docs(request: Request, body: QueryRequest, authorization: Optional[str] = Header(default=None)):
    """Cari dokumen relevan berdasarkan pertanyaan (tanpa generate jawaban LLM)."""
    supabase = _get_supabase()
    role = authenticated_role(supabase, authorization)
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "question is required")

    question_embedding = embed_text(question)
    retrieved = get_similar_documents(supabase, question_embedding, role, config.RAG_TOP_K, question)
    docs = rerank_documents(question, filter_documents_for_role(retrieved, role), config.RAG_FINAL_K)
    return {"data": public_sources(docs)}


@router.post("/chat")
@limiter.limit("30/minute")
async def chat(request: Request, body: QueryRequest, authorization: Optional[str] = Header(default=None)):
    """Endpoint chat utama dengan RAG pipeline lengkap."""
    supabase = _get_supabase()
    role = chat_role(supabase, authorization)

    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    # ========= SESSION =========
    persist_session = role != "anonymous"
    if persist_session:
        ensure_session(supabase, body.session_id)

    history = get_session_history(supabase, body.session_id) if persist_session else []

    # ========= QUERY =========
    search_query = build_search_query(question, history)
    if persist_session:
        save_message(supabase, body.session_id, "user", question)

    # ========= DOCUMENT INVENTORY SHORTCUT =========
    if _is_document_inventory_question(question):
        from rag.retrieval import document_summary, fetch_document_rows
        inventory = filter_documents_for_role(document_summary(fetch_document_rows(supabase)), role)
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
        search_embedding = embed_text(search_query)
        retrieved = get_similar_documents(supabase, search_embedding, role, config.RAG_TOP_K, search_query)
        accessible_documents = filter_documents_for_role(retrieved, role)
        docs = rerank_documents(search_query, accessible_documents, config.RAG_FINAL_K)

        # No evidence guard
        if not docs:
            logger.warning("No relevant documents found. role=%s question=%s", role, question)
            fallback_answer = "Maaf, informasi tersebut tidak ditemukan dalam dokumen yang tersedia."
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

    except Exception as exc:
        logger.exception("All LLM providers failed")
        raise HTTPException(status_code=502, detail=f"All LLM providers failed: {exc}")

    # ========= SAVE & RESPOND =========
    if persist_session:
        save_message(supabase, body.session_id, "assistant", answer)

    prompt_estimate = estimate_tokens(SYSTEM_PROMPT + "\n" + context + "\n" + question)
    evidence = calculate_evidence_confidence(question, docs, answer)

    return {
        "answer": answer,
        "session_id": body.session_id if persist_session else None,
        "provider": provider,
        "sources": public_sources(docs),
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
