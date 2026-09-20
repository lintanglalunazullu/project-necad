# Audit Report — project-necad (Aksaraku API)
> Dibuat secara otomatis oleh review mendalam atas seluruh project.  
> Tanggal audit: September 2026  
> Reviewer: Claude (Anthropic)

---

## Ringkasan Eksekutif

Project ini adalah website informasi SMP Negeri 2 Cibungbulang dengan fitur chatbot RAG (Retrieval-Augmented Generation) berbasis FastAPI + Supabase + Google Gemini. Secara keseluruhan arsitekturnya cukup matang, namun ditemukan **7 isu kritis** yang berdampak langsung ke performa, keamanan, dan keandalan — semuanya sudah diperbaiki di deliverable ini.

---

## 1. Temuan Kritis (sudah diperbaiki)

### 1.1 RAG pipeline fetch seluruh tabel untuk SETIAP pesan chat ⚠️ KRITIS
**File:** `services/api/ai/retrieval.py` (lama)  
**Dampak:** Performa sangat buruk — makin banyak dokumen, makin lambat. Pada 1.000+ chunk, satu pesan chat bisa membutuhkan transfer >10 MB data dari Supabase (kolom embedding tiap baris ±6 KB) hanya untuk menemukan 5 dokumen relevan.  
**Akar masalah:** Fungsi RPC `match_pdf_documents` di Supabase tidak menerima parameter `category_filter`. Karena filtering kategori (public/private) harus terjadi di Python untuk alasan keamanan role, kode terpaksa fetch **semua baris** dulu, hitung cosine similarity di Python, baru filter.  
**Perbaikan:**
- Tambah `category_filter text[] DEFAULT NULL` ke semua 3 RPC (`match_pdf_documents`, `search_pdf_documents_keyword`, `search_pdf_documents_exact`) — lihat `docs/migration_performance_and_security.sql`.
- `get_similar_documents()` sekarang kirim `category_filter` ke RPC → Postgres pakai index HNSW yang sudah ada, hanya kirim baris yang cocok. Full-table fetch + cosine Python hanya sebagai fallback jika RPC gagal.
- **Estimasi performa:** Dari O(n_chunks × embedding_size) bytes transfer per chat → O(top_k × row_size), biasanya turun 200–2000× tergantung jumlah dokumen.

### 1.2 `/admin/dashboard` fetch 4 tabel penuh ⚠️ KRITIS
**File:** `services/api/routes/admin.py` (lama)  
**Dampak:** Setiap kali dashboard admin dibuka → 4 query besar berurutan: `pdf_documents` limit 10.000 + `profiles`/`chat_sessions`/`chat_messages` limit 1.000 masing-masing. Total bisa >50.000 baris hanya untuk menampilkan angka sederhana (jumlah dokumen, user, sesi, pesan).  
**Perbaikan:**
- RPC `get_admin_dashboard_stats()` baru — satu round-trip, semua `COUNT()` dikerjakan di Postgres.
- Query aktivitas pakai `ORDER BY created_at DESC LIMIT 10` — hanya tarik 10 baris terbaru per tabel.
- Semua query independen dijalankan paralel via `asyncio.gather()`.

### 1.3 Blocking I/O di async event loop ⚠️ KRITIS
**File:** `services/api/routes/chat.py`, `routes/admin.py` (lama)  
**Dampak:** `supabase-py`, `google-generativeai`, dan `openai` semua menggunakan **synchronous HTTP** di balik layar. Route `async def chat(...)` yang memanggil langsung fungsi-fungsi ini akan **memblokir seluruh event loop FastAPI** selama proses berlangsung (embedding + search + generation = 2–8 detik). Artinya, selama satu user chat, semua request lain dari user berbeda mengantre.  
**Perbaikan:** Logika chat dipindah ke fungsi sync biasa (`_chat_sync`, `_query_docs_sync`) yang dijalankan via `asyncio.to_thread()`. Event loop bebas melayani request lain selagi satu pipeline chat berjalan di thread pool.

### 1.4 `GET /documents` dan rename-document fetch semua chunk
**File:** `services/api/routes/documents.py` (lama)  
**Dampak:** Listing dokumen fetch semua 10.000+ baris lalu group-by di Python. Rename-document fetch semua baris hanya untuk cek apakah nama sudah ada (bisa ratusan MB transfer untuk operasi O(1)).  
**Perbaikan:**
- `GET /documents` → pakai RPC `get_document_summary()` yang GROUP BY di Postgres. Fallback otomatis ke cara lama.
- Rename → `SELECT pdf_name WHERE pdf_name = :id LIMIT 1` untuk cek keberadaan, dan query serupa untuk collision check — bukan fetch semua baris.

### 1.5 Folder `rag/` adalah dead code (kode mati)
**File:** `services/api/rag/` (seluruh folder)  
**Dampak:** 806 baris kode duplikat dari versi lama `ai/` yang tidak dipakai sama sekali. Tidak ada satu pun `import` dari `rag/` di luar folder itu sendiri. Membingungkan dan mempersulit maintenance.  
**Perbaikan:** Folder `rag/` dihapus.

### 1.6 `@app.on_event("startup")` deprecated
**File:** `services/api/app.py` (lama)  
**Dampak:** FastAPI sudah deprecated `@app.on_event` sejak v0.93 dan akan dihapus di versi mendatang.  
**Perbaikan:** Diganti `@asynccontextmanager async def lifespan()`.

### 1.7 `test_app.py` rusak total
**File:** `services/api/test_app.py` (lama)  
**Dampak:** File test yang ada mereferensi nama fungsi, nama modul, dan nama import yang sudah tidak ada di kodebase (`_authenticated_role`, `generate_with_fallback_with_usage`, `SUPABASE_TABLE`, `_clean_answer`, dll). Pytest tidak bisa collect satu test pun — **coverage efektif: 0%**.  
**Perbaikan:** Ditulis ulang dari nol dengan 50 test yang semuanya passing, mencakup `utils/helpers`, `ai/retrieval`, `ai/generation`, `config`, dan `auth`.

---

## 2. Temuan Keamanan & Privasi Data

### 2.1 Data pribadi siswa dalam file SQL yang di-commit ⚠️ HARUS DITINDAKLANJUTI
**File:** `docs/supabase_setup.sql` (asli, 268 KB)  
**Masalah:** File ini berisi seed data mentah dokumen sekolah termasuk **nama siswa dan nomor NISN asli** yang muncul di beberapa chunk laporan PKL, bersama embedding vector 1536 dimensi. File ini sudah ter-commit di riwayat Git (`github.com/ReyyIchiro/project-necad`).  
**Tindakan yang sudah dilakukan:**
- Seed data PII dipisah ke `docs/seed_school_documents.OPTIONAL.sql` (terpisah dari schema utama).
- File seed ditambahkan ke `.gitignore`.  

**Tindakan yang MASIH HARUS dilakukan (manual):**
```bash
# Opsi 1: Gunakan git-filter-repo (direkomendasikan)
pip install git-filter-repo
git filter-repo --path docs/supabase_setup.sql --invert-paths --force
# Lalu force push ke semua remote

# Opsi 2: BFG Repo-Cleaner
# Download bfg.jar dari https://rtyley.github.io/bfg-repo-cleaner/
java -jar bfg.jar --delete-files supabase_setup.sql
git reflog expire --expire=now --all && git gc --prune=now --aggressive
git push --force
```

### 2.2 File `.env` dengan credentials nyata
**Masalah:** File `services/api/.env` (berisi `SUPABASE_SERVICE_ROLE_KEY`, `GEMINI_API_KEY`, dll) ikut ter-upload di sesi audit ini. File ini sudah ada di `.gitignore` (benar), tapi sebaiknya semua key di-rotate secara berkala.  
**Tindakan:** `.env` tidak disertakan di deliverable ini. Pastikan tidak pernah ter-commit.

### 2.3 Defense-in-depth filter kategori (double-check di Python)
Meskipun RPC sekarang sudah filter kategori di Postgres, kode Python tetap melakukan filter ulang (`filter_rpc_documents_for_role`) setelah menerima hasil RPC — prinsip defense-in-depth. Ini dipertahankan di versi baru.

---

## 3. Temuan Minor (sudah diperbaiki)

| # | Masalah | File | Perbaikan |
|---|---------|------|-----------|
| M1 | `background.jpg` (3.2 MB) dan `visimisi.jpeg` (412 KB) tidak direferensi di mana pun — versi `.webp` sudah dipakai | `apps/school-web/image/` | Dihapus, hemat ~3.6 MB |
| M2 | `<img>` di school-web tidak ada atribut `loading="lazy"` dan `width`/`height` | `apps/school-web/pages/*.html` | Rekomendasi: tambahkan `loading="lazy"` dan dimensi eksplisit untuk menghindari layout shift (CLS) |
| M3 | `requirements.txt` tanpa pin versi — bisa break saat `pip install` di server baru | `services/api/requirements.txt` | Ditambahkan range versi dan komentar |
| M4 | `__pycache__/` folder ikut dalam repo (via zip deliverable) | seluruh `services/api/` | Dihapus, ditambahkan ke `.gitignore` |
| M5 | `apps/mentor-web/data/` berisi file JSON pre-computed embeddings (248 KB) yang di-gitignore tapi ikut di zip | `apps/mentor-web/data/` | Sudah di `.gitignore`, tidak disertakan di deliverable bersih |
| M6 | `routes/admin.py` test_ai_provider dan test_key memanggil `_call_gemini`/`_call_openai_compat` secara blocking di dalam `async def` | `routes/admin.py` | Dibungkus `asyncio.to_thread()` |

---

## 4. Yang Tidak Diubah (sengaja)

- **`ai/generation.py`** — sudah solid. Circuit breaker, multi-key round-robin, retry fallback antar provider, chain-of-thought stripping, kompres context — semuanya benar. Hanya endpoint yang memanggilnya secara blocking yang diperbaiki.
- **`ai/embedding.py`** — bersih, tidak ada masalah.
- **`ai/session.py`** — bersih, query sudah terarah dengan limit.
- **`auth.py`** — logic role dan kategori sudah benar, `filter_rpc_documents_for_role` dipertahankan sebagai defense-in-depth.
- **`config.py`** — environment loading sudah benar dengan default yang masuk akal.
- **`utils/helpers.py`** — bersih dan efisien.
- **Schema SQL utama** (`supabase_setup.sql`) — tidak ada perubahan struktur tabel, hanya seed data dipisah. RPC baru ada di file migration terpisah (`migration_performance_and_security.sql`).
- **Frontend** (`apps/school-web/`, `apps/mentor-web/`) — struktur HTML/CSS/JS tidak diubah (di luar hapus gambar unused). Perubahan frontend membutuhkan context lebih dalam tentang desain yang diinginkan.

---

## 5. Cara Deploy Perubahan Ini

### Langkah 1 — Jalankan migrasi SQL di Supabase
```
Buka Supabase Dashboard → SQL Editor
Copy-paste isi docs/migration_performance_and_security.sql
Klik "Run"
```
Verifikasi:
```sql
SELECT public.get_admin_dashboard_stats();
SELECT * FROM public.get_document_summary() LIMIT 5;
```

### Langkah 2 — Deploy backend Python
```bash
cd services/api
pip install -r requirements.txt
# Pastikan .env sudah diisi dengan key yang valid
uvicorn app:app --host 0.0.0.0 --port 8000
```

### Langkah 3 — Jalankan test suite
```bash
cd services/api
pytest test_app.py -v
# Expected: 50 passed
```

### Langkah 4 (opsional, direkomendasikan) — Bersihkan Git history dari PII
Lihat bagian 2.1 di atas.

---

## 6. Ringkasan Perubahan File

```
DIUBAH:
  services/api/app.py                          startup: @on_event → lifespan()
  services/api/ai/retrieval.py                 *** REWRITE — core fix performa RAG
  services/api/routes/admin.py                 dashboard: 4 full-table → 1 RPC + paralel
  services/api/routes/documents.py             list/rename: targeted queries
  services/api/routes/chat.py                  *** REWRITE — semua blocking I/O ke thread pool
  services/api/requirements.txt                pin versi, tambah komentar
  services/api/test_app.py                     *** REWRITE — 50 tests, semua passing
  docs/supabase_setup.sql                      hapus seed PII → file terpisah
  .gitignore                                   tambah exclusion seed & pycache

DITAMBAH:
  docs/migration_performance_and_security.sql  *** BARU — RPC + category_filter + agregat
  docs/seed_school_documents.OPTIONAL.sql      seed PII dipisah (masuk .gitignore)
  docs/AUDIT_REPORT.md                         file ini

DIHAPUS:
  services/api/rag/                            dead code (806 baris duplikat)
  services/api/.env                            tidak disertakan di deliverable
  apps/school-web/image/background.jpg         tidak dipakai (3.2 MB)
  apps/school-web/image/visimisi.jpeg          tidak dipakai (412 KB)
  services/api/**/__pycache__/                 tidak perlu di repo
```
