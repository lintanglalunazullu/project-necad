# services/api/ai/guardrails.py
# Guardrails performa tinggi (<1ms) untuk sanitasi input dan proteksi prompt injection.
# Mencegah eksploitasi, kebocoran system prompt, dan menghemat kuota LLM.
import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger("aksaraku.guardrails")

# Pesan penolakan ramah standar untuk pelanggaran guardrails
GUARDRAIL_DEFLECTION_ANSWER = (
    "Halo! Saya adalah **Aksaraku AI**, asisten virtual resmi SMP Negeri 2 Cibungbulang. "
    "Saya diprogram khusus untuk membantu memberikan informasi seputar kegiatan sekolah, "
    "penerimaan peserta didik baru (PPDB), kurikulum akademik, fasilitas, profil sekolah, "
    "dan tata tertib siswa di SMPN 2 Cibungbulang.\n\n"
    "Mohon ajukan pertanyaan yang berkaitan dengan informasi sekolah. Ada hal seputar SMPN 2 Cibungbulang yang ingin Anda tanyakan?"
)

# Pola Delimiter Injeksi yang harus dibersihkan secara otomatis
DELIMITER_PATTERNS = [
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"\[INST\]",
    r"\[/INST\]",
    r"```system\b",
    r"```prompt\b",
    r"<system>",
    r"</system>",
    r"<<<SYSTEM>>>",
    r"<<<PROMPT>>>",
]

# Pola Regex Injeksi Prompt / Jailbreak
JAILBREAK_PATTERNS = [
    # English jailbreak patterns
    r"\bignore\s+(all\s+|any\s+|previous\s+|prior\s+|above\s+)*(instructions|directions|rules|commands|guidelines)\b",
    r"\b(disregard|forget)\s+(all\s+|any\s+|previous\s+|prior\s+)*(instructions|prompts|rules)\b",
    r"\byou\s+are\s+now\s+(a|an)?\s*(dan|jailbreak|unrestricted|god\s*mode|developer\s*mode|evil|hacker)\b",
    r"\bact\s+as\s+(a|an)?\s*(dan|unrestricted|evil|jailbroken|unfiltered)\b",
    r"\b(system\s*prompt|initial\s*prompt|internal\s*instructions)\s*(leak|reveal|show|print|output|display)\b",
    r"\b(show|print|reveal|give\s*me|repeat)\s+(your|the)?\s*(system\s*prompt|initial\s*prompt|instructions|secret)\b",
    r"\bbypass\s+(all\s+)?(safety|filters?|guardrails?|security|restrictions?)\b",

    # Indonesian jailbreak patterns
    r"\babaikan\s+(semua\s+|seluruh\s+|sebelumnya\s+|di\s*atas\s+)*(instruksi|perintah|aturan|petunjuk|pedoman)\b",
    r"\blupakan\s+(semua\s+|seluruh\s+|instruksi|perintah|aturan|kamu\s+adalah)\b",
    r"\bkamu\s+sekarang\s+adalah\s+(dan|hacker|bot\s*jahat|tanpa\s*aturan|tanpa\s*batas|bebas)\b",
    r"\bberperanlah\s+sebagai\s+(dan|hacker|ai\s*bebas|tanpa\s*filter)\b",
    r"\b(tampilkan|bocorkan|beritahu|cetak|tuliskan)\s+(system\s*prompt|prompt\s*sistem|instruksi\s*awal|perintah\s*rahasia)\b",
    r"\b(apa|sebutkan)\s+(isi\s+)?(system\s*prompt|prompt\s*sistem|instruksi\s*asli)\s*(kamu)?\b",
    r"\bbypass\s+(keamanan|filter|aturan|sistem|pembatasan)\b",

    # Malicious technical exploitation keywords
    r"\b(buatkan|bikin|tuliskan)\s+(script|kode|program)?\s*(malware|virus|trojan|ransomware|keylogger|ddos|exploit)\b",
    r"\b(hack|retas|bobol)\s+(wifi|akun|password|website|server|database)\b",
]

# Compile patterns for high-performance sub-millisecond execution
_COMPILED_DELIMITERS = [re.compile(p, re.IGNORECASE) for p in DELIMITER_PATTERNS]
_COMPILED_JAILBREAKS = [re.compile(p, re.IGNORECASE) for p in JAILBREAK_PATTERNS]


def sanitize_input_text(raw_text: str, max_length: int = 1000) -> str:
    """
    Sanitasi string input teks:
    1. Truncate ke max_length (mencegah overflow buffer dan flood token).
    2. Bersihkan karakter kontrol berbahaya dan tag delimiter prompt injection.
    3. Normalisasi spasi berlebih.
    """
    if not raw_text:
        return ""

    # Truncate
    text = raw_text.strip()[:max_length]

    # Hapus delimiter prompt engineering terlarang
    for pattern in _COMPILED_DELIMITERS:
        text = pattern.sub(" ", text)

    # Bersihkan multiple whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def check_guardrails(question: str) -> Tuple[bool, Optional[str], str]:
    """
    Evaluasi guardrails dengan kinerja tinggi (<1ms, murni CPU in-memory).
    
    Returns:
        (is_allowed: bool, violation_type: Optional[str], sanitized_question: str)
    """
    sanitized = sanitize_input_text(question)
    if not sanitized:
        return False, "empty_input", ""

    # Cek batas minimal karakter bermakna
    if len(sanitized) < 2:
        return False, "too_short", sanitized

    # Deteksi pola injeksi & jailbreak
    lower_text = sanitized.lower()
    for pattern in _COMPILED_JAILBREAKS:
        if pattern.search(lower_text):
            logger.warning("Guardrail triggered: prompt injection detected in query: '%s'", sanitized[:80])
            return False, "jailbreak_detected", sanitized

    return True, None, sanitized
