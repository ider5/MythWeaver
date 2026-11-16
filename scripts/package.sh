#!/usr/bin/env bash
# Build local release artifacts for simple self-host (frontend dist + optional images).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="${1:-dist}"

case "$MODE" in
  dist)
    echo "==> frontend production build"
    (cd frontend && npm ci && npm run build)
    mkdir -p dist/release
    rm -rf dist/release/web
    cp -R frontend/dist dist/release/web
    echo "Wrote dist/release/web (serve behind nginx; proxy /api to backend:8000)"
    ;;
  docker)
    if ! command -v docker >/dev/null 2>&1; then
      echo "docker not found" >&2
      exit 1
    fi
    if [[ ! -f backend/.env ]]; then
      echo "Missing backend/.env — copy from backend/.env.example first" >&2
      exit 1
    fi
    echo "==> docker compose build"
    docker compose build
    echo "OK. Start with: docker compose up -d"
    echo "Open http://localhost:8080"
    ;;
  *)
    echo "Usage: $0 [dist|docker]" >&2
    exit 2
    ;;
esac
