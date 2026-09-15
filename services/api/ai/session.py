# services/api/ai/session.py — Manajemen sesi dan riwayat chat
import logging
from typing import Optional

from supabase import Client

import config
from utils.helpers import extract_response_parts

logger = logging.getLogger("aksaraku.session")


def ensure_session(supabase: Client, session_id: Optional[str]) -> None:
    """Pastikan session dengan ID tersebut ada di database. Buat baru jika belum ada."""
    if not session_id:
        return
    try:
        found = (
            supabase.table(config.SESSION_TABLE)
            .select("id")
            .eq("id", session_id)
            .limit(1)
            .execute()
        )
        if not (extract_response_parts(found)["data"] or []):
            supabase.table(config.SESSION_TABLE).insert({"id": session_id}).execute()
    except Exception as exc:
        logger.warning("Session ensure failed: %s", exc)


def get_session_history(supabase: Client, session_id: Optional[str]) -> list[dict]:
    """Ambil riwayat pesan dari session yang diberikan."""
    if not session_id:
        return []
    try:
        response = (
            supabase.table(config.MESSAGE_TABLE)
            .select("role,content")
            .eq("session_id", session_id)
            .order("created_at", desc=True)
            .limit(config.SESSION_HISTORY_LIMIT)
            .execute()
        )
        rows = extract_response_parts(response)["data"] or []
        rows.reverse()
        return [
            {"role": r["role"], "content": r["content"]}
            for r in rows
            if r.get("role") in {"user", "assistant"} and r.get("content")
        ]
    except Exception as exc:
        logger.warning("History load failed: %s", exc)
        return []


def save_message(supabase: Client, session_id: Optional[str], role: str, content: str) -> None:
    """Simpan pesan ke tabel chat_messages."""
    if not session_id:
        return
    try:
        supabase.table(config.MESSAGE_TABLE).insert(
            {"session_id": session_id, "role": role, "content": content}
        ).execute()
    except Exception as exc:
        logger.warning("Message save failed: %s", exc)


def build_search_query(question: str, history: list[dict]) -> str:
    """
    Perkaya query pencarian dengan konteks dari riwayat chat sebelumnya
    jika ada kata kunci yang mengacu ke pesan sebelumnya.
    """
    if not history:
        return question
    markers = (
        "yang tadi", "yang sebelumnya", "yang itu", "bagaimana dengan",
        "kalau yang", "kalau untuk", "berapa yang", "dan yang",
        "terus", "lalu", "sedangkan", "dibandingkan", "tahun sebelumnya",
    )
    if not any(m in question.lower() for m in markers):
        return question
    previous = [x["content"] for x in history if x["role"] == "user"][-2:]
    return " ".join(previous + [question]) if previous else question
