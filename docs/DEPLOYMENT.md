# Panduan Deployment — Project Necad

## Overview Strategi Deployment

```
school-web  ──► Vercel / Cloudflare Pages (gratis, CDN global)
mentor-web  ──► Vercel / Cloudflare Pages (gratis, CDN global)
services/api ─► Railway / Fly.io / VPS Docker (perlu server Python)
```

> **Mengapa dipisah hosting?**
> Backend Python dengan SentenceTransformer membutuhkan memory 500MB–1GB.
> Frontend static tidak membutuhkan server — host di CDN saja sudah cukup & gratis.
> Dengan dipisah, jika AI API mengalami masalah, website sekolah tetap online.

---

## 1. Deploy `apps/school-web` → Vercel

### Langkah:
1. Buka [vercel.com](https://vercel.com) → New Project → Import dari GitHub
2. Root Directory: `apps/school-web`
3. Framework Preset: **Other** (static)
4. Build Command: *(kosongkan)*
5. Output Directory: `.` (titik)
6. Klik **Deploy**

### Custom Domain:
- Settings → Domains → tambahkan `smpn2cibungbulang.sch.id`

---

## 2. Deploy `apps/mentor-web` → Vercel

### Langkah:
1. Buka [vercel.com](https://vercel.com) → New Project → Import dari GitHub
2. Root Directory: `apps/mentor-web`
3. Framework Preset: **Other** (static)
4. Klik **Deploy**

### Setelah deploy, update API URL:
Edit `apps/mentor-web/js/config.js`:
```js
window.AKSARAKU_CONFIG = Object.freeze({
  API_BASE_URL: 'https://api.domain-anda.com',  // URL production API
  SUPABASE_URL: 'https://xxx.supabase.co',
  SUPABASE_ANON_KEY: 'eyJ...',
});
```
Commit & push → Vercel auto-redeploy.

### Custom Domain:
- Settings → Domains → tambahkan `aksara.smpn2cibungbulang.sch.id`

---

## 3. Deploy `services/api` → Railway (Rekomendasi)

Railway adalah platform hosting Python/Docker yang mudah & harga terjangkau.

### Langkah:
1. Buka [railway.app](https://railway.app) → New Project → Deploy from GitHub
2. Pilih folder `services/api` sebagai root
3. Railway mendeteksi Python otomatis dari `requirements.txt`
4. Tambahkan environment variables dari `.env.example` di panel Railway:
   - Settings → Variables → tambahkan semua vars
5. Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
6. Klik **Deploy**

### Custom Domain di Railway:
- Settings → Networking → Custom Domain: `api.smpn2cibungbulang.sch.id`

---

## 4. Deploy `services/api` → Fly.io (Alternatif)

### Install flyctl:
```bash
curl -L https://fly.io/install.sh | sh
fly auth login
```

### Deploy:
```bash
cd services/api
fly launch --name aksaraku-api --region sin  # Singapore region, dekat Indonesia
fly secrets set SUPABASE_URL=https://... GROQ_API_KEY=gsk_...
fly deploy
```

### Buat `fly.toml` di `services/api/` jika belum ada:
```toml
app = "aksaraku-api"
primary_region = "sin"

[build]
  builder = "paketobuildpacks/builder:base"

[http_service]
  internal_port = 3000
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 0

[[vm]]
  memory = "1gb"
  cpu_kind = "shared"
  cpus = 1
```

---

## 5. Deploy `services/api` → VPS dengan Docker

### Dockerfile (buat di `services/api/Dockerfile`):
```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 3000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "3000"]
```

### Jalankan:
```bash
# Build
docker build -t aksaraku-api ./services/api

# Run
docker run -d \
  --name aksaraku-api \
  --restart always \
  -p 3000:3000 \
  --env-file ./services/api/.env \
  aksaraku-api
```

---

## Setup Supabase Auth

Setelah deploy mentor-web ke domain resmi, konfigurasi Supabase:

1. Buka **Supabase Dashboard** → Authentication → URL Configuration
2. **Site URL**: `https://aksara.smpn2cibungbulang.sch.id`
3. **Redirect URLs**: tambahkan:
   - `https://aksara.smpn2cibungbulang.sch.id`
   - `https://aksara.smpn2cibungbulang.sch.id/**`
4. Authentication → Providers → Google: pastikan sudah aktif

---

## Setup CORS di API Production

Perketat CORS di `services/api/app.py` untuk production:
```python
# Ganti allow_origins=["*"] dengan domain spesifik:
app.add_middleware(CORSMiddleware,
    allow_origins=[
        "https://smpn2cibungbulang.sch.id",
        "https://aksara.smpn2cibungbulang.sch.id",
    ],
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)
```

---

## GitHub Actions: Supabase Keep-Alive

File `.github/workflows/supabase-keepalive.yml` sudah ada di root monorepo.
Tambahkan secrets di GitHub: Settings → Secrets → Actions:
- `SUPABASE_URL` — URL Supabase project
- `SUPABASE_ANON_KEY` — Anon key Supabase

Workflow ini berjalan setiap 3 hari untuk mencegah Supabase free tier pause.

---

## Checklist Pre-Launch

- [ ] `services/api/.env` diisi dengan nilai production
- [ ] `apps/mentor-web/js/config.js` `API_BASE_URL` diupdate ke URL production
- [ ] Supabase Auth URL Configuration diupdate
- [ ] CORS di `services/api/app.py` diperketat ke domain production
- [ ] Custom domain terpasang di Vercel & Railway/Fly.io
- [ ] GitHub Actions secrets sudah diisi
- [ ] Test semua endpoint API di production
- [ ] Test login Google di production domain
