# services/api/utils/helpers.py — Fungsi utilitas umum
import re
from typing import Any


def estimate_tokens(text: str) -> int:
    """Estimasi jumlah token dari teks (pendekatan sederhana: 4 karakter per token)."""
    return max(1, (len(text) + 3) // 4) if text else 0


def words(text: str) -> set[str]:
    """Ekstrak set kata unik dari teks, case-insensitive."""
    return set(re.findall(r"[a-zA-Z0-9À-ÿ]+", text.lower()))


def sentences(text: str) -> list[str]:
    """Pecah teks menjadi segmen kalimat dengan batas panjang maksimal."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", text) if p.strip()]
    segments: list[str] = []
    max_segment_chars = 900
    for part in parts:
        if len(part) <= max_segment_chars:
            segments.append(part)
            continue
        ws = part.split()
        current: list[str] = []
        current_length = 0
        for word in ws:
            next_length = current_length + len(word) + (1 if current else 0)
            if current and next_length > max_segment_chars:
                segments.append(" ".join(current))
                current = []
                current_length = 0
            current.append(word)
            current_length += len(word) + (1 if len(current) > 1 else 0)
        if current:
            segments.append(" ".join(current))
    return segments


def extract_response_parts(response: Any) -> dict:
    """Ekstrak field 'error' dan 'data' dari response Supabase."""
    if isinstance(response, dict):
        return {"error": response.get("error"), "data": response.get("data")}
    error = getattr(response, "error", None)
    data = getattr(response, "data", None)
    if data is None:
        data = getattr(response, "body", None)
    if data is None:
        data = getattr(response, "output", None)
    return {"error": error, "data": data}
