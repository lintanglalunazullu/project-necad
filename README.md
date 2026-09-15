# Project Necad — Monorepo

Monorepo untuk sistem website dan AI Mentor **SMP Negeri 2 Cibungbulang**.

## Struktur Project

```
project-necad/
├── apps/
│   ├── school-web/     # Website profil sekolah (static HTML/CSS/JS)
│   └── mentor-web/     # Portal AI Mentor Aksaraku (Dashboard user/guru/admin)
├── services/
│   └── api/            # Backend FastAPI — RAG Engine & AI Chat
├── docs/
│   ├── ARCHITECTURE.md # Diagram & penjelasan arsitektur sistem
│   └── DEPLOYMENT.md   # Panduan deployment lengkap
└── .github/
    └── workflows/
        └── supabase-keepalive.yml
```

## Komponen Sistem

### `apps/school-web` — Website Profil Sekolah
Website informasi statis untuk SMP Negeri 2 Cibungbulang.

**Halaman:**
- `/` — Beranda
- `/pages/akademik.html` — Info Akademik
- `/pages/informasi.html` — Berita & Informasi
- `/pages/kesiswaan.html` — Kesiswaan
- `/pages/kontak.html` — Kontak
- `/pages/ppdb.html` — PPDB
- `/pages/profile.html` — Profil Sekolah

**Deploy:** Vercel / Cloudflare Pages (static hosting gratis)

---

### `apps/mentor-web` — Portal AI Mentor (Aksaraku)
Web application dengan fitur AI chat berbasis RAG, manajemen dokumen, dan multi-role dashboard.

**Role & Akses:**
| Role | Login | Area |
|---|---|---|
| User / Siswa | `/login.html` (Google OAuth) | `/index.html` |
| Guru | `/teacher/login.html` | `/teacher/chat.html` |
| Admin | `/admin/login.html` | `/admin/index.html` |

**Fitur:**
- Chat AI berbasis RAG dengan session history
- Dashboard Admin: statistik, manajemen dokumen, manajemen user
- Upload & embed dokumen PDF ke Supabase Vector Store
- Multi-role authentication via Supabase Auth

**Konfigurasi:** `js/config.js`
```js
window.AKSARAKU_CONFIG = {
  API_BASE_URL: 'http://localhost:3000',  // Ubah ke URL production API
  SUPABASE_URL: '...',
  SUPABASE_ANON_KEY: '...',
}
```

**Deploy:** Vercel / Cloudflare Pages (static hosting)

---

### `services/api` — Backend FastAPI (Aksaraku API)
Backend Python dengan FastAPI untuk RAG engine, AI chat, dan manajemen data.

**Teknologi:**
- **FastAPI** — REST API framework
- **SentenceTransformers** — Embedding model lokal
- **Supabase** — Vector database & auth management
- **Groq + OpenRouter** — LLM providers (dengan fallback otomatis)

**Endpoints:**
| Method | Path | Deskripsi |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/admin/dashboard` | Statistik dashboard (admin only) |
| `DELETE` | `/admin/users/{id}` | Hapus user (admin only) |
| `GET` | `/documents` | Daftar semua dokumen |
| `PUT` | `/documents/{id}` | Rename/update kategori dokumen |
| `DELETE` | `/documents/{id}` | Hapus dokumen |
| `POST` | `/embed-upsert` | Upload chunk teks + generate embedding |
| `POST` | `/embed-upsert-raw` | Upload chunk dengan embedding precomputed |
| `POST` | `/query-docs` | Query dokumen via similarity search |
| `POST` | `/chat` | Chat AI dengan RAG + session history |

**Deploy:** Railway / Fly.io / VPS dengan Docker

---

## Quick Start — Development

### 1. Setup Backend API

```bash
cd services/api

# Buat virtual environment
python -m venv .venv
source .venv/bin/activate          # Linux/Mac
# .venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt

# Setup environment
cp .env.example .env
# Edit .env dengan nilai yang sesuai

# Jalankan server
uvicorn app:app --host 0.0.0.0 --port 3000 --reload
```

API akan berjalan di: `http://localhost:3000`

### 2. Jalankan Frontend (school-web)

Buka langsung di browser:
```bash
# Opsi 1: File langsung
open apps/school-web/index.html

# Opsi 2: Local server (direkomendasikan)
cd apps/school-web
python -m http.server 8080
# Buka: http://localhost:8080
```

### 3. Jalankan Frontend (mentor-web)

```bash
# Pastikan API sudah berjalan di port 3000
cd apps/mentor-web
python -m http.server 8081
# Buka: http://localhost:8081
```

> **Catatan:** `js/config.js` sudah dikonfigurasi ke `http://localhost:3000` untuk development.

---

## Konfigurasi Penting

### Update API URL untuk Production

Edit `apps/mentor-web/js/config.js`:
```js
window.AKSARAKU_CONFIG = Object.freeze({
  API_BASE_URL: 'https://api.domain-anda.com',  // URL API production
  SUPABASE_URL: 'https://xxx.supabase.co',
  SUPABASE_ANON_KEY: 'eyJ...',
});
```

### Environment Variables API

Lihat `services/api/.env.example` untuk daftar lengkap semua variabel yang diperlukan.

---

## Deployment

Lihat [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) untuk panduan deployment lengkap ke Vercel, Railway, Fly.io, dan VPS.

## Arsitektur

Lihat [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) untuk diagram arsitektur sistem lengkap.

---

## Tech Stack

| Layer | Teknologi |
|---|---|
| Frontend (Static) | HTML5, Vanilla CSS, Vanilla JS |
| Frontend (Portal) | HTML5, Tailwind CSS (CDN), Vanilla JS |
| Auth & Database | Supabase (PostgreSQL + pgvector + Auth) |
| Backend AI | Python, FastAPI, SentenceTransformers |
| LLM | Groq (Llama 3.3 70B) + OpenRouter (fallback) |
| Embedding | HuggingFace Inference / SentenceTransformers lokal |
| Hosting (Frontend) | Vercel / Cloudflare Pages |
| Hosting (Backend) | Railway / Fly.io / VPS |
