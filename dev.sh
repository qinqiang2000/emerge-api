#!/usr/bin/env bash
# emerge dev — start/stop/restart backend + frontend with rotated logs.
#
# Usage: ./dev.sh [start|stop|restart|status|log] [-b | -f]
#   default                 restart both, then tail logs
#   -b                      backend only  (uvicorn :8080)
#   -f                      frontend only (vite :5173)
#
# Examples:
#   ./dev.sh                # restart both, tail logs
#   ./dev.sh -b             # restart backend only, tail backend log
#   ./dev.sh start          # start (fails if already running)
#   ./dev.sh stop           # graceful SIGTERM → SIGKILL fallback
#   ./dev.sh status         # show what's running
#   ./dev.sh log -b         # tail backend log without touching processes

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT/.dev-logs"
BACKEND_PID="$LOG_DIR/backend.pid"
FRONTEND_PID="$LOG_DIR/frontend.pid"
LEGACY_PID="$ROOT/.dev.pid"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info() { echo -e "${BLUE}ℹ${NC} $1"; }
ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
err()  { echo -e "${RED}✗${NC} $1"; }

is_running() {  # $1=pidfile
  [ -f "$1" ] && ps -p "$(cat "$1")" >/dev/null 2>&1
}

# Drain a legacy multi-pid .dev.pid (from the previous version of this script).
drain_legacy() {
  [ -f "$LEGACY_PID" ] || return 0
  while read -r pid; do
    [ -n "$pid" ] && kill -TERM "$pid" 2>/dev/null || true
  done < "$LEGACY_PID"
  rm -f "$LEGACY_PID"
}

rotate_log() {  # $1=path/to/X.log → X-YYYYMMDD-HHMMSS.log
  [ -f "$1" ] || return 0
  local ts
  ts=$(date -r "$1" +%Y%m%d-%H%M%S 2>/dev/null || date +%Y%m%d-%H%M%S)
  mv "$1" "${1%.log}-$ts.log"
  info "rotated $(basename "$1") → $(basename "${1%.log}-$ts.log")"
}

graceful_stop() {  # $1=name $2=pidfile
  local name="$1" pidfile="$2"
  if ! is_running "$pidfile"; then
    [ -f "$pidfile" ] && rm -f "$pidfile"
    return 0
  fi
  local pid; pid=$(cat "$pidfile")
  info "stopping $name (pid $pid)..."
  kill -TERM "$pid" 2>/dev/null || true
  local i=0
  while ps -p "$pid" >/dev/null 2>&1 && [ $i -lt 10 ]; do
    sleep 1; echo -n "."; i=$((i+1))
  done
  echo
  if ps -p "$pid" >/dev/null 2>&1; then
    warn "$name did not exit in 10s; SIGKILL"
    kill -KILL "$pid" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$pidfile"
  ok "$name stopped"
}

start_backend() {
  if is_running "$BACKEND_PID"; then
    err "backend already running (pid $(cat "$BACKEND_PID")) — use restart"
    return 1
  fi
  mkdir -p "$LOG_DIR"
  rotate_log "$LOG_DIR/backend.log"
  cd "$ROOT/backend"
  nohup uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload \
    > "$LOG_DIR/backend.log" 2>&1 < /dev/null &
  echo $! > "$BACKEND_PID"
  disown
  sleep 1
  if is_running "$BACKEND_PID"; then
    ok "backend up (pid $(cat "$BACKEND_PID"))  http://localhost:8080  log: $LOG_DIR/backend.log"
  else
    err "backend failed to start — see $LOG_DIR/backend.log"
    rm -f "$BACKEND_PID"
    return 1
  fi
}

start_frontend() {
  if is_running "$FRONTEND_PID"; then
    err "frontend already running (pid $(cat "$FRONTEND_PID")) — use restart"
    return 1
  fi
  mkdir -p "$LOG_DIR"
  rotate_log "$LOG_DIR/frontend.log"
  cd "$ROOT/frontend"
  nohup npm run dev > "$LOG_DIR/frontend.log" 2>&1 < /dev/null &
  echo $! > "$FRONTEND_PID"
  disown
  sleep 1
  if is_running "$FRONTEND_PID"; then
    ok "frontend up (pid $(cat "$FRONTEND_PID"))  http://localhost:5173  log: $LOG_DIR/frontend.log"
  else
    err "frontend failed to start — see $LOG_DIR/frontend.log"
    rm -f "$FRONTEND_PID"
    return 1
  fi
}

show_status() {
  if is_running "$BACKEND_PID"; then
    ok "backend  running  pid $(cat "$BACKEND_PID")  http://localhost:8080"
  else
    warn "backend  stopped"
  fi
  if is_running "$FRONTEND_PID"; then
    ok "frontend running  pid $(cat "$FRONTEND_PID")  http://localhost:5173"
  else
    warn "frontend stopped"
  fi
  info "log dir: $LOG_DIR"
}

tail_logs() {  # $1=both|backend|frontend
  local files=()
  case "$1" in
    backend)  files=("$LOG_DIR/backend.log") ;;
    frontend) files=("$LOG_DIR/frontend.log") ;;
    *)        files=("$LOG_DIR/backend.log" "$LOG_DIR/frontend.log") ;;
  esac
  trap 'info "stopped tailing; processes keep running"; exit 0' INT
  # -F: keep following across rotations; -n 0: don't dump existing content.
  tail -F -n 0 "${files[@]}" 2>/dev/null
}

usage() {
  cat <<EOF
Usage: $0 [start|stop|restart|status|log] [-b|-f]

Commands:
  start    start service(s); fails if already running
  stop     graceful SIGTERM → SIGKILL after 10s
  restart  stop + start (default if no command given)
  status   show what's running and where the logs are
  log      tail log(s) without touching processes

Scope:
  -b       backend only  (uvicorn :8080)
  -f       frontend only (vite :5173)
  (none)   both

Logs rotated on each start → $LOG_DIR/{backend,frontend}{,-YYYYMMDD-HHMMSS}.log
EOF
}

# --- arg parsing ---

CMD="restart"
SCOPE="both"
for arg in "$@"; do
  case "$arg" in
    start|stop|restart|status|log) CMD="$arg" ;;
    -b) SCOPE="backend" ;;
    -f) SCOPE="frontend" ;;
    -h|--help|help) usage; exit 0 ;;
    *) err "unknown arg: $arg"; usage; exit 1 ;;
  esac
done

case "$CMD" in
  start)
    drain_legacy
    case "$SCOPE" in
      backend)  start_backend ;;
      frontend) start_frontend ;;
      both)     start_backend; start_frontend ;;
    esac
    ;;
  stop)
    drain_legacy
    case "$SCOPE" in
      backend)  graceful_stop backend  "$BACKEND_PID" ;;
      frontend) graceful_stop frontend "$FRONTEND_PID" ;;
      both)     graceful_stop backend  "$BACKEND_PID"
                graceful_stop frontend "$FRONTEND_PID" ;;
    esac
    ;;
  restart)
    drain_legacy
    case "$SCOPE" in
      backend)
        graceful_stop backend "$BACKEND_PID"
        start_backend
        echo
        info "tailing backend log (Ctrl+C to exit tail; process keeps running)"
        tail_logs backend
        ;;
      frontend)
        graceful_stop frontend "$FRONTEND_PID"
        start_frontend
        echo
        info "tailing frontend log (Ctrl+C to exit tail; process keeps running)"
        tail_logs frontend
        ;;
      both)
        graceful_stop backend  "$BACKEND_PID"
        graceful_stop frontend "$FRONTEND_PID"
        start_backend
        start_frontend
        echo
        info "tailing logs (Ctrl+C to exit tail; processes keep running)"
        tail_logs both
        ;;
    esac
    ;;
  status) show_status ;;
  log)    tail_logs "$SCOPE" ;;
esac
