#!/usr/bin/env bash
# One-shot deploy of emerge to the prod host (co-located with label-studio).
#
#   ./deploy.sh            # push working tree, rebuild frontend, restart services
#   ./deploy.sh --web      # frontend only (skip uv sync) — fastest for UI tweaks
#   ./deploy.sh --api      # backend only (skip npm/vite build)
#
# Idempotent. Protects server-managed state: backend/.env and backend/workspace
# are never overwritten or deleted (the prod .env has GOOGLE_PROXY commented out
# and points ANTHROPIC_BASE_URL at the on-host proxy; workspace holds migrated
# data). Frontend build uses `vite build` directly — `npm run build` runs
# `tsc -b` first which currently fails on pre-existing test-fixture type errors.
set -euo pipefail

PEM="${EMERGE_PEM:-$HOME/tools/pem/ty_sg01.pem}"
HOST="${EMERGE_HOST:-root@43.166.182.9}"
REMOTE="/root/emerge"
HERE="$(cd "$(dirname "$0")" && pwd)"

WEB=1; API=1
case "${1:-}" in
  --web) API=0 ;;
  --api) WEB=0 ;;
  "" ) ;;
  * ) echo "usage: $0 [--web|--api]" >&2; exit 1 ;;
esac

echo "→ rsync source to $HOST:$REMOTE"
rsync -az --delete -e "ssh -i $PEM" \
  --exclude='.venv/' --exclude='node_modules/' --exclude='backend/workspace/' \
  --exclude='.git/' --exclude='frontend/dist/' --exclude='__pycache__/' \
  --exclude='.pytest_cache/' --exclude='*.pyc' --exclude='.DS_Store' \
  --exclude='backend/.env' \
  "$HERE/" "$HOST:$REMOTE/"

REMOTE_CMD='set -e; export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"'
if [ "$API" = 1 ]; then
  REMOTE_CMD="$REMOTE_CMD"'
  echo "→ uv sync"; cd /root/emerge/backend && uv sync -q'
fi
if [ "$WEB" = 1 ]; then
  REMOTE_CMD="$REMOTE_CMD"'
  echo "→ npm install + vite build"; cd /root/emerge/frontend \
    && npm install --no-audit --no-fund --silent && npx vite build >/dev/null'
fi
REMOTE_CMD="$REMOTE_CMD"'
  echo "→ restart services"
  [ '"$API"' = 1 ] && systemctl restart emerge.service || true
  [ '"$WEB"' = 1 ] && systemctl restart emerge-web.service || true
  sleep 6
  systemctl is-active emerge.service emerge-web.service
  echo -n "healthz via 9090: "; curl -s -m5 http://127.0.0.1:9090/healthz; echo'

ssh -i "$PEM" "$HOST" "$REMOTE_CMD"
echo "✓ deployed → http://${HOST#root@}:9090"
