# Panduan Deployment 1 Server Hosting (Single VPS) — Project Necad

Dokumen ini adalah panduan lengkap deployment seluruh sistem **SMP Negeri 2 Cibungbulang** (Website Sekolah, Portal AI Mentor, dan Backend API) ke dalam **1 Server VPS Tunggal** berbasis **Subdomain**.

---

## 1. Arsitektur Single Server & Subdomain

```
                  ┌────────────────────────────────────────┐
                  │          INTERNET / PENGGUNA           │
                  └───────────────────┬────────────────────┘
                                      │
                 HTTPS (Port 443) / Let's Encrypt SSL
                                      ▼
             ┌──────────────────────────────────────────────────┐
             │       NGINX REVERSE PROXY (Port 80 / 443)        │
             └────────┬─────────────────┬─────────────────┬─────┘
                      │                 │                 │
     smpn2cibungbulang.sch.id           │                 │
    (dan www.smpn2cibungbulang.sch.id)  │                 │
                      │                 │                 │
                      ▼                 ▼                 ▼
             ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
             │ apps/school-web│ │ apps/mentor-web│ │ services/api   │
             │ (Web Sekolah)  │ │ (Portal Mentor)│ │ (FastAPI venv) │
             │  Static HTML   │ │  Static HTML   │ │ 127.0.0.1:3000 │
             └────────────────┘ └────────────────┘ └────────────────┘
```

### Keunggulan Arsitektur Ini:
1. **Biaya Super Hemat**: Hanya butuh 1 VPS (1 vCPU, 1–2 GB RAM seharga Rp 50.000–80.000/bulan).
2. **Performa Tinggi**: Backend API berbasis FastAPI sangat ringan (~50MB RAM) karena HuggingFace/PyTorch sudah digantikan oleh Gemini & Groq API.
3. **Smart Auto-Detect**: Frontend otomatis mengenali hostname lokal vs production tanpa perlu mengedit file konfigurasi setiap kali deploy/update.
4. **Resilience & Keamanan**: Menggunakan Systemd untuk auto-restart jika backend crash, Nginx dengan Gzip, caching aset statis, dan SSL Let's Encrypt gratis.

---

## 2. Pengaturan DNS Domain

Di panel registrar/DNS domain Anda (misal: Rumahweb, Niagahoster, Cloudflare, IDwebhost):
Tambahkan DNS Record berikut (ganti `103.xx.xx.xx` dengan IP Publik VPS Anda):

| Tipe | Nama Host / Subdomain | Target / Nilai | TTL | Keterangan |
|---|---|---|---|---|
| **A** | `@` | `103.xx.xx.xx` | Auto / 3600 | Website Sekolah utama |
| **A** | `www` | `103.xx.xx.xx` | Auto / 3600 | Alias Website Sekolah |
| **A** | `mentor` | `103.xx.xx.xx` | Auto / 3600 | Portal AI Mentor |
| **A** | `api` | `103.xx.xx.xx` | Auto / 3600 | Backend API & Swagger Docs |

---

## 3. Langkah Instalasi di Server VPS (Ubuntu 22.04 / 24.04 LTS)

### Langkah 1: Update Server & Install Paket Dasar
Login ke VPS via SSH, lalu jalankan:
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git nginx python3 python3-venv python3-pip certbot python3-certbot-nginx
```

### Langkah 2: Clone Repositori ke Direktori Web
```bash
sudo mkdir -p /var/www
sudo chown -R $USER:$USER /var/www
cd /var/www
git clone https://github.com/ReyyIchiro/project-necad.git
cd /var/www/project-necad
```

### Langkah 3: Setup Virtual Environment & Dependensi Backend
```bash
cd /var/www/project-necad/services/api
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Langkah 4: Konfigurasi Environment Variable (`.env`)
Salin template `.env.example`:
```bash
cp .env.example .env
nano .env
```
Isi nilai-nilai wajib:
- `SUPABASE_URL` & `SUPABASE_SERVICE_ROLE_KEY`: dari Supabase Dashboard.
- `GEMINI_API_KEY`: API Key dari [Google AI Studio](https://aistudio.google.com/apikey).
- `GROQ_API_KEY` (opsional): API Key dari [Groq Console](https://console.groq.com/keys).
- `ALLOWED_ORIGINS`:
  `https://smpn2cibungbulang.sch.id,https://mentor.smpn2cibungbulang.sch.id`

Simpan dengan menekan `Ctrl+O` lalu `Enter`, dan keluar dengan `Ctrl+X`.

### Langkah 5: Pasang Service Systemd (Auto-Start Backend)
Salin unit service yang sudah disediakan:
```bash
sudo cp /var/www/project-necad/docs/systemd/aksaraku-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable aksaraku-api
sudo systemctl start aksaraku-api
```

Cek status service untuk memastikan backend sudah running:
```bash
sudo systemctl status aksaraku-api
```
*(Harus berstatus: `active (running)`)*

### Langkah 6: Pasang Konfigurasi Nginx
Salin konfigurasi Nginx dari repositori:
```bash
sudo cp /var/www/project-necad/docs/nginx/smpn2cibungbulang.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/smpn2cibungbulang.conf /etc/nginx/sites-enabled/
```
*(Opsional: hapus konfigurasi default jika tidak dipakai)*
```bash
sudo rm -f /etc/nginx/sites-enabled/default
```

Uji sintaks Nginx dan restart web server:
```bash
sudo nginx -t
sudo systemctl restart nginx
```

### Langkah 7: Pasang Sertifikat SSL Gratis (HTTPS) via Certbot
Jalankan satu perintah ini untuk mengaktifkan HTTPS otomatis pada semua domain dan subdomain:
```bash
sudo certbot --nginx -d smpn2cibungbulang.sch.id -d www.smpn2cibungbulang.sch.id -d mentor.smpn2cibungbulang.sch.id -d api.smpn2cibungbulang.sch.id
```
Certbot akan otomatis memodifikasi konfigurasi Nginx dan mengatur auto-renewal SSL setiap 90 hari.

---

## 4. Konfigurasi Supabase Auth untuk Production

Agar fitur login Google dan sesi auth bekerja di domain produksi:
1. Buka **[Supabase Dashboard](https://supabase.com/dashboard)** → Pilih project Anda.
2. Masuk ke menu **Authentication** → **URL Configuration**.
3. **Site URL**:
   `https://mentor.smpn2cibungbulang.sch.id`
4. **Redirect URLs**: tambahkan URL berikut:
   - `http://localhost:8081`
   - `http://localhost:8081/**`
   - `https://mentor.smpn2cibungbulang.sch.id`
   - `https://mentor.smpn2cibungbulang.sch.id/**`
5. Klik **Save**.

---

## 5. Pemeliharaan & Update Rutin (Maintenance)

Jika ada perubahan kode di GitHub yang ingin ditarik ke server:
```bash
cd /var/www/project-necad
git pull origin main

# Update dependensi jika ada perubahan requirements.txt
source services/api/.venv/bin/activate
pip install -r services/api/requirements.txt

# Restart backend service
sudo systemctl restart aksaraku-api

# (Opsional) Reload Nginx jika ada update konfigurasi web
sudo nginx -t && sudo systemctl reload nginx
```

### Melihat Log Backend Secara Realtime:
```bash
sudo journalctl -u aksaraku-api -f
```

### Melihat Log Nginx:
```bash
sudo tail -f /var/log/nginx/error.log
```
