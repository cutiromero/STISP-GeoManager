#!/usr/bin/env zsh
# start-dev.sh — One-click test environment launcher
#
# Starts frontend (pnpm dev) and backend (Django runserver) concurrently.
# Press Ctrl+C to stop both.

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
typeset -a SERVICE_PIDS=()
STOPPING=0

cleanup() {
  if (( STOPPING )); then
    return
  fi

  STOPPING=1
  trap - SIGINT SIGTERM EXIT

  echo ""
  echo "Stopping all services..."

  for pid in "${SERVICE_PIDS[@]}"; do
    stop_process_group "$pid" TERM
  done

  if ! wait_for_process_groups 10; then
    echo "Services did not stop within 10s; forcing shutdown..."
    for pid in "${SERVICE_PIDS[@]}"; do
      stop_process_group "$pid" KILL
    done
  fi

  for pid in "${SERVICE_PIDS[@]}"; do
    wait "$pid" 2>/dev/null || true
  done

  echo "All services stopped."
}

is_process_group_alive() {
  local pid="$1"
  [[ -n "$pid" ]] || return 1
  command kill -0 -- "-$pid" 2>/dev/null || command kill -0 "$pid" 2>/dev/null
}

stop_process_group() {
  local pid="$1"
  local signal="$2"

  [[ -n "$pid" ]] || return 0
  command kill "-$signal" -- "-$pid" 2>/dev/null || command kill "-$signal" "$pid" 2>/dev/null || true
}

wait_for_process_groups() {
  local timeout_seconds="$1"
  local elapsed=0
  local pid

  while (( elapsed < timeout_seconds )); do
    local alive=0
    for pid in "${SERVICE_PIDS[@]}"; do
      if is_process_group_alive "$pid"; then
        alive=1
        break
      fi
    done

    if (( ! alive )); then
      return 0
    fi

    sleep 1
    (( elapsed += 1 ))
  done

  return 1
}

start_backend() {
  if command -v setsid >/dev/null 2>&1; then
    setsid zsh -c 'cd "$1" || exit 1; pixi install && pixi run migrate && exec pixi run dev' start-dev-backend "$ROOT_DIR/backend" &
  else
    zsh -c 'cd "$1" || exit 1; pixi install && pixi run migrate && exec pixi run dev' start-dev-backend "$ROOT_DIR/backend" &
  fi

  BACKEND_PID=$!
  SERVICE_PIDS+=("$BACKEND_PID")
}

start_frontend() {
  if command -v setsid >/dev/null 2>&1; then
    setsid zsh -c 'cd "$1" || exit 1; exec pnpm dev' start-dev-frontend "$ROOT_DIR/frontend" &
  else
    zsh -c 'cd "$1" || exit 1; exec pnpm dev' start-dev-frontend "$ROOT_DIR/frontend" &
  fi

  FRONTEND_PID=$!
  SERVICE_PIDS+=("$FRONTEND_PID")
}

monitor_services() {
  local pid
  local status

  while true; do
    for pid in "${SERVICE_PIDS[@]}"; do
      if ! command kill -0 "$pid" 2>/dev/null; then
        set +e
        wait "$pid"
        status=$?
        set -e
        echo "A dev service exited with status $status; stopping the rest."
        return "$status"
      fi
    done

    sleep 1
  done
}

trap cleanup SIGINT SIGTERM EXIT

# ── Backend ─────────────────────────────────────────────
echo "Starting backend (Django runserver)..."
start_backend

# ── Frontend ────────────────────────────────────────────
echo "Starting frontend (pnpm dev)..."
start_frontend

echo ""
echo "╔══════════════════════════════════════╗"
echo "║  Dev servers starting up...          ║"
echo "║  Frontend: http://127.0.0.1:5173     ║"
echo "║  Backend:  http://127.0.0.1:8000     ║"
echo "║  Press Ctrl+C to stop                ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Stop the remaining service if either side exits.
monitor_services
