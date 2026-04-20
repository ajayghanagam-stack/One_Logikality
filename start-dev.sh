#!/usr/bin/env bash
#
# One Logikality — local development bring-up.
#
# Tested on macOS + OrbStack. Windows users: run under WSL2 Ubuntu
# (see docs/TechStack.md §13).
#
# Docker services   db (Postgres 5437), temporal-db, temporal (7234), temporal-ui (8086)
# Native processes  uvicorn (FastAPI, 8001), Temporal worker, Next.js dev (9999)
#
# Usage:  ./start-dev.sh
# Stop:   Ctrl+C

set -eo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
VENV_PY="$BACKEND_DIR/.venv/bin/python"
VENV_UVICORN="$BACKEND_DIR/.venv/bin/uvicorn"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

log_step() { echo -e "${CYAN}$1${NC}"; }
log_ok()   { echo -e "${GREEN}$1${NC}"; }
log_warn() { echo -e "${YELLOW}$1${NC}"; }
log_err()  { echo -e "${RED}$1${NC}" >&2; }

# ------------------------------------------------------------------
# Preflight
# ------------------------------------------------------------------
if [ ! -f "$ROOT_DIR/.env" ]; then
  log_err "Missing .env at repo root."
  log_err "  Run: cp .env.example .env"
  exit 1
fi
if [ ! -x "$VENV_PY" ]; then
  log_err "Backend venv not found at backend/.venv."
  log_err "  Run: cd backend && python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  log_err "Frontend node_modules not found."
  log_err "  Run: cd frontend && npm install"
  exit 1
fi

# ------------------------------------------------------------------
# Cleanup on exit
# ------------------------------------------------------------------
PIDS=()
cleanup() {
  trap - EXIT SIGINT SIGTERM
  echo
  log_warn "Shutting down..."
  if [ ${#PIDS[@]} -gt 0 ]; then
    for pid in "${PIDS[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
  fi
  docker compose -f "$ROOT_DIR/docker-compose.yml" stop 2>/dev/null || true
  log_ok "All stopped."
}
trap cleanup EXIT SIGINT SIGTERM

# ------------------------------------------------------------------
# [0/5] Kill stale processes on our ports and stray workers
# ------------------------------------------------------------------
log_step "[0/5] Cleaning up stale processes..."
for port in 8001 9999; do
  stale=$(lsof -ti :"$port" 2>/dev/null || true)
  if [ -n "$stale" ]; then
    log_warn "       Killing process on :$port ($stale)"
    echo "$stale" | xargs kill 2>/dev/null || true
    sleep 1
  fi
done
stale_workers=$(pgrep -f "app.pipeline.worker" 2>/dev/null || true)
if [ -n "$stale_workers" ]; then
  log_warn "       Killing stale Temporal worker(s): $stale_workers"
  echo "$stale_workers" | xargs kill 2>/dev/null || true
  sleep 1
fi
log_ok "       Done"

# ------------------------------------------------------------------
# [1/5] Bring up Docker services
# ------------------------------------------------------------------
log_step "[1/5] Starting Docker services..."
docker compose -f "$ROOT_DIR/docker-compose.yml" up -d

log_step "       Waiting for Postgres..."
until docker compose -f "$ROOT_DIR/docker-compose.yml" exec -T db pg_isready -U postgres >/dev/null 2>&1; do
  sleep 1
done
log_ok "       Postgres ready on localhost:5437"

log_step "       Waiting for Temporal on localhost:7234..."
for i in $(seq 1 90); do
  if nc -z localhost 7234 2>/dev/null; then
    sleep 3  # give Temporal a moment to fully initialize after port opens
    log_ok "       Temporal ready on localhost:7234"
    break
  fi
  if [ "$i" -eq 90 ]; then
    log_warn "       WARNING: Temporal may not be ready yet (timed out)"
  fi
  sleep 2
done

# ------------------------------------------------------------------
# [2/5] Apply Alembic migrations + seed demo data
# ------------------------------------------------------------------
log_step "[2/5] Applying Alembic migrations..."
cd "$BACKEND_DIR"
"$VENV_PY" -m alembic upgrade head
log_ok "       Migrations applied"

log_step "       Seeding demo data..."
"$VENV_PY" -m scripts.seed
log_ok "       Seed complete"

# ------------------------------------------------------------------
# [3/5] Start FastAPI
# ------------------------------------------------------------------
log_step "[3/5] Starting FastAPI on http://localhost:8001 ..."
cd "$BACKEND_DIR"
"$VENV_UVICORN" app.main:app --host 127.0.0.1 --port 8001 --reload &
PIDS+=($!)

# ------------------------------------------------------------------
# [4/5] Start Temporal worker (idle placeholder until Phase 3 activities land)
# ------------------------------------------------------------------
log_step "[4/5] Starting Temporal worker (task queue: ecv)..."
cd "$BACKEND_DIR"
"$VENV_PY" -m app.pipeline.worker &
PIDS+=($!)

# ------------------------------------------------------------------
# [5/5] Start Next.js dev server
# ------------------------------------------------------------------
log_step "[5/5] Starting Next.js on http://localhost:9999 ..."
cd "$FRONTEND_DIR"
npm run dev &
PIDS+=($!)

echo
log_ok "========================================="
log_ok " All services running"
log_ok "========================================="
echo -e "  UI:          ${CYAN}http://localhost:9999${NC}"
echo -e "  API:         ${CYAN}http://localhost:8001${NC}"
echo -e "  API docs:    ${CYAN}http://localhost:8001/docs${NC}"
echo -e "  Temporal UI: ${CYAN}http://localhost:8086${NC}"
echo -e "  Postgres:    ${CYAN}localhost:5437${NC}"
echo
log_warn "Press Ctrl+C to stop all services"
wait
