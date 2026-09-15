#!/usr/bin/env bash
# =============================================================
# dev.sh — Jalankan semua service project-necad sekaligus
# =============================================================
# Cara pakai:
#   chmod +x scripts/dev.sh   (sekali aja)
#   ./scripts/dev.sh
#
# Tekan Ctrl+C buat stop semua service sekaligus.
# =============================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$REPO_ROOT/.dev.pids"

# ---- Warna terminal ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# ---- Cleanup saat Ctrl+C ----
cleanup() {
  echo ""
  echo -e "${YELLOW}${BOLD}🛑  Stopping semua service...${NC}"
  if [[ -f "$PID_FILE" ]]; then
    while IFS= read -r pid; do
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
      fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
  fi
  # Jaga-jaga kill proses python http.server yang mungkin masih jalan
  pkill -f "python.*http.server 8080" 2>/dev/null || true
  pkill -f "python.*http.server 8081" 2>/dev/null || true
  pkill -f "uvicorn app:app" 2>/dev/null || true
  echo -e "${GREEN}✅  Semua service sudah dihentikan.${NC}"
  exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# ---- Cek file .env API ----
ENV_FILE="$REPO_ROOT/services/api/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo -e "${RED}❌  File .env belum ada di services/api/.env${NC}"
  echo -e "${YELLOW}   Jalankan: cp services/api/.env.example services/api/.env${NC}"
  echo -e "${YELLOW}   Lalu isi API key yang dibutuhkan, terus jalankan lagi.${NC}"
  exit 1
fi

# ---- Cek virtual environment Python ----
VENV_DIR="$REPO_ROOT/services/api/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
  echo -e "${CYAN}📦  Virtual environment belum ada, bikin dulu...${NC}"
  python3 -m venv "$VENV_DIR"
  echo -e "${CYAN}📦  Install dependensi Python...${NC}"
  "$VENV_DIR/bin/pip" install --quiet --upgrade pip
  "$VENV_DIR/bin/pip" install --quiet -r "$REPO_ROOT/services/api/requirements.txt"
  echo -e "${GREEN}✅  Dependensi Python berhasil diinstall.${NC}"
fi

# ---- Cek apakah port sudah dipakai ----
check_port() {
  local port=$1
  if lsof -Pi ":$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo -e "${RED}❌  Port $port sudah dipakai. Stop proses yang pakai port itu dulu.${NC}"
    echo -e "${YELLOW}   Cari prosesnya: lsof -i :$port${NC}"
    exit 1
  fi
}

echo -e "${BLUE}${BOLD}🔍  Cek ketersediaan port...${NC}"
check_port 3000
check_port 8080
check_port 8081

# ---- Hapus PID file lama ----
rm -f "$PID_FILE"

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       🚀  Project Necad — Dev Server             ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# ---- Jalankan Backend API ----
echo -e "${CYAN}▶  Menjalankan Backend API...${NC}"
(
  cd "$REPO_ROOT/services/api"
  source "$VENV_DIR/bin/activate"
  exec "$VENV_DIR/bin/uvicorn" app:app \
    --host 0.0.0.0 \
    --port 3000 \
    --reload \
    --log-level info \
    2>&1 | sed "s/^/$(printf '\033[0;34m')[API]$(printf '\033[0m') /"
) &
echo $! >> "$PID_FILE"

sleep 1  # kasih jeda supaya port 3000 sempat kebuka

# ---- Jalankan School Web ----
echo -e "${CYAN}▶  Menjalankan Website Sekolah (port 8080)...${NC}"
(
  cd "$REPO_ROOT/apps/school-web"
  exec python3 -m http.server 8080 \
    2>&1 | sed "s/^/$(printf '\033[0;32m')[SCHOOL]$(printf '\033[0m') /"
) &
echo $! >> "$PID_FILE"

# ---- Jalankan Mentor Web ----
echo -e "${CYAN}▶  Menjalankan Portal Mentor (port 8081)...${NC}"
(
  cd "$REPO_ROOT/apps/mentor-web"
  exec python3 -m http.server 8081 \
    2>&1 | sed "s/^/$(printf '\033[1;33m')[MENTOR]$(printf '\033[0m') /"
) &
echo $! >> "$PID_FILE"

echo ""
echo -e "${BOLD}══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}✅  Semua service berjalan!${NC}"
echo ""
echo -e "  ${BLUE}🌐  Website Sekolah${NC}   → http://localhost:8080"
echo -e "  ${YELLOW}🤖  Portal Mentor${NC}     → http://localhost:8081"
echo -e "  ${CYAN}⚙️   Backend API${NC}       → http://localhost:3000"
echo -e "  ${CYAN}📖  API Swagger Docs${NC}  → http://localhost:3000/docs"
echo ""
echo -e "  ${RED}Ctrl+C untuk stop semua service.${NC}"
echo -e "${BOLD}══════════════════════════════════════════════════${NC}"
echo ""

# ---- Tunggu semua background process ----
wait
