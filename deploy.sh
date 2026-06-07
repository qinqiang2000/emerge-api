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
#
# Frontend serving: nginx serves the built dist/ on the public domain
# fpydoc.duckdns.org :80/:443 (config in deploy/emerge.nginx.conf →
# /etc/nginx/conf.d/emerge.conf) with immutable caching on hashed assets + API
# proxy to the local backend. This replaced the old `vite preview` node server
# (emerge-web.service), which a web deploy now disables.
#
# 2026-06-07 port swap: emerge took the public domain (:80/:443) from
# label-studio, which moved to plain HTTP on :9090. Both nginx server blocks
# are owned by this repo (deploy/emerge.nginx.conf + deploy/label-studio.nginx.conf)
# and installed together below — they're coupled (only one :80/:443
# default_server may exist), so they must always be swapped as a pair.
# `nginx -t` gates every reload so a bad config never drops either server.
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
    && npm install --no-audit --no-fund --silent && npx vite build >/dev/null
  echo "→ install nginx sites (emerge :80/:443 + label-studio :9090) + retire vite-preview"
  install -m 0644 /root/emerge/deploy/emerge.nginx.conf /etc/nginx/conf.d/emerge.conf
  install -m 0644 /root/emerge/deploy/label-studio.nginx.conf /etc/nginx/conf.d/label-studio.conf
  systemctl disable --now emerge-web.service 2>/dev/null || true'
fi
REMOTE_CMD="$REMOTE_CMD"'
  echo "→ restart services"
  [ '"$API"' = 1 ] && systemctl restart emerge.service || true
  # emerge now owns :80/:443, label-studio :9090. Validate the config before
  # reloading so a syntax slip can never take either server down.
  if [ '"$WEB"' = 1 ]; then nginx -t && systemctl reload nginx; fi
  sleep 4
  systemctl is-active emerge.service nginx
  echo -n "backend healthz: "; curl -s -m5 http://127.0.0.1:8080/healthz; echo
  echo -n "https healthz:   "; curl -s -m5 -k --resolve fpydoc.duckdns.org:443:127.0.0.1 https://fpydoc.duckdns.org/healthz; echo'

ssh -i "$PEM" "$HOST" "$REMOTE_CMD"
echo "✓ deployed → https://fpydoc.duckdns.org  (label-studio → http://${HOST#root@}:9090)"
