#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$ROOT/.dev.pid"
LOG_DIR="$ROOT/.dev-logs"

usage() {
  echo "Usage: $0 [-b | -f | stop | log]"
  echo "  (no flag)  start backend + frontend in background"
  echo "  -b         backend only  (port 8080)"
  echo "  -f         frontend only (port 5173)"
  echo "  stop       stop all running dev processes"
  echo "  log        tail logs"
  exit 1
}

start_backend() {
  mkdir -p "$LOG_DIR"
  cd "$ROOT/backend"
  nohup uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload \
    > "$LOG_DIR/backend.log" 2>&1 &
  echo $! >> "$PID_FILE"
  echo "backend started (pid $!) → $LOG_DIR/backend.log"
}

start_frontend() {
  mkdir -p "$LOG_DIR"
  cd "$ROOT/frontend"
  nohup npm run dev > "$LOG_DIR/frontend.log" 2>&1 &
  echo $! >> "$PID_FILE"
  echo "frontend started (pid $!) → $LOG_DIR/frontend.log"
}

do_stop() {
  if [[ ! -f "$PID_FILE" ]]; then
    echo "no running processes (no .dev.pid found)"
    return
  fi
  while read -r pid; do
    if kill "$pid" 2>/dev/null; then
      echo "killed $pid"
    fi
  done < "$PID_FILE"
  rm -f "$PID_FILE"
}

case "${1:-all}" in
  all)
    do_stop 2>/dev/null || true
    rm -f "$PID_FILE"
    start_backend
    start_frontend
    echo "--- tailing logs (Ctrl+C to exit tail, processes keep running) ---"
    tail -f "$LOG_DIR"/backend.log "$LOG_DIR"/frontend.log
    ;;
  -b)
    do_stop 2>/dev/null || true
    rm -f "$PID_FILE"
    start_backend
    echo "--- tailing backend log (Ctrl+C to exit tail, process keeps running) ---"
    tail -f "$LOG_DIR/backend.log"
    ;;
  -f)
    do_stop 2>/dev/null || true
    rm -f "$PID_FILE"
    start_frontend
    echo "--- tailing frontend log (Ctrl+C to exit tail, process keeps running) ---"
    tail -f "$LOG_DIR/frontend.log"
    ;;
  stop)
    do_stop
    ;;
  log)
    tail -f "$LOG_DIR"/backend.log "$LOG_DIR"/frontend.log 2>/dev/null
    ;;
  *) usage ;;
esac
