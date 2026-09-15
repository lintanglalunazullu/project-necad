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
│       ├── app.py      # Entry point (ringan, cuma setup + routing)
│       ├── config.py   # Semua ENV variable terpusat
│       ├── auth.py     # Autentikasi & otorisasi role-based
│       ├── models.py   # Pydantic request/response models
│       ├── ai/         # AI pipeline (embedding Gemini, multi-provider LLM, retrieval, session)
│       ├── rag/        # Legacy RAG pipeline (deprecated, akan dihapus)
│       ├── routes/     # Route handlers (chat, documents, admin)
│       └── utils/      # Helper functions
├── scripts/
│   ├── dev.sh          # Jalankan semua service sekaligus (dev mode)
│   └── stop.sh         # Hentikan semua service
├── docs/
│   ├── supabase_setup.sql       # SQL: Skema database lengkap (tabel, RPC, RLS, seed data)
│   ├── ARCHITECTURE.md          # Diagram & penjelasan arsitektur sistem
│   ├── DEPLOYMENT.md            # Panduan deployment lengkap
│   ├── ai_provider_config.sql   # SQL: Tabel config AI provider (sudah include di supabase_setup.sql)
│   └── migration_embedding_768.sql  # SQL: Migrasi embedding 384→768 (opsional)
└── .github/
    └── workflows/
        ├── lint.yml            # Lint & test Python on PR
        ├── deploy-web.yml      # Auto-deploy ke Vercel
        └── deploy-api.yml      # Auto-deploy ke Railway
```

---

## 🚀 Quick Start — Development (Semua Sekaligus)

> Cara tercepat untuk jalankan semua service cukup **satu perintah**.

```bash
# 1. Clone repo
git clone https://github.com/ReyyIchiro/project-necad.git
cd project-necad

# 2. Buat file .env backend (sekali aja)
cp services/api/.env.example services/api/.env
# Edit services/api/.env — isi: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, GEMINI_API_KEY

# 3. Setup Database Supabase (sekali aja)
# Buka Supabase Dashboard → SQL Editor → New Query
# Salin seluruh isi file docs/supabase_setup.sql, tempel, lalu klik RUN

# 4. Kasih izin eksekusi (sekali aja)
chmod +x scripts/dev.sh scripts/stop.sh

# 5. Jalankan SEMUA service sekaligus
./scripts/dev.sh
```

Setelah jalan, bisa langsung akses:

| Service | URL |
|---|---|
| 🌐 Website Sekolah | http://localhost:8080 |
| 🤖 Portal Mentor | http://localhost:8081 |
| ⚙️ Backend API | http://localhost:3000 |
| 📖 API Swagger Docs | http://localhost:3000/docs |

```bash
# Stop semua service
./scripts/stop.sh

# Atau tekan Ctrl+C di terminal yang jalankan dev.sh
```

> **Catatan:** Pertama kali dijalankan, `dev.sh` akan otomatis membuat virtual environment Python dan menginstall semua dependensi. Tidak perlu setup manual. Install sekarang lebih cepat karena tidak ada model HuggingFace yang perlu didownload.

---

## Komponen Sistem

### `apps/school-web` — Website Profil Sekolah

Website informasi statis untuk SMP Negeri 2 Cibungbulang.

**Halaman:**
- `/` — Beranda
- `/pages/akademik.html` — Info Akademik
- `/pages/informasi.html` — Berita & Informasi
- `/pages/kesiswaan.html` — Kesiswaan
- `/pages/kontak.html` — Kontak
- `/pages/ppdb.html` — PPDB / SPMB
- `/pages/profile.html` — Profil Sekolah

**Deploy:** Vercel / Cloudflare Pages (static hosting gratis)

**SEO:** Meta description, OG tags, Schema.org, sitemap.xml, robots.txt sudah tersedia.

---

### `apps/mentor-web` — Portal AI Mentor (Aksaraku)

Web application dengan fitur AI chat berbasis RAG, manajemen dokumen, dan multi-role dashboard.

**Role & Akses:**
| Role | Login | Area |
|---|---|---|
| User / Siswa | `/login.html` (Google OAuth) | `/index.html` |
| Guru | `/teacher/login.html` | `/teacher/chat.html` |
| Admin | `/admin/login.html` | `/admin/index.html` |

**Konfigurasi:** `js/config.js` — satu-satunya tempat untuk set API URL dan Supabase credentials.

```js
window.AKSARAKU_CONFIG = Object.freeze({
  API_BASE_URL: 'http://localhost:3000',  // Ganti ke URL production
  SUPABASE_URL: 'https://xxx.supabase.co',
  SUPABASE_ANON_KEY: 'eyJ...',
})
```

**Deploy:** Vercel / Cloudflare Pages (static hosting)

---

### `services/api` — Backend FastAPI (Aksaraku API v3.0)

Backend Python dengan FastAPI untuk RAG engine, AI chat, dan manajemen data.

**Teknologi:**
- **FastAPI** — REST API framework
- **Gemini text-embedding-004** — Embedding via API (ringan, instant startup, tidak ada model lokal)
- **Supabase** — Vector database & auth management
- **Gemini + Groq + OpenRouter** — LLM providers dengan smart fallback + circuit breaker
- **slowapi** — Rate limiting

**Endpoints Utama:**

| Method | Path | Auth | Deskripsi |
|---|---|---|---|
| `GET` | `/health` | - | Health check + status AI providers |
| `GET` | `/admin/dashboard` | Admin | Statistik dashboard |
| `DELETE` | `/admin/users/{id}` | Admin | Hapus user |
| `GET` | `/admin/ai/providers` | Admin | List AI provider + status + stats |
| `PUT` | `/admin/ai/providers/{name}` | Admin | Update config provider (tanpa restart) |
| `POST` | `/admin/ai/providers/test` | Admin | Test provider dengan prompt dummy |
| `GET` | `/admin/ai/stats` | Admin | Statistik penggunaan + error rate |
| `POST` | `/admin/ai/reload` | Admin | Reload config dari Supabase ke memory |
| `GET` | `/documents` | User/Teacher/Admin | Daftar dokumen (difilter by role) |
| `PUT` | `/documents/{id}` | Teacher/Admin | Rename/ubah kategori |
| `DELETE` | `/documents/{id}` | Admin | Hapus dokumen |
| `POST` | `/embed-upsert` | Teacher/Admin | Upload + embed dokumen (via Gemini) |
| `POST` | `/embed-upsert-raw` | Teacher/Admin | Upload chunk dengan embedding precomputed |
| `POST` | `/query-docs` | Semua (terautentikasi) | Cari dokumen via similarity |
| `POST` | `/chat` | Semua (anonim diizinkan) | Chat AI dengan RAG (30 req/min) |

**Deploy:** Railway / Fly.io / VPS

**Rate Limits:**
- Global: 100 req/menit per IP
- `/chat`: 30 req/menit per IP
- `/query-docs`: 60 req/menit per IP

---

## Konfigurasi Penting

### Environment Variables Minimal (Wajib)

```env
# Supabase
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...

# Gemini (embedding + chat LLM)
GEMINI_API_KEY=AIzaSy...

# Dimensi vector — sesuaikan dengan kolom vector di Supabase!
EXPECTED_EMBEDDING_DIMENSION=768
```

### Tambahan LLM Providers (Opsional, sebagai fallback)

```env
GROQ_API_KEY=gsk_xxx         # Priority 2
OPENROUTER_API_KEY=sk-or-xxx # Priority 3
```

### CORS (Wajib di production)

```env
ALLOWED_ORIGINS=https://smpn2cibungbulang.sch.id,https://aksaraku.vercel.app
```

Lihat `services/api/.env.example` untuk daftar lengkap.

---

## Admin: Kelola AI Provider via Dashboard

Setelah login sebagai admin, kamu bisa kelola AI provider **tanpa restart server**:

```bash
# Lihat status semua provider
GET /admin/ai/providers

# Nonaktifkan Groq sementara
PUT /admin/ai/providers/groq
{ "enabled": false }

# Ganti model Gemini
PUT /admin/ai/providers/gemini
{ "model": "gemini-2.5-flash" }

# Test provider
POST /admin/ai/providers/test
{ "provider": "gemini", "prompt": "Halo, siapa kamu?" }
```

Untuk config yang **survive server restart**, jalankan SQL di `docs/ai_provider_config.sql` di Supabase.

---

## Migrasi dari v2 ke v3

Kalau kamu upgrade dari v2 (pakai HuggingFace):

1. **Tambahkan** `GEMINI_API_KEY` di `.env`
2. **Hapus** `HUGGINGFACE_API_KEY` dan `HUGGINGFACE_EMBEDDING_MODEL` dari `.env`
3. **Putuskan dimensi embedding:**
   - Tetap `384`: set `EXPECTED_EMBEDDING_DIMENSION=384` (backward compat, data lama tetap bisa dipakai)
   - Upgrade ke `768`: set `EXPECTED_EMBEDDING_DIMENSION=768`, lalu jalankan `docs/migration_embedding_768.sql` dan re-embed semua dokumen
4. **Install ulang dependencies:** `pip install -r requirements.txt`

---

## CI/CD

Semua pipeline CI/CD ada di `.github/workflows/`:

| Workflow | Trigger | Aksi |
|---|---|---|
| `lint.yml` | Push/PR ke `services/api/**` | Ruff lint + pytest |
| `deploy-web.yml` | Push ke `main` di `apps/**` | Deploy ke Vercel |
| `deploy-api.yml` | Push ke `main` di `services/api/**` | Deploy ke Railway |

**Setup secrets yang dibutuhkan di GitHub:**
- `VERCEL_TOKEN` — dari Vercel dashboard
- `RAILWAY_TOKEN` — dari Railway dashboard

---

## Tech Stack

| Layer | Teknologi |
|---|---|
| Frontend (Static) | HTML5, Vanilla CSS, Vanilla JS |
| Frontend (Portal) | HTML5, Tailwind CSS (CDN, pinned), Vanilla JS |
| Auth & Database | Supabase (PostgreSQL + pgvector + Auth) |
| Backend AI | Python 3.12, FastAPI |
| Embedding | Gemini text-embedding-004 (API, tanpa model lokal) |
| LLM | Gemini 2.0 Flash → Groq (Llama 3.3 70B) → OpenRouter (fallback) |
| Rate Limiting | slowapi |
| Hosting (Frontend) | Vercel / Cloudflare Pages |
| Hosting (Backend) | Railway / Fly.io / VPS |
