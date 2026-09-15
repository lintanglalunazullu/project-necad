#!/usr/bin/env bash
# =============================================================
# stop.sh — Hentikan semua service project-necad
# =============================================================
# Cara pakai:
#   ./scripts/stop.sh
# =============================================================

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$REPO_ROOT/.dev.pids"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo -e "${YELLOW}${BOLD}🛑  Stopping semua service project-necad...${NC}"

killed=0

if [[ -f "$PID_FILE" ]]; then
  while IFS= read -r pid; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null && echo -e "  Stopped PID $pid" && ((killed++)) || true
    fi
  done < "$PID_FILE"
  rm -f "$PID_FILE"
fi

# Jaga-jaga — kill berdasarkan nama proses kalau masih ada
pkill -f "python.*http.server 8080" 2>/dev/null && ((killed++)) || true
pkill -f "python.*http.server 8081" 2>/dev/null && ((killed++)) || true
pkill -f "uvicorn app:app" 2>/dev/null && ((killed++)) || true

if [[ $killed -gt 0 ]]; then
  echo -e "${GREEN}✅  Semua service berhasil dihentikan.${NC}"
else
  echo -e "${YELLOW}⚠️   Tidak ada service yang sedang berjalan.${NC}"
fi
