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
│       ├── rag/        # RAG pipeline (embedding, retrieval, generation, session)
│       ├── routes/     # Route handlers (chat, documents, admin)
│       └── utils/      # Helper functions
├── scripts/
│   ├── dev.sh          # Jalankan semua service sekaligus (dev mode)
│   └── stop.sh         # Hentikan semua service
├── docs/
│   ├── ARCHITECTURE.md # Diagram & penjelasan arsitektur sistem
│   └── DEPLOYMENT.md   # Panduan deployment lengkap
└── .github/
    └── workflows/
        ├── lint.yml            # Lint & test Python on PR
        ├── deploy-web.yml      # Auto-deploy ke Vercel
        └── deploy-api.yml      # Auto-deploy ke Railway
        └── supabase-keepalive.yml
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
# Edit services/api/.env — isi API key Supabase, Groq, HuggingFace

# 3. Jalankan SEMUA service sekaligus
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

> **Catatan:** Pertama kali dijalankan, `dev.sh` akan otomatis membuat virtual environment Python dan menginstall semua dependensi dari `requirements.txt`. Tidak perlu setup manual.

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

### `services/api` — Backend FastAPI (Aksaraku API)

Backend Python dengan FastAPI untuk RAG engine, AI chat, dan manajemen data.

**Teknologi:**
- **FastAPI** — REST API framework
- **SentenceTransformers** — Embedding model lokal
- **Supabase** — Vector database & auth management
- **Groq + OpenRouter** — LLM providers (dengan fallback otomatis)
- **slowapi** — Rate limiting

**Endpoints:**
| Method | Path | Auth | Deskripsi |
|---|---|---|---|
| `GET` | `/health` | - | Health check |
| `GET` | `/admin/dashboard` | Admin | Statistik dashboard |
| `DELETE` | `/admin/users/{id}` | Admin | Hapus user |
| `GET` | `/documents` | User/Teacher/Admin | Daftar dokumen (difilter by role) |
| `PUT` | `/documents/{id}` | Teacher/Admin | Rename/ubah kategori |
| `DELETE` | `/documents/{id}` | Admin | Hapus dokumen |
| `POST` | `/embed-upsert` | Teacher/Admin | Upload + embed dokumen PDF |
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

### CORS (Wajib di production)

Edit `services/api/.env`:
```env
ALLOWED_ORIGINS=https://smpn2cibungbulang.sch.id,https://aksaraku.vercel.app
```

### Environment Variables API

Lihat `services/api/.env.example` untuk daftar lengkap semua variabel yang diperlukan.

---

## Deployment Production

Lihat [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) untuk panduan deployment lengkap ke Vercel, Railway, Fly.io, dan VPS.

## Arsitektur

Lihat [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) untuk diagram arsitektur sistem lengkap.

---

## CI/CD

Semua pipeline CI/CD ada di `.github/workflows/`:

| Workflow | Trigger | Aksi |
|---|---|---|
| `lint.yml` | Push/PR ke `services/api/**` | Ruff lint + pytest |
| `deploy-web.yml` | Push ke `main` di `apps/**` | Deploy ke Vercel |
| `deploy-api.yml` | Push ke `main` di `services/api/**` | Deploy ke Railway |
| `supabase-keepalive.yml` | Cron harian | Ping Supabase biar tidak pause |

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
| Backend AI | Python 3.12, FastAPI, SentenceTransformers |
| LLM | Groq (Llama 3.3 70B) + OpenRouter (fallback) |
| Embedding | SentenceTransformers lokal (`all-MiniLM-L6-v2`) |
| Rate Limiting | slowapi |
| Hosting (Frontend) | Vercel / Cloudflare Pages |
| Hosting (Backend) | Railway / Fly.io / VPS |
